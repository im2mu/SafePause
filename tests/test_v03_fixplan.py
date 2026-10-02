"""v0.3 수정 계획(docs/v03_fixplan.md, 적대적 검증 반영) 백엔드 테스트.

- A 돈 보내기: 확인한 거래의 시각(45일 규칙·하루씩 밀리지 않음), 돈 흐름 분석에서 확인 기록 빼기, 확인 기록 지우기,
  보낸 척하는 문구 없음
- B 받는 사람 추천: 저장하지 않은 확인 거래(pending)도 이해충돌, 들어온 돈은 충돌 아님, 모두 충돌이면 상담하는 곳
- C 내가 한 거예요(reviews.json): 저장·API·집계 제외(탐지 등급은 그대로)
- D 항목 ai 칸, 연습용 거래 기본 조합(AI만 먼저 잡은 거래 1건 이상)
- E 지난달 같은 기간 비교, .xlsx 읽기(표준 라이브러리, 압축 폭탄 거절), 이어 붙여 올리기, 알린 거래 표시,
  직접 보낸 알림 기록 지우기, 분석 결과 표 한국어 값
- BE-1~10: 가리기 견고화, 손상 파일, 교체 순서, 옛 연락처, 오류 형식·이름표
- 새 API마다 서비스·router == FastAPI 같은 응답, 한국어 422·403·404
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient

from safepause.api import constants
from safepause.api.router import dispatch
from safepause.api.schemas import (
    ConsentIn,
    CounselorIn,
    DecideIn,
    FlagIn,
    HelperIn,
    NoticeRecordIn,
    NoticeRemoveIn,
    PendingIn,
    SampleIn,
    SuggestIn,
)
from safepause.api.service import Service, ServiceError, _mask_contact
from safepause.config import Settings
from safepause.data import xlsx as xl
from safepause.data.loader import LoaderError, load_csv
from safepause.guardian.outbox import DELIVERY_NOTE
from safepause.models import Channel, Consent, Direction, Transaction
from safepause.server.app import create_app
from safepause.store import FLAGS_FILE, NOTICES_FILE, REVIEWS_FILE, STORE_FILES, StoreError

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
NOW = datetime(2026, 10, 3, 15, 0, 0)
MOM = {"name": "엄마", "relation": "가족", "phone": "010-1234-5678", "email": "mom.kim@example.org"}


def _service(path: Path, now: Optional[Callable[[], datetime]] = None, **kw: Any) -> Service:
    return Service(path, now=now or (lambda: NOW), **kw)


@pytest.fixture
def ready(tmp_path: Path) -> Service:
    s = _service(tmp_path / "ready")
    s.put_consent(ConsentIn(monitoring=True))
    s.data_sample(SampleIn(persona="worker", seed=2, scenarios=True))
    return s


def _err(fn: Callable[[], Any]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        fn()
    return info.value


def _client(path: Path, **kw: Any) -> TestClient:
    return TestClient(create_app(path, now=lambda: NOW, **kw), base_url=BASE, headers={"X-SafePause": "1"})


def _pc(client: TestClient) -> Callable[[str, str, Any], tuple[int, Any]]:
    def call(m: str, p: str, b: Any = None) -> tuple[int, Any]:
        r = client.request(m, p, json=b) if b is not None else client.request(m, p)
        return r.status_code, r.json()
    return call


def _app(svc: Service) -> Callable[[str, str, Any], tuple[int, Any]]:
    def call(m: str, p: str, b: Any = None) -> tuple[int, Any]:
        status, body = dispatch(svc, m, p, b)
        return status, json.loads(json.dumps(body, ensure_ascii=False))
    return call


def _txn(i: int, ts: datetime, amount: int, channel: Channel = Channel.CARD, direction: Direction = Direction.OUT,
         who: str = "가게") -> Transaction:
    return Transaction(id=f"t{i:04d}", ts=ts, amount=amount, direction=direction, channel=channel, counterparty=who)


def _strings(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings(v)]
    return []


# ======================================================================================
# .xlsx: 테스트 안에서 zipfile로 직접 만든 파일(공유 문자열·인라인·숫자·날짜 일련번호·빈 칸)
# ======================================================================================

_XMLNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def serial(dt: datetime, date1904: bool = False) -> float:
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    return (dt - base).total_seconds() / 86400


def _sheet_xml(rows: list[list[Any]], doctype: str = "") -> str:
    """rows: 줄마다 칸 목록. 칸은 None(칸 없음) | ("s", 공유 문자열 번호) | ("is", 글) | ("n", 숫자, 서식 번호)
    | ("str", 글) | ("b", 0/1) | ("e", "#N/A"). 줄 앞에 정수를 두면 그 줄 번호(r)를 쓴다."""
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{doctype}<worksheet {_XMLNS}><sheetData>']
    number = 0
    for row in rows:
        if row and isinstance(row[0], int):
            number, row = row[0], row[1:]
        else:
            number += 1
        cells = []
        for k, cell in enumerate(row):
            if cell is None:
                continue
            ref = f"{chr(65 + k)}{number}"
            kind = cell[0]
            if kind == "s":
                cells.append(f'<c r="{ref}" t="s"><v>{cell[1]}</v></c>')
            elif kind == "is":
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(cell[1])}</t></is></c>')
            elif kind == "n":
                style = f' s="{cell[2]}"' if len(cell) > 2 else ""
                cells.append(f'<c r="{ref}"{style}><v>{cell[1]!r}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="{kind}"><v>{escape(str(cell[1]))}</v></c>')
        out.append(f'<row r="{number}">{"".join(cells)}</row>')
    out.append("</sheetData></worksheet>")
    return "".join(out)


def make_xlsx(rows: list[list[Any]], shared: list[str], *, date1904: bool = False, doctype: str = "",
              first_is_sheet2: bool = False, shared_xml: Optional[str] = None, big_shared: int = 0) -> bytes:
    """최소 xlsx(통합 문서·관계·공유 문자열·서식·시트). 서식 번호: 0 일반, 1 날짜(내장 14), 2 사용자 날짜·시각,
    3 시각(내장 20), 4 #,##0."""
    sst = shared_xml or (f'<sst {_XMLNS} count="{len(shared)}" uniqueCount="{len(shared)}">'
                         + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>")
    styles = (f'<styleSheet {_XMLNS}><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\.mm\\.dd hh:mm:ss"/>'
              '</numFmts><cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs><cellXfs count="5">'
              '<xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/><xf numFmtId="164" applyNumberFormat="1"/>'
              '<xf numFmtId="20" applyNumberFormat="1"/><xf numFmtId="3" applyNumberFormat="1"/></cellXfs></styleSheet>')
    order = [("다른 시트", "rId2"), ("거래내역", "rId1")] if first_is_sheet2 else [("거래내역", "rId1"), ("다른 시트", "rId2")]
    sheets = "".join(f'<sheet name="{n}" sheetId="{k + 1}" r:id="{rid}"/>' for k, (n, rid) in enumerate(order))
    pr = '<workbookPr date1904="1"/>' if date1904 else "<workbookPr/>"
    workbook = f'<workbook {_XMLNS} {_RNS}>{pr}<sheets>{sheets}</sheets></workbook>'
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="worksheet" Target="/xl/worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="sharedStrings" Target="sharedStrings.xml"/></Relationships>')
    data_sheet = _sheet_xml(rows, doctype)
    other = _sheet_xml([[("is", "이 시트는 읽지 않아요")]])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/sharedStrings.xml", b" " * big_shared if big_shared else sst)
        zf.writestr("xl/styles.xml", styles)
        # first_is_sheet2: 통합 문서의 첫 시트(rId2 → sheet2.xml)에 거래가 있다(파일 이름 순서와 다름)
        zf.writestr("xl/worksheets/sheet2.xml" if first_is_sheet2 else "xl/worksheets/sheet1.xml", data_sheet)
        zf.writestr("xl/worksheets/sheet1.xml" if first_is_sheet2 else "xl/worksheets/sheet2.xml", other)
    return buf.getvalue()


BANK_SHARED = ["거래일시", "적요", "출금액", "입금액", "내용", "모바일이체", "김*호", "카페", "급여", "회사", "합계"]


def bank_rows(date1904: bool = False) -> list[list[Any]]:
    def when(*a: int) -> tuple[str, float, int]:
        return ("n", serial(datetime(*a), date1904), 2)
    return [
        [("is", "입출금 거래내역 조회")],
        [3, ("s", 0), ("s", 1), ("s", 2), ("s", 3), ("s", 4)],                       # 2번째 줄은 비어 있음
        [when(2026, 8, 15, 12, 3, 55), ("is", "체크카드"), ("n", 5200, 4), ("n", 0), ("s", 7)],
        [when(2026, 8, 15, 3, 24, 5), ("s", 5), ("n", 250000, 4), None, ("s", 6)],   # 입금액 칸 없음(빈 칸)
        [when(2026, 8, 14, 8, 50, 37), ("is", "체크카드"), ("n", 9600), ("n", 0), ("s", 7)],
        [when(2026, 8, 14, 2, 17, 5), ("s", 5), ("n", 300000), ("n", 0), ("s", 6)],
        [when(2026, 8, 13, 9, 0, 0), ("s", 8), ("n", 0), ("n", 2100000), ("s", 9)],
        [("s", 10), None, ("n", 564800), ("n", 2100000)],
    ]


def test_xlsx_bank_file_reads_like_csv() -> None:
    data = make_xlsx(bank_rows(), BANK_SHARED)
    text = xl.xlsx_to_csv_text(data)
    lines = text.splitlines()
    assert lines[0] == "입출금 거래내역 조회" and lines[1] == ""                  # 빈 줄도 엑셀 줄 번호대로
    assert lines[2] == "거래일시,적요,출금액,입금액,내용"
    assert lines[3] == "2026-08-15 12:03:55,체크카드,5200,0,카페"
    assert lines[4] == "2026-08-15 03:24:05,모바일이체,250000,,김*호"            # 빈 칸
    assert lines[5].startswith("2026-08-14 08:50:37,")                            # 초 단위 반올림(37초가 36초로 줄지 않음)
    txns, report = load_csv(data)
    assert report["encoding"] == "xlsx" and report["header_row"] == 3
    got = [(t.ts.isoformat(sep=" "), t.amount, t.direction.value, t.counterparty) for t in txns]
    assert got == [("2026-08-13 09:00:00", 2100000, "in", "회사"), ("2026-08-14 02:17:05", 300000, "out", "김*호"),
                   ("2026-08-14 08:50:37", 9600, "out", "카페"), ("2026-08-15 03:24:05", 250000, "out", "김*호"),
                   ("2026-08-15 12:03:55", 5200, "out", "카페")]
    assert any("합계" in w for w in report["warnings"])                           # 합계 줄은 거래가 아님


def test_xlsx_date1904_first_sheet_rich_text_and_cell_kinds() -> None:
    shared_xml = (f'<sst {_XMLNS}><si><t>거래일시</t></si><si><t>출금액</t></si><si><t>내용</t></si>'
                  '<si><r><t>동네</t></r><r><t>마트</t></r><rPh sb="0" eb="1"><t>읽는 법</t></rPh></si></sst>')
    rows = [[("s", 0), ("s", 1), ("s", 2), ("is", "메모")],
            [("n", serial(datetime(2026, 9, 1, 10, 0), True), 2), ("n", 12000), ("s", 3), ("b", 1)],
            [("n", serial(datetime(2026, 9, 2, 0, 0), True), 1), ("n", 1.5e4), ("str", "수식 글"), ("e", "#N/A")]]
    text = xl.xlsx_to_csv_text(make_xlsx(rows, [], date1904=True, first_is_sheet2=True, shared_xml=shared_xml))
    assert text.splitlines() == ["거래일시,출금액,내용,메모", "2026-09-01 10:00:00,12000,동네마트,TRUE",
                                 "2026-09-02,15000,수식 글"]                       # 오류 값은 빈 칸(줄 끝은 지움)


def test_xlsx_general_format_serials_under_date_and_time_headers() -> None:
    day = serial(datetime(2026, 7, 1))
    rows = [[("is", "거래일자"), ("is", "거래시간"), ("is", "출금액"), ("is", "내용")],
            [("n", day), ("n", 0.25), ("n", 5000), ("is", "카페")],                     # 서식 없음(일반)
            [("n", day + 0.75), ("n", 0.5 + 30 / 86400), ("n", 7000), ("is", "분식집")]]
    lines = xl.xlsx_to_csv_text(make_xlsx(rows, [])).splitlines()
    assert lines[1] == "2026-07-01,06:00:00,5000,카페"
    assert lines[2] == "2026-07-01 18:00:00,12:00:30,7000,분식집"
    assert xl.format_kind("yyyy\"년\" mm\"월\" dd\"일\"") == "date"
    assert xl.format_kind("[$-412]AM/PM h:mm:ss") == "time" and xl.format_kind("#,##0") is None
    assert xl.format_kind("General") is None and xl.format_kind("yyyy-mm-dd hh:mm") == "datetime"
    assert xl.serial_to_text(serial(datetime(2026, 8, 14, 8, 50, 37)) - 1e-9, "datetime") == "2026-08-14 08:50:37"


def test_xlsx_zip_bomb_is_rejected_before_unzipping() -> None:
    bomb = make_xlsx([[("is", "a")]], [], big_shared=xl.MAX_UNZIPPED + 1)
    assert len(bomb) < constants.MAX_UPLOAD_BYTES                                 # 올릴 수 있는 크기지만
    with pytest.raises(xl.XlsxError, match="너무 커요"):
        xl.xlsx_to_csv_text(bomb)
    with pytest.raises(LoaderError, match="압축을 푼 크기가 30MB"):
        load_csv(bomb)


def test_xlsx_rejects_dtd_too_many_rows_and_non_excel_zip() -> None:
    evil = make_xlsx([[("is", "a")]], [], doctype='<!DOCTYPE x [<!ENTITY a "aaaa">]>')
    with pytest.raises(LoaderError, match="엑셀 파일\\(.xlsx\\)을 읽지 못했어요"):
        load_csv(evil)
    tall = make_xlsx([[("is", "거래일시")], [xl.MAX_ROWS + 1, ("is", "x")]], [])
    with pytest.raises(LoaderError, match="줄이 너무 많아요"):
        load_csv(tall)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<document/>")
    with pytest.raises(LoaderError, match="엑셀\\(.xlsx\\)이 아닌 압축 파일"):
        load_csv(buf.getvalue())


def test_xlsx_upload_router_matches_fastapi(tmp_path: Path) -> None:
    data = make_xlsx(bank_rows(), BANK_SHARED)
    with _client(tmp_path / "pc") as c:
        c.put("/api/consent", json={"monitoring": True})
        pc = c.post("/api/data/upload", files={"file": ("거래.xlsx", data, "application/vnd.ms-excel")})
        pc_tx = c.get("/api/transactions").json()
    svc = _service(tmp_path / "app")
    svc.put_consent(ConsentIn(monitoring=True))
    status, body = dispatch(svc, "POST", "/api/data/upload", {"mapping": ""}, data)
    assert pc.status_code == status == 200
    assert pc.json() == json.loads(json.dumps(body, ensure_ascii=False))
    assert body["summary"]["count"] == 5 and body["mode"] == "replace" and body["added"] == 5
    assert body["report"]["encoding"] == "xlsx"
    assert [i["txn"]["amount"] for i in pc_tx["items"]] == [5200, 250000, 9600, 300000, 2100000]


# ======================================================================================
# E 이어 붙여 올리기(AUG-03)
# ======================================================================================

def _csv(rows: list[tuple[str, int, str]]) -> bytes:
    lines = ["거래일시,출금액,입금액,내용"] + [f"{ts},{amt},0,{who}" for ts, amt, who in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


JULY = [("2026-07-01 10:00", 5000, "카페"), ("2026-07-02 11:00", 7000, "분식집"), ("2026-07-03 12:00", 9000, "서점")]
AUGUST = [("2026-07-03 12:00", 9000, "서점"), ("2026-08-01 10:00", 5000, "카페"), ("2026-08-01 10:00", 5000, "카페")]


def test_upload_append_keeps_old_skips_duplicates_and_keeps_marks(tmp_path: Path) -> None:
    s = _service(tmp_path)
    s.put_consent(ConsentIn(monitoring=True))
    first = s.upload(_csv(JULY))
    assert (first["mode"], first["added"], first["duplicates"]) == ("replace", 3, 0)
    old_ids = [t.id for t in s.store.load_transactions()]
    s.add_flag(FlagIn(txn_id=old_ids[0]))
    s.add_review(FlagIn(txn_id=old_ids[1]))
    r = s.upload(_csv(AUGUST), mode="append")
    # 서점(7/3)은 이미 있어 한 번만. 8/1 카페 두 건은 저장된 쪽에 없으므로 둘 다 더한다(개수까지 셈)
    assert (r["mode"], r["added"], r["duplicates"], r["summary"]["count"]) == ("append", 2, 1, 5)
    assert "이미 저장된 거래와 같은 1건은 한 번만 두었어요." in r["report"]["warnings"]
    stored = s.store.load_transactions()
    ids = [t.id for t in stored]
    assert len(set(ids)) == 5 and ids[:3] == old_ids                       # 옛 id는 그대로, 새 id는 겹치지 않음
    assert [f["txn_id"] for f in s.store.load_flags()] == [old_ids[0]]       # 담은 거래·확인 표시 유지
    assert [x["txn_id"] for x in s.store.load_reviews()] == [old_ids[1]]
    again = s.upload(_csv(AUGUST), mode="append")                           # 같은 파일을 또 올리면 모두 겹침
    assert (again["added"], again["duplicates"], again["summary"]["count"]) == (0, 3, 5)
    replaced = s.upload(_csv(JULY), mode="replace")                         # 모두 바꾸면 담음·확인 표시를 비운다
    assert replaced["summary"]["count"] == 3 and s.store.load_flags() == [] and s.store.load_reviews() == []


def test_upload_append_does_not_attach_old_marks_to_new_ids(tmp_path: Path) -> None:
    s = _service(tmp_path)
    s.put_consent(ConsentIn(monitoring=True))
    s.upload(_csv(JULY))
    s.add_flag(FlagIn(txn_id="imp-00003"))
    s.add_review(FlagIn(txn_id="imp-00003"))
    s.store.save_transactions([t for t in s.store.load_transactions() if t.id != "imp-00003"])   # 담은 거래가 사라짐
    sept = [("2026-09-01 10:00", 1000, "새 가게"), ("2026-09-02 10:00", 2000, "새 가게"),
            ("2026-09-03 10:00", 3000, "새 가게")]
    r = s.upload(_csv(sept), mode="append")                                  # 새 파일 id도 imp-00001~3
    assert r["added"] == 3
    new_ids = {t.id for t in s.store.load_transactions() if t.counterparty == "새 가게"}
    assert len(new_ids) == 3 and not new_ids & {"imp-00001", "imp-00002", "imp-00003"}
    items = s.transactions()["items"]
    assert not any(i["flagged"] or i["reviewed"] for i in items)              # 옛 표시가 새 거래에 붙지 않음


@pytest.mark.parametrize("mode", ["merge", " ", 5])
def test_upload_mode_is_checked_in_korean_on_both_paths(tmp_path: Path, mode: Any) -> None:
    data = _csv(JULY)
    svc = _service(tmp_path / "app")
    svc.put_consent(ConsentIn(monitoring=True))
    status, body = dispatch(svc, "POST", "/api/data/upload", {"mapping": "", "mode": mode}, data)
    if mode == " ":       # 빈 글은 기본값(모두 바꾸기)
        assert status == 200 and body["mode"] == "replace"
        return
    assert status == 422 and body["detail"] == "입력한 값을 확인해 주세요: 올리는 방법"
    if isinstance(mode, str):
        with _client(tmp_path / "pc") as c:
            c.put("/api/consent", json={"monitoring": True})
            r = c.post("/api/data/upload", files={"file": ("a.csv", data, "text/csv")}, data={"mode": mode})
        assert r.status_code == 422 and r.json() == body


def test_upload_append_via_fastapi_form_field(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        c.put("/api/consent", json={"monitoring": True})
        c.post("/api/data/upload", files={"file": ("a.csv", _csv(JULY), "text/csv")})
        r = c.post("/api/data/upload", files={"file": ("b.csv", _csv(AUGUST), "text/csv")}, data={"mode": "append"})
    assert r.status_code == 200 and (r.json()["added"], r.json()["duplicates"]) == (2, 1)


# ======================================================================================
# C 내가 한 거예요(reviews)
# ======================================================================================

def test_reviews_add_remove_and_counts_without_changing_levels(ready: Service) -> None:
    ready.put_consent(ConsentIn(counseling_referral=True))
    before = ready.transactions()
    highs = [i["txn"]["id"] for i in ready.transactions("high")["items"]]
    assert before["open_summary"] == before["summary"] and before["reviewed_count"] == 0
    assert ready.cards(limit=1)["counseling"]["suggest"] is True
    for k, tid in enumerate(highs, start=1):
        assert ready.add_review(FlagIn(txn_id=tid)) == {"ok": True, "count": k}
    assert ready.add_review(FlagIn(txn_id=highs[0]))["count"] == len(highs)   # 이미 표시돼 있으면 그대로
    after = ready.transactions()
    assert after["summary"] == before["summary"]                               # 탐지 등급은 그대로
    assert after["open_summary"]["high"] == 0 and after["reviewed_count"] == len(highs)
    assert {i["txn"]["id"] for i in after["items"] if i["reviewed"]} == set(highs)
    cards = ready.cards(limit=500)
    assert (cards["total"], cards["reviewed"], cards["open"]) == (before["summary"]["caution"] + len(highs),
                                                                 len(highs), before["summary"]["caution"])
    assert {c["txn"]["id"] for c in cards["items"] if c["reviewed"]} == set(highs)
    # 상담 안내 기준(30일 3번)·받는 사람 추천의 counseling_due도 내가 확인한 것을 빼고 센다
    assert cards["counseling"]["suggest"] is False and cards["counseling"]["recent_high"] == 0
    ready.put_counselors([CounselorIn(id="c1", name="센터")])
    sug = ready.notify_suggest(SuggestIn())
    assert sug["counseling_due"] is False and sug["counselors"][0]["suggested"] is False
    assert ready.export_validation()["summary"]["alerts"]["reviewed_ok"] == len(highs)
    assert ready.remove_review(FlagIn(txn_id=highs[0]))["count"] == len(highs) - 1
    assert ready.remove_review(FlagIn(txn_id=highs[0]))["count"] == len(highs) - 1   # 없는 것을 빼도 그대로
    assert json.loads((ready.store.root / REVIEWS_FILE).read_text(encoding="utf-8"))[0] == {
        "txn_id": highs[1], "status": "ok", "created_at": NOW.isoformat()}


def test_reviews_need_consent_and_known_txn(ready: Service) -> None:
    e = _err(lambda: ready.add_review(FlagIn(txn_id="no-such")))
    assert e.status == 404 and e.detail == constants.TXN_NOT_FOUND
    tid = ready.transactions("all", 1, 0)["items"][0]["txn"]["id"]
    ready.add_review(FlagIn(txn_id=tid))
    ready.put_consent(ConsentIn(monitoring=False))
    e = _err(lambda: ready.add_review(FlagIn(txn_id=tid)))
    assert e.status == 403 and e.detail == constants.NO_MONITORING
    assert ready.remove_review(FlagIn(txn_id=tid))["count"] == 0              # 빼기는 동의 없이도 된다


def test_reviews_cleared_on_replace_kept_on_append_and_wiped(ready: Service) -> None:
    tid = ready.transactions("all", 1, 0)["items"][0]["txn"]["id"]
    ready.add_review(FlagIn(txn_id=tid))
    ready.upload(_csv(JULY), mode="append")
    assert [r["txn_id"] for r in ready.store.load_reviews()] == [tid]
    ready.data_sample(SampleIn(persona="worker", seed=3))
    assert not (ready.store.root / REVIEWS_FILE).exists()
    ready.add_review(FlagIn(txn_id=ready.transactions("all", 1, 0)["items"][0]["txn"]["id"]))
    assert REVIEWS_FILE in STORE_FILES and REVIEWS_FILE in ready.wipe()["removed"]
    assert not (ready.store.root / REVIEWS_FILE).exists()


# ======================================================================================
# D AI가 한 일(ai 칸)·연습용 거래 기본 조합
# ======================================================================================

def test_default_sample_has_ai_only_case(tmp_path: Path) -> None:
    """기본 조합(인물 근로자·번호 10): 김*호 첫 새벽 이체를 규칙보다 AI가 먼저 잡는다(J3). 평가 시드와는 별개."""
    assert (SampleIn().persona, SampleIn().seed) == (constants.DEFAULT_SAMPLE_PERSONA, constants.DEFAULT_SAMPLE_SEED)
    s = _service(tmp_path)
    s.put_consent(ConsentIn(monitoring=True))
    r = s.data_sample(SampleIn())
    assert r["ai_only"] >= 1 and r["levels"]["high"] >= 10
    only = [i for i in s.transactions("caution")["items"] if i["ai"]["only_ai"]]
    assert only and all(not i["signals"] and i["level"] != "none" for i in only)
    first = only[-1]
    assert (first["txn"]["counterparty"], first["txn"]["amount"], first["txn"]["channel"]) == ("김*호", 280000, "transfer")
    assert first["ai"]["fitted"] is True and first["ai"]["percentile"] >= 98
    assert first["ai"]["top_feature"] == constants.AI_NIGHT_TEXT
    later = [i for i in s.transactions("high")["items"] if i["txn"]["counterparty"] == "김*호"]
    assert later and all(i["txn"]["ts"] > first["txn"]["ts"] and i["signals"] for i in later)   # 그다음부터 규칙도
    # 돈 보내기 예시(엄마 5만·김*호 30만 새벽·새 가게 80만)는 기본 조합에서도 그대로 나뉜다
    levels = [s.check(PendingIn(**p))["assessment"]["level"] for p in (
        {"to": "엄마", "amount": 50000, "time": "15:00"}, {"to": "김*호", "amount": 300000, "time": "02:00"},
        {"to": "새로 연 전자상가", "amount": 800000, "channel": "card", "time": "15:00"})]
    assert levels == ["none", "high", "high"]


def test_sample_summary_needs_monitoring_consent(tmp_path: Path) -> None:
    s = _service(tmp_path)
    r = s.data_sample(SampleIn())
    assert r["ai_only"] is None and r["levels"] is None                    # 동의 전에는 판단하지 않는다


def test_item_ai_field_shape(ready: Service) -> None:
    items = ready.transactions("all")["items"]
    for i in items:
        ai = i["ai"]
        assert list(ai) == ["fitted", "percentile", "top_feature", "only_ai", "raised"]
        assert ai["fitted"] is True and 0 <= ai["percentile"] <= 100
        assert abs(ai["percentile"] - i["anomaly_score"] * 100) <= 0.06
        assert ai["only_ai"] == (i["level"] != "none" and not i["signals"])
        if ai["top_feature"] is not None:
            assert any(r["code"].startswith("anomaly:") for r in i["reasons"])
            assert ai["top_feature"].endswith("요.") and "패턴" not in ai["top_feature"]
    raised = [i for i in items if i["ai"]["raised"]]
    assert raised and all(i["level"] == "high" and i["signals"] for i in raised)
    cards = ready.cards(limit=3)["items"]
    assert all(set(c["ai"]) == {"fitted", "percentile", "top_feature", "only_ai", "raised"} for c in cards)
    flagged = ready.transactions("high", 1, 0)["items"][0]["txn"]["id"]
    ready.add_flag(FlagIn(txn_id=flagged))
    assert ready.get_flags()["items"][0]["item"]["ai"]["fitted"] is True


def test_ai_field_when_model_not_fitted(tmp_path: Path) -> None:
    s = _service(tmp_path)
    s.store.save_consent(Consent(monitoring=True))
    s.store.save_transactions([_txn(i, datetime(2026, 9, 1, 10) + timedelta(days=i), 1000 + i) for i in range(10)])
    item = s.transactions()["items"][0]
    assert item["ai"] == {"fitted": False, "percentile": None, "top_feature": None, "only_ai": False, "raised": False}
    assert s.check(PendingIn(to="가게", amount=5000, channel="card"))["ai"]["fitted"] is False


# ======================================================================================
# A 확인한 거래의 시각·돈 흐름 분석에서 빼기·지우기, 보낸 척하는 문구 없음
# ======================================================================================

def test_checked_time_on_old_data_never_drifts(ready: Service) -> None:
    last = max(t.ts for t in ready.store.load_transactions())
    stamps = []
    for amount in (300000, 350000, 400000):
        r = ready.check(PendingIn(to="박*수", amount=amount, time="02:00"))
        d = ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="send"))
        stamps.append(d["pending"]["ts"])
        assert r["ts_note"] == constants.TS_NOTE
    # 오래된 데이터: 마지막 실제 거래 날짜(02:00이 그보다 이르면 다음 날)에 머물고, 여러 번 확인해도 밀리지 않는다
    assert len(set(stamps)) == 1
    assert stamps[0] == datetime.combine(last.date() + timedelta(days=1), datetime.min.time()).replace(hour=2).isoformat()
    later = ready.check(PendingIn(to="박*수", amount=1000, time="23:59"))
    assert later["pending"]["ts"] == f"{last.date().isoformat()}T23:59:00"


def test_checked_time_on_recent_data_uses_today(tmp_path: Path) -> None:
    s = _service(tmp_path)
    s.store.save_consent(Consent(monitoring=True))
    start = NOW - timedelta(days=60)
    s.store.save_transactions([_txn(i, start + timedelta(days=i, hours=1), 5000 + i) for i in range(57)])  # 3일 전까지
    r = s.check(PendingIn(to="가게", amount=5000, channel="card"))                 # 지금
    assert r["pending"]["ts"] == NOW.isoformat() and r["ts_note"] == ""
    r2 = s.check(PendingIn(to="가게", amount=5000, channel="card", time="15:00"))
    assert r2["pending"]["ts"] == f"{NOW.date().isoformat()}T15:00:00"
    d = s.decide(DecideIn(pending=PendingIn(**r2["pending"]), decision="send"))
    d2 = s.decide(DecideIn(pending=PendingIn(to="가게", amount=6000, channel="card", time="15:00"), decision="send"))
    assert d["pending"]["ts"][:10] == d2["pending"]["ts"][:10] == NOW.date().isoformat()


def test_insights_exclude_checked_records(ready: Service) -> None:
    before = ready.insights()
    r = ready.check(PendingIn(to="박*수", amount=750000, time="02:00"))
    ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="send"))
    after = ready.insights()
    assert after["checked_excluded"] == 1 and before["checked_excluded"] == 0
    assert {k: v for k, v in after.items() if k != "checked_excluded"} == \
        {k: v for k, v in before.items() if k != "checked_excluded"}                 # 나간 돈·건수·차트 그대로
    assert ready.transactions()["count"] == len(ready.store.load_transactions())       # 내 거래에는 적혀 있다


