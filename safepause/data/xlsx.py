"""엑셀(.xlsx) 첫 시트를 CSV 글로 바꾼다. 표준 라이브러리(zipfile + xml.etree)만 쓴다(앱의 Pyodide에서도 동작).

바꾼 글은 data.loader의 CSV 처리(머리글 찾기·합계 줄 건너뛰기 등)로 그대로 넘긴다(v0.3 수정 AUG-02).

- 첫 시트(통합 문서에 적힌 순서의 첫 번째)만 읽는다.
- 칸 값: 공유 문자열(sharedStrings)·인라인 문자열·숫자·참거짓·수식 결과. 오류 값(#N/A 등)은 빈 칸.
- 날짜: 칸 서식이 날짜·시각이면 엑셀 일련번호를 'YYYY-MM-DD HH:MM:SS'로 바꾼다(초 단위 반올림, 1904 날짜 체계).
  서식이 일반이어도 머리글이 날짜·일시면 그 열의 일련번호를, 머리글이 시간·시각이면 0~1 사이 값을 시각으로 바꾼다.
- 안전: 압축 해제 합계 상한(압축 폭탄), zip 안 파일 수 상한, 줄·칸 수 상한, DTD(<!DOCTYPE·<!ENTITY)가 든 XML 거부.
  필요한 부분(통합 문서·관계·공유 문자열·서식·첫 시트)만 읽는다. 시트·공유 문자열은 흘려 읽고, 다시 볼 일이 없는
  요소는 바로 떼어 메모리를 아낀다(작은 zip이 푼 30MB 안의 빈 요소 수백만 개로 메모리가 수백 MB 부풀던 것 방지).
  XML 깊이(MAX_XML_DEPTH), 통째로 읽는 부분의 요소 수, 줄·공유 문자열 하나에 담아 두는 요소 수에 상한을 둔다.
  zip·XML이 손상됐거나 이상하면(압축 자료 오류, 모르는 압축 방식, 없는 인코딩 선언 등) 모두 같은 '손상' 안내.
"""
from __future__ import annotations

import csv
import io
import posixpath
import re
import zipfile
from datetime import datetime, timedelta
from typing import Optional
from xml.etree import ElementTree as ET

MAX_UNZIPPED = 30 * 1024 * 1024   # 읽는 부분의 압축 해제 합계 상한(바이트)
MAX_ENTRIES = 5000                # zip 안 파일 수 상한
MAX_ROWS = 100_000                # 줄 수 상한(엑셀 줄 번호 기준)
MAX_COLS = 256                    # 이보다 오른쪽 칸은 읽지 않는다
MAX_CELLS = 3_000_000             # 표 전체 칸 수 상한(줄마다 맨 오른쪽 칸까지 센다. 작은 파일이 큰 빈 표로 불어나는 것 방지)
HEADER_SCAN_ROWS = 30             # 일반 서식 날짜 열을 찾을 때 머리글을 훑어보는 앞쪽 줄 수
_MAX_SERIAL = 2958466             # 9999-12-31 다음 날(이보다 크면 날짜가 아님)
MAX_XML_DEPTH = 256               # XML 중첩 깊이 상한. 엑셀이 쓰는 깊이는 10 안팎. 앱의 Pyodide(3.14.2)는 4,000단계로
                                  # 중첩된 요소를 풀어 줄 때 스택이 넘쳐 엔진 전체가 죽는다(데스크톱 Chrome에서 3,000은 됨,
                                  # 2KB xlsx로 재현). 안드로이드 WebView의 스택이 더 작을 수 있어 넉넉히 낮춘다.
MAX_TREE_ELEMENTS = 1_000_000     # 통째로 읽는 부분(통합 문서·관계·서식)의 요소 수 상한(약 90MB)
MAX_KEPT_ELEMENTS = 1_000_000     # 줄(row)·공유 문자열(si) 하나를 다 읽을 때까지 담아 두는 요소 수 상한
MAX_RATIO = 100                   # 한 부분의 압축률(푼 크기 ÷ 압축 크기) 상한. Apache POI의 압축 폭탄 기본값과 같은 100배.
RATIO_GRACE = 4 * 1024 * 1024     # 푼 크기가 이보다 작으면 압축률을 보지 않는다. 은행 거래내역 모양 10만 줄 시트는 약 7배,
                                  # 서식만 있는 빈 줄 30만 개도 약 29배였다(2026-10-03 잼). 30KB가 30MB로 풀리는
                                  # 빈 요소 폭탄(약 1,000배)은 푸는 데 0.1초, 읽으면 7~9초가 들어 미리 거절한다.

