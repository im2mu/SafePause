"""실제 은행·카드사 거래내역 파일 모양에 대비한 불러오기 시험(2026-10-03).

모든 시험 자료는 조사한 구조만 흉내 낸 합성 파일이다(값은 가짜). 실제 은행 이름은 이 기록과 시험 파일 이름에만 쓴다
(앱 화면에는 쓰지 않는다). 실제 은행 파일로 시험한 적은 없다.

조사 기록(공개 자료만, 개인정보 파일은 열지 않음. 확인 못 한 것은 '미확인')
---------------------------------------------------------------------------------------------------
기관·메뉴              파일                         확인한 구조                                         출처
기업은행 거래내역조회    확장자 .xls인 HTML 표          첫 표=제목·메타 줄, 둘째 표 첫 줄 <th> 머리글: No·거래일시·출금·입금·   [A]
                       (인코딩 미확인: 그 코드는         거래후 잔액·거래내용·송금메시지·상대계좌번호·상대은행·거래구분·
                        UTF-8 → CP949 순서로 시도)   수표어음금액·CMS코드·상대계좌예금주명. 거래일시 YYYY-MM-DD HH:MM:SS,
                                                    금액 '38,000'·'0', 거래구분 예 타행이체·체크·펌이체
현대카드 웹 이용내역     확장자 .xls인 HTML 표          위에 메타 줄, 끝에 '국내 일시불 소계 N건'·'본인 소계' 줄, 취소·환불은   [A]
                                                    음수 금액, 날짜 '2026년 05월 30일'·'2026.05.30'. 열 이름은 이용일·
                                                    이용가맹점·이용금액 등(코드의 별칭 목록이라 정확한 열 구성은 미확인)
카카오뱅크 앱 내보내기   .xlsx(이메일 첨부), Office 표준   시트 '카카오뱅크 거래내역', 머리글 11번째 줄: 거래일시·구분·거래금액·      [B][A][C]
                       암호화(ECMA-376 Agile, 복합 문서로   거래 후 잔액·거래구분·내용·메모. 구분 = 입금/출금. 금액 부호(출금 음수)·
                       감쌈, 비밀번호 생년월일 6자리)      날짜 모양은 시험 데이터 기준이라 미확인
KB국민은행 앱 .xls      진짜 엑셀 97~2003(BIFF, xlrd로 읽음) 머리글 위 안내 줄 있음('거래일시' 칸으로 머리글을 찾음). 거래일시      [D]
                                                    'YYYY.MM.DD …', 보낸분/받는분, 출금액(숫자 칸). 다른 열 미확인
KB국민카드 앱 .xls      BIFF(xlrd)                     이용일, 이용하신곳, '국내이용금액\\n(원)'(머리글 칸 안 줄바꿈). 해외 이용은 [D]
                                                    국내이용금액 0. 할부·결제방법 열은 그 저장소의 시험 CSV 기준(미확인)
신한카드 이용내역        Shinhancard_YYYYMMDD.xlsx      머리글에 거래일·가맹점명, 날짜 YYYY.MM.DD, 승인번호·취소 표시 열(이름 미확인) [E]
우리카드                이용대금명세서 report.xls(형식 미확인) 날짜 'MM.DD'(연도 없음 → 지원 안 함), 구분 값 국내일시불·국내체크·   [E][F]
                                                    국내할부·취소·해외취소. 웹 이용내역 엑셀 열: 이용일·승인번호·이용카드·
                                                    이용가맹점·사업자번호·할부개월·이용금액·취소금액·결제예정일
토스뱅크                입출금 거래내역서는 PDF         카드 이용내역확인서(부가세용) 이메일 엑셀은 검색 요약뿐(원문·열 미확인)   [G]
예금거래내역서(기관 미확인) 미확인                        거래일자·찾으신금액·맡기신금액·남은금액·거래내용·거래기록사항·거래점      [H]
은행·카드사 일반         'HTML 기반' 엑셀 파일이 엑셀 보호된 보기에서 막힌 사례(2016)                                     [I]
신한·우리·하나·농협은행, 케이뱅크: 엑셀 저장 기능은 있으나 파일 형식·열 이름 미확인(원문 확인 못 함)
통신사 휴대폰 소액결제: 화면 조회만 확인, 파일 내려받기 형식 미확인

[A] https://github.com/orpheus393/budget (app.py parse_ibk_account_file·parse_hyundai_file·parse_kakaobank_file,
    scripts/test_ibk_parser.py, tests/test_kakao_export.py; 2026-09 갱신)
[B] https://github.com/Gigang-ST/gigang-client/issues/570
[C] https://laystory.com/entry/카카오뱅크-입출금-거래내역-엑셀-저장-방법-정리 (이메일 발송·생년월일 6자리 암호)
[D] https://github.com/kimshuk/budget-tracker (parsers/kb_bank.py·kb_card.py, README '앱에서 내보낸 .xls'; 2026-06)
[E] https://github.com/eunjo-jang/moa (index.html parseWoori·parseShinhan)
[F] https://thisthatbase.com/wooricard-payment-history/
[G] https://www.clien.net/service/board/park/17101054 (2022, 거래내역은 PDF만)
[H] https://ko.hinative.com/questions/20291368 (질문 제목에 적힌 열 이름)
[I] https://learn.microsoft.com/ko-kr/answers/questions/667a403e-f320-4a31-ab04-89fab0f81324

시험 자료
- tests/fixtures/bank_formats/ : 글 파일(HTML 표 .xls, 탭 .txt). CSV는 저장소 규칙(.gitignore `*.csv`, 배포 zip은
  sample_data 밖 CSV를 뺌: 실제 거래내역 CSV가 섞이지 않게)에 따라 파일로 두지 않고 이 파일 안 글에서 만든다.
- .xlsx·.xls(BIFF8)·암호 걸린 엑셀은 이 파일 안에서 표준 라이브러리(zipfile·struct)로 만든다(아래 만들기 함수).

엑셀 교차 확인(2026-10-03, 저장소 밖에서 한 번. 엑셀이 만든 파일에는 저장한 폴더 경로 등이 들어가므로 저장소에 넣지 않음)
- Microsoft 365 엑셀이 저장한 .xls(BIFF8, 1900·1904 날짜 체계, 405줄: 글 날짜·날짜/시각 서식 숫자·#,##0·수식 글/숫자/
  참거짓/오류·음수 소수, 공유 문자열이 8,224바이트를 넘어 CONTINUE로 나뉨)을 data.xls가 기대값과 한 칸도 다르지 않게 읽었고,
  같은 통합 문서를 .xlsx로 저장한 것과 CSV 글이 같았다(이때 .xlsx 1904 날짜 버그를 찾아 고침).
- 엑셀이 암호를 걸어 저장한 .xls(FILEPASS)·.xlsx(암호로 감싼 복합 문서)는 '암호가 걸린 엑셀' 안내가 나왔다.
- 아래 make_cfb·make_xls로 만든 파일(미니 스트림, 4096바이트 섹터, DIFAT 섹터가 있는 7.4MB 파일, 37·64바이트에서 나눈
  CONTINUE, LABEL·수식·참거짓·오류·MULRK·1904)을 엑셀이 열어 의도한 값과 같게 읽었다. 단, 가짜 SHRFMLA를 넣은 파일은 엑셀이
  거부하므로 그 레코드는 shrfmla=True일 때만 넣는다(읽는 쪽이 건너뛰는지 보는 시험용).
"""
from __future__ import annotations