def test_insights_compare_same_period_of_last_month(tmp_path: Path) -> None:
    """3/1~6/2 매일 2만 원(FN-01): 6월 1~2일과 5월 1~2일을 견준다(지난달 한 달 전체가 아님)."""
    s = _service(tmp_path)
    s.store.save_consent(Consent(monitoring=True))
    start = datetime(2026, 3, 1, 12)
    days = (datetime(2026, 6, 2) - datetime(2026, 3, 1)).days + 1
    s.store.save_transactions([_txn(i, start + timedelta(days=i), 20000) for i in range(days)])
    got = s.insights()
    assert got["this_month"]["out_total"] == 40000 and got["prev_month"]["out_total"] == 31 * 20000
    assert got["compare"] == {"month": "2026-05", "days": 2, "prev_days": 2, "prev_same_period_out": 40000,
                              "prev_same_period_count": 2}
    s.store.save_transactions([_txn(i, start + timedelta(days=i), 20000) for i in range(31)])   # 3월만: 지난달 없음
    assert s.insights()["compare"] is None
    late = [_txn(i, datetime(2026, 5, 20) + timedelta(days=i), 20000) for i in range(20)]   # 5/20부터: 5월 1일을 모름
    s.store.save_transactions(late)
    assert s.insights()["compare"] is None