_EPOCH_1900 = datetime(1899, 12, 30)   # 1900 날짜 체계(1900-02-29 버그 보정이 된 기준, 61 이후 정확)
_EPOCH_1904 = datetime(1904, 1, 1)

_SAVE_AS_CSV = ("엑셀에서 [다른 이름으로 저장]을 누르고 파일 형식을 [CSV UTF-8(쉼표로 분리)]로 골라 저장한 뒤 "
                "그 파일을 올려 주세요.")
TOO_BIG = "엑셀 파일이 너무 커요. 압축을 푼 크기가 30MB를 넘어요. 기간을 나눠 내려받아 올려 주세요."
TOO_MANY_ROWS = f"엑셀 파일의 줄이 너무 많아요({MAX_ROWS:,}줄까지). 기간을 나눠 내려받아 올려 주세요."
TOO_MANY_CELLS = f"표의 칸이 너무 많아요({MAX_CELLS:,}칸까지). 기간을 나눠 내려받아 올려 주세요."
BROKEN = "엑셀 파일(.xlsx)을 읽지 못했어요. 파일이 손상됐거나 암호가 걸려 있을 수 있어요. " + _SAVE_AS_CSV
TOO_PACKED = "엑셀 파일 안의 내용이 보통보다 지나치게 많이 압축돼 있어 안전을 위해 읽지 않았어요. " + _SAVE_AS_CSV
NOT_EXCEL = "엑셀(.xlsx)이 아닌 압축 파일은 읽지 못해요. 거래내역 파일(.csv, .xls, .xlsx)을 골라 올려 주세요."

_DTD_RE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_REF_RE = re.compile(r"([A-Za-z]{1,3})(\d+)$")
# 내장 날짜·시각 서식 번호(ECMA-376 18.8.30, 한국어 등 동아시아 지역 서식 27~36·50~58 포함)
_BUILTIN_DATE = frozenset({14, 15, 16, 17, 27, 28, 29, 30, 31, 34, 35, 36, 50, 51, 52, 53, 54, 57, 58})
_BUILTIN_TIME = frozenset({18, 19, 20, 21, 32, 33, 45, 46, 47, 55, 56})
_BUILTIN_DATETIME = frozenset({22})
_DATE_HEADERS = ("일시", "일자", "날짜", "거래일", "date")
_TIME_HEADERS = ("시간", "시각", "time")


class XlsxError(ValueError):
    """엑셀 파일을 읽을 수 없을 때(한국어 안내)."""


# XML이 잘못됐을 때 ElementTree가 내는 예외: 문법 오류(ParseError), 선언된 인코딩이 없는 이름·글이 아닌 코덱
# (LookupError), 여러 바이트 인코딩·코덱 오류(ValueError·UnicodeError). 모두 '손상'으로 안내한다(퍼징으로 찾음).
_XML_ERRORS = (ET.ParseError, ValueError, LookupError)


def _local(tag: str) -> str:
    """'{네임스페이스}이름' → '이름'(표준·Strict OOXML 네임스페이스를 함께 받는다)."""
    return tag.rsplit("}", 1)[-1]


def _attr(elem: ET.Element, name: str) -> Optional[str]:
    """네임스페이스와 관계없이 속성 값(r:id 등)."""
    for key, value in elem.attrib.items():
        if _local(key) == name:
            return value
    return None


class _Package:
    """zip 안 부분을 이름(대소문자 무시)으로 읽는다. 압축 해제 합계를 세어 상한을 넘으면 XlsxError."""

    def __init__(self, zf: zipfile.ZipFile) -> None:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise XlsxError(TOO_BIG)
        self._zf = zf
        self._names = {i.filename.lower(): i for i in infos}
        self._used = 0

    def has(self, name: str) -> bool:
        return name.lower() in self._names

    def names(self) -> list[str]:
        return [i.filename for i in self._names.values()]

    def read(self, name: str) -> Optional[bytes]:
        info = self._names.get(name.lower())
        if info is None:
            return None
        room = MAX_UNZIPPED - self._used
        if info.file_size > room:
            raise XlsxError(TOO_BIG)
        try:
            with self._zf.open(info) as f:
                data = f.read(room + 1)   # 적힌 크기를 믿지 않고 실제로 푼 크기를 센다
        except (XlsxError, MemoryError):
            raise
        except Exception as exc:   # noqa: BLE001 - 손상된 zip 한 부분: zlib.error·LZMAError·BadZipFile(CRC)·모르는 압축 방식 등
            raise XlsxError(BROKEN) from exc
        self._used += len(data)
        if len(data) > room:
            raise XlsxError(TOO_BIG)
        if len(data) > RATIO_GRACE and len(data) > MAX_RATIO * max(info.compress_size, 1):
            raise XlsxError(TOO_PACKED)   # 압축 폭탄: 작은 파일이 상한 가까이 풀려 수 초씩 읽게 하는 것
        if _DTD_RE.search(data):   # 내부 엔터티 확장(억만 웃음) 등을 막는다. 정상 xlsx에는 DTD가 없다
            raise XlsxError(BROKEN)
        return data


