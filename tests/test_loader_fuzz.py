"""거래내역 파일 읽기(data.loader·xlsx·xls·htmltable) 퍼징 시험(2026-10-03).

망가진 입력을 대량으로 넣어 세 가지를 본다.
- 처리 안 된 예외 0: 읽지 못하면 언제나 LoaderError(한국어 안내). 읽으면 거래·리포트가 계약대로(금액 > 0, 연도 범위 등).
- 시간: 파일 하나가 TIME_LIMIT(2초) 안에 끝난다(이차 시간 없음). 무한 루프는 사례마다 WATCHDOG_SEC 감시로 잡는다.
- 메모리: tracemalloc 최고치가 MEM_LIMIT 안(압축 폭탄·깊은 중첩·작은 파일이 큰 표로 불어나는 것 없음).
  tracemalloc은 시간을 크게 늘리므로 시간은 끈 채 재고, 메모리는 MEMORY_PROBE_SEC보다 오래 걸린 사례만 다시 돌려 잰다.

씨앗: tests/fixtures/bank_formats 파일, sample_data CSV, test_loader_bank_formats.py의 만들기 함수(make_xls·make_cfb·
make_xlsx·encrypted_xlsx)와 이 파일의 공유 문자열 .xlsx·HTML 표·CSV 글.
변이: 바이트 뒤집기·덮어쓰기·정수 칸(0, FFFF, FFFFFFFE 등)·끼우기·지우기·자르기·덧붙이기·조각 반복·이어 붙이기,
글(구분자·따옴표·태그·긴 칸·공백 줄·인코딩 바꾸기), BIFF 레코드(길이·번호·복제·CONTINUE 폭주·BOF 중첩·SST 색인),
CFB(머리 칸·FAT 순환·디렉터리 순환·크기), xlsx(부분 XML 깊은 중첩·많은 요소·공유 문자열 색인 범위 밖·rels 경로·zip 머리
압축 방식·암호 표시·크기), HTML(깊은 중첩·거대 colspan/rowspan·닫히지 않은 구문).

- 짧은 판 test_fuzz_short: 기본 pytest에서 돈다(고정 씨앗 SHORT_CASES건, 수 초).
- 긴 판 test_fuzz_long: ``pytest -m fuzz_long tests/test_loader_fuzz.py`` (또는 SAFEPAUSE_FUZZ_LONG=1).
  SAFEPAUSE_FUZZ_CASES(기본 20000)·SAFEPAUSE_FUZZ_SEED(기본 1)로 조절. 실패하면 사례 번호와 함께 알린다
  (``case_bytes(seed, i)``로 같은 입력을 다시 만들 수 있다).
- 회귀: 퍼징·검토로 찾아 고친 문제의 재현 입력(tests/fixtures/loader_fuzz/*.bin.gz, 무엇·찾은 곳·고치기 전 결과는
  MANIFEST.json). 고친 곳이 정상 입력의 결과를 바꾸지 않는지 고치기 전 식과 무작위로 대조하는 시험도 둔다.
"""
from __future__ import annotations

import faulthandler
import gzip
import io
import json
import os
import random
import re
import struct
import time
import tracemalloc
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import pytest

from safepause.data import htmltable, loader, xlsx
from safepause.data.loader import LoaderError, load_csv
from safepause.data.synth import MAX_YEAR, MIN_YEAR
from test_loader_bank_formats import (
    XF_DATE, XF_DATETIME, XF_TIME, encrypted_xlsx, grid, make_cfb, make_xls, make_xlsx, serial,
)

HERE = Path(__file__).parent
REGRESS = HERE / "fixtures" / "loader_fuzz"
TIME_LIMIT = 2.0                 # 파일 하나(초, tracemalloc 없이 잼)
MEM_LIMIT = 96 * 1024 * 1024     # tracemalloc 최고치(바이트). 씨앗이 수 KB라 변이 입력은 300KB 안팎까지
MEMORY_PROBE_SEC = 0.005         # 이보다 오래 걸린 사례만 메모리를 잰다(run_case. 긴 판·회귀 시험)
SHORT_PROBE_SEC = 0.05           # 짧은 판은 이보다 오래 걸린 사례만(수 초 안에 끝나게. 폭탄 입력은 회귀 시험이 잰다)
WATCHDOG_SEC = 120               # 사례 하나가 이보다 오래 걸리면 무한 루프로 보고 프로세스를 끝낸다
MAX_CASE_BYTES = 300_000         # 변이가 만드는 입력 크기 상한(조각 반복 등)
SHORT_CASES = 800
_HANGUL = re.compile(r"[가-힣]")


# ======================================================================================
# 씨앗
# ======================================================================================

_XMLNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _shared_xlsx_parts() -> dict[str, bytes]:
    """공유 문자열·서식(날짜·시각)·두 시트가 있는 .xlsx 부분들(은행 거래내역 모양, 값은 가짜)."""
    shared = ["거래일시", "적요", "출금액", "입금액", "내용", "체크카드", "김*호", "카페", "급여", "회사", "합계", "모바일이체"]
    day = serial(__import__("datetime").datetime(2026, 8, 15, 12, 3, 55))
    rows = [
        '<row r="1"><c r="A1" t="inlineStr"><is><t>입출금 거래내역 조회(가상)</t></is></c></row>',
        '<row r="3"><c r="A3" t="s"><v>0</v></c><c r="B3" t="s"><v>1</v></c><c r="C3" t="s"><v>2</v></c>'
        '<c r="D3" t="s"><v>3</v></c><c r="E3" t="s"><v>4</v></c></row>',
        f'<row r="4"><c r="A4" s="2"><v>{day!r}</v></c><c r="B4" t="s"><v>5</v></c><c r="C4" s="4"><v>5200</v></c>'
        '<c r="D4"><v>0</v></c><c r="E4" t="s"><v>7</v></c></row>',
        f'<row r="5"><c r="A5" s="1"><v>{day - 1!r}</v></c><c r="B5" t="s"><v>11</v></c><c r="C5"><v>250000</v></c>'
        '<c r="E5" t="s"><v>6</v></c></row>',
        f'<row r="6"><c r="A6" s="2"><v>{day - 2.5!r}</v></c><c r="B6" t="s"><v>8</v></c><c r="C6"><v>0</v></c>'
        '<c r="D6"><v>2100000</v></c><c r="E6" t="s"><v>9</v></c></row>',
        '<row r="7"><c r="A7" t="s"><v>10</v></c><c r="C7" t="str"><v>255200</v></c>'
        '<c r="D7" t="b"><v>1</v></c><c r="E7" t="e"><v>#N/A</v></c></row>',
    ]
    sheet = f'<worksheet {_XMLNS}><sheetData>{"".join(rows)}</sheetData></worksheet>'
    sst = (f'<sst {_XMLNS} count="{len(shared)}" uniqueCount="{len(shared)}">'
           + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared[:-1])
           + '<si><r><rPr><b/></rPr><t>모바일</t></r><r><t>이체</t></r><rPh sb="0" eb="1"><t>읽는 법</t></rPh></si></sst>')
    styles = (f'<styleSheet {_XMLNS}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\.mm\\.dd hh:mm:ss"/>'
              '</numFmts><cellXfs count="5"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="164"/>'
              '<xf numFmtId="20"/><xf numFmtId="3"/></cellXfs></styleSheet>')
    return {
        "[Content_Types].xml": b"<Types/>",
        "xl/workbook.xml": (f'<workbook {_XMLNS} {_RNS}><workbookPr/><sheets><sheet name="a" sheetId="1" r:id="rId1"/>'
                            '<sheet name="b" sheetId="2" r:id="rId2"/></sheets></workbook>').encode(),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="worksheet" Target="/xl/worksheets/sheet2.xml"/></Relationships>').encode(),
        "xl/sharedStrings.xml": sst.encode(),
        "xl/styles.xml": styles.encode(),
        "xl/worksheets/sheet1.xml": sheet.encode(),
        "xl/worksheets/sheet2.xml": f'<worksheet {_XMLNS}><sheetData/></worksheet>'.encode(),
    }