def test_insights_compare_clips_to_shorter_last_month(tmp_path: Path) -> None:
    s = _service(tmp_path)
    s.store.save_consent(Consent(monitoring=True))
    txns = [_txn(i, datetime(2026, 1, 25) + timedelta(days=i), 1000) for i in range(66)]   # 1/25 ~ 3/31
    s.store.save_transactions(txns)
    got = s.insights()["compare"]
    assert got == {"month": "2026-02", "days": 31, "prev_days": 28, "prev_same_period_out": 28000,
                   "prev_same_period_count": 28}


def test_remove_checked_record(ready: Service) -> None:
    r = ready.check(PendingIn(to="박*수", amount=300000, time="02:00"))
    d = ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="send"))
    live = d["pending"]["id"]
    count = len(ready.store.load_transactions())
    ready.add_flag(FlagIn(txn_id=live))
    ready.add_review(FlagIn(txn_id=live))
    other = ready.transactions("all", 2, 0)["items"][1]["txn"]["id"]
    ready.add_flag(FlagIn(txn_id=other))
    ready.put_consent(ConsentIn(monitoring=False))                         # 지우기는 동의 없이도 된다
    assert ready.remove_checked(FlagIn(txn_id=live)) == {"ok": True, "count": count - 1}
    assert live not in {t.id for t in ready.store.load_transactions()}
    assert [f["txn_id"] for f in ready.store.load_flags()] == [other]        # 관련 담음·확인 표시만 정리
    assert ready.store.load_reviews() == []
    assert any(x["txn_id"] == live for x in ready.store.load_decisions())    # 결정 기록은 남긴다
    e = _err(lambda: ready.remove_checked(FlagIn(txn_id=live)))
    assert e.status == 404 and e.detail == constants.TXN_NOT_FOUND
    e = _err(lambda: ready.remove_checked(FlagIn(txn_id=other)))
    assert e.status == 400 and e.detail == constants.ONLY_CHECKED == "보내기 전 확인 기록만 지울 수 있어요."