_FEED_CHUNK = 1024   # expat에 한 번에 넣는 바이트 수(아래 _events)


def _events(data: bytes):
    """ET.iterparse(events=("start", "end"))와 같은 (사건, 요소)를 내되, 글을 작게 나눠 넣는다.

    iterparse는 16KB씩 넣어, 깊이를 검사하기 전에 '<a>'만 5천 단계 넘게 이어진 나무가 먼저 만들어질 수 있다. 앱의
    Pyodide는 그런 나무를 풀어 줄 때 스택이 넘쳐 엔진이 죽으므로, 1KB씩 넣어 검사 전에 미리 생기는 단계를
    341(=1024/3) 안으로 묶는다."""
    parser = ET.XMLPullParser(events=("start", "end"))
    for k in range(0, len(data), _FEED_CHUNK):
        parser.feed(data[k:k + _FEED_CHUNK])
        yield from parser.read_events()
    parser.close()
    yield from parser.read_events()


def _parse(data: bytes) -> ET.Element:
    """ET.fromstring과 같은 나무. 깊이(MAX_XML_DEPTH)·요소 수(MAX_TREE_ELEMENTS)를 넘거나 XML이 잘못되면 XlsxError."""
    root: Optional[ET.Element] = None
    depth = count = 0
    try:
        for event, el in _events(data):
            if event == "end":
                depth -= 1
                continue
            depth += 1
            count += 1
            if depth > MAX_XML_DEPTH or count > MAX_TREE_ELEMENTS:
                raise XlsxError(BROKEN)
            if root is None:
                root = el
    except XlsxError:
        raise
    except _XML_ERRORS as exc:
        raise XlsxError(BROKEN) from exc
    if root is None:   # 요소가 없는 글은 ParseError로 끝나므로 오지 않는다(만일을 위해)
        raise XlsxError(BROKEN)
    return root


def _detach(stack: list[ET.Element], el: ET.Element) -> None:
    """방금 끝난 요소를 부모에서 뗀다(다시 읽지 않는 요소의 메모리를 바로 돌려준다). 이미 떨어졌으면 그대로."""
    if stack:
        parent = stack[-1]
        if len(parent) and parent[-1] is el:
            del parent[-1]


def _first_sheet_path(pkg: _Package) -> tuple[str, bool]:
    """(첫 시트 경로, 1904 날짜 체계 여부)."""
    book = pkg.read("xl/workbook.xml")
    if book is None:
        raise XlsxError(NOT_EXCEL)
    root = _parse(book)
    date1904 = False
    rid: Optional[str] = None
    # 날짜 체계는 통합 문서 바로 아래 workbookPr에서만 읽는다. 엑셀은 extLst 안에도 x14:workbookPr
    # (chartTrackingRefBase 등, date1904 없음)를 적으므로 그것이 앞의 값을 덮으면 1904 파일 날짜가 1462일 어긋난다.
    for el in root:
        if _local(el.tag) == "workbookPr":
            date1904 = str(_attr(el, "date1904") or "").strip().lower() in ("1", "true")
            break
    for el in root.iter():
        if _local(el.tag) == "sheet" and rid is None:
            rid = _attr(el, "id")
    if rid:
        rels = pkg.read("xl/_rels/workbook.xml.rels")
        if rels is not None:
            for rel in _parse(rels).iter():
                if _local(rel.tag) == "Relationship" and rel.get("Id") == rid:
                    target = (rel.get("Target") or "").replace("\\", "/")
                    path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                        posixpath.join("xl", target))
                    if pkg.has(path):
                        return path, date1904
    sheets = sorted((n for n in pkg.names() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n, re.IGNORECASE)),
                    key=lambda n: int(re.sub(r"\D", "", n.rsplit("/", 1)[-1]) or 0))
    if not sheets:
        raise XlsxError(BROKEN)
    return sheets[0], date1904


