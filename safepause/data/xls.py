"""옛 엑셀(.xls, 엑셀 97~2003 BIFF8) 첫 시트를 CSV 글로 바꾼다. 표준 라이브러리(struct)만 쓴다(앱의 Pyodide에서도 동작).

바꾼 글은 data.loader의 CSV 처리(머리글 찾기·합계 줄 건너뛰기 등)로 그대로 넘긴다(.xlsx와 같은 길).

- 파일은 복합 문서(CFB, 앞 8바이트 D0 CF 11 E0 A1 B1 1A E1)다. 맨 위의 Workbook 스트림을 읽는다([MS-CFB]).
- BIFF8 첫 워크시트(통합 문서에 적힌 순서의 첫 번째)의 칸: 공유 문자열(SST)·문자열(LABEL)·숫자(NUMBER·RK·MULRK)·
  수식 결과(FORMULA·STRING)·참거짓. 오류 값은 빈 칸. 시트 안에 끼어 있는 차트 등(BOF~EOF)은 건너뛴다([MS-XLS]).
- 날짜: 칸 서식(XF → FORMAT)이 날짜·시각이면 엑셀 일련번호를 글로 바꾼다(xlsx와 같은 규칙, 1904 날짜 체계).
  서식이 일반이어도 머리글이 날짜·일시·시간이면 xlsx와 같이 바꾼다(data.xlsx.rows_to_csv_text).
- 알아보고 안내하는 것: 암호가 걸린 엑셀(.xlsx를 암호로 감싼 복합 문서, .xls의 FILEPASS), 엑셀 95 이전(BIFF5 이하),
  엑셀이 아닌 복합 문서(한글·워드 등).
- 안전: 섹터 사슬의 순환·범위 밖 번호·잘린 파일은 손상으로 본다. 스트림은 파일 크기 안에서만 읽는다. 줄 수 상한
  (xlsx와 같은 10만 줄, BIFF8 자체 상한은 65,536줄), 256칸, 표 전체 300만 칸(xlsx와 같음). 파일 크기 상한 30MB.
"""
from __future__ import annotations

import struct
import sys
from array import array
from typing import Optional, Sequence

from safepause.data import xlsx as _xlsx
from safepause.data.xlsx import MAX_COLS, MAX_ROWS, TOO_MANY_CELLS, TOO_MANY_ROWS, format_kind, rows_to_csv_text, serial_to_text

CFB_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
MAX_FILE_BYTES = 30 * 1024 * 1024   # 이보다 큰 .xls는 읽지 않는다(xlsx 압축 해제 상한과 같은 크기)

_SAVE_AS_CSV = ("엑셀에서 [다른 이름으로 저장]을 누르고 파일 형식을 [CSV UTF-8(쉼표로 분리)]로 골라 저장한 뒤 "
                "그 파일을 올려 주세요.")
BROKEN = "엑셀 파일(.xls)을 읽지 못했어요. 파일이 손상됐을 수 있어요. " + _SAVE_AS_CSV
ENCRYPTED = ("암호가 걸린 엑셀 파일이라 읽지 못해요. 엑셀에서 암호를 넣어 연 다음 [다른 이름으로 저장]에서 "
             "파일 형식을 [CSV UTF-8(쉼표로 분리)]로 골라 저장한 뒤 그 파일을 올려 주세요.")
TOO_OLD = "엑셀 95 이전의 아주 옛 엑셀 파일이라 읽지 못해요. " + _SAVE_AS_CSV
NOT_EXCEL = "엑셀이 아닌 문서 파일(한글·워드 등)은 읽지 못해요. 거래내역 파일(.csv, .xls, .xlsx)을 골라 올려 주세요."
TOO_BIG = "엑셀 파일이 너무 커요(30MB까지). 기간을 나눠 내려받아 올려 주세요."
NO_SHEET = "엑셀 파일(.xls)에서 표가 든 시트를 찾지 못했어요. " + _SAVE_AS_CSV

# CFB 특수 섹터 번호
_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
_MAXREGSECT = 0xFFFFFFFA
_NOSTREAM = 0xFFFFFFFF