def test_money_texts_promise_nothing_sent(ready: Service) -> None:
    ready.put_consent(ConsentIn(helper_alerts=True, counseling_referral=True))
    ready.put_helpers([HelperIn(id="h1", min_level="caution", **MOM), HelperIn(id="h2", name="아빠", min_level="caution")])
    texts: list[str] = [DELIVERY_NOTE]
    for decision in ("send", "cancel", "ask_helper"):
        r = ready.check(PendingIn(to="박*수", amount=900000, time="02:00"))
        texts += _strings(r["notify_plan_preview"]) + [r["ts_note"]]
        helper_ids = ["h1"] if decision == "ask_helper" else None
        d = ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision=decision, helper_ids=helper_ids))
        texts += _strings({k: v for k, v in d.items() if k not in ("assessment", "pending")})
    texts += _strings(ready.notices())
    for text in texts:
        for banned in ("알려 드릴", "알렸어요", "결정은 본인이 해요", "결정은 내가 해요", "이 기기", "보내지 않아요"):
            assert banned not in text or text == constants.NOTICES_NOTE, (banned, text)
    assert DELIVERY_NOTE == "알림은 기록만 해요. 문자나 메일은 알림 보내기에서 보낼 수 있어요."


def test_old_auto_records_are_shown_without_decision_sentence(ready: Service) -> None:
    old = [{"helper_id": "h1", "helper_name": "010-1234-5678", "txn_id": "live-00001", "level": "high",
            "message": "[SafePause] 함께 확인이 필요한 거래가 있어요. 결정은 본인이 해요. 먼저 본인과 이야기해 주세요.",
            "created_at": "2026-09-01T10:00:00"}]
    (ready.store.root / NOTICES_FILE).write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    item = ready.notices()["items"][0]
    assert item["message"] == "[SafePause] 함께 확인이 필요한 거래가 있어요. 먼저 본인과 이야기해 주세요."
    assert item["helper_name"] == "010-****-5678" and item["kind"] == "auto"