def _text_of(si: ET.Element) -> str:
    """<si>·<is> 안의 글(서식 있는 글의 여러 조각 포함). 읽는 법 조각(<rPh>)은 뺀다.

    문서 순서대로 <t>의 글을 잇는다(<t> 안쪽과 <rPh> 안쪽은 보지 않는다). 재귀 대신 반복자 더미로 걷는다
    (깊게 중첩된 글에서 RecursionError가 나지 않게)."""
    parts: list[str] = []
    stack = [iter(si)]
    while stack:
        for child in stack[-1]:
            name = _local(child.tag)
            if name == "rPh":
                continue
            if name == "t":
                parts.append(child.text or "")
                continue
            stack.append(iter(child))
            break
        else:
            stack.pop()
    return "".join(parts)


def _shared_strings(pkg: _Package) -> list[str]:
    data = pkg.read("xl/sharedStrings.xml")
    if data is None:
        return []
    out: list[str] = []
    stack: list[ET.Element] = []   # 열린 요소(부모 찾기·깊이)
    open_si = kept = 0             # 열린 <si> 수, 바깥 <si> 하나를 읽는 동안 담아 둔 요소 수
    try:
        for event, el in _events(data):
            if event == "start":
                stack.append(el)
                if len(stack) > MAX_XML_DEPTH:
                    raise XlsxError(BROKEN)
                if open_si:
                    kept += 1
                    if kept > MAX_KEPT_ELEMENTS:
                        raise XlsxError(BROKEN)
                if _local(el.tag) == "si":
                    open_si += 1
                continue
            stack.pop()
            if _local(el.tag) == "si":
                out.append(_text_of(el))
                el.clear()
                open_si -= 1
                if not open_si:
                    kept = 0
            if not open_si:   # 열린 <si> 밖에서 끝난 요소는 다시 읽지 않는다
                _detach(stack, el)
    except XlsxError:
        raise
    except _XML_ERRORS as exc:
        raise XlsxError(BROKEN) from exc
    return out


def format_kind(code: str) -> Optional[str]:
    """사용자 서식 문자열 → 'date' | 'time' | 'datetime' | None(날짜·시각 서식이 아님)."""
    s = re.sub(r'"[^"]*"', "", code or "")            # 따옴표로 묶은 글
    s = re.sub(r"\\.", "", s)                          # \ 뒤 한 글자
    s = re.sub(r"_.|\*.", "", s)                       # 칸 맞춤용 문자
    s = re.sub(r"\[(h+|m+|s+)\]", r"\1", s, flags=re.IGNORECASE)   # 경과 시간 [h]:mm
    # [Red]·[$-412] 같은 색·지역 표시. 마지막 ']' 뒤의 '['는 짝이 없어 남으므로 그 앞까지만 정규식에 넘긴다
    # (짝 없는 '['가 수만 개인 서식에서 생기던 이차 시간을 없앤다. 결과는 같다. 퍼징으로 찾음)
    end = s.rfind("]") + 1
    s = re.sub(r"\[[^\]]*\]", "", s[:end]) + s[end:]
    s = s.split(";")[0].lower()
    if s.strip() in ("", "general", "@"):
        return None
    has_time = "h" in s or "s" in s
    has_date = "y" in s or "d" in s or ("m" in s and not has_time)
    if has_date and has_time:
        return "datetime"
    if has_date:
        return "date"
    if has_time:
        return "time"
    return None


def _style_kinds(pkg: _Package) -> list[Optional[str]]:
    """칸 서식 번호(c의 s 속성) → 날짜 종류. styles.xml의 cellXfs 순서."""
    data = pkg.read("xl/styles.xml")
    if data is None:
        return []
    root = _parse(data)
    custom: dict[int, str] = {}
    kinds: list[Optional[str]] = []
    custom_kind: dict[int, Optional[str]] = {}   # 같은 사용자 서식을 쓰는 xf가 많아도 한 번만 해석
    for el in root.iter():
        if _local(el.tag) == "numFmt":
            try:
                custom[int(el.get("numFmtId", ""))] = el.get("formatCode", "")
            except ValueError:
                continue
    for el in root.iter():
        if _local(el.tag) != "cellXfs":
            continue
        for xf in el:
            if _local(xf.tag) != "xf":
                continue
            try:
                fid = int(xf.get("numFmtId", "0"))
            except ValueError:
                fid = 0
            if fid in custom:
                if fid not in custom_kind:
                    custom_kind[fid] = format_kind(custom[fid])
                kinds.append(custom_kind[fid])
            elif fid in _BUILTIN_DATETIME:
                kinds.append("datetime")
            elif fid in _BUILTIN_DATE:
                kinds.append("date")
            elif fid in _BUILTIN_TIME:
                kinds.append("time")
            else:
                kinds.append(None)
        break
    return kinds