import io
import json
import struct
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.sax.saxutils import escape

import pytest

from safepause.data import htmltable, xls
from safepause.data.loader import LoaderError, load_csv, plain_message
from safepause.models import Channel, Direction

FIXTURES = Path(__file__).parent / "fixtures" / "bank_formats"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _summary(txns) -> list[tuple[str, str, int, str]]:
    return [(t.ts.strftime("%Y-%m-%d %H:%M:%S"), t.direction.value, t.amount, t.counterparty) for t in txns]


# ======================================================================================
# 만들기 함수: 복합 문서(CFB) · BIFF8 .xls · .xlsx (표준 라이브러리만)
# ======================================================================================

ENDOFCHAIN, FREESECT, FATSECT, DIFSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFC, 0xFFFFFFFF


def make_cfb(streams: dict[str, bytes], *, sector_shift: int = 9) -> bytes:
    """[MS-CFB] 복합 문서. 4096바이트보다 작은 스트림은 미니 스트림에 넣는다. 디렉터리는 이름 순 오른쪽 사슬.
    FAT 섹터 번호는 머리에 109개까지 적고 나머지는 DIFAT 섹터에 적는다."""
    ss = 1 << sector_shift
    per = ss // 4
    names = sorted(streams, key=lambda n: (len(n), n.upper()))
    mini = bytearray()
    minifat: list[int] = []
    where: dict[str, int] = {}
    for name in names:
        data = streams[name]
        if 0 < len(data) < 4096:
            first, n = len(mini) // 64, -(-len(data) // 64)
            minifat += [first + k + 1 for k in range(n - 1)] + [ENDOFCHAIN]
            mini += data.ljust(n * 64, b"\0")
            where[name] = first

    def nsec(nbytes: int) -> int:
        return -(-nbytes // ss)

    regions: list[tuple[str, bytes]] = [("dir", b"\0" * (128 * (1 + len(names)))),
                                        ("minifat", b"".join(struct.pack("<I", v) for v in minifat)),
                                        ("mini", bytes(mini))]
    regions += [(name, streams[name]) for name in names if len(streams[name]) >= 4096]
    n_data = sum(nsec(len(d)) for _, d in regions)
    n_fat = n_difat = 0
    while True:
        need_fat = -(-(n_data + n_fat + n_difat) // per)
        need_difat = 0 if need_fat <= 109 else -(-(need_fat - 109) // (per - 1))
        if (need_fat, need_difat) == (n_fat, n_difat):
            break
        n_fat, n_difat = need_fat, need_difat
    fat = [FREESECT] * (n_fat * per)
    for k in range(n_fat):
        fat[k] = FATSECT
    for k in range(n_difat):
        fat[n_fat + k] = DIFSECT
    pos = n_fat + n_difat
    start: dict[str, int] = {}
    for key, data in regions:
        n = nsec(len(data))
        start[key] = pos if n else ENDOFCHAIN
        for k in range(n):
            fat[pos + k] = pos + k + 1 if k < n - 1 else ENDOFCHAIN
        pos += n

    def entry(name: str, kind: int, right: int, child: int, first: int, size: int) -> bytes:
        raw = name.encode("utf-16-le") + b"\0\0"
        return (raw.ljust(64, b"\0") + struct.pack("<HBB", len(raw), kind, 1) + struct.pack("<III", NOSTREAM, right, child)
                + b"\0" * 36 + struct.pack("<IQ", first, size))

    dir_bytes = entry("Root Entry", 5, NOSTREAM, 1 if names else NOSTREAM, start["mini"], len(mini))
    for k, name in enumerate(names, start=1):
        data = streams[name]
        first = where.get(name, start.get(name, ENDOFCHAIN)) if data else ENDOFCHAIN
        dir_bytes += entry(name, 2, k + 1 if k < len(names) else NOSTREAM, NOSTREAM, first, len(data))
    empty = b"\0" * 68 + struct.pack("<III", NOSTREAM, NOSTREAM, NOSTREAM) + b"\0" * 48
    dir_bytes += empty * ((-len(dir_bytes) // 128) % (ss // 128))
    regions[0] = ("dir", dir_bytes)

    header = bytearray(512)
    header[:8] = xls.CFB_MAGIC
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3 if ss == 512 else 4, 0xFFFE, sector_shift, 6)
    struct.pack_into("<IIIIIIIII", header, 0x28, 0 if ss == 512 else nsec(len(dir_bytes)), n_fat, start["dir"], 0,
                     4096, start["minifat"], nsec(len(regions[1][1])),
                     n_fat if n_difat else ENDOFCHAIN, n_difat)
    fat_ids = list(range(n_fat))
    head_ids = (fat_ids[:109] + [FREESECT] * 109)[:109]
    struct.pack_into("<109I", header, 0x4C, *head_ids)
    out = bytearray(bytes(header).ljust(ss, b"\0"))
    for k in range(n_fat):
        out += struct.pack(f"<{per}I", *fat[k * per:(k + 1) * per])
    rest = fat_ids[109:]
    for k in range(n_difat):
        chunk = rest[k * (per - 1):(k + 1) * (per - 1)]
        nxt = n_fat + k + 1 if k < n_difat - 1 else ENDOFCHAIN
        out += struct.pack(f"<{per}I", *(chunk + [FREESECT] * (per - 1 - len(chunk))), nxt)
    for _key, data in regions:
        out += data.ljust(nsec(len(data)) * ss, b"\0")
    return bytes(out)


def _rec(rid: int, body: bytes = b"") -> bytes:
    return struct.pack("<HH", rid, len(body)) + body


def _ustr(text: str, short: bool = False) -> bytes:
    """XLUnicodeString(short=True면 ShortXLUnicodeString). 0~255 글자만이면 1바이트로 줄여 적는다."""
    try:
        raw, flag = text.encode("latin-1"), 0
    except UnicodeEncodeError:
        raw, flag = text.encode("utf-16-le"), 1
    return (struct.pack("<BB", len(text), flag) if short else struct.pack("<HB", len(text), flag)) + raw


def _sst(strings: list[str], limit: int) -> bytes:
    """SST + CONTINUE. 글자 부분이 나뉘면 CONTINUE 첫 바이트에 글자 폭을 적는다(엑셀과 같은 방식)."""
    pieces: list[bytes] = []
    cur = bytearray(struct.pack("<II", len(strings), len(strings)))
    for s in strings:
        high = any(ord(c) > 255 for c in s)
        width = 2 if high else 1
        enc = s.encode("utf-16-le") if high else s.encode("latin-1")
        if len(cur) + 3 + width > limit:
            pieces.append(bytes(cur))
            cur = bytearray()
        cur += struct.pack("<HB", len(s), 1 if high else 0)
        done = 0
        while done < len(enc):
            room = (limit - len(cur)) // width * width
            if room <= 0:
                pieces.append(bytes(cur))
                cur = bytearray([1 if high else 0])
                continue
            take = min(room, len(enc) - done)
            cur += enc[done:done + take]
            done += take
    pieces.append(bytes(cur))
    return _rec(0x00FC, pieces[0]) + b"".join(_rec(0x003C, p) for p in pieces[1:])


def _rk(value: float) -> Optional[int]:
    if float(value).is_integer() and -(1 << 29) <= value < (1 << 29):
        return ((int(value) << 2) & 0xFFFFFFFF) | 2
    raw = struct.unpack("<Q", struct.pack("<d", float(value)))[0]
    if raw & 0x3FFFFFFFF == 0:
        return raw >> 32
    return None


XF_GENERAL, XF_DATE, XF_DATETIME, XF_TIME = 15, 16, 17, 18   # 셀 서식 번호: 일반, 날짜(내장 14), 사용자 날짜·시각(164), 시각(내장 20)

_STYLE_XF = bytes.fromhex("00000000F5FF200000F40000000000000000C020")
_CELL_XF = bytes.fromhex("000000000100200000000000000000000000C020")


def _xf(ifmt: int) -> bytes:
    body = bytearray(_CELL_XF)
    struct.pack_into("<H", body, 2, ifmt)
    if ifmt:
        body[9] = 0x04   # 숫자 서식을 이 칸에서 정함
    return _rec(0x00E0, bytes(body))


def make_xls(cells: list[tuple], *, sst: bool = True, sst_limit: int = 8224, date1904: bool = False,
             filepass: bool = False, version: int = 0x0600, chart_inside: bool = False,
             chart_sheet_first: bool = False, second_sheet: bool = True, shrfmla: bool = False) -> bytes:
    """BIFF8 Workbook 스트림. cells: (줄, 칸, 값[, 서식]) 목록(0부터). 값: str(글), int·float(숫자 → RK 또는 NUMBER),
    ("num", v)(NUMBER로), ("mulrk", [v...])(MULRK, 칸부터 오른쪽으로), ("fstr", 글)(글 결과 수식 + STRING),
    ("fnum", v)(숫자 수식), ("bool", 참거짓), ("err",)(오류 값), ("label", 글)(LABEL 레코드)."""
    strings: list[str] = []
    for c in cells:
        if isinstance(c[2], str) and sst and c[2] not in strings:
            strings.append(c[2])

    def bof(dt: int) -> bytes:
        return _rec(0x0809, struct.pack("<HHHHII", version, dt, 0x0DBB, 0x07CC, 0, 6))

    def sheet_stream(content: list[tuple]) -> bytes:
        out = bytearray(bof(0x0010))
        rows = [c[0] for c in content] or [0]
        out += _rec(0x0200, struct.pack("<IIHHH", min(rows), max(rows) + 1, 0, 64, 0))
        for c in sorted(content, key=lambda x: (x[0], x[1])):
            row, col, value = c[0], c[1], c[2]
            xf = c[3] if len(c) > 3 else XF_GENERAL
            head = struct.pack("<HHH", row, col, xf)
            if isinstance(value, str):
                out += (_rec(0x00FD, head + struct.pack("<I", strings.index(value))) if sst
                        else _rec(0x0204, head + _ustr(value)))
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                rk = _rk(value)
                out += (_rec(0x027E, head + struct.pack("<I", rk)) if rk is not None
                        else _rec(0x0203, head + struct.pack("<d", value)))
            elif value[0] == "num":
                out += _rec(0x0203, head + struct.pack("<d", value[1]))
            elif value[0] == "label":
                out += _rec(0x0204, head + _ustr(value[1]))
            elif value[0] == "mulrk":
                body = struct.pack("<HH", row, col) + b"".join(struct.pack("<HI", xf, _rk(v)) for v in value[1])
                out += _rec(0x00BD, body + struct.pack("<H", col + len(value[1]) - 1))
            elif value[0] == "fstr":
                rgce = b"\x17" + _ustr(value[1], short=True)
                out += _rec(0x0006, head + b"\x00\x00\x00\x00\x00\x00\xff\xff" + struct.pack("<HIH", 0, 0, len(rgce)) + rgce)
                if shrfmla:   # 수식과 STRING 사이에 올 수 있는 레코드(내용은 가짜: 읽는 쪽이 건너뛰는지만 본다)
                    out += _rec(0x04BC, b"\0" * 10)
                out += _rec(0x0207, _ustr(value[1]))
            elif value[0] == "fnum":
                rgce = b"\x1f" + struct.pack("<d", value[1])
                out += _rec(0x0006, head + struct.pack("<d", value[1]) + struct.pack("<HIH", 0, 0, len(rgce)) + rgce)
            elif value[0] == "bool":
                out += _rec(0x0205, head + struct.pack("<BB", 1 if value[1] else 0, 0))
            elif value[0] == "err":
                out += _rec(0x0205, head + struct.pack("<BB", 0x07, 1))
        if chart_inside:   # 시트 안 차트 하위 스트림: 이 안의 칸은 읽지 않아야 한다
            out += bof(0x0020) + _rec(0x0203, struct.pack("<HHHd", 0, 0, XF_GENERAL, 999.0)) + _rec(0x000A)
        out += _rec(0x023E, struct.pack("<HHHIHHI", 0x06B6, 0, 0, 0x40, 0, 0, 0))
        out += _rec(0x000A)
        return bytes(out)

    sheets = [("거래내역", 0, sheet_stream(cells))]
    if chart_sheet_first:
        sheets.insert(0, ("차트", 2, bof(0x0020) + _rec(0x000A)))
    if second_sheet:
        sheets.append(("다른 시트", 0, sheet_stream([(0, 0, ("label", "이 시트는 읽지 않아요"))])))

    def globals_stream(offsets: list[int]) -> bytes:
        out = bytearray(bof(0x0005))
        if filepass:
            out += _rec(0x002F, struct.pack("<H", 1) + b"\0" * 52)
        out += _rec(0x0042, struct.pack("<H", 1200))
        out += _rec(0x003D, struct.pack("<HHHHHHHHH", 0, 0, 0x25BC, 0x1572, 0x38, 0, 0, 1, 0x258))
        out += _rec(0x0022, struct.pack("<H", 1 if date1904 else 0))
        for _ in range(4):
            out += _rec(0x0031, struct.pack("<HHHHHBBBB", 200, 0, 0x7FFF, 400, 0, 0, 0, 0, 0) + _ustr("Arial", short=True))
        out += _rec(0x041E, struct.pack("<H", 164) + _ustr("yyyy\\.mm\\.dd hh:mm:ss"))
        for _ in range(15):
            out += _rec(0x00E0, _STYLE_XF)
        out += _xf(0) + _xf(14) + _xf(164) + _xf(20)
        out += _rec(0x0293, struct.pack("<HBB", 0x8000, 0, 0xFF))
        for (name, kind, _), offset in zip(sheets, offsets):
            out += _rec(0x0085, struct.pack("<IBB", offset, 0, kind) + _ustr(name, short=True))
        if sst:
            out += _sst(strings, sst_limit)
        out += _rec(0x000A)
        return bytes(out)

    base = len(globals_stream([0] * len(sheets)))
    offsets, pos = [], base
    for _, _, stream in sheets:
        offsets.append(pos)
        pos += len(stream)
    return globals_stream(offsets) + b"".join(s for _, _, s in sheets)


def xls_file(cells: list[tuple], *, sector_shift: int = 9, extra: Optional[dict] = None,
             **kw: Any) -> bytes:
    streams = {"Workbook": make_xls(cells, **kw)}
    streams.update(extra or {})
    return make_cfb(streams, sector_shift=sector_shift)


def serial(dt: datetime, date1904: bool = False) -> float:
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    return (dt - base).total_seconds() / 86400


def grid(rows: list[list[Any]], first_row: int = 0) -> list[tuple]:
    """줄 목록 → (줄, 칸, 값[, 서식]) 목록. 값이 None이면 칸 없음. (값, 서식) 쌍이면 서식 번호를 붙인다."""
    out: list[tuple] = []
    for r, row in enumerate(rows, start=first_row):
        for c, value in enumerate(row):
            if value is None:
                continue
            if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], int) and value[0] not in (
                    "num", "label", "fstr", "fnum", "bool", "mulrk"):
                out.append((r, c, value[0], value[1]))
            else:
                out.append((r, c, value))
    return out


_XMLNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def make_xlsx(rows: list[list[Any]], date1904: bool = False) -> bytes:
    """최소 .xlsx(글은 인라인 글, 숫자는 숫자 칸, (일련번호, 'date')는 날짜·시각 서식 칸). 첫 시트 이름은 거래내역.
    date1904: 엑셀이 저장한 1904 날짜 체계 파일처럼 workbookPr에 date1904를 적고, extLst 안에도
    x14:workbookPr(chartTrackingRefBase, date1904 없음)를 적는다(Microsoft 365 엑셀 저장 파일에서 확인한 모양)."""
    def cell(ref: str, value: Any) -> str:
        if isinstance(value, tuple):
            return f'<c r="{ref}" s="1"><v>{value[0]!r}</v></c>'
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value!r}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'

    body = []
    for r, row in enumerate(rows, start=1):
        cells = "".join(cell(f"{chr(65 + c)}{r}", v) for c, v in enumerate(row) if v not in (None, ""))
        body.append(f'<row r="{r}">{cells}</row>')
    sheet = f'<worksheet {_XMLNS}><sheetData>{"".join(body)}</sheetData></worksheet>'
    styles = (f'<styleSheet {_XMLNS}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\.mm\\.dd hh:mm:ss"/>'
              '</numFmts><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="164" applyNumberFormat="1"/></cellXfs>'
              '</styleSheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        pr = '<workbookPr date1904="1" defaultThemeVersion="202300"/>' if date1904 else ""
        ext = ('<extLst><ext uri="{140A7094-0E35-4892-8432-C4D2E57EDEB5}" '
               'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
               '<x14:workbookPr chartTrackingRefBase="1"/></ext></extLst>') if date1904 else ""
        zf.writestr("xl/workbook.xml", f'<workbook {_XMLNS} {_RNS}>{pr}<sheets><sheet name="거래내역" sheetId="1" '
                                       f'r:id="rId1"/></sheets>{ext}</workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/styles.xml", styles)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _fake_bytes(n: int, seed: int = 7) -> bytes:
    out, x = bytearray(), seed
    while len(out) < n:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(x >> 16 & 0xFF)
    return bytes(out)


def encrypted_xlsx() -> bytes:
    """암호로 감싼 .xlsx 모양([MS-OFFCRYPTO]): 복합 문서 안에 EncryptionInfo·EncryptedPackage 스트림(내용은 가짜)."""
    info = struct.pack("<HHI", 4, 4, 0x40) + b'<?xml version="1.0" encoding="UTF-8"?><encryption/>'
    return make_cfb({"EncryptionInfo": info, "EncryptedPackage": struct.pack("<Q", 6000) + _fake_bytes(6008)})


# ======================================================================================
# 1. HTML 표 .xls (기업은행·현대카드 흉내)
# ======================================================================================

IBK_EXPECTED = [
    ("2026-05-15 02:10:00", "out", 300000, "김*호"),
    ("2026-05-20 18:04:42", "out", 148070, "가상보험(주)"),       # 상대계좌예금주명이 거래내용보다 먼저
    ("2026-05-31 09:37:18", "out", 14000, "테스트식당"),          # 예금주명이 비면 거래내용
    ("2026-05-31 09:56:17", "in", 38000, "가나다"),
]


@pytest.mark.parametrize("name", ["ibk_like_table_utf8.xls", "ibk_like_table_cp949_br.xls"])
def test_html_table_xls_like_ibk(name: str) -> None:
    txns, report = load_csv(_fixture(name))
    assert report["encoding"] == "html" and report["header_row"] == 1    # 메타 표가 아니라 머리글이 있는 둘째 표
    assert _summary(txns) == IBK_EXPECTED
    assert [t.channel for t in txns] == [Channel.TRANSFER, Channel.TRANSFER, Channel.CARD, Channel.INCOME]
    assert txns[0].counterparty_id == "900-0101-100001" and txns[1].counterparty_id == "가상보험(주)"
    assert report["mapping"]["type_text"] == "거래구분"                  # 거래구분 '체크' → 카드결제 추정
    assert report["skipped"] == 1 and report["skipped_rows"] == [6]       # 잘못된 날짜 줄
    assert any("최근 거래가 위에 있는 파일" in w for w in report["warnings"])


def test_html_table_xls_like_hyundai_card() -> None:
    txns, report = load_csv(_fixture("hyundaicard_like_table.xls"))
    assert _summary(txns) == [("2026-05-27 12:00:00", "out", 4500, "가상카페"),
                              ("2026-05-28 12:00:00", "out", 1200000, "가상전자"),
                              ("2026-05-30 12:00:00", "out", 52300, "가상마트")]
    assert all(t.channel == Channel.CARD for t in txns)
    text = " ".join(report["warnings"])
    assert "합계·소계 줄 2개" in text and "취소로 보이는 1줄" in text and "카드 이용내역으로 보고" in text
    assert report["skipped"] == 3


def test_html_nested_layout_colspan_rowspan_script_and_entities() -> None:
    html = """<!DOCTYPE html><html><head><script>var x = "<table><tr><td>거래일시</td><td>출금액</td></tr>";</script></head>
<body><table><tr><td>
  <table><tr><td colspan="2">제목&nbsp;줄</td></tr></table>
  <table>
    <tr><th>거래일시</th><th>적요</th><th>출금액</th><th>입금액</th><th>내용</th></tr>
    <tr><td rowspan="2">2026.09.01<br/>10:00:00</td><td>체크카드</td><td>1,000</td><td>0</td><td>가&amp;나<style>.x{}</style></td>
    <tr><td>모바일이체</td><td>2,000</td><td>0</td><td>김*호</td></tr>
    <tr><td>2026.09.02 11:00</td><td colspan="2">합계 3,000</td><td>0</td><td></td></tr>
  </table>
</td></tr></table></body></html>"""
    txns, report = load_csv(html.encode("utf-8"))
    assert _summary(txns) == [("2026-09-01 10:00:00", "out", 1000, "가&나"), ("2026-09-01 10:00:00", "out", 2000, "김*호")]
    assert report["skipped"] == 1   # 합계 줄
    assert htmltable.html_tables("<table><tr><td>a<td>b<tr><td>c</table>") == [[["a", "b"], ["c"]]]


def test_html_rowspan_at_row_end_and_header_only_table() -> None:
    assert htmltable.html_tables('<table><tr><td>a</td><td rowspan="2">b</td></tr><tr><td>c</td></tr></table>') == [
        [["a", "b"], ["c", "b"]]]
    with pytest.raises(LoaderError, match="머리글 아래에 거래 줄이 없어요"):
        load_csv("<table><tr><td>거래일시</td><td>출금액</td><td>입금액</td></tr></table>".encode("utf-8"))


@pytest.mark.parametrize("text", [
    "<html><body><p>거래내역이 없습니다</p></body></html>",
    '<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"><Table><Row><Cell>'
    '<Data ss:Type="String">거래일시</Data></Cell></Row></Table></Workbook>',
    "<style>" + "x" * 3000 + "</style><table><tr><td>가</td></tr></table>",
])
def test_html_without_transaction_table_gets_guidance(text: str) -> None:
    with pytest.raises(LoaderError, match="웹 페이지\\(HTML\\) 모양의 파일인데 거래내역 표를 찾지 못했어요"):
        load_csv(text.encode("cp949", errors="replace"))


def test_html_mapping_picks_matching_table_and_reports_missing_columns() -> None:
    html = ("<table><tr><th>거래일시</th><th>출금액</th><th>입금액</th></tr><tr><td>2026-09-01 10:00</td><td>1</td><td>0</td></tr></table>"
            "<table><tr><th>when</th><th>out</th><th>in</th></tr><tr><td>2026-09-02 10:00</td><td>7</td><td>0</td></tr></table>")
    txns, _ = load_csv(html.encode("utf-8"), mapping={"datetime": "when", "out_amount": "out", "in_amount": "in"})
    assert [t.amount for t in txns] == [7]
    with pytest.raises(LoaderError, match="mapping에 적은 열을 파일에서 찾지 못했어요: .*없는열"):
        load_csv(html.encode("utf-8"), mapping={"datetime": "없는열", "out_amount": "out", "in_amount": "in"})


def test_html_too_many_rows(monkeypatch) -> None:
    monkeypatch.setattr(htmltable, "MAX_ROWS", 3)
    rows = "".join("<tr><td>2026-09-01 10:00</td><td>1</td><td>0</td></tr>" for _ in range(5))
    with pytest.raises(LoaderError, match="줄이 너무 많아요"):
        load_csv(f"<table><tr><th>거래일시</th><th>출금액</th><th>입금액</th></tr>{rows}</table>".encode("utf-8"))


def test_html_colspan_and_table_count_limits(monkeypatch) -> None:
    monkeypatch.setattr(htmltable, "MAX_CELLS", 1000)
    bomb = "<table>" + '<tr><td colspan="256">x</td></tr>' * 10 + "</table>"   # 작은 글이 큰 빈 표로 불어남
    with pytest.raises(LoaderError, match="표의 칸이 너무 많아요"):
        load_csv(bomb.encode("utf-8"))
    monkeypatch.setattr(htmltable, "MAX_TABLES", 5)
    with pytest.raises(LoaderError, match="너무 커요"):
        load_csv(("<table>" * 6).encode("utf-8"))


def test_html_table_text_input_and_utf16() -> None:
    html = "<table>\n<tr><th>거래일시</th><th>출금액</th><th>입금액</th></tr>\n<tr><td>2026-09-01 10:00</td><td>5</td><td>0</td></tr>\n</table>\n"
    for src in (html, html.encode("utf-16")):
        txns, report = load_csv(src)
        assert [t.amount for t in txns] == [5] and report["encoding"] == "html"


# ======================================================================================
# 2. 탭 TXT·CSV (UTF-8·CP949·UTF-16)
# ======================================================================================

KAKAO_LIKE_EXPECTED = [
    ("2026-06-04 23:10:00", "out", 200000, "김*호"),
    ("2026-06-05 12:30:00", "out", 15000, "가상식당"),
    ("2026-06-06 10:00:00", "out", 3000, "가상은행 기기"),
    ("2026-06-07 09:00:00", "in", 50000, "가나다"),
]


def _check_kakao_like(txns, report) -> None:
    assert report["header_row"] == 11                                     # 위 10줄은 제목·계좌 정보
    assert _summary(txns) == KAKAO_LIKE_EXPECTED
    assert [t.channel for t in txns] == [Channel.TRANSFER, Channel.CARD, Channel.ATM, Channel.INCOME]   # 거래구분 글로 추정
    assert report["mapping"]["kind"] == "구분" and report["mapping"]["type_text"] == "거래구분"
    assert report["mapping"]["memo"] == "메모" and txns[0].memo == "빌려줌"
    assert report["skipped"] == 1 and any("취소로 보이는 1줄" in w for w in report["warnings"])   # 체크카드취소


def test_unicode_text_tab_like_kakaobank_export_saved_from_excel() -> None:
    txns, report = load_csv(_fixture("kakaobank_like_unicode_text.txt"))
    assert report["encoding"] == "utf-16" and report["delimiter"] == "\t"
    _check_kakao_like(txns, report)


def test_passbook_like_tab_cp949_date_only() -> None:
    txns, report = load_csv(_fixture("passbook_like_tab_cp949.txt"))
    assert report["encoding"] == "cp949" and report["header_row"] == 3
    assert _summary(txns) == [("2026-05-02 12:00:00", "in", 1500000, "가상회사"),
                              ("2026-05-03 12:00:00", "out", 50000, "김*호"),
                              ("2026-05-03 12:00:00", "out", 12000, "가상분식")]
    text = " ".join(report["warnings"])
    assert "낮 12시" in text and "합계·소계 줄 1개" in text


KB_BANK_LIKE_CSV = ("KB 거래내역 조회(가상)\n조회기간,2026.05.01 ~ 2026.05.31\n\n"
                    "거래일시,적요,보낸분/받는분,송금메모,출금액,입금액,잔액,거래점\n"
                    "2026.05.03 08:12:44,체크카드,가상편의점,,\"4,800\",0,\"995,200\",가상지점\n"
                    "2026.05.02 22:01:05,모바일,김*호,용돈,\"100,000\",0,\"1,000,000\",가상지점\n"
                    "2026.05.01 09:00:00,급여,가상회사,,0,\"1,100,000\",\"1,100,000\",가상지점\n")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp949"])
def test_bank_like_csv_with_notice_rows_and_slash_counterparty(encoding: str) -> None:
    txns, report = load_csv(KB_BANK_LIKE_CSV.encode(encoding))
    assert report["encoding"] == encoding and report["header_row"] == 4
    assert _summary(txns) == [("2026-05-01 09:00:00", "in", 1100000, "가상회사"),
                              ("2026-05-02 22:01:05", "out", 100000, "김*호"),
                              ("2026-05-03 08:12:44", "out", 4800, "가상편의점")]
    assert [t.channel for t in txns] == [Channel.INCOME, Channel.TRANSFER, Channel.CARD]


CARD_LIKE_CSV = ("이용일,이용하신곳,\"국내이용금액\n(원)\",\"해외이용금액\n($)\",할부,결제방법\n"
                 "2026-05-15,가상카페 강남점,4500,0,일시불,신용카드\n"
                 "2026-05-16,가상마트,\"32,000\",0,3개월,신용카드\n"
                 "2026-05-17,GLOBAL SHOP,0,12.5,일시불,신용카드\n"
                 "2026-05-18,가상서점,-7000,0,일시불,신용카드\n"
                 "총계,,\"36,500\",12.5,,\n")


def test_card_like_csv_domestic_amount_and_merchant_aliases() -> None:
    txns, report = load_csv(CARD_LIKE_CSV.encode("cp949"))
    assert _summary(txns) == [("2026-05-15 12:00:00", "out", 4500, "가상카페 강남점"),
                              ("2026-05-16 12:00:00", "out", 32000, "가상마트")]
    assert all(t.channel == Channel.CARD for t in txns)
    assert report["mapping"]["amount"] == "국내이용금액" and report["mapping"]["merchant"] == "이용하신곳"
    reasons = report["warnings"][-1]
    assert "4번째 줄(금액이 비었거나 0원)" in reasons and "5번째 줄(취소로 보이는 음수 금액)" in reasons
    assert "6번째 줄(합계·소계 줄)" in reasons                              # '총계' 줄


@pytest.mark.parametrize("cell,expected", [("체크", Channel.CARD), ("체크카드", Channel.CARD), ("체크 결제", Channel.CARD),
                                           ("호텔체크인", Channel.TRANSFER), ("체크인", Channel.TRANSFER),
                                           ("타행이체", Channel.TRANSFER), ("ATM출금", Channel.ATM)])
def test_type_column_word_rules(cell: str, expected: Channel) -> None:
    text = f"거래일시,출금,입금,거래내용,거래구분\n2026-09-01 10:00,1000,0,가상상대,{cell}\n"
    txns, _ = load_csv(text)
    assert txns[0].channel == expected


def test_type_text_does_not_reuse_kind_or_memo_columns() -> None:
    text = "거래일시,거래구분,금액,내용\n2026-09-01 10:00,출금,1000,가상상대\n"
    txns, report = load_csv(text)
    assert report["mapping"]["kind"] == "거래구분" and "type_text" not in report["mapping"]
    text = "거래일시,적요,출금액,입금액,내용\n2026-09-01 10:00,체크카드,1000,0,가상상대\n"
    _, report = load_csv(text)
    assert report["mapping"]["memo"] == "적요" and "type_text" not in report["mapping"]


# ======================================================================================
# 3. .xlsx (카카오뱅크 흉내: 머리글 11번째 줄, 구분 + 부호 있는 금액)
# ======================================================================================

def _kakao_like_rows(dates_as_serial: bool) -> list[list[Any]]:
    rows: list[list[Any]] = [["카카오뱅크 거래내역(가상)"], [], ["성명", "가상"], ["계좌번호", "0000-00-0000000"],
                             ["조회기간", "2026.06.01 ~ 2026.06.30"], [], [], [], [], []]
    data = [
        ["거래일시", "구분", "거래금액", "거래 후 잔액", "거래구분", "내용", "메모"],
        [datetime(2026, 6, 7, 9, 0, 0), "입금", 50000, 1035000, "일반입금", "가나다", "메모A"],
        [datetime(2026, 6, 6, 10, 0, 0), "출금", -3000, 985000, "ATM출금", "가상은행 기기", ""],
        [datetime(2026, 6, 5, 12, 30, 0), "출금", -15000, 988000, "체크카드", "가상식당", ""],
        [datetime(2026, 6, 4, 23, 10, 0), "출금", -200000, 1003000, "이체", "김*호", "빌려줌"],
        [datetime(2026, 6, 3, 8, 0, 0), "출금", -4500, 1203000, "체크카드취소", "가상카페", ""],
    ]
    for row in data:
        if isinstance(row[0], datetime):
            row[0] = (serial(row[0]), "date") if dates_as_serial else row[0].strftime("%Y.%m.%d %H:%M:%S")
    return rows + data


@pytest.mark.parametrize("dates_as_serial", [False, True])
def test_xlsx_like_kakaobank(dates_as_serial: bool) -> None:
    txns, report = load_csv(make_xlsx(_kakao_like_rows(dates_as_serial)))
    assert report["encoding"] == "xlsx"
    _check_kakao_like(txns, report)


def test_xlsx_date1904_ignores_extension_workbook_properties() -> None:
    """엑셀이 저장한 1904 날짜 체계 .xlsx: extLst 안 x14:workbookPr가 date1904를 덮지 않는다(고친 버그: 1462일 어긋남)."""
    when = datetime(2026, 9, 1, 8, 50, 37)
    rows = [["거래일시", "출금액", "입금액", "내용"], [(serial(when, date1904=True), "date"), 5200, 0, "가게"]]
    txns, _ = load_csv(make_xlsx(rows, date1904=True))
    assert _summary(txns) == [("2026-09-01 08:50:37", "out", 5200, "가게")]


def test_encrypted_xlsx_gets_plain_guidance() -> None:
    with pytest.raises(LoaderError) as e:
        load_csv(encrypted_xlsx())
    message = str(e.value)
    assert message == xls.ENCRYPTED and "암호를 넣어 연 다음" in message and "CSV UTF-8" in message
    assert plain_message(message) == message


# ======================================================================================
# 4. 옛 엑셀 .xls (BIFF8, KB국민은행·KB국민카드 흉내)
# ======================================================================================

def _kb_bank_like_cells(**kw: Any) -> list[tuple]:
    rows: list[list[Any]] = [
        ["거래내역조회(가상)"],
        ["조회기간", "2026.05.01 ~ 2026.05.31"],
        [],
        ["거래일시", "적요", "보낸분/받는분", "송금메모", "출금액", "입금액", "잔액", "거래점"],
        ["2026.05.03 08:12:44", "체크카드", "가상편의점", None, 4800, 0, 995200, "가상지점"],
        ["2026.05.02 22:01:05", "모바일", "김*호", "용돈", ("num", 100000.0), 0, 1000000, "가상지점"],
        ["2026.05.01 09:00:00", "급여", "가상회사", None, 0, 1100000.5, 1100000.5, "가상지점"],
    ]
    return grid(rows)


KB_BANK_EXPECTED = [("2026-05-01 09:00:00", "in", 1100001, "가상회사"),   # 소수 금액 칸(RK): 0.5원은 올림(round_amount)
                    ("2026-05-02 22:01:05", "out", 100000, "김*호"),
                    ("2026-05-03 08:12:44", "out", 4800, "가상편의점")]


def test_xls_like_kb_bank() -> None:
    txns, report = load_csv(xls_file(_kb_bank_like_cells()))
    assert report["encoding"] == "xls" and report["header_row"] == 4
    assert _summary(txns) == KB_BANK_EXPECTED
    assert [t.channel for t in txns] == [Channel.INCOME, Channel.TRANSFER, Channel.CARD]


def test_xls_like_kb_card_newline_header_and_overseas_zero() -> None:
    rows = [["이용일", "이용하신곳", "국내이용금액\n(원)", "해외이용금액\n($)", "할부", "결제방법"],
            ["2026-05-15", "가상카페 강남점", 4500, 0, "일시불", "신용카드"],
            ["2026-05-16", "가상마트", 32000, 0, "3개월", "신용카드"],
            ["2026-05-17", "GLOBAL SHOP", 0, 12.5, "일시불", "신용카드"]]
    txns, report = load_csv(xls_file(grid(rows)))
    assert _summary(txns) == [("2026-05-15 12:00:00", "out", 4500, "가상카페 강남점"),
                              ("2026-05-16 12:00:00", "out", 32000, "가상마트")]
    assert report["skipped"] == 1 and all(t.channel == Channel.CARD for t in txns)


def test_xls_cell_kinds_dates_formulas_and_text() -> None:
    when = datetime(2026, 9, 1, 13, 5, 7)
    rows = [["거래일시", "일자", "시간", "수식 글", "수식 숫자", "참거짓", "오류", "라벨", "숫자", "일반 날짜"],
            [(serial(when), XF_DATETIME), (serial(datetime(2026, 9, 1)), XF_DATE), (13 / 24 + 5 / 1440, XF_TIME),
             ("fstr", "가나 abc"), ("fnum", 12.25), ("bool", True), ("err",), ("label", "라벨 글자"), -1234.5,
             serial(when)]]
    text = xls.xls_to_csv_text(xls_file(grid(rows), shrfmla=True))
    lines = text.splitlines()
    assert lines[0] == "거래일시,일자,시간,수식 글,수식 숫자,참거짓,오류,라벨,숫자,일반 날짜"
    # 일반 서식 칸도 머리글('날짜')을 보고 일련번호를 바꾼다(xlsx와 같은 규칙)
    assert lines[1] == "2026-09-01 13:05:07,2026-09-01,13:05:00,가나 abc,12.25,TRUE,,라벨 글자,-1234.5,2026-09-01 13:05:07"


def test_xls_date1904_mulrk_and_label_strings_without_sst() -> None:
    when = datetime(2026, 9, 1, 8, 50, 37)
    cells = grid([["거래일시", "출금액", "입금액", "내용"],
                  [(serial(when, True), XF_DATETIME), None, None, "가게"]])
    cells.append((1, 1, ("mulrk", [5200, 0])))
    text = xls.xls_to_csv_text(xls_file(cells, date1904=True, sst=False))
    assert text.splitlines()[1] == "2026-09-01 08:50:37,5200,0,가게"


def test_xls_sst_split_across_continue_records() -> None:
    names = [f"가상상대{k:03d}" + "가" * (k % 7) for k in range(120)] + ["latin only", "섞인 글 mixed"]
    rows = [["거래일시", "출금액", "입금액", "내용"]]
    rows += [[f"2026-09-01 10:{k % 60:02d}", 1000 + k, 0, name] for k, name in enumerate(names)]
    for limit in (8224, 37, 64):   # 작은 한도: 글 가운데에서 CONTINUE가 나뉘고 다음 조각 첫 바이트가 글자 폭
        txns, report = load_csv(xls_file(grid(rows), sst_limit=limit))
        assert sorted(t.counterparty for t in txns) == sorted(names) and report["loaded"] == len(names)


@pytest.mark.parametrize("sector_shift,pad,extra", [(9, 0, 0), (9, 9000, 0), (12, 9000, 0), (9, 0, 7_400_000)])
def test_xls_cfb_variants(sector_shift: int, pad: int, extra: int) -> None:
    """미니 스트림(4096바이트 미만)·보통 섹터·4096바이트 섹터(4판)·DIFAT 섹터(FAT 섹터가 109개를 넘는 7MB대 파일).
    같은 만들기 함수로 만든 파일을 엑셀(Microsoft 365)이 열어 같은 값을 읽는 것을 확인했다(2026-10-03, 저장소 밖에서 한 번)."""
    rows = [["거래일시", "출금액", "입금액", "내용"], ["2026-09-01 10:00", 1000, 0, "가게"]]
    rows += [["", "", "", "메모 " + "가" * 50] for _ in range(pad // 120)]
    data = xls_file(grid(rows), sector_shift=sector_shift, extra={"Pad": bytes(extra)} if extra else None)
    txns, _ = load_csv(data)
    assert _summary(txns) == [("2026-09-01 10:00:00", "out", 1000, "가게")]
    assert (struct.unpack_from("<I", data, 0x48)[0] >= 1) == bool(extra)   # DIFAT 섹터를 실제로 썼는지


def test_xls_first_worksheet_only_skips_chart_sheet_and_embedded_chart() -> None:
    rows = [["거래일시", "출금액", "입금액", "내용"], ["2026-09-01 10:00", 1000, 0, "가게"]]
    text = xls.xls_to_csv_text(xls_file(grid(rows), chart_inside=True, chart_sheet_first=True))
    assert text == "거래일시,출금액,입금액,내용\n2026-09-01 10:00,1000,0,가게\n"   # 차트 안 999는 읽지 않음, 둘째 시트도


@pytest.mark.parametrize("make,message", [
    (lambda: xls_file(grid([["a"]]), filepass=True), xls.ENCRYPTED),
    (lambda: encrypted_xlsx(), xls.ENCRYPTED),
    (lambda: xls_file(grid([["a"]]), version=0x0500), xls.TOO_OLD),
    (lambda: make_cfb({"Book": b"\x09\x08\x08\x00\x00\x05\x05\x00" + b"\0" * 8}), xls.TOO_OLD),
    (lambda: make_cfb({"WordDocument": _fake_bytes(5000)}), xls.NOT_EXCEL),
    (lambda: make_cfb({"FileHeader": b"HWP Document File" + b"\0" * 239, "BodyText": b""}), xls.NOT_EXCEL),
    (lambda: bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 30, xls.BROKEN),
])
def test_xls_guidance_messages(make, message: str) -> None:
    with pytest.raises(LoaderError) as e:
        load_csv(make())
    assert str(e.value) == message


def _patch(data: bytes, offset: int, fmt: str, *values: int) -> bytes:
    out = bytearray(data)
    struct.pack_into(fmt, out, offset, *values)
    return bytes(out)


def test_xls_broken_structures_are_rejected() -> None:
    rows = [["거래일시", "출금액", "입금액", "내용"]] + [["2026-09-01 10:00", 1000, 0, f"가상{k:03d}" + "가" * 40]
                                                   for k in range(80)]
    good = xls_file(grid(rows))
    assert load_csv(good)[1]["loaded"] == 80
    ss = 512
    first_dir = struct.unpack_from("<I", good, 0x30)[0]
    dir_at = (first_dir + 1) * ss
    workbook_entry = dir_at + 128
    start = struct.unpack_from("<I", good, workbook_entry + 116)[0]
    fat0 = ss   # 첫 FAT 섹터
    broken = [
        good[: len(good) // 2],                                                     # 잘린 파일
        _patch(good, fat0 + 4 * start, "<I", start),                                # FAT 순환(자기 자신)
        _patch(good, workbook_entry + 72, "<I", 1),                                 # 디렉터리 순환(오른쪽 = 자기)
        _patch(good, workbook_entry + 120, "<Q", 10 ** 7),                          # 적힌 크기 > 사슬
        _patch(good, 0x1C, "<H", 0xFEFF),                                           # 바이트 순서 표시가 틀림
        _patch(good, 0x2C, "<I", 10 ** 6),                                          # FAT 섹터 수가 파일보다 큼
    ]
    for data in broken:
        with pytest.raises(LoaderError) as e:
            load_csv(data)
        assert str(e.value) == xls.BROKEN


def test_xls_record_past_stream_end_and_size_limit(monkeypatch) -> None:
    stream = make_xls(grid([["거래일시", "출금액", "입금액"], ["2026-09-01 10:00", 1, 0]]), second_sheet=False)
    with pytest.raises(LoaderError) as e:   # 마지막 레코드(WINDOW2·EOF) 가운데에서 잘린 스트림
        load_csv(make_cfb({"Workbook": stream[:-10]}))
    assert str(e.value) == xls.BROKEN
    monkeypatch.setattr(xls, "MAX_FILE_BYTES", 1000)
    with pytest.raises(LoaderError, match="30MB"):
        load_csv(xls_file(grid([["거래일시"]]), extra={"Pad": _fake_bytes(5000)}))


def test_sparse_far_right_cells_cannot_blow_up_xls_or_xlsx(monkeypatch) -> None:
    """줄마다 맨 오른쪽 칸 하나만 있는 작은 파일: 줄마다 빈 칸을 채우면 표가 크게 불어나므로 칸 수 합계로 막는다."""
    from safepause.data import xlsx as xl
    monkeypatch.setattr(xl, "MAX_CELLS", 2000)
    cells = [(0, 0, "거래일시"), (0, 1, "출금액"), (0, 2, "입금액")] + [(r, 200, "x") for r in range(1, 20)]
    with pytest.raises(LoaderError, match="표의 칸이 너무 많아요"):
        load_csv(xls_file(cells))
    rows: list[list[Any]] = [["거래일시", "출금액", "입금액"]] + [[None] * 25 + ["x"] for _ in range(100)]
    with pytest.raises(LoaderError, match="표의 칸이 너무 많아요"):
        load_csv(make_xlsx(rows))
    txns, _ = load_csv(xls_file(grid([["거래일시", "출금액", "입금액"], ["2026-09-01 10:00", 1, 0]])))   # 보통 파일은 그대로
    assert len(txns) == 1


# ======================================================================================
# 5. 서버로 올리기(.xls·HTML 표 .xls): PC 서버와 앱 라우터가 같은 응답
# ======================================================================================

def test_upload_xls_and_html_xls_through_server_and_router(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from safepause.api.router import dispatch
    from safepause.api.schemas import ConsentIn
    from safepause.api.service import Service
    from safepause.server.app import create_app

    now = datetime(2026, 9, 30, 12)
    cases = [("거래.xls", xls_file(_kb_bank_like_cells()), "xls", 3),
             ("거래내역조회.xls", _fixture("ibk_like_table_utf8.xls"), "html", 4)]
    for name, data, encoding, count in cases:
        app = create_app(tmp_path / f"pc-{encoding}", now=lambda: now)
        with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-SafePause": "1"}) as client:
            assert client.put("/api/consent", json={"monitoring": True}).status_code == 200
            r = client.post("/api/data/upload", files={"file": (name, data, "application/vnd.ms-excel")})
        svc = Service(tmp_path / f"app-{encoding}", now=lambda: now)
        svc.put_consent(ConsentIn(monitoring=True))
        status, body = dispatch(svc, "POST", "/api/data/upload", {"mapping": ""}, data)
        assert r.status_code == status == 200
        assert r.json()["report"] == json.loads(json.dumps(body["report"], ensure_ascii=False))
        assert body["report"]["encoding"] == encoding
        assert body["summary"]["count"] == count
    app = create_app(tmp_path / "pc-locked", now=lambda: now)
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-SafePause": "1"}) as client:
        client.put("/api/consent", json={"monitoring": True})
        r = client.post("/api/data/upload", files={"file": ("잠김.xlsx", encrypted_xlsx(), "application/octet-stream")})
    assert r.status_code == 400 and r.json()["detail"] == xls.ENCRYPTED