# BIFF 레코드 번호([MS-XLS] 2.3)
_BOF, _EOF, _CONTINUE = 0x0809, 0x000A, 0x003C
_FILEPASS, _DATEMODE, _FORMAT, _XF, _BOUNDSHEET, _SST = 0x002F, 0x0022, 0x041E, 0x00E0, 0x0085, 0x00FC
_LABELSST, _LABEL, _RSTRING, _NUMBER, _RK, _MULRK = 0x00FD, 0x0204, 0x00D6, 0x0203, 0x027E, 0x00BD
_FORMULA, _STRING, _BOOLERR = 0x0006, 0x0207, 0x0205
_SHRFMLA, _ARRAY, _TABLE = 0x04BC, 0x0221, 0x0236   # 수식과 그 글 결과(STRING) 사이에 올 수 있는 레코드
_BIFF8 = 0x0600
_DT_GLOBALS, _DT_WORKSHEET = 0x0005, 0x0010

# 내장 날짜·시각 서식 번호(xlsx와 같은 번호 체계, 한국어 등 동아시아 지역 서식 포함)
_BUILTIN_DATE = frozenset({14, 15, 16, 17, 27, 28, 29, 30, 31, 34, 35, 36, 50, 51, 52, 53, 54, 57, 58})
_BUILTIN_TIME = frozenset({18, 19, 20, 21, 32, 33, 45, 46, 47, 55, 56})
_BUILTIN_DATETIME = frozenset({22})

_Cell = tuple[str, Optional[float]]
_UINT32 = array("I")


class XlsError(ValueError):
    """.xls 파일을 읽을 수 없을 때(한국어 안내)."""


def is_cfb(data: bytes) -> bool:
    return data[:8] == CFB_MAGIC


# ---------------------------------------------------------------------------
# 복합 문서(CFB)
# ---------------------------------------------------------------------------

class _Entry:
    __slots__ = ("name", "kind", "left", "right", "child", "start", "size")

    def __init__(self, raw: bytes, major: int) -> None:
        name_len = struct.unpack_from("<H", raw, 64)[0]
        self.name = raw[:max(0, min(name_len, 64) - 2)].decode("utf-16-le", "replace") if name_len >= 2 else ""
        self.kind = raw[66]
        self.left, self.right, self.child = struct.unpack_from("<III", raw, 68)
        self.start = struct.unpack_from("<I", raw, 116)[0]
        size = struct.unpack_from("<Q", raw, 120)[0]
        self.size = size & 0xFFFFFFFF if major == 3 else size   # 3판은 위 4바이트가 쓰레기일 수 있다([MS-CFB] 2.6.3)