def serial_to_text(value: float, kind: str, date1904: bool = False) -> Optional[str]:
    """엑셀 일련번호 → 글. 초 단위로 반올림한다(08:50:37이 08:50:36으로 줄지 않게). 범위 밖이면 None."""
    if not (0 <= value < _MAX_SERIAL):
        return None
    secs = int(round(value * 86400))
    if kind == "time":
        secs %= 86400
        return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    try:
        dt = (_EPOCH_1904 if date1904 else _EPOCH_1900) + timedelta(seconds=secs)
    except OverflowError:
        return None
    if kind == "date" and secs % 86400 == 0:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _number_text(raw: str) -> tuple[str, Optional[float]]:
    """숫자 칸의 글과 값. 정수면 소수점 없이, 지수 표기는 풀어 쓴다."""
    raw = raw.strip()
    try:
        value = float(raw)
    except ValueError:
        return raw, None
    if value != value or value in (float("inf"), float("-inf")):
        return raw, None
    if re.fullmatch(r"-?\d+", raw):
        return raw, value
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value)), value
    return format(value, ".15g"), value


def _col_index(ref: Optional[str], fallback: int) -> int:
    if ref:
        m = _REF_RE.match(ref.strip())
        if m:
            n = 0
            for ch in m.group(1).upper():
                n = n * 26 + (ord(ch) - 64)
            return n - 1
    return fallback


# 칸 하나: (글, 숫자 값(숫자 칸이고 서식으로 날짜를 바꾸지 않았을 때만), 서식으로 날짜를 바꿨는지)
_Cell = tuple[str, Optional[float]]


def _read_rows(data: bytes, shared: list[str], kinds: list[Optional[str]],
               date1904: bool) -> list[list[_Cell]]:
    rows: list[list[_Cell]] = []
    sheet_data: Optional[ET.Element] = None
    last_row = 0
    n_cells = 0
    stack: list[ET.Element] = []   # 열린 요소(부모 찾기·깊이)
    open_rows = kept = 0           # 열린 <row> 수, 바깥 <row> 하나를 읽는 동안 담아 둔 요소 수
    try:
        for event, el in _events(data):
            name = _local(el.tag)
            if event == "start":
                stack.append(el)
                if len(stack) > MAX_XML_DEPTH:
                    raise XlsxError(BROKEN)
                if open_rows:
                    kept += 1
                    if kept > MAX_KEPT_ELEMENTS:
                        raise XlsxError(BROKEN)
                if name == "sheetData":
                    sheet_data = el
                elif name == "row":
                    open_rows += 1
                continue
            stack.pop()
            if name == "row":
                open_rows -= 1
                if not open_rows:
                    kept = 0
                number = _row_number(el, last_row)
                cells: dict[int, _Cell] = {}
                col = -1
                for c in el:
                    if _local(c.tag) != "c":
                        continue
                    col = _col_index(c.get("r"), col + 1)
                    if col >= MAX_COLS or col < 0:
                        continue
                    cell = _cell_value(c, shared, kinds, date1904)
                    if cell[0] != "":
                        cells[col] = cell
                el.clear()
                if sheet_data is not None:
                    sheet_data.clear()   # 읽은 줄을 버려 메모리를 아낀다
                if cells:
                    if number > MAX_ROWS:
                        raise XlsxError(TOO_MANY_ROWS)
                    number = max(number, last_row + 1)
                    rows.extend([] for _ in range(number - last_row - 1))   # 빈 줄(줄 번호를 엑셀과 맞춘다)
                    width = max(cells) + 1
                    n_cells += width
                    if n_cells > MAX_CELLS:
                        raise XlsxError(TOO_MANY_CELLS)
                    rows.append([cells.get(k, ("", None)) for k in range(width)])
                    last_row = number
            if not open_rows:   # 열린 <row> 밖에서 끝난 요소(다 읽은 줄 포함)는 다시 읽지 않는다
                _detach(stack, el)
    except XlsxError:
        raise
    except _XML_ERRORS as exc:
        raise XlsxError(BROKEN) from exc
    return rows