# ======================================================================================
# B 받는 사람 추천(pending·들어온 돈·모두 충돌)
# ======================================================================================

def test_suggest_pending_payee_helper_is_conflict(ready: Service) -> None:
    """RF-1: 물어볼래요로 넘어온 저장하지 않은 확인 거래도 이해충돌을 본다."""
    ready.put_consent(ConsentIn(helper_alerts=True))
    ready.put_helpers([HelperIn(id="kim", name="김철수", identifiers=["김*호"], min_level="caution",
                                phone="010-2222-3333")])
    r = ready.check(PendingIn(to="김*호", amount=300000, channel="transfer", time="02:00"))
    count = len(ready.store.load_transactions())
    old = ready.notify_suggest(SuggestIn())                                   # 거래 없이: 예전처럼 active만
    assert old["helpers"][0]["suggested"] is True
    got = ready.notify_suggest(SuggestIn(pending=PendingIn(**r["pending"])))
    assert got["helpers"] == [{"id": "kim", "name": "김철수", "suggested": False, "conflict": True,
                               "reason": constants.CONFLICT_REASON}]
    assert len(ready.store.load_transactions()) == count                      # 저장하지 않는다
    # 그래도 보낼래요로 이미 적힌 확인 거래(같은 id)도 같은 판단
    d = ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="send"))
    saved = ready.notify_suggest(SuggestIn(txn_ids=[d["pending"]["id"]], pending=PendingIn(**d["pending"])))
    assert saved["helpers"][0]["conflict"] is True


def test_suggest_incoming_money_from_helper_is_not_conflict(ready: Service) -> None:
    """BE-4: 조력자가 돈을 보낸(들어온 돈) 거래에서는 돈을 받은 사람이 아니다."""
    ready.put_consent(ConsentIn(helper_alerts=True))
    incoming = next(t for t in ready.store.load_transactions() if t.direction == Direction.IN and t.counterparty)
    ready.put_helpers([HelperIn(id="mom", name="엄마", identifiers=[incoming.counterparty])])
    got = ready.notify_suggest(SuggestIn(txn_ids=[incoming.id]))["helpers"][0]
    assert got["conflict"] is False and got["reason"] == ""