class _Cfb:
    """복합 문서에서 맨 위 스트림을 이름으로 읽는다. 어긋난 번호·순환·잘린 파일은 XlsError(BROKEN)."""

    def __init__(self, data: bytes) -> None:
        if len(data) < 512 or not is_cfb(data):
            raise XlsError(BROKEN)
        major, byte_order, sector_shift, mini_shift = struct.unpack_from("<HHHH", data, 0x1A)
        if byte_order != 0xFFFE or sector_shift not in (9, 12) or mini_shift != 6:
            raise XlsError(BROKEN)
        (n_fat, first_dir, _sig, cutoff, first_minifat, n_minifat,
         first_difat, n_difat) = struct.unpack_from("<IIIIIIII", data, 0x2C)
        self.data = data
        self.major = major
        self.size = 1 << sector_shift
        self.cutoff = cutoff
        self.n_sectors = max(0, (len(data) - self.size + self.size - 1) // self.size)
        if n_fat > self.n_sectors or n_difat > self.n_sectors or n_minifat > self.n_sectors:
            raise XlsError(BROKEN)
        self.fat = self._read_fat(n_fat, first_difat, n_difat)
        self.entries = [_Entry(chunk, major) for chunk in self._split(self._chain_bytes(first_dir, self.fat), 128)]
        if not self.entries or self.entries[0].kind != 5:   # 0번은 뿌리(Root Entry)
            raise XlsError(BROKEN)
        root = self.entries[0]
        self.mini = self._chain_bytes(root.start, self.fat)[:root.size] if root.size else b""
        self.minifat = (self._ints(self._chain_bytes(first_minifat, self.fat)) if n_minifat else [])
        self.top = self._top_level()

    # -- 섹터 ---------------------------------------------------------------
    def _sector(self, sid: int) -> bytes:
        start = (sid + 1) * self.size
        if sid > _MAXREGSECT or start >= len(self.data):
            raise XlsError(BROKEN)
        return self.data[start:start + self.size]

    @staticmethod
    def _ints(raw: bytes) -> Sequence[int]:
        """4바이트 부호 없는 정수(작은 끝) 목록. FAT가 커도 메모리를 덜 쓰게 array로 담는다."""
        n = len(raw) // 4
        if _UINT32.itemsize != 4:   # 드문 플랫폼: struct로
            return list(struct.unpack_from(f"<{n}I", raw, 0)) if n else []
        out = array(_UINT32.typecode)
        out.frombytes(raw[:n * 4])
        if sys.byteorder == "big":
            out.byteswap()
        return out

    @staticmethod
    def _split(raw: bytes, width: int) -> list[bytes]:
        return [raw[k:k + width] for k in range(0, len(raw) - width + 1, width)]

    def _read_fat(self, n_fat: int, first_difat: int, n_difat: int) -> Sequence[int]:
        ids = [s for s in struct.unpack_from("<109I", self.data, 0x4C) if s != _FREESECT]
        sid, seen = first_difat, set()
        per = self.size // 4 - 1
        while sid not in (_ENDOFCHAIN, _FREESECT) and len(seen) < n_difat:
            if sid in seen:
                raise XlsError(BROKEN)
            seen.add(sid)
            values = self._ints(self._sector(sid))
            ids.extend(s for s in values[:per] if s != _FREESECT)
            sid = values[per]
        ids = ids[:n_fat]
        if len(ids) < n_fat:
            raise XlsError(BROKEN)
        return self._ints(b"".join(self._sector(sid) for sid in ids))

    def _chain(self, start: int, table: Sequence[int], limit: int) -> list[int]:
        """시작 번호부터 사슬(ENDOFCHAIN까지). 순환·범위 밖·너무 긴 사슬은 손상."""
        out: list[int] = []
        seen: set[int] = set()
        sid = start
        while sid != _ENDOFCHAIN:
            if sid >= len(table) or sid in seen or len(out) >= limit:
                raise XlsError(BROKEN)
            seen.add(sid)
            out.append(sid)
            sid = table[sid]
        return out

    def _chain_bytes(self, start: int, table: Sequence[int]) -> bytes:
        if start in (_ENDOFCHAIN, _FREESECT):
            return b""
        return b"".join(self._sector(s) for s in self._chain(start, table, self.n_sectors))

    def _top_level(self) -> dict[str, _Entry]:
        """뿌리 바로 아래 항목(이름 소문자 → 항목). 형제 나무를 따라가며 순환을 막는다."""
        out: dict[str, _Entry] = {}
        stack = [self.entries[0].child]
        seen: set[int] = set()
        while stack:
            k = stack.pop()
            if k == _NOSTREAM:
                continue
            if k >= len(self.entries) or k in seen:
                raise XlsError(BROKEN)
            seen.add(k)
            entry = self.entries[k]
            out.setdefault(entry.name.lower(), entry)
            stack.extend((entry.left, entry.right))
        return out

    # -- 스트림 -------------------------------------------------------------
    def has(self, name: str) -> bool:
        return name.lower() in self.top

    def stream(self, name: str) -> bytes:
        entry = self.top.get(name.lower())
        if entry is None or entry.kind != 2:
            raise XlsError(BROKEN)
        if entry.size == 0:
            return b""
        if entry.size < self.cutoff:   # 작은 스트림은 미니 스트림(64바이트 조각) 안에 있다
            sids = self._chain(entry.start, self.minifat, max(1, len(self.mini) // 64))
            raw = b"".join(self.mini[s * 64:(s + 1) * 64] for s in sids)
        else:
            raw = self._chain_bytes(entry.start, self.fat)
        if len(raw) < entry.size:
            raise XlsError(BROKEN)
        return raw[:entry.size]


# ---------------------------------------------------------------------------
# BIFF8
# ---------------------------------------------------------------------------

class _Pieces:
    """CONTINUE로 나뉜 레코드 내용을 이어 읽는다. 글자 부분이 나뉘면 다음 조각 첫 바이트가 글자 폭 표시다."""

    def __init__(self, pieces: list[bytes]) -> None:
        self.pieces = pieces
        self.i = 0
        self.pos = 0

    def _next_piece(self) -> None:
        while self.i < len(self.pieces) and self.pos >= len(self.pieces[self.i]):
            self.i += 1
            self.pos = 0
        if self.i >= len(self.pieces):
            raise XlsError(BROKEN)

    def at_end(self) -> bool:
        """남은 바이트가 없는지."""
        if self.i >= len(self.pieces):
            return True
        if self.pos < len(self.pieces[self.i]):
            return False
        return not any(self.pieces[self.i + 1:])

    def take(self, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            self._next_piece()
            piece = self.pieces[self.i]
            k = min(n, len(piece) - self.pos)
            out += piece[self.pos:self.pos + k]
            self.pos += k
            n -= k
        return bytes(out)

    def chars(self, count: int, high: bool) -> str:
        parts: list[str] = []
        while count > 0:
            piece = self.pieces[self.i] if self.i < len(self.pieces) else b""
            if self.pos >= len(piece):   # 글자 중간에 조각이 바뀜: 새 조각 첫 바이트 = 글자 폭
                self.i += 1
                self.pos = 0
                if self.i >= len(self.pieces) or not self.pieces[self.i]:
                    raise XlsError(BROKEN)
                high = bool(self.pieces[self.i][0] & 1)
                self.pos = 1
                continue
            width = 2 if high else 1
            k = min(count, (len(piece) - self.pos) // width)
            if k == 0:
                raise XlsError(BROKEN)
            raw = piece[self.pos:self.pos + k * width]
            parts.append(raw.decode("utf-16-le", "replace") if high else raw.decode("latin-1"))
            self.pos += k * width
            count -= k
        return "".join(parts)


def _rich_string(reader: _Pieces) -> str:
    """XLUnicodeRichExtendedString(SST 안 글). 서식 조각·읽는 법(ExtRst)은 건너뛴다."""
    count, flags = struct.unpack("<HB", reader.take(3))
    runs = struct.unpack("<H", reader.take(2))[0] if flags & 0x08 else 0
    ext = struct.unpack("<I", reader.take(4))[0] if flags & 0x04 else 0
    text = reader.chars(count, bool(flags & 0x01))
    if runs:
        reader.take(4 * runs)
    if ext:
        reader.take(ext)
    return text


def _unicode_string(body: bytes, pos: int) -> str:
    """XLUnicodeString(LABEL·FORMAT·STRING 안 글): 글자 수(2) + 폭 표시(1) + 글자."""
    if pos + 3 > len(body):
        raise XlsError(BROKEN)
    count, flags = struct.unpack_from("<HB", body, pos)
    return _Pieces([body[pos + 3:]]).chars(count, bool(flags & 0x01)) if count else ""


def _rk(value: int) -> float:
    """RK 숫자([MS-XLS] 2.5.217): 끝 2비트가 100으로 나눔·정수 표시."""
    if value & 0x02:
        number = float(value >> 2) if not value & 0x80000000 else float((value >> 2) - (1 << 30))
    else:
        number = struct.unpack("<d", struct.pack("<Q", (value & 0xFFFFFFFC) << 32))[0]
    return number / 100 if value & 0x01 else number


def _records(stream: bytes, pos: int = 0):
    """(번호, 내용, 시작 위치)를 차례로. 잘린 레코드는 손상."""
    n = len(stream)
    while pos + 4 <= n:
        rid, size = struct.unpack_from("<HH", stream, pos)
        end = pos + 4 + size
        if end > n:
            raise XlsError(BROKEN)
        yield rid, stream[pos + 4:end], pos
        pos = end


class _Book:
    def __init__(self, stream: bytes) -> None:
        self.stream = stream
        self.date1904 = False
        self.formats: dict[int, str] = {}
        self.xf_formats: list[int] = []
        self.sheets: list[int] = []   # 워크시트 BOF 위치(통합 문서 순서)
        self.sst: list[str] = []
        self._read_globals()

    def _read_globals(self) -> None:
        records = list(_globals_records(self.stream))
        if not records or records[0][0] != _BOF:
            raise XlsError(BROKEN)
        version, kind = struct.unpack_from("<HH", records[0][1].ljust(4, b"\0"), 0)
        if version != _BIFF8:
            raise XlsError(TOO_OLD)
        if kind != _DT_GLOBALS:
            raise XlsError(BROKEN)
        for k, (rid, body, _pos) in enumerate(records):
            if rid == _FILEPASS:
                raise XlsError(ENCRYPTED)
            if rid == _DATEMODE and len(body) >= 2:
                self.date1904 = struct.unpack_from("<H", body, 0)[0] == 1
            elif rid == _FORMAT and len(body) >= 5:
                self.formats[struct.unpack_from("<H", body, 0)[0]] = _unicode_string(body, 2)
            elif rid == _XF and len(body) >= 4:
                self.xf_formats.append(struct.unpack_from("<H", body, 2)[0])
            elif rid == _BOUNDSHEET and len(body) >= 6:
                offset, _state, sheet_type = struct.unpack_from("<IBB", body, 0)
                if sheet_type == 0:   # 0 워크시트(차트·매크로 시트는 뺀다)
                    self.sheets.append(offset)
            elif rid == _SST:
                pieces = [body]
                for rid2, body2, _ in records[k + 1:]:
                    if rid2 != _CONTINUE:
                        break
                    pieces.append(body2)
                self.sst = _read_sst(pieces)

    def _kind(self, xf: int) -> Optional[str]:
        if not 0 <= xf < len(self.xf_formats):
            return None
        fid = self.xf_formats[xf]
        if fid in self.formats:
            return format_kind(self.formats[fid])
        if fid in _BUILTIN_DATETIME:
            return "datetime"
        if fid in _BUILTIN_DATE:
            return "date"
        if fid in _BUILTIN_TIME:
            return "time"
        return None

    def _number(self, value: float, xf: int) -> _Cell:
        kind = self._kind(xf)
        if kind:
            converted = serial_to_text(value, kind, self.date1904)
            if converted is not None:
                return converted, None
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value)), value
        return format(value, ".15g"), value

    def first_sheet_rows(self) -> list[list[_Cell]]:
        for offset in self.sheets:
            if 0 <= offset < len(self.stream):
                return self._sheet_rows(offset)
        raise XlsError(NO_SHEET)

    def _sheet_rows(self, offset: int) -> list[list[_Cell]]:
        cells: dict[int, dict[int, _Cell]] = {}
        depth = 0
        pending_string: Optional[tuple[int, int]] = None   # 글 결과 수식의 자리(다음 STRING 레코드가 글)
        for rid, body, _pos in _records(self.stream, offset):
            if depth == 0 and rid != _BOF:   # 시트 위치가 BOF를 가리키지 않음
                raise XlsError(BROKEN)
            if rid == _BOF:
                depth += 1
                if depth == 1:
                    if len(body) < 4:
                        raise XlsError(BROKEN)
                    version, kind = struct.unpack_from("<HH", body, 0)
                    if version != _BIFF8 or kind != _DT_WORKSHEET:
                        raise XlsError(NO_SHEET)
                continue
            if rid == _EOF:
                depth -= 1
                if depth <= 0:
                    break
                continue
            if depth != 1:   # 시트 안에 끼어 있는 차트 등
                continue
            if rid == _STRING and pending_string is not None:
                row, col = pending_string
                pending_string = None
                _put(cells, row, col, (_unicode_string(body, 0), None))
                continue
            if rid in (_SHRFMLA, _ARRAY, _TABLE, _CONTINUE):
                continue
            pending_string = None
            if len(body) < 6:
                continue
            row, col, xf = struct.unpack_from("<HHH", body, 0)
            if rid == _LABELSST and len(body) >= 10:
                index = struct.unpack_from("<I", body, 6)[0]
                _put(cells, row, col, (self.sst[index] if index < len(self.sst) else "", None))
            elif rid in (_LABEL, _RSTRING):
                _put(cells, row, col, (_unicode_string(body, 6), None))
            elif rid == _NUMBER and len(body) >= 14:
                _put(cells, row, col, self._number(struct.unpack_from("<d", body, 6)[0], xf))
            elif rid == _RK and len(body) >= 10:
                _put(cells, row, col, self._number(_rk(struct.unpack_from("<I", body, 6)[0]), xf))
            elif rid == _MULRK and len(body) >= 12:
                count = (len(body) - 6) // 6
                for k in range(count):
                    cxf, value = struct.unpack_from("<HI", body, 4 + 6 * k)
                    _put(cells, row, col + k, self._number(_rk(value), cxf))
            elif rid == _FORMULA and len(body) >= 14:
                result = body[6:14]
                if result[6:8] == b"\xff\xff":
                    if result[0] == 0:          # 글 결과: 다음 STRING 레코드
                        pending_string = (row, col)
                    elif result[0] == 1:        # 참거짓
                        _put(cells, row, col, ("TRUE" if result[2] else "FALSE", None))
                else:
                    _put(cells, row, col, self._number(struct.unpack("<d", result)[0], xf))
            elif rid == _BOOLERR and len(body) >= 8:
                if body[7] == 0:                # 오류 값(#N/A 등)은 빈 칸
                    _put(cells, row, col, ("TRUE" if body[6] else "FALSE", None))
        if not cells:
            return []
        last = max(cells)
        if last + 1 > MAX_ROWS:
            raise XlsError(TOO_MANY_ROWS)
        if sum(max(line) + 1 for line in cells.values()) > _xlsx.MAX_CELLS:   # 줄마다 맨 오른쪽 칸까지 채우므로
            raise XlsError(TOO_MANY_CELLS)
        rows: list[list[_Cell]] = []
        for r in range(last + 1):
            line = cells.get(r)
            if not line:
                rows.append([])
                continue
            width = max(line) + 1
            rows.append([line.get(c, ("", None)) for c in range(width)])
        return rows


def _put(cells: dict[int, dict[int, _Cell]], row: int, col: int, cell: _Cell) -> None:
    if col < MAX_COLS and cell[0] != "":
        cells.setdefault(row, {})[col] = cell


def _globals_records(stream: bytes):
    """통합 문서 전체 레코드(첫 BOF ~ 첫 EOF)."""
    for rid, body, pos in _records(stream, 0):
        yield rid, body, pos
        if rid == _EOF:
            return


def _read_sst(pieces: list[bytes]) -> list[str]:
    reader = _Pieces(pieces)
    _total, unique = struct.unpack("<II", reader.take(8))
    size = sum(len(p) for p in pieces)
    out: list[str] = []
    for _ in range(min(unique, size // 3)):   # 글 하나는 적어도 3바이트(글자 수·폭 표시)
        if reader.at_end():   # 적힌 개수보다 글이 적은 표: 글 경계에서 끝났으면 읽은 데까지(중간에 잘리면 손상)
            break
        out.append(_rich_string(reader))
    return out


def xls_to_csv_text(data: bytes) -> str:
    """.xls(BIFF8) 바이트 → 첫 워크시트의 CSV 글(쉼표, 줄바꿈 \\n). 읽지 못하면 한국어 안내와 함께 XlsError."""
    if len(data) > MAX_FILE_BYTES:
        raise XlsError(TOO_BIG)
    try:
        cfb = _Cfb(data)
        if cfb.has("EncryptionInfo") and cfb.has("EncryptedPackage"):   # 암호로 감싼 .xlsx([MS-OFFCRYPTO])
            raise XlsError(ENCRYPTED)
        if not cfb.has("Workbook"):
            raise XlsError(TOO_OLD if cfb.has("Book") else NOT_EXCEL)
        book = _Book(cfb.stream("Workbook"))
        return rows_to_csv_text(book.first_sheet_rows(), book.date1904)
    except XlsError:
        raise
    except (struct.error, IndexError, ValueError, OverflowError) as exc:
        raise XlsError(BROKEN) from exc


__all__ = ["CFB_MAGIC", "MAX_FILE_BYTES", "XlsError", "is_cfb", "xls_to_csv_text"]