def zip_parts(parts: dict[str, bytes], deflate: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


def unzip_parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {i.filename: zf.read(i) for i in zf.infolist()}


_CSV_BANK = ("KB 거래내역 조회(가상)\n조회기간,2026.05.01 ~ 2026.05.31\n\n"
             "거래일시,적요,보낸분/받는분,송금메모,출금액,입금액,잔액,거래점\n"
             "2026.05.03 08:12:44,체크카드,가상편의점,,\"4,800\",0,\"995,200\",가상지점\n"
             "2026.05.02 22:01:05,모바일,김*호,용돈,\"100,000\",0,\"1,000,000\",가상지점\n"
             "2026.05.02 03:01:05,휴대폰결제,SKT 010-1234-5678,,\"30,000\",0,\"1,100,000\",가상지점\n"
             "2026.05.01 09:00:00,급여,가상회사,,0,\"1,100,000\",\"1,100,000\",가상지점\n"
             "합계,,,,\"134,800\",\"1,100,000\",,\n")
_CSV_CARD = ("이용일,이용하신곳,\"국내이용금액\n(원)\",\"해외이용금액\n($)\",할부,결제방법\n"
             "2026-05-15,가상카페 강남점,4500,0,일시불,신용카드\n"
             "2026-05-16,가상마트,\"32,000\",0,3개월,신용카드\n"
             "2026-05-18,가상서점,-7000,0,일시불,신용카드\n"
             "총계,,\"36,500\",12.5,,\n")
_CSV_SPLIT = ("거래일자;거래시간;구분;금액;내용;메모\n"
              "2026/09/01;오후 1:05:07;출금;₩5,000;가나통신 요금;\n"
              "2026/09/02;91030;입금;(3,000);회사;\n"
              "2026/09/03;0500;출금;5,000-;ATM 현금;메모\n")
_CSV_STANDARD = ("id,ts,amount,direction,channel,counterparty,counterparty_id,line_id,memo,label\n"
                 "t1,2026-03-03T12:58:08,5400,out,micropay,게임아이템,MP-GAME,010-****-9012,휴대폰결제,normal\n"
                 "t2,2026-03-03T13:10:44+09:00,4200,out,card,편의점,M-1,,체크카드,normal\n"
                 "t2,2026-03-04T19:15:05Z,45000.5,in,income,회사,C-1,,급여,normal\n")
_HTML_TABLE = ("<html><head><meta charset=\"utf-8\"><style>td{x:1}</style><script>var a='<td>';</script></head><body>"
               "<table><tr><td>조회기간</td><td>2026-05-01 ~ 2026-05-31</td></tr></table>"
               "<table border=1><tr><th>거래일시</th><th>출금</th><th>입금</th><th>거래내용</th></tr>"
               "<tr><td colspan=4>안내 줄</td></tr>"
               "<tr><td rowspan=2>2026-05-03 08:12:44</td><td>4,800</td><td>0</td><td>가상<br>편의점&nbsp;</td></tr>"
               "<tr><td>0</td><td>1,100,000</td><td>가상회사</td>"
               "<tr><td>2026-05-04 09:00:00<td>1,000<td>0<td><table><tr><td>안쪽</td></tr></table>바깥</tr>"
               "</table></body></html>")


def _xls_cells() -> list[tuple]:
    when = __import__("datetime").datetime(2026, 9, 1, 13, 5, 7)
    rows: list[list[Any]] = [
        ["거래내역조회(가상)"],
        ["거래일시", "적요", "보낸분/받는분", "출금액", "입금액", "일자", "시간", "메모"],
        [(serial(when), XF_DATETIME), "체크카드", "가상편의점", 4800, 0, (serial(when), XF_DATE),
         (13 / 24, XF_TIME), ("fstr", "수식 글")],
        ["2026.05.02 22:01:05", "모바일", "김*호", ("num", 100000.0), 0, None, None, ("bool", True)],
        ["2026.05.01 09:00:00", "급여", "가상회사", 0, 1100000.5, None, None, ("err",)],
        ["2026.05.01 10:00:00", ("label", "라벨"), "가"*300, ("mulrk", [1000, 2000.5, 3]), None, None, None,
         ("fnum", 12.25)],
    ]
    return grid(rows)


def _seeds() -> list[tuple[str, bytes, dict[str, Any]]]:
    """(종류, 바이트, 구조 정보). 구조 정보: xls → {'streams': {...}, 'shift': 9|12}, xlsx → {'parts': {...}}."""
    out: list[tuple[str, bytes, dict[str, Any]]] = []
    for path in sorted((HERE / "fixtures" / "bank_formats").iterdir()):
        data = path.read_bytes()
        kind = "html" if data.lstrip().startswith(b"<") else "text"
        out.append((kind, data, {}))
    for name in ("bank_export_example.csv", "student_normal.csv"):
        data = (HERE.parent / "sample_data" / name).read_bytes()
        out.append(("text", data[:4000], {}))
    for text, enc in ((_CSV_BANK, "utf-8-sig"), (_CSV_BANK, "cp949"), (_CSV_CARD, "cp949"), (_CSV_SPLIT, "utf-8"),
                      (_CSV_STANDARD, "utf-8"), (_CSV_BANK.replace(",", "\t"), "utf-16")):
        out.append(("text", text.encode(enc), {}))
    out.append(("html", _HTML_TABLE.encode("utf-8"), {}))
    out.append(("html", _HTML_TABLE.encode("cp949", "replace"), {}))
    cells = _xls_cells()
    for kw, shift in (({}, 9), ({"sst": False, "date1904": True}, 12), ({"sst_limit": 37, "chart_inside": True,
                                                                          "chart_sheet_first": True, "shrfmla": True}, 9)):
        streams = {"Workbook": make_xls(cells, **kw)}
        out.append(("xls", make_cfb(streams, sector_shift=shift), {"streams": streams, "shift": shift}))
    big = {"Workbook": make_xls(cells + [(r, 0, f"줄{r}") for r in range(7, 400)])}   # 4096바이트 넘는 스트림(FAT 사슬)
    out.append(("xls", make_cfb(big), {"streams": big, "shift": 9}))
    enc = encrypted_xlsx()
    out.append(("cfb", enc, {}))
    parts = _shared_xlsx_parts()
    out.append(("xlsx", zip_parts(parts), {"parts": parts}))
    rows = [["거래일시", "구분", "거래금액", "내용"], [(serial(__import__("datetime").datetime(2026, 6, 7, 9)), "date"),
                                               "입금", 50000, "가나다"], ["2026.06.06 10:00:00", "출금", -3000, "가게"]]
    simple = unzip_parts(make_xlsx(rows, date1904=True))
    out.append(("xlsx", zip_parts(simple), {"parts": simple}))
    return out


_SEEDS: Optional[list[tuple[str, bytes, dict[str, Any]]]] = None


def seeds() -> list[tuple[str, bytes, dict[str, Any]]]:
    global _SEEDS
    if _SEEDS is None:
        _SEEDS = _seeds()
    return _SEEDS


# ======================================================================================
# 변이
# ======================================================================================

_I16 = (0, 1, 2, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFE, 0xFFFF)
_I32 = (0, 1, 2, 109, 4096, 0x10000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFA, 0xFFFFFFFB, 0xFFFFFFFC, 0xFFFFFFFD,
        0xFFFFFFFE, 0xFFFFFFFF)
_TEXT_TOKENS = (
    '"', ",", "\t", ";", "|", "\n", "\r\n", "\r", "\x00", "<", ">", "&", "&#0;", "&#x110000;", "&#99999999999;",
    "&nbsp;", "&amp;lt;", "<!--", "-->", "<!", "<?", "</", "<a ", "<a b='", '<a b="', "<td>", "</td>", "<tr>",
    "</tr>", "<table>", "</table>", '<th colspan="1000">', '<td rowspan="1000">', "<td colspan=99999999999>",
    "<td rowspan=-5 colspan=x>", "<script>", "</script>", "<style>", "<br>", "<![CDATA[", "(", ")", "[", "]",
    "취소", "합계", "소계", "2026-01-01", "2026.05.01 12:00:00", "1900-01-01T00:00:00+09:00", "1969-12-31 23:59:59+09:00",
    "2026-09-01 1:2", "0001-01-01", "9999-12-31 23:59:59", " ", "\u3000", "\u00a0", "\ufeff", "\u200b", "1e400",
    "nan", "-0", "inf", "(3,000)", "△", "\\", "₩", "KRW", "오전", "오후", "PM", "12:00", "25:61", "010-1234-5678",
    "+82 10-1234-5678", "SKT", "KT&G", "통신", "체크", "ATM", "가나통신", "거래일시", "출금액", "입금액", "금액",
    "구분", "id,ts,amount,direction,channel", "\ud800",
)
_RUN_CHARS = ("가", "(", "[", " ", "\t", '"', "<", "1", "a", "\n", ",", "통", "-", ":")


def _cap(b: bytes) -> bytes:
    return b[:MAX_CASE_BYTES]


def m_flip(rng: random.Random, b: bytes) -> bytes:
    if not b:
        return b
    out = bytearray(b)
    for _ in range(rng.randint(1, 8)):
        i = rng.randrange(len(out))
        out[i] ^= 1 << rng.randrange(8)
    return bytes(out)


def m_overwrite(rng: random.Random, b: bytes) -> bytes:
    if not b:
        return b
    out = bytearray(b)
    for _ in range(rng.randint(1, 16)):
        out[rng.randrange(len(out))] = rng.choice((0, 0xFF, 0x7F, 0x80, 0x3C, 0x22, 0x0A, rng.randrange(256)))
    return bytes(out)


def m_int(rng: random.Random, b: bytes) -> bytes:
    if len(b) < 4:
        return b
    out = bytearray(b)
    for _ in range(rng.randint(1, 3)):
        if rng.random() < 0.5:
            i = rng.randrange(len(out) - 1)
            struct.pack_into("<H", out, i, rng.choice(_I16 + (len(b) & 0xFFFF,)))
        else:
            i = rng.randrange(len(out) - 3)
            struct.pack_into("<I", out, i, rng.choice(_I32 + (len(b),)))
    return bytes(out)


def m_insert(rng: random.Random, b: bytes) -> bytes:
    i = rng.randrange(len(b) + 1)
    if rng.random() < 0.5:
        piece = bytes(rng.randrange(256) for _ in range(rng.randint(1, 64)))
    else:
        piece = rng.choice(_TEXT_TOKENS).encode("utf-8", "surrogatepass")
    return _cap(b[:i] + piece + b[i:])


def m_delete(rng: random.Random, b: bytes) -> bytes:
    if not b:
        return b
    i = rng.randrange(len(b))
    j = min(len(b), i + rng.choice((1, 2, 4, 16, 64, 512, 4096)))
    return b[:i] + b[j:]


def m_truncate(rng: random.Random, b: bytes) -> bytes:
    return b[:rng.randrange(len(b) + 1)]


def m_append(rng: random.Random, b: bytes) -> bytes:
    if rng.random() < 0.5:
        tail = bytes(rng.randrange(256) for _ in range(rng.randint(1, 256)))
    else:
        tail = rng.choice(_TEXT_TOKENS).encode("utf-8", "surrogatepass") * rng.randint(1, 2000)
    return _cap(b + tail)


def m_repeat(rng: random.Random, b: bytes) -> bytes:
    """조각 하나를 여러 번 반복해 끼운다(작은 입력이 크게 불어나는 경로)."""
    if not b:
        return b
    i = rng.randrange(len(b))
    piece = b[i:i + rng.randint(1, 64)]
    k = rng.choice((2, 10, 100, 1000, 5000))
    return _cap(b[:i] + piece * k + b[i:])


def m_splice(rng: random.Random, b: bytes) -> bytes:
    other = rng.choice(seeds())[1]
    return _cap(b[:rng.randrange(len(b) + 1)] + other[rng.randrange(len(other) + 1):])


BYTE_MUTATORS: tuple[Callable[[random.Random, bytes], bytes], ...] = (
    m_flip, m_overwrite, m_int, m_insert, m_delete, m_truncate, m_append, m_repeat, m_splice)


# -- 글 ----------------------------------------------------------------------------------

def t_token(rng: random.Random, s: str) -> str:
    i = rng.randrange(len(s) + 1)
    return s[:i] + rng.choice(_TEXT_TOKENS) * rng.choice((1, 1, 1, 3, 50, 2000)) + s[i:]


def t_run(rng: random.Random, s: str) -> str:
    """같은 글자(괄호·공백·한글·따옴표 등)를 길게 끼운다: 정규식 되돌이 폭주를 찾는다."""
    i = rng.randrange(len(s) + 1)
    run = rng.choice(_RUN_CHARS) * rng.choice((100, 1000, 5000, 20000, 60000))
    return s[:i] + run + s[i:]


def t_cell_run(rng: random.Random, s: str) -> str:
    """칸 안쪽(구분자 뒤)에 '값 + 긴 공백/글자 + 꼬리'를 넣는다: 날짜·시각·금액 칸 해석 폭주를 찾는다."""
    lines = s.split("\n")
    k = rng.randrange(len(lines))
    head = rng.choice(("2026-01-01", "2026-01-01 1:2", "1:2", "2026.05.01 12:00:00", "4,800", "가", "(", "SKT",
                       "010-1234", "오후 1"))
    filler = rng.choice((" ", "\t", "\u3000", "(", "가", "1", ":", "-", "통"))
    cell = head + filler * rng.choice((200, 2000, 20000)) + rng.choice(("x", "", "통신", ")", "요금"))
    parts = lines[k].split(",")
    parts[rng.randrange(len(parts))] = cell
    lines[k] = ",".join(parts)
    return "\n".join(lines)


def t_dup_line(rng: random.Random, s: str) -> str:
    lines = s.split("\n")
    k = rng.randrange(len(lines))
    lines[k:k] = [lines[k]] * rng.choice((2, 50, 1000, 3000))
    return "\n".join(lines)


def t_delim(rng: random.Random, s: str) -> str:
    a, b = rng.sample((",", "\t", ";", "|", '"', "\n"), 2)
    return s.replace(a, b)


def t_html_nest(rng: random.Random, s: str) -> str:
    i = rng.randrange(len(s) + 1)
    unit = rng.choice(("<table><tr><td>", "<div>", "<td>", "<tr>", "<table>", "<b><i>", "<!--", "<a ", "</",
                       "<td colspan=1000 rowspan=1000>", "<tr><td rowspan=1000>"))
    k = rng.choice((10, 300, 3000, 20000))
    close = rng.choice(("", "</td></tr></table>" * min(k, 50)))
    return s[:i] + unit * k + close + s[i:]


def t_span(rng: random.Random, s: str) -> str:
    big = rng.choice(("1000", "999999999999", "-1", "0", "1e3", "２", " 7 ", "65536"))
    return re.sub(r"<t([dh])\b", lambda m: f'<t{m.group(1)} colspan="{big}" rowspan="{rng.choice(("1", big))}"'
                  if rng.random() < 0.3 else m.group(0), s)


TEXT_MUTATORS = (t_token, t_run, t_cell_run, t_dup_line, t_delim, t_html_nest, t_span)
_ENCODINGS = ("utf-8", "utf-8-sig", "cp949", "utf-16", "utf-16-le", "latin-1")


def _decode(b: bytes) -> str:
    for enc in ("utf-16", "utf-8-sig", "cp949") if b[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp949"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1")


def mutate_text(rng: random.Random, b: bytes) -> bytes:
    s = _decode(b)
    for _ in range(rng.randint(1, 3)):
        s = rng.choice(TEXT_MUTATORS)(rng, s)
    enc = rng.choice(_ENCODINGS)
    return _cap(s.encode(enc, "surrogatepass" if enc.startswith("utf") else "replace"))


# -- BIFF·CFB ------------------------------------------------------------------------------

_RIDS = (0x0809, 0x000A, 0x003C, 0x002F, 0x0022, 0x041E, 0x00E0, 0x0085, 0x00FC, 0x00FD, 0x0204, 0x00D6, 0x0203,
         0x027E, 0x00BD, 0x0006, 0x0207, 0x0205, 0x04BC, 0x0000, 0xFFFF)


def _records(stream: bytes) -> list[list[Any]]:
    out, pos = [], 0
    while pos + 4 <= len(stream):
        rid, size = struct.unpack_from("<HH", stream, pos)
        out.append([rid, stream[pos + 4:pos + 4 + size]])
        pos += 4 + size
    return out


def _pack(records: list[list[Any]]) -> bytes:
    return b"".join(struct.pack("<HH", rid, len(body) & 0xFFFF) + body[:0xFFFF] for rid, body in records)


def mutate_biff(rng: random.Random, stream: bytes) -> bytes:
    recs = _records(stream)
    if not recs:
        return stream
    op = rng.randrange(9)
    k = rng.randrange(len(recs))
    if op == 0:                                   # 레코드 번호 바꾸기
        recs[k][0] = rng.choice(_RIDS)
    elif op == 1:                                 # 레코드 복제(여러 번)
        recs[k + 1:k + 1] = [list(recs[k]) for _ in range(rng.choice((1, 10, 500, 3000)))]
    elif op == 2:
        del recs[k]
    elif op == 3:                                 # 내용 바이트 변이
        recs[k][1] = rng.choice((m_flip, m_int, m_truncate, m_append, m_overwrite))(rng, recs[k][1])
    elif op == 4:                                 # CONTINUE 폭주(빈 조각·작은 조각)
        body = rng.choice((b"", b"\x00", b"\x01a\x00", struct.pack("<HB", 1, 0) + b"a"))
        recs[k + 1:k + 1] = [[0x003C, body] for _ in range(rng.choice((10, 1000, 8000)))]
    elif op == 5:                                 # 새 레코드: 큰 개수·범위 밖 번호
        new = rng.choice((
            [0x00FC, struct.pack("<II", 0xFFFFFFFF, rng.choice(_I32))],
            [0x00FD, struct.pack("<HHHI", rng.randrange(70000) & 0xFFFF, rng.randrange(300), 15, rng.choice(_I32))],
            [0x0085, struct.pack("<IBB", rng.choice(_I32 + (rng.randrange(len(stream) + 8),)), 0, 0) + b"\x01\x00a"],
            [0x00BD, struct.pack("<HH", 1, rng.choice((0, 200, 255, 0xFFFF))) + struct.pack("<HI", 15, 2) * 2000],
            [0x0006, struct.pack("<HHH", 1, 1, 15) + b"\x00" * 6 + b"\xff\xff" + b"\x00" * 8],
            [0x0809, struct.pack("<HHHHII", 0x0600, rng.choice((5, 0x10, 0x20)), 0, 0, 0, 6)],
            [0x041E, struct.pack("<HHB", 164, 0xFFFF, 0) + rng.choice((b"[", b"[$-412]", b"y")) * 200],
            [0x0204, struct.pack("<HHHHB", 2, 0, 15, 0xFFFF, 1) + b"a\x00" * 10],
        ))
        recs.insert(k, new)
    elif op == 6:                                 # BOF 깊은 중첩
        bof = [0x0809, struct.pack("<HHHHII", 0x0600, 0x20, 0, 0, 0, 6)]
        recs[k:k] = [list(bof) for _ in range(rng.choice((10, 1000, 10000)))]
    elif op == 7:                                 # 내용 길이를 거짓으로(뒤 레코드가 어긋남)
        out = bytearray(_pack(recs))
        pos = sum(4 + len(b) for _, b in recs[:k])
        if pos + 4 <= len(out):
            struct.pack_into("<H", out, pos + 2, rng.choice(_I16))
        return bytes(out)
    else:                                         # 큰 칸 수: MULRK·NUMBER 많은 줄
        rows = rng.choice((10, 300, 2000))
        recs[k:k] = [[0x00BD, struct.pack("<HH", r, 0) + struct.pack("<HI", 15, ((r + 1) << 2) | 2) * 30
                      + struct.pack("<H", 29)] for r in range(rows)]
    return _pack(recs)


def mutate_cfb(rng: random.Random, data: bytes) -> bytes:
    """복합 문서 구조 칸: 머리, FAT 순환, 디렉터리 항목(형제·자식 순환, 시작 섹터, 크기)."""
    if len(data) < 512:
        return data
    out = bytearray(data)
    shift = struct.unpack_from("<H", out, 0x1E)[0]
    ss = 1 << shift if shift in (9, 12) else 512
    op = rng.randrange(4)
    if op == 0:
        off = rng.choice((0x18, 0x1A, 0x1C, 0x1E, 0x20, 0x2C, 0x30, 0x38, 0x3C, 0x40, 0x44, 0x48,
                          0x4C + 4 * rng.randrange(109)))
        fmt = "<H" if off < 0x2C else "<I"
        struct.pack_into(fmt, out, off, rng.choice(_I16 if fmt == "<H" else _I32 + (rng.randrange(64),)))
    elif op == 1:                                 # FAT 칸: 자기 자신·앞 섹터(순환)·범위 밖
        fat0 = struct.unpack_from("<I", out, 0x4C)[0]
        base = (fat0 + 1) * ss
        n = ss // 4
        if base + ss <= len(out):
            for _ in range(rng.randint(1, 4)):
                i = rng.randrange(n)
                struct.pack_into("<I", out, base + 4 * i, rng.choice((i, max(0, i - 1), 0, rng.randrange(n),
                                                                     0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFA)))
    else:                                         # 디렉터리 항목
        first_dir = struct.unpack_from("<I", out, 0x30)[0]
        base = (first_dir + 1) * ss
        if base + 128 <= len(out):
            e = base + 128 * rng.randrange(max(1, min(ss, len(out) - base) // 128))
            if e + 128 <= len(out):
                field = rng.choice((64, 66, 68, 72, 76, 116, 120))
                if field == 64:
                    struct.pack_into("<H", out, e + 64, rng.choice((0, 1, 2, 64, 66, 0xFFFF)))
                elif field == 66:
                    out[e + 66] = rng.choice((0, 1, 2, 5, 0xFF))
                elif field == 120:
                    struct.pack_into("<Q", out, e + 120, rng.choice((0, 1, 63, 4095, 4096, 1 << 32, (1 << 64) - 1,
                                                                     rng.randrange(1 << 20))))
                else:
                    struct.pack_into("<I", out, e + field, rng.choice((0, 1, 2, 3, 0xFFFFFFFF, 0xFFFFFFFE,
                                                                       rng.randrange(64))))
    return bytes(out)


# -- xlsx ----------------------------------------------------------------------------------

_XML_TOKENS = (
    '<row r="1048577"><c r="A1"><v>1</v></c></row>', '<row r="99999999999999999999"/>', '<row r="-3"><c><v>1</v></c></row>',
    '<c r="XFD1" t="s"><v>99999999</v></c>', '<c t="s"><v>-1</v></c>', '<c t="s"><v>1e9</v></c>',
    '<c s="99999"><v>45000</v></c>', '<c s="-1"><v>45000.5</v></c>', '<c r="ZZZZ9"><v>1</v></c>',
    '<c t="inlineStr"><is><r><t>가</t></r><rPh><t>x</t></rPh></is></c>', '<c t="d"><v>2026-01-01</v></c>',
    '<!DOCTYPE x [<!ENTITY a "b">]>', "&#0;", "&lt;", "<![CDATA[x]]>", "<?pi x?>", "<!-- c -->",
    '<c><v>1e400</v></c>', '<c><v>nan</v></c>', '<c><v>' + "9" * 5000 + "</v></c>",
    '<numFmt numFmtId="2" formatCode="' + "[" * 3000 + 'y"/>', '<xf numFmtId="164"/>', '<sheet r:id="rId9"/>',
    '<workbookPr date1904="true"/>', '<si><t>추가</t></si>',
)


def mutate_xml(rng: random.Random, xml: bytes) -> bytes:
    s = xml.decode("utf-8", "surrogateescape")
    op = rng.randrange(6)
    i = s.find(">", rng.randrange(len(s) + 1)) + 1 if s else 0
    if op == 0:
        s = s[:i] + rng.choice(_XML_TOKENS) * rng.choice((1, 1, 5, 500)) + s[i:]
    elif op == 1:                                 # 깊은 중첩
        name = rng.choice(("x", "r", "t", "is", "si", "row", "c", "sheetData"))
        k = rng.choice((50, 2000, 20000))
        s = s[:i] + f"<{name}>" * k + f"</{name}>" * k + s[i:]
    elif op == 2:                                 # 많은 빈 요소
        s = s[:i] + rng.choice(("<x/>", "<si/>", "<row/>", "<c/>", "<t/>")) * rng.choice((100, 5000, 40000)) + s[i:]
    elif op == 3:                                 # 공유 문자열 색인·줄 번호·칸 이름 바꾸기
        s = re.sub(r"<v>(\d+)</v>", lambda m: f"<v>{rng.choice(('0', '-1', '12', '99999999', m.group(1)))}</v>", s)
        s = re.sub(r'r="([A-Z]+)(\d+)"', lambda m: f'r="{rng.choice((m.group(1), "XFD", "ZZZ", "A"))}'
                   f'{rng.choice((m.group(2), "0", "100001", "1048576"))}"', s)
    elif op == 4:
        s = t_token(rng, s)
    else:
        s = s[:rng.randrange(len(s) + 1)]
    try:
        return _cap(s.encode("utf-8", "surrogateescape"))   # 원래 바이트를 그대로
    except UnicodeEncodeError:                              # 끼운 외톨이 대리 글자(\ud800)
        return _cap(s.encode("utf-8", "surrogatepass"))


def mutate_xlsx(rng: random.Random, parts: dict[str, bytes]) -> bytes:
    parts = dict(parts)
    names = list(parts)
    op = rng.randrange(7)
    if op <= 2:
        name = rng.choice(names)
        parts[name] = mutate_xml(rng, parts[name])
    elif op == 3:
        del parts[rng.choice(names)]
    elif op == 4:                                 # 관계 경로
        target = rng.choice(("../../../etc/x", "/xl/worksheets/sheet9.xml", "C:\\x", "", "worksheets/../worksheets/sheet2.xml",
                             "WORKSHEETS/SHEET1.XML", "sharedStrings.xml"))
        rels = "xl/_rels/workbook.xml.rels"
        if rels in parts:
            new = ('Target="' + target + '"').encode()
            parts[rels] = re.sub(rb'Target="[^"]*"', lambda _m: new, parts[rels], count=1)
    elif op == 5:
        name = rng.choice(names)
        parts[name] = rng.choice(BYTE_MUTATORS)(rng, parts[name])
    else:                                         # 이름 대소문자·덧붙인 부분
        name = rng.choice(names)
        parts[name.upper()] = parts.pop(name)
    data = zip_parts(parts, deflate=rng.random() < 0.7)
    if rng.random() < 0.3:                        # zip 머리: 압축 방식·암호 표시·크기·CRC
        out = bytearray(data)
        cds = [m.start() for m in re.finditer(rb"PK\x01\x02", out)]
        lhs = [m.start() for m in re.finditer(rb"PK\x03\x04", out)]
        pick = rng.randrange(4)
        if pick == 0 and cds:
            struct.pack_into("<H", out, rng.choice(cds) + 10, rng.choice((1, 6, 12, 14, 93, 99)))
        elif pick == 1 and cds:
            struct.pack_into("<H", out, rng.choice(cds) + 8, rng.choice((1, 0x41, 0x2000)))
        elif pick == 2 and cds:
            struct.pack_into("<I", out, rng.choice(cds) + 24, rng.choice((0, 1, 0x7FFFFFFF, 0xFFFFFFFF)))
        elif lhs:
            struct.pack_into("<I", out, rng.choice(lhs) + 14, rng.randrange(1 << 32))
        data = bytes(out)
    return data


# ======================================================================================
# 사례 만들기·돌리기
# ======================================================================================

def make_case(rng: random.Random) -> tuple[bytes, Optional[dict[str, Any]]]:
    kind, data, info = rng.choice(seeds())
    roll = rng.random()
    if kind == "xls" and roll < 0.6:
        streams = dict(info["streams"])
        streams["Workbook"] = mutate_biff(rng, streams["Workbook"])
        if rng.random() < 0.3:
            streams["Workbook"] = mutate_biff(rng, streams["Workbook"])
        data = make_cfb(streams, sector_shift=info["shift"])
        if rng.random() < 0.2:
            data = mutate_cfb(rng, data)
    elif kind in ("xls", "cfb") and roll < 0.85:
        data = mutate_cfb(rng, data)
    elif kind == "xlsx" and roll < 0.75:
        data = mutate_xlsx(rng, info["parts"])
    elif kind in ("text", "html") and roll < 0.7:
        data = mutate_text(rng, data)
    for _ in range(rng.choice((0, 1, 1, 2, 3))):
        data = rng.choice(BYTE_MUTATORS)(rng, data)
    mapping = None
    if rng.random() < 0.1:
        mapping = rng.choice(({"date_format": "%Y.%m.%d %H:%M:%S"}, {"default_direction": "out"},
                              {"datetime": "거래일시", "out_amount": "출금액", "in_amount": "입금액", "counterparty": "내용"},
                              {"date": "이용일", "amount": "국내이용금액", "default_direction": "out"}))
    return data, mapping


def case_bytes(seed: int, i: int) -> tuple[bytes, Optional[dict[str, Any]]]:
    """퍼징 사례 하나를 다시 만든다(실패 사례 재현용)."""
    return make_case(random.Random(seed * 1_000_003 + i))


def check_result(txns: list, report: dict[str, Any]) -> None:
    """읽은 결과의 계약: 거래가 1건 이상, 금액은 양의 정수, 연도는 범위 안, 리포트는 JSON으로 바꿀 수 있음."""
    assert txns and report["loaded"] == len(txns)
    for t in txns:
        assert isinstance(t.amount, int) and t.amount > 0
        assert MIN_YEAR <= t.ts.year <= MAX_YEAR and t.ts.tzinfo is None
    json.dumps(report, ensure_ascii=False)


def _attempt(data: bytes, mapping: Optional[dict[str, Any]]) -> tuple[str, str]:
    try:
        txns, report = load_csv(data, mapping)
        check_result(txns, report)
        return "ok", f"{len(txns)}건"
    except LoaderError as exc:
        message = str(exc)
        return ("error", message) if _HANGUL.search(message) else ("crash", "한국어 없는 안내: " + message)
    except Exception as exc:   # noqa: BLE001 - 퍼징: 어떤 예외든 실패로 기록
        return "crash", f"{type(exc).__name__}: {str(exc)[:200]}"


def run_case(data: bytes, mapping: Optional[dict[str, Any]] = None, *,
             measure_memory: bool = True, probe_sec: float = MEMORY_PROBE_SEC) -> tuple[str, str, float, int]:
    """(결과: ok|error|crash, 설명, 걸린 초, 메모리 최고치 바이트). crash = LoaderError가 아닌 예외·계약 위반.

    시간은 tracemalloc 없이 잰다(tracemalloc은 할당이 많은 경로를 10배 가까이 느리게 한다). 메모리는 probe_sec보다
    오래 걸린 사례만 tracemalloc을 켜고 한 번 더 돌려 잰다(MEM_LIMIT만큼 할당하려면 그보다 훨씬 오래 걸린다).
    사례 하나가 WATCHDOG_SEC를 넘으면 무한 루프로 보고 faulthandler가 스택을 찍고 프로세스를 끝낸다(멈춰 있지 않게)."""
    faulthandler.dump_traceback_later(WATCHDOG_SEC, exit=True)
    try:
        t0 = time.perf_counter()
        status, detail = _attempt(data, mapping)
        elapsed = time.perf_counter() - t0
        peak = 0
        if measure_memory and elapsed >= probe_sec:
            tracemalloc.start()
            try:
                _attempt(data, mapping)
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
    finally:
        faulthandler.cancel_dump_traceback_later()
    return status, detail, elapsed, peak


def fuzz(seed: int, cases: int, *, time_limit: float = TIME_LIMIT, mem_limit: int = MEM_LIMIT,
         probe_sec: float = MEMORY_PROBE_SEC) -> dict[str, Any]:
    stats = {"ok": 0, "error": 0, "crash": 0, "slow": 0, "big": 0, "max_sec": 0.0, "max_mb": 0.0, "failures": []}
    for i in range(cases):
        data, mapping = case_bytes(seed, i)
        status, detail, sec, peak = run_case(data, mapping, probe_sec=probe_sec)
        stats[status] += 1
        stats["max_sec"] = max(stats["max_sec"], sec)
        stats["max_mb"] = max(stats["max_mb"], peak / 2**20)
        problems = []
        if status == "crash":
            problems.append(detail)
        if sec > time_limit:
            stats["slow"] += 1
            problems.append(f"{sec:.2f}초")
        if peak > mem_limit:
            stats["big"] += 1
            problems.append(f"{peak / 2**20:.0f}MB")
        if problems:
            stats["failures"].append((seed, i, len(data), "; ".join(problems)))
    return stats


def _assert_clean(stats: dict[str, Any]) -> None:
    shown = "\n".join(f"  씨앗 {s} 사례 {i} ({n}바이트): {why}  → case_bytes({s}, {i})"
                      for s, i, n, why in stats["failures"][:20])
    assert not stats["failures"], f"퍼징 실패 {len(stats['failures'])}건\n{shown}"


def test_fuzz_short() -> None:
    stats = fuzz(seed=20261003, cases=SHORT_CASES, probe_sec=SHORT_PROBE_SEC)
    _assert_clean(stats)
    # 변이가 실제로 여러 길을 지나는지(모두 같은 안내로 끝나면 퍼징이 헛돈다)
    assert stats["ok"] >= SHORT_CASES // 20 and stats["error"] >= SHORT_CASES // 4


def _long_enabled(config: pytest.Config) -> bool:
    return bool(os.environ.get("SAFEPAUSE_FUZZ_LONG")) or "fuzz_long" in (config.getoption("markexpr") or "")


@pytest.mark.fuzz_long
def test_fuzz_long(request: pytest.FixtureRequest) -> None:
    if not _long_enabled(request.config):
        pytest.skip("긴 퍼징: pytest -m fuzz_long tests/test_loader_fuzz.py 또는 SAFEPAUSE_FUZZ_LONG=1")
    seed = int(os.environ.get("SAFEPAUSE_FUZZ_SEED", "1"))
    cases = int(os.environ.get("SAFEPAUSE_FUZZ_CASES", "20000"))
    stats = fuzz(seed=seed, cases=cases)
    _assert_clean(stats)


# ======================================================================================
# 회귀: 퍼징·검토로 찾아 고친 문제의 재현 입력(tests/fixtures/loader_fuzz, 무엇·찾은 곳·고치기 전 결과는 MANIFEST.json)
# ======================================================================================

_MANIFEST: dict[str, dict[str, Any]] = json.loads((REGRESS / "MANIFEST.json").read_text(encoding="utf-8"))["inputs"]


def test_regression_files_match_manifest() -> None:
    files = {p.name[:-len(".bin.gz")] for p in REGRESS.glob("*.bin.gz")}
    assert files == set(_MANIFEST)


@pytest.mark.parametrize("name", sorted(_MANIFEST))
def test_regression_input(name: str) -> None:
    entry = _MANIFEST[name]
    data = gzip.decompress((REGRESS / f"{name}.bin.gz").read_bytes())
    status, detail, sec, peak = run_case(data)
    assert status == entry["expect"], detail
    assert entry.get("message", "") in detail
    assert sec <= TIME_LIMIT, f"{sec:.2f}초"
    assert peak <= MEM_LIMIT, f"{peak / 2**20:.0f}MB"


# ======================================================================================
# 고친 곳이 결과를 바꾸지 않는지(고치기 전 식과 무작위 대조)
# ======================================================================================

def _random_text(rng: random.Random, alphabet: list[str], n: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, n)))


def test_bracket_drop_matches_old_regex() -> None:
    old = re.compile(r"[\(\[].*?[\)\]]")
    rng = random.Random(1)
    alphabet = ["(", ")", "[", "]", "\n", "\r", "a", "가", " ", " "]
    for _ in range(5000):
        s = _random_text(rng, alphabet, 20)
        assert loader._drop_brackets(s) == old.sub("", s), repr(s)


def test_telecom_single_letter_matches_old_regex() -> None:
    old = re.compile(loader._TELECOM_RE.pattern.replace("|[가-힣A-Za-z](?<!정보)", "|[가-힣A-Za-z]+(?<!정보)"),
                     re.IGNORECASE)
    assert old.pattern != loader._TELECOM_RE.pattern
    rng = random.Random(2)
    alphabet = ["통신", "텔레콤", "정보", "전자", "가", "A", "k", "1", " ", "요금", "KT", "&", "SKT", "케이티", "앤", "지",
                "ſ", "K", "비", "알뜰폰", "-"]
    for _ in range(5000):
        s = _random_text(rng, alphabet, 8)
        assert bool(old.search(s)) == bool(loader._TELECOM_RE.search(s)), repr(s)


def test_squeezed_spaces_keep_datetime_matches() -> None:
    rng = random.Random(3)
    alphabet = ["2026", "1", "12", "09", "-", ".", "/", "년", "월", "일", "(", "화", ")", "T", " ", "  ", "\t", "　",
                ":", "시", "분", "초", "오전", "PM", "a.m.", "Z", "+09:00", ".123", "x", "\n"]
    for _ in range(5000):
        s = _random_text(rng, alphabet, 12)
        for pattern in (loader._DT_RE, loader._TIME_RE):
            a, b = pattern.fullmatch(s), pattern.fullmatch(loader._squeeze(s))
            assert (a is None) == (b is None) and (a is None or a.groupdict() == b.groupdict()), repr(s)


def test_format_kind_bracket_rule_matches_old_regex() -> None:
    rng = random.Random(4)
    alphabet = ["[", "]", "h", "m", "s", "y", "d", '"', "\\", "_", "*", ";", "@", "0", "Red", "$-412", " "]
    for _ in range(5000):
        s = _random_text(rng, alphabet, 12)
        end = s.rfind("]") + 1
        assert re.sub(r"\[[^\]]*\]", "", s[:end]) + s[end:] == re.sub(r"\[[^\]]*\]", "", s), repr(s)
        assert xlsx.format_kind(s) in (None, "date", "time", "datetime")


def test_text_of_iterative_matches_recursive() -> None:
    def recursive(si: ET.Element) -> str:
        parts: list[str] = []

        def walk(el: ET.Element) -> None:
            for child in el:
                name = child.tag.rsplit("}", 1)[-1]
                if name == "rPh":
                    continue
                if name == "t":
                    parts.append(child.text or "")
                else:
                    walk(child)
        walk(si)
        return "".join(parts)

    rng = random.Random(5)

    def tree(depth: int) -> str:
        tag = rng.choice(("t", "t", "r", "rPh", "x", "a:t"))
        kids = "".join(tree(depth + 1) for _ in range(rng.randint(0, 3))) if depth < 5 else ""
        text = rng.choice(("", "가", "b", "12"))
        return f"<{tag}>{text}{kids}</{tag}>"

    for _ in range(2000):
        body = "".join(tree(0) for _ in range(rng.randint(0, 4)))
        si = ET.fromstring(f'<si xmlns:a="urn:a">{body}</si>')
        assert xlsx._text_of(si) == recursive(si)


# ======================================================================================
# 상한(고치면서 새로 생긴 안내)
# ======================================================================================

def _deep_sheet(depth: int) -> bytes:
    parts = _shared_xlsx_parts()
    sheet = parts["xl/worksheets/sheet1.xml"]
    head, tail = sheet.split(b"<sheetData>", 1)
    parts["xl/worksheets/sheet1.xml"] = head + b"<sheetData>" + b"<x>" * depth + b"</x>" * depth + tail
    return zip_parts(parts)


def test_xml_depth_limit() -> None:
    txns, _ = load_csv(_deep_sheet(xlsx.MAX_XML_DEPTH - 2))   # worksheet·sheetData와 합쳐 상한까지
    assert len(txns) == 3
    with pytest.raises(LoaderError) as e:
        load_csv(_deep_sheet(xlsx.MAX_XML_DEPTH - 1))
    assert str(e.value) == xlsx.BROKEN


def test_compression_ratio_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xlsx, "RATIO_GRACE", 1000)
    parts = _shared_xlsx_parts()
    parts["xl/styles.xml"] = parts["xl/styles.xml"].replace(b"</styleSheet>", b"<x/>" * 20000 + b"</styleSheet>")
    with pytest.raises(LoaderError) as e:
        load_csv(zip_parts(parts, deflate=True))         # 80KB가 수백 바이트로 압축됨(약 300배)
    assert str(e.value) == xlsx.TOO_PACKED
    txns, _ = load_csv(zip_parts(parts, deflate=False))  # 같은 내용을 압축하지 않은 zip은 그대로 읽는다
    assert len(txns) == 3


def test_html_few_unclosed_tags_are_still_read() -> None:
    """닫히지 않은 구문이 FREE_RESCANS번까지는 남은 글 길이와 관계없이 그대로 읽는다(정상 파일의 끝이 잘린 경우)."""
    rows = "".join(f"<tr><td>2026-05-{d:02d} 10:00</td><td>{d * 100}</td><td>0</td><td>가게</td></tr>"
                   for d in range(1, 29))
    head = "<html><table><tr><th>거래일시</th><th>출금액</th><th>입금액</th><th>내용</th></tr>"
    text = head + rows + "</table><td cla" + "가" * 2_000_000   # 잘린 태그 뒤에 '>' 없는 긴 글: 끝까지 여러 번 훑음
    txns, report = load_csv(text.encode("utf-8"))
    assert report["encoding"] == "html" and len(txns) == 28