def test_suggest_counselors_when_every_eligible_helper_is_payee(tmp_path: Path) -> None:
    """BE-5: 알릴 조력자가 모두 돈을 받은 사람이면(policy의 all_conflicted) 상담하는 곳을 추천한다."""
    s = _service(tmp_path, settings=Settings(high_repeat_for_counseling=99))   # 반복 기준(30일 3번)은 빼고 본다
    s.put_consent(ConsentIn(monitoring=True, helper_alerts=True, counseling_referral=True))
    s.data_sample(SampleIn(persona="worker", seed=2))
    payee = next(i["txn"] for i in s.transactions("high")["items"] if "payee_surge" in i["signals"])
    s.put_helpers([HelperIn(id="h1", name="받은 사람", identifiers=[payee["counterparty"]], min_level="caution"),
                   HelperIn(id="h2", name="자동 끔", active=False)])
    s.put_counselors([CounselorIn(id="c1", name="센터"), CounselorIn(id="c2", name="쉬는 곳", active=False)])
    got = s.notify_suggest(SuggestIn(txn_ids=[payee["id"]]))
    assert got["counseling_due"] is False and got["counseling_reason"] == "conflict"
    assert [(c["id"], c["suggested"]) for c in got["counselors"]] == [("c1", True), ("c2", False)]
    s.put_consent(ConsentIn(counseling_referral=False))
    off = s.notify_suggest(SuggestIn(txn_ids=[payee["id"]]))
    assert off["counseling_reason"] == "" and not any(c["suggested"] for c in off["counselors"])
    s.put_consent(ConsentIn(counseling_referral=True))
    s.put_helpers([HelperIn(id="h1", name="받은 사람", identifiers=[payee["counterparty"]], min_level="caution"),
                   HelperIn(id="h3", name="엄마", min_level="caution")])          # 알릴 수 있는 사람이 있으면 아님
    assert s.notify_suggest(SuggestIn(txn_ids=[payee["id"]]))["counseling_reason"] == ""


@pytest.mark.parametrize("pending,label", [({"to": "", "amount": 1}, "받는 사람"), ({"to": "x", "amount": 0}, "금액"),
                                           ({"to": "x", "amount": 1, "channel": "income"}, "보내는 방법")])
def test_suggest_pending_input_errors_are_korean(tmp_path: Path, pending: dict[str, Any], label: str) -> None:
    status, body = dispatch(_service(tmp_path), "POST", "/api/notify/suggest", {"txn_ids": [], "pending": pending})
    assert status == 422 and body["detail"] == f"입력한 값을 확인해 주세요: {label}"


# ======================================================================================
# E 알린 거래 표시·직접 보낸 알림 기록 지우기
# ======================================================================================

def test_notified_at_and_notice_remove(tmp_path: Path) -> None:
    clock = [NOW]
    s = _service(tmp_path, now=lambda: clock[0])
    s.put_consent(ConsentIn(monitoring=True))
    s.data_sample(SampleIn(persona="worker", seed=2))
    a, b = (i["txn"]["id"] for i in s.transactions("high", 2, 0)["items"])
    s.put_helpers([HelperIn(id="h1", **MOM)])
    body = {"channel": "sms", "recipients": [{"kind": "helper", "id": "h1", "name": "엄마"}], "message": "확인해 주세요."}
    first = s.record_notice(NoticeRecordIn(**body, txn_ids=[a]))
    clock[0] = NOW + timedelta(hours=1)
    s.record_notice(NoticeRecordIn(**body, txn_ids=[a, b]))
    s.record_notice(NoticeRecordIn(**{**body, "channel": "copy"}, txn_ids=[]))
    assert first["recipients"] == [{"kind": "helper", "id": "h1", "name": "엄마"}]   # 다시 보내기용 id
    items = {i["txn"]["id"]: i for i in s.transactions("high")["items"]}
    later = (NOW + timedelta(hours=1)).isoformat()
    assert items[a]["notified_at"] == later and items[b]["notified_at"] == later
    assert sum(1 for i in items.values() if i["notified_at"]) == 2
    cards = {c["txn"]["id"]: c for c in s.cards(limit=500)["items"]}
    assert cards[a]["notified_at"] == later
    # 직접 보낸 기록만 지운다
    assert s.remove_notice(NoticeRemoveIn(id="m1")) == {"ok": True, "count": 2}
    assert [i["id"] for i in s.notices()["items"]] == ["m3", "m2"]
    e = _err(lambda: s.remove_notice(NoticeRemoveIn(id="m1")))
    assert e.status == 404 and e.detail == constants.NOTICE_NOT_FOUND
    s.store.append_notice_record({"helper_id": "h1", "helper_name": "엄마", "txn_id": a, "level": "high",
                                  "message": "자동", "created_at": NOW.isoformat()})   # 자동 기록(id 없음)
    for rid in ("auto", "h1"):
        assert _err(lambda: s.remove_notice(NoticeRemoveIn(id=rid))).status == 404
    assert len(s.notices()["items"]) == 3


def test_unknown_recipient_id_is_not_stored(svc_path: Path) -> None:
    s = _service(svc_path)
    rec = s.record_notice(NoticeRecordIn(channel="sms", message="확인해 주세요.",
                                         recipients=[{"kind": "helper", "id": "010-1234-5678", "name": "엄마"}]))
    assert rec["recipients"] == [{"kind": "helper", "id": "", "name": "엄마"}]


@pytest.fixture
def svc_path(tmp_path: Path) -> Path:
    return tmp_path / "svc"


# ======================================================================================
# 분석 결과 표(CSV) 한국어 값
# ======================================================================================

def test_results_csv_uses_screen_names(ready: Service) -> None:
    text = ready.export_results_csv()["text"].lstrip("﻿")
    header, *rows = text.splitlines()
    assert header == "거래일시,나감/들어옴,방법,상대,금액(원),판단,걸린 약속,AI 점수(0~1),보내기 전 확인"
    methods = {r.split(",")[2] for r in rows}
    assert methods <= set(constants.CHANNEL_KO.values())
    for code in [*constants.SIGNAL_KO, "transfer", "micropay", "telecom_bill"]:
        assert code not in text
    assert any("한 사람에게 송금 집중" in r for r in rows)


# ======================================================================================
# BE-1~3 가리기, BE-6 손상 파일, BE-7 교체 순서
# ======================================================================================

def test_scrub_catches_number_and_email_variants(svc_path: Path) -> None:
    s = _service(svc_path)
    s.put_helpers([HelperIn(id="h1", **MOM)])
    s.put_counselors([CounselorIn(id="c1", name="선생님", phone="010 5555 6666")])
    variants = ["010 1234 5678", "010.1234.5678", "+82-10-1234-5678", "+821012345678", "(010)1234-5678",
                "+82 (0)10 1234 5678", "MOM.KIM@EXAMPLE.ORG", "Mom.Kim@example.org", "010-5555-6666", "01055556666"]
    rec = s.record_notice(NoticeRecordIn(channel="sms", recipients=[{"kind": "helper", "id": "h1", "name": "엄마"}],
                                         message=" / ".join(variants)))
    stored = (svc_path / NOTICES_FILE).read_text(encoding="utf-8")
    for text in (rec["message"], stored, json.dumps(s.notices(), ensure_ascii=False)):
        assert "1234" not in text and "5555" not in text and "mom.kim" not in text.lower(), text
    assert rec["message"].count("010-****-5678") == 6 and rec["message"].count("010-****-6666") == 2
    assert rec["message"].count(" / ") == len(variants) - 1                  # 앞뒤 띄어쓰기는 그대로
    assert rec["message"].count("mo***@example.org") == 2                     # 대소문자가 달라도 같은 메일
    # 다른 번호(가게 번호 등)는 그대로
    other = s.record_notice(NoticeRecordIn(channel="sms", recipients=[{"kind": "helper", "name": "엄마"}],
                                           message="가게 02-987-6543"))
    assert other["message"] == "가게 02-987-6543"


@pytest.mark.parametrize("raw,masked", [("엄마@example.org", "엄***@example.org"), ("mom@메일.한국", "mo***@메일.한국"),
                                        ("mom@my_host.org", "mo***@my_host.org"),
                                        ("first&last@example.com", "fi***@example.com")])