def _row_number(row: ET.Element, last_row: int) -> int:
    """<row r="..">의 줄 번호. 없거나 0이거나 숫자가 아니면 앞 줄 다음."""
    try:
        return int(row.get("r", "") or 0) or last_row + 1
    except ValueError:
        return last_row + 1


def _cell_value(c: ET.Element, shared: list[str], kinds: list[Optional[str]], date1904: bool) -> _Cell:
    kind = c.get("t", "n")
    v_text: Optional[str] = None
    inline: Optional[ET.Element] = None
    for child in c:
        name = _local(child.tag)
        if name == "v":
            v_text = child.text or ""
        elif name == "is":
            inline = child
    if kind == "inlineStr":
        return (_text_of(inline) if inline is not None else ""), None
    if v_text is None:
        return "", None
    if kind == "s":
        try:
            idx = int(v_text)
        except ValueError:
            return "", None
        return (shared[idx] if 0 <= idx < len(shared) else ""), None
    if kind in ("str", "d"):
        return v_text, None
    if kind == "b":
        return ("TRUE" if v_text.strip() in ("1", "true") else "FALSE"), None
    if kind == "e":
        return "", None
    text, value = _number_text(v_text)
    if value is not None:
        try:
            style = kinds[int(c.get("s", "0") or 0)]
        except (ValueError, IndexError):
            style = None
        if style:
            converted = serial_to_text(value, style, date1904)
            if converted is not None:
                return converted, None
    return text, value


def _convert_by_header(rows: list[list[_Cell]], date1904: bool) -> list[list[str]]:
    """서식이 일반인 날짜·시각 열: 머리글(날짜·일시 / 시간·시각)을 보고 일련번호를 바꾼다."""
    date_cols: set[int] = set()
    time_cols: set[int] = set()
    header_at = -1
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        for k, (text, value) in enumerate(row):
            label = text.strip().casefold()
            if value is not None or not label or len(label) > 20:
                continue
            if any(h in label for h in _DATE_HEADERS):
                date_cols.add(k)
            elif any(h in label for h in _TIME_HEADERS):
                time_cols.add(k)
        if date_cols or time_cols:
            header_at = i
            break
    out: list[list[str]] = []
    for i, row in enumerate(rows):
        line: list[str] = []
        for k, (text, value) in enumerate(row):
            if i > header_at >= 0 and value is not None:
                if k in date_cols and value >= 1:
                    text = serial_to_text(value, "datetime" if value % 1 else "date", date1904) or text
                elif k in time_cols and 0 <= value < 1:
                    text = serial_to_text(value, "time", date1904) or text
            line.append(text)
        while line and line[-1] == "":
            line.pop()
        out.append(line)
    return out


def is_zip(data: bytes) -> bool:
    return data[:4] in (b"PK\x03\x04", b"PK\x05\x06")


def xlsx_to_csv_text(data: bytes) -> str:
    """xlsx 바이트 → 첫 시트의 CSV 글(쉼표, 줄바꿈 \\n). 엑셀이 아닌 zip·손상·너무 큰 파일은 XlsxError."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except MemoryError:
        raise
    except Exception as exc:   # noqa: BLE001 - 손상된 zip 목차: BadZipFile·모르는 zip 판(NotImplementedError) 등(퍼징으로 찾음)
        raise XlsxError(BROKEN) from exc
    with zf:
        pkg = _Package(zf)
        if not pkg.has("xl/workbook.xml"):
            raise XlsxError(NOT_EXCEL)
        sheet_path, date1904 = _first_sheet_path(pkg)
        shared = _shared_strings(pkg)
        kinds = _style_kinds(pkg)
        sheet = pkg.read(sheet_path)
        if sheet is None:
            raise XlsxError(BROKEN)
        rows = _read_rows(sheet, shared, kinds, date1904)
    return rows_to_csv_text(rows, date1904)


def rows_to_csv_text(rows: list[list[_Cell]], date1904: bool = False) -> str:
    """칸 목록(글, 숫자 값) → CSV 글. 서식이 일반인 날짜·시각 열은 머리글을 보고 바꾼다(.xls 읽기도 같이 쓴다)."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for line in _convert_by_header(rows, date1904):
        writer.writerow(line)
    return buf.getvalue()


__all__ = ["MAX_CELLS", "MAX_COLS", "MAX_ENTRIES", "MAX_RATIO", "MAX_ROWS", "MAX_UNZIPPED", "MAX_XML_DEPTH",
           "XlsxError", "format_kind", "is_zip", "rows_to_csv_text", "serial_to_text", "xlsx_to_csv_text"]