def test_mask_contact_covers_every_accepted_email(svc_path: Path, raw: str, masked: str) -> None:
    assert _mask_contact(raw) == masked
    s = _service(svc_path)
    h = s.put_helpers([HelperIn(name="엄마", email=raw)])[0]
    assert h["email"] == raw and h["email_masked"] == masked
    rec = s.record_notice(NoticeRecordIn(channel="email", recipients=[{"kind": "helper", "id": h["id"], "name": "엄마"}],
                                         message=f"{raw} 로 보냈어요"))
    assert raw not in rec["message"]


def test_auto_record_helper_name_is_masked(ready: Service) -> None:
    """BE-3: 이름이 번호인 조력자도 적어 둔 기록에는 가린 값만."""
    ready.put_consent(ConsentIn(helper_alerts=True))
    ready.put_helpers([HelperIn(id="h1", name="010-1234-5678", phone="010-1234-5678", min_level="caution")])
    r = ready.check(PendingIn(to="모르는 사람", amount=900000, time="02:00"))
    ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="send"))
    assert "010-1234-5678" not in (ready.store.root / NOTICES_FILE).read_text(encoding="utf-8")
    assert ready.notices()["items"][0]["helper_name"] == "010-****-5678"


@pytest.mark.parametrize("broken", ['{"a":1}', '[{"txn_id":5}]', "[1,2]", "{{{"])
def test_broken_flags_or_reviews_file_does_not_block_screens(ready: Service, broken: str) -> None:
    for name in (FLAGS_FILE, REVIEWS_FILE):
        (ready.store.root / name).write_text(broken, encoding="utf-8")
    assert ready.transactions("all", 1, 0)["flagged_count"] == 0
    assert ready.cards(limit=1)["total"] > 0 and ready.get_flags() == {"items": []}
    assert dispatch(ready, "GET", "/api/transactions?limit=1")[0] == 200
    assert ready.remove_flag(FlagIn(txn_id="x")) == {"ok": True, "count": 0}       # 손상 파일을 비워 고친다
    assert ready.remove_review(FlagIn(txn_id="x")) == {"ok": True, "count": 0}
    assert ready.store.load_flags() == [] and ready.store.load_reviews() == []
    tid = ready.transactions("all", 1, 0)["items"][0]["txn"]["id"]
    (ready.store.root / FLAGS_FILE).write_text(broken, encoding="utf-8")
    assert ready.add_flag(FlagIn(txn_id=tid))["count"] == 1                          # 담기도 새 목록으로


@pytest.mark.parametrize("broken", ["{{{", '[{"name":"x"}]', '["x"]'])
def test_broken_counselors_file_does_not_block_cards(ready: Service, broken: str) -> None:
    ready.put_consent(ConsentIn(counseling_referral=True))
    (ready.store.root / "counselors.json").write_text(broken, encoding="utf-8")
    assert ready.cards(limit=1)["counseling"]["orgs"] == ["지역발달장애인지원센터", "장애인권익옹호기관"]
    assert ready.get_counselors()["items"] == [] and ready.notify_suggest(SuggestIn())["counselors"] == []
    rec = ready.record_notice(NoticeRecordIn(channel="sms", recipients=[{"kind": "counselor", "id": "c1", "name": "센터"}],
                                             message="확인해 주세요."))
    assert rec["recipients"] == [{"kind": "counselor", "id": "", "name": "센터"}]
    ready.put_counselors([CounselorIn(name="새 센터")])                         # 다시 저장하면 새 목록으로
    assert [c["name"] for c in ready.get_counselors()["items"]] == ["새 센터"]


def test_replace_clears_marks_before_saving_transactions(ready: Service, monkeypatch: pytest.MonkeyPatch) -> None:
    """BE-7: 담음 비우기가 실패하면 거래도 바꾸지 않는다(옛 담음이 새 거래에 붙지 않게)."""
    ids = [i["txn"]["id"] for i in ready.transactions("all", 3, 0)["items"]]
    for tid in ids:
        ready.add_flag(FlagIn(txn_id=tid))
    before = [t.id for t in ready.store.load_transactions()]

    def fail() -> None:
        raise StoreError("저장 파일을 쓸 수 없어요.")
    monkeypatch.setattr(ready.store, "clear_flags", fail)
    status, body = dispatch(ready, "POST", "/api/data/sample", {"persona": "worker", "seed": 9, "days": 200})
    assert status == 500 and "쓸 수 없어요" in body["detail"]
    assert [t.id for t in ready.store.load_transactions()] == before
    assert {f["txn_id"] for f in ready.store.load_flags()} == set(ids)


# ======================================================================================
# BE-9·10 오류 형식·이름표, 새 API 파리티
# ======================================================================================

@pytest.mark.parametrize("method,path,body", [("POST", "/api/flags", []), ("PUT", "/api/counselors", [None]),
                                              ("POST", "/api/notify/suggest", []), ("POST", "/api/reviews", []),
                                              ("PUT", "/api/helpers", [None]), ("POST", "/api/notices/remove", [])])
def test_non_object_body_errors_match_fastapi(tmp_path: Path, method: str, path: str, body: Any) -> None:
    with _client(tmp_path / "pc") as c:
        pc = c.request(method, path, json=body)
    status, app_body = dispatch(_service(tmp_path / "app"), method, path, body)
    assert pc.status_code == status == 422
    assert pc.json() == json.loads(json.dumps(app_body, ensure_ascii=False))


@pytest.mark.parametrize("path,body,label", [
    ("/api/counselors", [{"name": "a", "active": "yes"}], "사용"),
    ("/api/counselors", [None], "상담하는 곳"),
    ("/api/helpers", [None], "조력자"),
    ("/api/helpers", [{"name": "엄마", "active": "yes"}], "자동으로 알리기"),
])
def test_korean_labels_per_screen(tmp_path: Path, path: str, body: Any, label: str) -> None:
    for call in (_pc(_client(tmp_path / "pc")), _app(_service(tmp_path / "app"))):
        status, out = call("PUT", path, body)
        assert status == 422 and out["detail"] == f"입력한 값을 확인해 주세요: {label}"


def test_recipient_id_error_label(tmp_path: Path) -> None:
    body = {"channel": "sms", "recipients": [{"kind": "helper", "id": 5, "name": "엄마"}], "message": "확인해 주세요."}
    for call in (_pc(_client(tmp_path / "pc")), _app(_service(tmp_path / "app"))):
        status, out = call("POST", "/api/notices/record", body)
        assert status == 422 and out["detail"] == "입력한 값을 확인해 주세요: 받는 사람"


def _new_api_scenario(call: Callable[[str, str, Any], tuple[int, Any]]) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []

    def step(m: str, p: str, b: Any = None) -> Any:
        out.append(call(m, p, b))
        return out[-1][1]

    step("POST", "/api/reviews", {"txn_id": "x"})                                           # 403
    step("PUT", "/api/consent", {"monitoring": True, "helper_alerts": True, "counseling_referral": True})
    step("POST", "/api/data/sample", {"persona": "worker", "seed": 2})
    high = step("GET", "/api/transactions?level=high&limit=2")["items"]
    step("POST", "/api/reviews", {"txn_id": high[0]["txn"]["id"]})
    step("POST", "/api/reviews", {"txn_id": "no-such"})                                     # 404
    step("POST", "/api/reviews", {})                                                        # 422
    step("POST", "/api/reviews", {"txn_id": "a", "more": 1})                                # 422
    step("GET", "/api/transactions?limit=3")
    step("GET", "/api/cards?limit=3")
    step("PUT", "/api/helpers", [{"id": "kim", "name": "김철수", "identifiers": ["김*호"], "min_level": "caution"}])
    pending = step("POST", "/api/safepause/check", {"to": "김*호", "amount": 300000, "time": "02:00"})["pending"]
    step("POST", "/api/notify/suggest", {"txn_ids": [], "pending": pending})
    step("POST", "/api/notify/suggest", {"txn_ids": [], "pending": {"to": "", "amount": 1}})   # 422
    sent = step("POST", "/api/safepause/decide", {"pending": pending, "decision": "send"})["pending"]
    step("POST", "/api/notices/record", {"channel": "sms", "recipients": [{"kind": "helper", "id": "kim", "name": "김"}],
                                          "txn_ids": [high[1]["txn"]["id"]], "message": "확인해 주세요."})
    step("GET", "/api/notices")
    step("POST", "/api/notices/remove", {"id": "m1"})
    step("POST", "/api/notices/remove", {"id": "m1"})                                       # 404
    step("POST", "/api/notices/remove", {"id": " "})                                        # 422
    step("GET", "/api/insights")
    step("POST", "/api/transactions/remove-checked", {"txn_id": high[1]["txn"]["id"]})      # 400
    step("POST", "/api/transactions/remove-checked", {"txn_id": sent["id"]})
    step("POST", "/api/transactions/remove-checked", {"txn_id": sent["id"]})               # 404
    step("POST", "/api/reviews/remove", {"txn_id": high[0]["txn"]["id"]})
    step("PUT", "/api/reviews", {"txn_id": "a"})                                           # 405
    step("POST", "/api/wipe")
    return out


def test_router_matches_fastapi_for_new_apis(tmp_path: Path) -> None:
    with _client(tmp_path / "pc") as c:
        got_pc = _new_api_scenario(_pc(c))
    got_app = _new_api_scenario(_app(_service(tmp_path / "app")))
    assert got_pc == got_app
    statuses = [s for s, _ in got_pc]
    assert statuses.count(403) == 1 and statuses.count(404) == 3 and statuses.count(422) == 4
    assert statuses.count(400) == 1 and statuses.count(405) == 1
    assert all(re.search(r"[가-힣]", b["detail"]) for s, b in got_pc if s != 200)
    sug = got_pc[12][1]
    assert sug["helpers"][0]["conflict"] is True and sug["helpers"][0]["suggested"] is False
    assert REVIEWS_FILE in got_pc[-1][1]["removed"]


def test_new_light_routes_do_not_load_numpy(tmp_path: Path) -> None:
    """내가 한 거예요·지우기 API는 AI 패키지 없이 처리한다(앱이 AI를 싣기 전에도: worker.mjs BASIC에 넣을 수 있음)."""
    code = r'''
import json, sys
from datetime import datetime
from safepause.api.router import dispatch
from safepause.api.service import Service
from safepause.models import Channel, Consent, Direction, Transaction
s = Service(sys.argv[1])
s.store.save_consent(Consent(monitoring=True))
s.store.save_transactions([Transaction(id="live-00001", ts=datetime(2026, 9, 1, 10), amount=1000,
                                       direction=Direction.OUT, channel=Channel.TRANSFER, counterparty="가게")])
calls = [("POST", "/api/reviews", {"txn_id": "live-00001"}), ("POST", "/api/reviews/remove", {"txn_id": "live-00001"}),
         ("POST", "/api/notices/record", {"channel": "sms", "recipients": [{"kind": "helper", "name": "엄마"}],
                                          "message": "확인해 주세요."}),
         ("POST", "/api/notices/remove", {"id": "m1"}),
         ("POST", "/api/transactions/remove-checked", {"txn_id": "live-00001"})]
print(json.dumps([dispatch(s, m, p, b)[0] for m, p, b in calls]))
print(int("numpy" in sys.modules), int("sklearn" in sys.modules))
'''
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path / "s")], capture_output=True, text=True,
                         cwd=ROOT, check=True)
    statuses, loaded = out.stdout.strip().splitlines()
    assert json.loads(statuses) == [200] * 5
    assert loaded.split() == ["0", "0"]


# ======================================================================================
# E 거래 검색·기간(AUG-09·J9), 조력자·기관용 요약 한 장(AUG-10)
# ======================================================================================

def test_transactions_search_by_name_and_period(tmp_path: Path) -> None:
    s = _service(tmp_path)
    s.put_consent(ConsentIn(monitoring=True))
    s.data_sample(SampleIn())                                                  # 근로자·번호 10(김*호 사례)
    all_kim = [t for t in s.store.load_transactions() if t.counterparty == "김*호"]
    got = s.transactions("all", 0, 0, q=" 김 *호 ")                            # 공백·대소문자 무시
    assert got["matched"] == len(all_kim) and {i["txn"]["counterparty"] for i in got["items"]} == {"김*호"}
    assert got["count"] == len(s.store.load_transactions())                   # 전체 수는 그대로
    first = min(t.ts for t in all_kim).date()
    late = s.transactions("high", 0, 0, q="김*호", since=first + timedelta(days=1))
    assert late["matched"] >= 1 and all(i["txn"]["ts"][:10] > first.isoformat() for i in late["items"])
    one_day = s.transactions("all", 0, 0, since=first, until=first)
    assert {i["txn"]["ts"][:10] for i in one_day["items"]} == {first.isoformat()}
    assert s.transactions("all", 0, 0, q="없는 이름")["matched"] == 0


def test_transactions_filters_parity_and_errors(tmp_path: Path) -> None:
    def scenario(call: Callable[[str, str, Any], tuple[int, Any]]) -> list[tuple[int, Any]]:
        out = [call("PUT", "/api/consent", {"monitoring": True}),
               call("POST", "/api/data/sample", {"persona": "worker", "seed": 10})]
        for qs in ("q=%EA%B9%80*%ED%98%B8&limit=3", "since=2026-06-18&until=2026-06-20&level=high",
                   "since=2026-13-01", "until=abc", "q=" + "x" * 41):
            out.append(call("GET", f"/api/transactions?{qs}", None))
        return out
    with _client(tmp_path / "pc") as c:
        got_pc = scenario(_pc(c))
    got_app = scenario(_app(_service(tmp_path / "app")))
    assert got_pc == got_app
    assert [s for s, _ in got_pc] == [200, 200, 200, 200, 422, 422, 422]
    assert [b["detail"] for _, b in got_pc[4:]] == ["입력한 값을 확인해 주세요: 시작 날짜",
                                                   "입력한 값을 확인해 주세요: 끝 날짜", "입력한 값을 확인해 주세요: 검색어"]


def test_export_summary_has_no_names_or_accounts(ready: Service) -> None:
    ready.put_helpers([HelperIn(id="h1", **MOM)])
    tid = ready.transactions("high", 1, 0)["items"][0]["txn"]["id"]
    ready.add_review(FlagIn(txn_id=tid))
    ready.record_notice(NoticeRecordIn(channel="sms", recipients=[{"kind": "helper", "id": "h1", "name": "엄마"}],
                                       message="확인해 주세요.", txn_ids=[tid]))
    out = ready.export_summary()
    text = out["text"]
    assert out["mime"] == "text/plain" and out["filename"] == "safepause-summary-20261003.txt"
    names = {t.counterparty for t in ready.store.load_transactions() if t.counterparty}
    ids = {t.counterparty_id for t in ready.store.load_transactions() if t.counterparty_id}
    assert not [n for n in names | ids if n and n in text]
    assert "엄마" not in text and "010" not in text
    summary = ready.transactions()
    assert f"꼭 확인할 거래 {summary['open_summary']['high']:,}건" in text
    assert "직접 한 거래라고 표시한 1건은 빼고 셌어요." in text and "직접 보낸 알림 기록 1건" in text
    assert "한 사람에게 송금 집중:" in text and "payee_surge" not in text
    for line in text.splitlines():                                         # 한 줄에 한 문장
        assert line.count("요.") <= 1, line
    ready.put_consent(ConsentIn(monitoring=False))
    assert _err(ready.export_summary).status == 403
    assert dispatch(ready, "GET", "/api/export/summary")[0] == 403
