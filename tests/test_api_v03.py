"""v0.3 API 테스트: 조력자 번호·메일 원본, 상담하는 곳, 알림 목록에 담기, 보낸 알림 기록, 돈 흐름 분석,
받는 사람 추천(notify/suggest), 돈 보내기 응답 글(check/decide에 연습이라는 말 없음).

- 서비스 동작, 라우터(안드로이드) = FastAPI(PC) 같은 응답, 입력 오류 422(한국어), 동의 꺼짐 403
- 모두 지우기가 새 저장 파일(counselors.json·flags.json)을 지우는지, 거래를 통째로 바꾸면 담은 거래가 비는지
- insights 수치를 거래 목록에서 직접 다시 계산해 대조
- 번호·메일 원본이 내보내기·알림 기록에 들어가지 않는지
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pytest
from fastapi.testclient import TestClient

from safepause import __version__
from safepause.api import constants
from safepause.api.router import dispatch
from safepause.api.schemas import ConsentIn, CounselorIn, FlagIn, HelperIn, NoticeRecordIn, SampleIn, SuggestIn
from safepause.api.service import Service, ServiceError
from safepause.explain.easy_card import FORBIDDEN_WORDS
from safepause.guardian.policy import COUNSELING_ORGS
from safepause.models import Channel, Consent, Direction, Transaction
from safepause.server.app import create_app
from safepause.store import COUNSELORS_FILE, FLAGS_FILE, NOTICES_FILE, STORE_FILES, Store

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
NOW = datetime(2026, 9, 30, 12, 0, 0)
BANK_EXAMPLE = ROOT / "sample_data" / "bank_export_example.csv"
MOM = {"name": "엄마", "relation": "가족", "phone": "010-1234-5678", "email": "mom.kim@example.org"}


def _service(path: Path) -> Service:
    return Service(path, now=lambda: NOW)


@pytest.fixture
def svc(tmp_path: Path) -> Service:
    return _service(tmp_path / "store")


@pytest.fixture
def ready(tmp_path: Path) -> Service:
    s = _service(tmp_path / "ready")
    s.put_consent(ConsentIn(monitoring=True))
    s.data_sample(SampleIn(persona="worker", seed=2, scenarios=True))
    return s


def _ids(s: Service, level: str = "all", n: int = 3) -> list[str]:
    return [i["txn"]["id"] for i in s.transactions(level, n, 0)["items"]]


def _err(fn: Callable[[], Any]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        fn()
    return info.value


# ---- 버전·문구 -------------------------------------------------------------------------

def test_version_is_0_3_0() -> None:
    assert __version__ == "0.3.0"
    assert 'version = "0.3.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_python_user_phrases_have_no_quoted_words() -> None:
    """R14: 파이썬 사용자 문구에 따옴표로 감싼 낱말이 없다."""
    from safepause.explain.easy_card import NO_HELPER_HINT
    quoted = re.compile(r"['\"‘’“”][^'\"‘’“”]*[가-힣][^'\"‘’“”]*['\"‘’“”]")
    texts = [constants.NO_MONITORING, constants.NOTICES_NOTE, constants.TXN_NOT_FOUND, NO_HELPER_HINT,
             *(p["name"] + p["memo"] for p in constants.COUNSELOR_PRESETS)]
    for text in texts:
        assert not quoted.search(text), text
    assert constants.NO_MONITORING.endswith("동의 화면에서 거래 살펴보기를 켜 주세요.")


def test_new_phrases_avoid_forbidden_words() -> None:
    texts = [constants.NOTICES_NOTE, constants.TXN_NOT_FOUND,
             *(p["name"] + p["memo"] for p in constants.COUNSELOR_PRESETS)]
    for text in texts:
        for word in (*FORBIDDEN_WORDS, "고위험", "푸시", "당사자님", "막지 않아요", "127.0.0.1"):
            assert word not in text, (word, text)


def test_counseling_consent_field_name() -> None:
    from safepause.api.schemas import FIELD_KO
    assert FIELD_KO["counseling_referral"] == "상담하는 곳에 알려 주기"


# ---- 3.1 조력자 번호·메일 원본 -------------------------------------------------------------

def test_helper_phone_email_saved_raw_and_shown_masked(svc: Service) -> None:
    saved = svc.put_helpers([HelperIn(**MOM)])
    h = saved[0]
    assert list(h) == ["id", "name", "relation", "phone", "email", "phone_masked", "email_masked",
                       "identifiers", "min_level", "signal_scope", "active", "contact"]
    assert (h["phone"], h["email"]) == ("010-1234-5678", "mom.kim@example.org")
    assert (h["phone_masked"], h["email_masked"]) == ("010-****-5678", "mo***@example.org")
    assert h["contact"] == "010-****-5678 · mo***@example.org"
    assert svc.get_helpers() == saved
    again = svc.put_helpers([HelperIn(**h)])          # GET 모양을 그대로 돌려보내도 된다
    assert again == saved


@pytest.mark.parametrize("contact,phone,email", [
    ("010-1234-5678", "010-1234-5678", ""),
    ("mom@example.org", "", "mom@example.org"),
    ("엄마(010-1234-5678)", "010-1234-5678", ""),
    ("010ㆍ1234ㆍ5678", "01012345678", ""),
    ("+82 10 1234 5678", "+82 10 1234 5678", ""),
])
def test_legacy_contact_in_request_is_split(svc: Service, contact: str, phone: str, email: str) -> None:
    h = svc.put_helpers([HelperIn(name="엄마", contact=contact)])[0]
    assert (h["phone"], h["email"]) == (phone, email)


def test_legacy_contact_in_store_is_converted_on_read(svc: Service) -> None:
    rows = [{"id": "h1", "name": "엄마", "relation": "", "contact": "mom@example.org"},
            {"id": "h2", "name": "아빠", "relation": "", "contact": "010-9876-5432"},
            {"id": "h3", "name": "센터", "relation": "", "contact": "010-****-1111"},
            {"id": "h4", "name": "이모", "relation": "", "contact": "ab***@x.kr"}]
    (svc.store.root / "helpers.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    got = {h["id"]: h for h in svc.get_helpers()}
    assert (got["h1"]["phone"], got["h1"]["email"]) == ("", "mom@example.org")
    assert (got["h2"]["phone"], got["h2"]["email"]) == ("010-9876-5432", "")
    # 이미 가린 값은 그대로(보낼 수 없어 원본 칸은 비어 있음)
    assert (got["h3"]["phone"], got["h3"]["phone_masked"], got["h3"]["contact"]) == ("", "010-****-1111", "010-****-1111")
    assert (got["h4"]["email"], got["h4"]["email_masked"]) == ("", "ab***@x.kr")
    # 새 화면이 GET 항목을 그대로 돌려보내면: 원본은 그대로, 옛 가린 표시도 그대로(BE-8: 다른 조력자를 저장하기만 해도
    # 어느 번호였는지 단서가 사라지던 문제)
    again = {h["id"]: h for h in svc.put_helpers([HelperIn(**h) for h in got.values()])}
    assert {k: (v["phone"], v["email"]) for k, v in again.items()} == {k: (v["phone"], v["email"]) for k, v in got.items()}
    assert (again["h3"]["contact"], again["h3"]["phone_masked"], again["h4"]["email_masked"]) == \
        ("010-****-1111", "010-****-1111", "ab***@x.kr")
    # 화면 toPayload 모양(phone·email 빈 글, contact 없음) + 새 조력자 한 명을 더해도 지킨다
    payload = [{k: v for k, v in h.items() if k not in ("contact", "phone_masked", "email_masked")}
               for h in again.values()]
    more = {h["id"]: h for h in svc.put_helpers([HelperIn(**h) for h in payload] + [HelperIn(name="새 조력자")])}
    assert (more["h3"]["phone_masked"], more["h4"]["email_masked"]) == ("010-****-1111", "ab***@x.kr")
    assert json.loads((svc.store.root / "helpers.json").read_text(encoding="utf-8"))[2]["contact"] == "010-****-1111"
    # 본인이 지우겠다고 하면(clear_contact) 그때 지운다
    cleared = {h["id"]: h for h in svc.put_helpers([HelperIn(**{**p, "clear_contact": True}) for p in payload])}
    assert (cleared["h3"]["contact"], cleared["h3"]["phone_masked"], cleared["h4"]["email_masked"]) == ("", "", "")
    # 옛 클라이언트(번호·메일 칸 없이 contact만)는 가린 값을 그대로 둔다
    old = svc.put_helpers([HelperIn(id="h3", name="센터", contact="010-****-1111")])[0]
    assert (old["phone"], old["phone_masked"], old["contact"]) == ("", "010-****-1111", "010-****-1111")


def test_cleared_phone_and_email_leave_no_stale_display(svc: Service) -> None:
    shown = svc.put_helpers([HelperIn(**MOM)])[0]
    cleared = svc.put_helpers([HelperIn(**{**shown, "phone": "", "email": ""})])[0]   # contact 표시를 같이 보내도
    assert (cleared["phone"], cleared["email"], cleared["contact"]) == ("", "", "")
    assert (cleared["phone_masked"], cleared["email_masked"]) == ("", "")


@pytest.mark.parametrize("field,value", [("phone", "010-12ab-5678"), ("phone", "1" * 21), ("phone", "()"),
                                         ("email", "not-an-email"), ("email", "a@b"), ("email", "x" * 75 + "@ex.kr")])
def test_helper_bad_phone_or_email_is_422(tmp_path: Path, field: str, value: str) -> None:
    status, body = dispatch(_service(tmp_path), "PUT", "/api/helpers", [{"name": "엄마", field: value}])
    assert status == 422
    assert body["detail"] == f"입력한 값을 확인해 주세요: {'전화번호' if field == 'phone' else '이메일'}"


# ---- 3.2 상담하는 곳 -------------------------------------------------------------------

def test_counselors_presets_are_verified_numbers_only(svc: Service) -> None:
    out = svc.get_counselors()
    assert out["items"] == []
    numbers = {p["kind"]: p["phone"] for p in out["presets"]}
    assert numbers == {"rights_agency": "1644-8295", "finance": "1332", "police": "112", "disability_center": ""}
    for p in out["presets"]:   # 그대로 PUT에 넣을 수 있는 모양
        CounselorIn(**p)
        assert p["kind"] in constants.COUNSELOR_KINDS


def test_counselors_put_assigns_ids_and_keeps_order(svc: Service) -> None:
    items = [CounselorIn(**p) for p in constants.COUNSELOR_PRESETS[:2]]
    items.append(CounselorIn(id="c1", name="우리 동네 센터", kind="disability_center", phone="02-123-4567",
                             email="center@example.org", memo="담당 김 선생님", active=False))
    saved = svc.put_counselors(items)["items"]
    assert [c["id"] for c in saved] == ["c2", "c3", "c1"]
    assert list(saved[0]) == ["id", "name", "kind", "phone", "email", "memo", "active"]
    assert saved[2]["active"] is False and saved[2]["phone"] == "02-123-4567"
    assert svc.get_counselors()["items"] == saved
    assert json.loads((svc.store.root / COUNSELORS_FILE).read_text(encoding="utf-8")) == saved


def test_counselors_limit_and_validation(tmp_path: Path) -> None:
    s = _service(tmp_path)
    e = _err(lambda: s.put_counselors([CounselorIn(name=f"곳{i}") for i in range(21)]))
    assert e.status == 422 and e.detail == "상담하는 곳은 20곳까지 정할 수 있어요."
    for bad, label in [({"name": ""}, "이름"), ({"name": "가" * 31}, "이름"), ({"name": "x", "kind": "bank"}, "종류"),
                       ({"name": "x", "memo": "m" * 101}, "메모"), ({"name": "x", "phone": "번호"}, "전화번호"),
                       ({"name": "x", "extra": 1}, "받지 않는 항목(extra)")]:
        status, body = dispatch(s, "PUT", "/api/counselors", [bad])
        assert status == 422 and body["detail"] == f"입력한 값을 확인해 주세요: {label}", bad


def test_counseling_names_use_my_counselors(ready: Service) -> None:
    ready.put_consent(ConsentIn(counseling_referral=True))
    hint = ready.cards(limit=1)["counseling"]
    assert hint["suggest"] is True and hint["recent_high"] >= hint["threshold"] == 3
    assert hint["orgs"] == list(COUNSELING_ORGS)                       # 정한 곳이 없으면 기본 2곳
    ready.put_counselors([CounselorIn(name="우리 동네 센터", kind="disability_center"),
                          CounselorIn(name="쉬는 곳", active=False),
                          CounselorIn(**constants.COUNSELOR_PRESETS[0])])
    assert ready.counseling_names() == ["우리 동네 센터", constants.COUNSELOR_PRESETS[0]["name"]]
    assert ready.cards(limit=1)["counseling"]["orgs"] == ready.counseling_names()
    ready.put_consent(ConsentIn(counseling_referral=False))
    off = ready.cards(limit=1)["counseling"]
    assert off["suggest"] is False and off["orgs"] == []


def test_counseling_names_in_check_and_decide(ready: Service) -> None:
    from safepause.api.schemas import DecideIn, PendingIn
    ready.put_consent(ConsentIn(counseling_referral=True))
    ready.put_counselors([CounselorIn(name="우리 동네 센터")])
    pending = PendingIn(to="김*호", amount=300000, channel="transfer", time="02:00")
    r = ready.check(pending)
    plan = r["notify_plan_preview"]
    assert plan["suggest_counseling"] is True and plan["counseling_orgs"] == ["우리 동네 센터"]
    d = ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="cancel"))
    assert d["notify_plan"]["counseling_orgs"] == ["우리 동네 센터"]


# ---- 3.3 담은 거래 ---------------------------------------------------------------------

def test_flags_add_list_remove(ready: Service) -> None:
    a, b = _ids(ready, "high", 2)
    assert ready.add_flag(FlagIn(txn_id=a)) == {"ok": True, "count": 1}
    assert ready.add_flag(FlagIn(txn_id=b)) == {"ok": True, "count": 2}
    assert ready.add_flag(FlagIn(txn_id=a)) == {"ok": True, "count": 2}   # 이미 담겨 있으면 그대로
    items = ready.get_flags()["items"]
    assert [i["txn_id"] for i in items] == [b, a]                          # 최근 담은 것부터
    assert all(i["created_at"] == NOW.isoformat() and i["item"]["flagged"] is True for i in items)
    assert set(items[0]["item"]) == {"txn", "level", "signals", "anomaly_score", "reasons", "practice", "flagged",
                                     "reviewed", "notified_at", "ai"}
    listing = ready.transactions("all")
    assert {i["txn"]["id"] for i in listing["items"] if i["flagged"]} == {a, b}
    assert listing["flagged_count"] == 2
    assert [i["txn"]["id"] for i in ready.transactions("flagged")["items"]] == \
        [i["txn"]["id"] for i in listing["items"] if i["flagged"]]
    cards = ready.cards(limit=100)["items"]
    assert {c["txn"]["id"] for c in cards if c["flagged"]} == {a, b}
    assert ready.remove_flag(FlagIn(txn_id=a)) == {"ok": True, "count": 1}
    assert ready.remove_flag(FlagIn(txn_id=a)) == {"ok": True, "count": 1}   # 없는 것을 빼도 그대로
    assert [i["txn_id"] for i in ready.get_flags()["items"]] == [b]


def test_flag_unknown_txn_is_404(ready: Service) -> None:
    e = _err(lambda: ready.add_flag(FlagIn(txn_id="no-such-txn")))
    assert e.status == 404 and e.detail == "그 거래를 찾지 못했어요."


def test_flags_need_monitoring_consent(ready: Service) -> None:
    tid = _ids(ready, "all", 1)[0]
    ready.add_flag(FlagIn(txn_id=tid))
    ready.put_consent(ConsentIn(monitoring=False))
    for fn in (ready.get_flags, lambda: ready.add_flag(FlagIn(txn_id=tid)), ready.insights):
        e = _err(fn)
        assert e.status == 403 and e.detail == constants.NO_MONITORING
    assert ready.remove_flag(FlagIn(txn_id=tid))["count"] == 0          # 빼기는 동의 없이도 된다


def test_flags_cleared_when_transactions_replaced(ready: Service) -> None:
    ready.add_flag(FlagIn(txn_id=_ids(ready)[0]))
    assert (ready.store.root / FLAGS_FILE).exists()
    ready.data_sample(SampleIn(persona="worker", seed=3, scenarios=True))   # 연습용 거래 다시 불러오기
    assert not (ready.store.root / FLAGS_FILE).exists() and ready.get_flags() == {"items": []}
    ready.add_flag(FlagIn(txn_id=_ids(ready)[0]))
    ready.upload(BANK_EXAMPLE.read_bytes())                                  # 파일 올리기
    assert ready.store.load_flags() == [] and ready.transactions()["flagged_count"] == 0


def test_flags_skip_vanished_transactions(ready: Service) -> None:
    a, b = _ids(ready, "all", 2)
    ready.add_flag(FlagIn(txn_id=a))
    ready.add_flag(FlagIn(txn_id=b))
    txns = [t for t in ready.store.load_transactions() if t.id != a]          # 밖에서 거래 하나가 사라짐
    ready.store.save_transactions(txns)
    assert [i["txn_id"] for i in ready.get_flags()["items"]] == [b]
    assert ready.add_flag(FlagIn(txn_id=b))["count"] == 1                   # 담을 때 사라진 것은 정리


def test_flag_input_errors_are_korean(tmp_path: Path) -> None:
    s = _service(tmp_path)
    for body in ({}, {"txn_id": ""}, {"txn_id": "   "}, {"txn_id": "x" * 201}, {"txn_id": "a", "more": 1}):
        status, out = dispatch(s, "POST", "/api/flags/remove", body)
        assert status == 422 and out["detail"].startswith("입력한 값을 확인해 주세요: "), body
    assert dispatch(s, "POST", "/api/flags", {"txn_id": ""})[1]["detail"] == "입력한 값을 확인해 주세요: 거래"


# ---- 3.4 보낸 알림 기록 ----------------------------------------------------------------

def _record(**extra: Any) -> NoticeRecordIn:
    body = {"channel": "sms", "recipients": [{"kind": "helper", "id": "h1", "name": "엄마"}],
            "txn_ids": ["t1"], "message": "[SafePause] 걱정되는 거래가 있어 알려요. 확인해 주세요."}
    return NoticeRecordIn(**{**body, **extra})


def test_record_notice_format_and_merged_list(ready: Service) -> None:
    from safepause.api.schemas import DecideIn, PendingIn
    ready.put_consent(ConsentIn(helper_alerts=True))
    ready.put_helpers([HelperIn(id="h1", min_level="caution", **MOM)])
    ready.put_counselors([CounselorIn(id="c1", **constants.COUNSELOR_PRESETS[0])])
    # 자동 기록 1건(확인할 때도 알리는 조력자 + 조력자 알림 동의)
    r = ready.check(PendingIn(to="김*호", amount=300000, channel="transfer", time="02:00"))
    ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision="send"))
    rec = ready.record_notice(_record(channel="email", recipients=[
        {"kind": "helper", "id": "h1", "name": "다른 이름"},           # 저장된 이름을 쓴다
        {"kind": "counselor", "id": "c1", "name": "x", "phone": "1644-8295"},   # 다른 칸은 버린다
        {"kind": "helper", "id": "h1", "name": "엄마"}]))                 # 겹치면 한 번만
    assert rec == {"id": "m1", "kind": "manual", "channel": "email",
                   "recipients": [{"kind": "helper", "id": "h1", "name": "엄마"},
                                  {"kind": "counselor", "id": "c1", "name": constants.COUNSELOR_PRESETS[0]["name"]}],
                   "txn_ids": ["t1"], "message": "[SafePause] 걱정되는 거래가 있어 알려요. 확인해 주세요.",
                   "created_at": NOW.isoformat()}
    assert ready.record_notice(_record(channel="copy"))["id"] == "m2"
    out = ready.notices()
    assert out["delivery_note"] == "이 기기에 적어 둔 기록이에요. 실제로 보냈는지는 문자·메일 앱에서 확인해 주세요."
    assert [i["kind"] for i in out["items"]] == ["manual", "manual", "auto"]   # 최근 것부터
    assert [i["id"] for i in out["items"][:2]] == ["m2", "m1"]
    auto = out["items"][2]
    assert set(auto) == {"helper_id", "helper_name", "txn_id", "level", "message", "created_at", "kind"}
    summary = ready.export_validation()["summary"]
    assert summary["helper_notices"] == 1 and summary["manual_notices"] == 2


def test_record_notice_does_not_need_consent(svc: Service) -> None:
    assert svc.store.load_consent().monitoring is False
    assert svc.record_notice(_record())["kind"] == "manual"


@pytest.mark.parametrize("body,label", [
    ({"channel": "fax"}, "보내는 방법"),
    ({"recipients": []}, "받는 사람"),
    ({"recipients": [{"kind": "helper", "name": "엄마"}] * 11}, "받는 사람"),
    ({"recipients": [{"kind": "friend", "name": "엄마"}]}, "종류"),
    ({"recipients": [{"kind": "helper", "name": " "}]}, "이름"),
    ({"txn_ids": [f"t{i}" for i in range(21)]}, "거래"),
    ({"message": "   "}, "보낼 글"),
    ({"message": "가" * 1001}, "보낼 글"),
    ({"phone": "010-1234-5678"}, "받지 않는 항목(phone)"),
])
def test_record_notice_input_errors_are_korean(tmp_path: Path, body: dict[str, Any], label: str) -> None:
    base = {"channel": "sms", "recipients": [{"kind": "helper", "name": "엄마"}], "message": "확인해 주세요."}
    status, out = dispatch(_service(tmp_path), "POST", "/api/notices/record", {**base, **body})
    assert status == 422 and out["detail"] == f"입력한 값을 확인해 주세요: {label}"


def test_raw_contacts_never_reach_records_or_exports(ready: Service) -> None:
    ready.put_helpers([HelperIn(id="h1", **MOM)])
    ready.put_counselors([CounselorIn(id="c1", name="담당 선생님", phone="010-5555-6666", email="teacher.lee@example.org")])
    msg = "엄마 010-1234-5678, 01012345678, mom.kim@example.org / 선생님 010-5555-6666 teacher.lee@example.org"
    ready.record_notice(_record(message=msg, recipients=[{"kind": "helper", "id": "h1", "name": "엄마"},
                                                         {"kind": "counselor", "id": "c1", "name": "담당 선생님"}]))
    raws = ("010-1234-5678", "01012345678", "mom.kim@example.org", "010-5555-6666", "teacher.lee@example.org")
    texts = {
        "notices.json": (ready.store.root / NOTICES_FILE).read_text(encoding="utf-8"),
        "GET notices": json.dumps(ready.notices(), ensure_ascii=False),
        "validation": ready.export_validation()["text"],
        "results": ready.export_results_csv()["text"],
    }
    for where, text in texts.items():
        for raw in raws:
            assert raw not in text, (where, raw)
    stored = ready.notices()["items"][0]["message"]
    assert "010-****-5678" in stored and "mo***@example.org" in stored
    assert "1234" not in stored


# ---- 3.5 돈 흐름 분석 -------------------------------------------------------------------

def _expected_insights(items: list[dict[str, Any]]) -> dict[str, Any]:
    """거래 목록(/api/transactions 항목)만으로 insights를 다시 계산한다(서비스 코드를 쓰지 않음).

    보내기 전 확인 기록(practice)은 뺀다. compare는 지난달 같은 날짜 범위(1일~기준일)의 나간 돈이다.
    """
    checked = sum(1 for i in items if i["practice"])
    rows = [(datetime.fromisoformat(i["txn"]["ts"]), i["txn"], i["level"]) for i in items if not i["practice"]]
    flagged_total = {"caution": sum(lv == "caution" for *_, lv in rows), "high": sum(lv == "high" for *_, lv in rows)}
    bands = [("dawn", "0-6", 0, 6), ("morning", "6-12", 6, 12), ("day", "12-18", 12, 18), ("evening", "18-24", 18, 24)]

    def band_rows(sel: list[Any]) -> list[dict[str, Any]]:
        return [{"band": b, "hours": h, "flagged": sum(1 for ts, _, lv in sel if lo <= ts.hour < hi and lv != "none"),
                 "out_count": sum(1 for ts, t, _ in sel if lo <= ts.hour < hi and t["direction"] == "out")}
                for b, h, lo, hi in bands]

    if not rows:
        return {"as_of": None, "months": [], "this_month": None, "prev_month": None, "compare": None, "channels": [],
                "time_bands": band_rows([]), "top_payees": [], "flagged_total": flagged_total,
                "checked_excluded": checked}
    last = max(ts for ts, *_ in rows)
    first = min(ts for ts, *_ in rows)
    keys: list[str] = []
    y, m = last.year, last.month
    for _ in range(6):
        if y * 12 + m < first.year * 12 + first.month:
            break
        keys.insert(0, f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)

    def month(k: str) -> dict[str, Any]:
        sel = [(ts, t, lv) for ts, t, lv in rows if ts.strftime("%Y-%m") == k]
        return {"month": k, "out_total": sum(t["amount"] for _, t, _ in sel if t["direction"] == "out"),
                "in_total": sum(t["amount"] for _, t, _ in sel if t["direction"] == "in"),
                "out_count": sum(1 for _, t, _ in sel if t["direction"] == "out"),
                "flagged": {"caution": sum(lv == "caution" for *_, lv in sel), "high": sum(lv == "high" for *_, lv in sel)}}

    months = [month(k) for k in keys]
    cur = [(ts, t, lv) for ts, t, lv in rows if ts.strftime("%Y-%m") == keys[-1]]
    ch: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for _, t, _ in cur:
        if t["direction"] == "out":
            ch[t["channel"]][0] += t["amount"]
            ch[t["channel"]][1] += 1
    whole = sum(v[0] for v in ch.values())
    channels = sorted(({"channel": c, "out_total": v[0], "out_count": v[1], "share": round(v[0] / whole, 3) if whole else 0.0}
                       for c, v in ch.items()), key=lambda r: (-r["out_total"], -r["out_count"], r["channel"]))
    pay: dict[str, dict[str, Any]] = {}
    for _, t, lv in cur:
        name = " ".join((t["counterparty"] or "").split())
        if t["direction"] == "out" and t["channel"] in ("transfer", "card") and name:
            row = pay.setdefault(name, {"name": name, "out_total": 0, "out_count": 0, "flagged": 0})
            row["out_total"] += t["amount"]
            row["out_count"] += 1
            row["flagged"] += lv != "none"
    top = sorted(pay.values(), key=lambda r: (-r["out_total"], -r["out_count"], r["name"]))[:3]
    compare = None
    if len(keys) > 1:
        py, pm = (int(x) for x in keys[-2].split("-"))
        nxt = datetime(py + (pm == 12), pm % 12 + 1, 1)
        prev_len = (nxt - timedelta(days=1)).day
        n = min(last.day, prev_len)
        if first.date() <= datetime(py, pm, 1).date():          # 지난달 1일부터 데이터가 있을 때만
            sel = [t for ts, t, _ in rows if (ts.year, ts.month) == (py, pm) and ts.day <= n and t["direction"] == "out"]
            compare = {"month": keys[-2], "days": last.day, "prev_days": n,
                       "prev_same_period_out": sum(t["amount"] for t in sel), "prev_same_period_count": len(sel)}
    return {"as_of": last.date().isoformat(), "months": months, "this_month": months[-1],
            "prev_month": months[-2] if len(months) > 1 else None, "compare": compare, "channels": channels,
            "time_bands": band_rows(cur), "top_payees": top, "flagged_total": flagged_total,
            "checked_excluded": checked}


def test_insights_match_recomputation_from_transactions(ready: Service) -> None:
    got = ready.insights()
    assert got == _expected_insights(ready.transactions("all")["items"])
    assert got["as_of"] == max(t.ts for t in ready.store.load_transactions()).date().isoformat()
    assert 1 <= len(got["months"]) <= 6 and got["this_month"]["month"] == got["as_of"][:7]
    assert abs(sum(c["share"] for c in got["channels"]) - 1) < 0.01
    assert got["flagged_total"]["high"] == ready.transactions()["summary"]["high"]
    assert list(got) == ["as_of", "months", "this_month", "prev_month", "compare", "channels", "time_bands",
                         "top_payees", "flagged_total", "checked_excluded"]


def _txn(i: int, ts: datetime, amount: int, channel: Channel = Channel.CARD, direction: Direction = Direction.OUT,
         who: str = "가게") -> Transaction:
    return Transaction(id=f"t{i:03d}", ts=ts, amount=amount, direction=direction, channel=channel, counterparty=who)


def test_insights_month_window_across_year_and_gap(svc: Service) -> None:
    svc.store.save_consent(Consent(monitoring=True))
    start = datetime(2025, 9, 3, 10, 0)
    txns = [_txn(i, start + timedelta(days=7 * i), 10_000 + i) for i in range(10)]          # 2025-09 ~ 2025-11
    txns += [_txn(100, datetime(2026, 2, 1, 3, 0), 500_000, Channel.TRANSFER, who="김*호"),   # 12·1월은 비어 있음
             _txn(101, datetime(2026, 2, 2, 9, 0), 1_000_000, Channel.INCOME, Direction.IN, who="회사"),
             _txn(102, datetime(2026, 2, 3, 19, 0), 20_000, Channel.CARD, who="편의점")]
    svc.store.save_transactions(txns)
    got = svc.insights()
    assert [m["month"] for m in got["months"]] == ["2025-09", "2025-10", "2025-11", "2025-12", "2026-01", "2026-02"]
    assert got["months"][3]["out_total"] == got["months"][4]["out_count"] == 0
    assert got["this_month"]["out_total"] == 520_000 and got["this_month"]["in_total"] == 1_000_000
    assert got["prev_month"]["month"] == "2026-01"
    assert [c["channel"] for c in got["channels"]] == ["transfer", "card"]
    assert [p["name"] for p in got["top_payees"]] == ["김*호", "편의점"]
    assert [b["out_count"] for b in got["time_bands"]] == [1, 0, 0, 1]
    assert got == _expected_insights(svc.transactions("all")["items"])


def test_insights_empty(svc: Service) -> None:
    svc.store.save_consent(Consent(monitoring=True))
    got = svc.insights()
    assert got["months"] == [] and got["channels"] == [] and got["top_payees"] == []
    assert got["as_of"] is None and got["this_month"] is None and got["prev_month"] is None
    assert [b["band"] for b in got["time_bands"]] == ["dawn", "morning", "day", "evening"]


# ---- 받는 사람 추천(docs/v03_spec_money.md) ---------------------------------------------------

def _flagged(s: Service) -> list[dict[str, Any]]:
    """걱정되는 거래(확인해요·꼭 확인해요) 목록 항목."""
    return s.transactions("caution")["items"]


def _pick(s: Service, level: str, signal: Optional[str] = None) -> dict[str, Any]:
    """등급(과 걸린 신호)이 맞는 첫 거래. signal=""이면 신호 없이 AI만 걱정한 거래."""
    for it in _flagged(s):
        if it["level"] != level:
            continue
        if signal is None or (signal == "" and not it["signals"]) or (signal and signal in it["signals"]):
            return it
    raise AssertionError(f"연습용 거래에 {level}/{signal} 거래가 없어요")


def _suggest(s: Service, *txn_ids: str) -> dict[str, Any]:
    return s.notify_suggest(SuggestIn(txn_ids=list(txn_ids)))


def _by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in rows}


def test_suggest_needs_monitoring_consent(ready: Service) -> None:
    ready.put_consent(ConsentIn(monitoring=False))
    for ids in ([], ["anything"]):
        e = _err(lambda: _suggest(ready, *ids))
        assert e.status == 403 and e.detail == constants.NO_MONITORING
    status, body = dispatch(ready, "POST", "/api/notify/suggest", {"txn_ids": []})
    assert status == 403 and body == {"detail": constants.NO_MONITORING}


def test_suggest_response_shape(ready: Service) -> None:
    ready.put_consent(ConsentIn(helper_alerts=True))
    ready.put_helpers([HelperIn(id="h1", **MOM)])
    ready.put_counselors([CounselorIn(id="c1", name="센터")])
    out = _suggest(ready, _pick(ready, "high")["txn"]["id"])
    assert list(out) == ["helpers", "counselors", "counseling_due", "counseling_reason"]
    assert list(out["helpers"][0]) == ["id", "name", "suggested", "conflict", "reason"]
    assert list(out["counselors"][0]) == ["id", "name", "suggested"]
    assert out["helpers"][0]["name"] == "엄마" and out["counselors"][0]["name"] == "센터"


def test_suggest_conflict_helper_is_not_suggested(ready: Service) -> None:
    ready.put_consent(ConsentIn(helper_alerts=True))
    payee = _pick(ready, "high", "payee_surge")["txn"]
    other = _pick(ready, "high", "micropay_surge")["txn"]
    ready.put_helpers([
        HelperIn(id="by-name", name="돈 받은 사람", identifiers=[payee["counterparty"]], min_level="caution"),
        HelperIn(id="by-account", name="계좌 주인", identifiers=[f"우리 동네 은행 {payee['counterparty_id']}"]),
        HelperIn(id="mom", name="엄마", min_level="caution"),
    ])
    got = _by_id(_suggest(ready, payee["id"])["helpers"])
    for hid in ("by-name", "by-account"):
        assert got[hid]["conflict"] is True and got[hid]["suggested"] is False
        assert got[hid]["reason"] == "이 거래에서 돈을 받은 사람이에요." == constants.CONFLICT_REASON
    assert got["mom"] == {"id": "mom", "name": "엄마", "suggested": True, "conflict": False, "reason": ""}
    # 여러 거래 가운데 하나라도 그 사람이 돈을 받았으면 추천하지 않는다(다른 거래에는 알맞아도)
    many = _by_id(_suggest(ready, other["id"], payee["id"])["helpers"])
    assert many["by-name"]["conflict"] is True and many["by-name"]["suggested"] is False
    # 그 사람과 관계없는 거래만 고르면 이해충돌이 아니다
    alone = _by_id(_suggest(ready, other["id"])["helpers"])
    assert alone["by-name"] == {"id": "by-name", "name": "돈 받은 사람", "suggested": True, "conflict": False,
                                "reason": ""}


def test_suggest_level_and_scope(ready: Service) -> None:
    ready.put_consent(ConsentIn(helper_alerts=True))
    high = _pick(ready, "high", "payee_surge")["txn"]["id"]
    ai_caution = _pick(ready, "caution", "")["txn"]["id"]      # 신호 없이 AI만 걱정한 확인해요 거래
    ready.put_helpers([
        HelperIn(id="high-only", name="꼭 확인만", min_level="high"),
        HelperIn(id="caution", name="확인부터", min_level="caution"),
        HelperIn(id="scope-other", name="소액결제만", min_level="caution", signal_scope=["micropay_surge"]),
        HelperIn(id="scope-same", name="송금 집중만", min_level="caution", signal_scope=["payee_surge"]),
    ])
    on_high = _by_id(_suggest(ready, high)["helpers"])
    assert {k: v["suggested"] for k, v in on_high.items()} == {
        "high-only": True, "caution": True, "scope-other": False, "scope-same": True}
    on_caution = _by_id(_suggest(ready, ai_caution)["helpers"])
    assert {k: v["suggested"] for k, v in on_caution.items()} == {
        "high-only": False, "caution": True, "scope-other": False, "scope-same": False}
    assert not any(v["conflict"] or v["reason"] for v in on_caution.values())
    # 여러 거래: 하나라도 등급·범위에 들면 추천
    both = _by_id(_suggest(ready, ai_caution, high)["helpers"])
    assert {k: v["suggested"] for k, v in both.items()} == {
        "high-only": True, "caution": True, "scope-other": False, "scope-same": True}


def test_suggest_inactive_helper_is_never_suggested(ready: Service) -> None:
    ready.put_consent(ConsentIn(helper_alerts=True))
    ready.put_helpers([HelperIn(id="off", name="자동 끔", min_level="caution", active=False),
                       HelperIn(id="on", name="자동 켬", min_level="caution")])
    for ids in ([], [_pick(ready, "high")["txn"]["id"]]):
        got = _by_id(_suggest(ready, *ids)["helpers"])
        assert got["off"]["suggested"] is False and got["on"]["suggested"] is True, ids


def test_suggest_without_transactions_uses_active(ready: Service) -> None:
    ready.put_consent(ConsentIn(helper_alerts=True))
    ready.put_helpers([HelperIn(id="a", name="엄마", min_level="high", signal_scope=["micropay_surge"]),
                       HelperIn(id="b", name="아빠", active=False)])
    got = _suggest(ready)["helpers"]
    assert [(h["id"], h["suggested"], h["conflict"], h["reason"]) for h in got] == [
        ("a", True, False, ""), ("b", False, False, "")]


def test_suggest_helper_alerts_off_suggests_nobody(ready: Service) -> None:
    payee = _pick(ready, "high", "payee_surge")["txn"]
    ready.put_helpers([HelperIn(id="mom", name="엄마", min_level="caution"),
                       HelperIn(id="payee", name="받은 사람", identifiers=[payee["counterparty"]])])
    assert ready.store.load_consent().helper_alerts is False
    for ids in ([], [payee["id"]], [i["txn"]["id"] for i in _flagged(ready)][:20]):
        got = _by_id(_suggest(ready, *ids)["helpers"])
        assert not any(h["suggested"] for h in got.values()), ids
    # 이해충돌 경고는 동의와 관계없이 알려 준다(본인이 직접 고를 때 참고)
    assert _by_id(_suggest(ready, payee["id"])["helpers"])["payee"]["conflict"] is True


def test_suggest_matches_automatic_alert_rule(ready: Service) -> None:
    """조력자 추천 = 자동 알림(policy.decide)이 알릴 조력자(거래 하나씩)."""
    from safepause.guardian import policy
    ready.put_consent(ConsentIn(helper_alerts=True))
    flagged = _flagged(ready)
    payee = _pick(ready, "high", "payee_surge")["txn"]
    ready.put_helpers([HelperIn(id="h1", name="엄마", min_level="caution"),
                       HelperIn(id="h2", name="아빠", min_level="high", signal_scope=["night_repeat_transfer"]),
                       HelperIn(id="h3", name="받은 사람", min_level="caution", identifiers=[payee["counterparty"]]),
                       HelperIn(id="h4", name="쉬는 사람", active=False)])
    helpers = ready.store.load_helpers()
    consent = ready.store.load_consent()
    snap = ready.snapshot()
    index = {t.id: (t, a) for t, a in zip(snap.txns, snap.assessments)}
    assert len(flagged) >= 10
    for it in flagged:
        t, a = index[it["txn"]["id"]]
        plan = policy.decide(a, t, helpers, consent, 0, ready.settings)
        got = _suggest(ready, t.id)["helpers"]
        assert {h["id"] for h in got if h["suggested"]} == {n.helper_id for n in plan.notices}, t.id
        assert {h["id"] for h in got if h["conflict"]} == {h.id for h in helpers if policy.is_conflict(h, t)}


def test_suggest_counseling_due_uses_counseling_hint_rule(ready: Service) -> None:
    ready.put_counselors([CounselorIn(id="c1", name="우리 동네 센터"), CounselorIn(id="c2", name="쉬는 곳", active=False)])
    off = _suggest(ready)
    assert off["counseling_due"] is False and not any(c["suggested"] for c in off["counselors"])
    ready.put_consent(ConsentIn(counseling_referral=True))
    hint = ready.cards(limit=1)["counseling"]
    assert hint["suggest"] is True and hint["recent_high"] >= hint["threshold"] == 3
    on = _suggest(ready)
    assert on["counseling_due"] is True
    assert [(c["id"], c["suggested"]) for c in on["counselors"]] == [("c1", True), ("c2", False)]
    assert _suggest(ready, _pick(ready, "high")["txn"]["id"])["counseling_due"] is True   # 고른 거래와 관계없음
    # 기준(30일 동안 꼭 확인할 일 N번)을 넘지 않으면 동의가 있어도 아니다: 상담 안내 띠와 같은 기준
    from safepause.config import Settings
    strict = Service(ready.store.root, settings=Settings(high_repeat_for_counseling=999), now=lambda: NOW)
    assert strict.cards(limit=1)["counseling"]["suggest"] is False
    due = strict.notify_suggest(SuggestIn())
    assert due["counseling_due"] is False and not any(c["suggested"] for c in due["counselors"])


def test_suggest_without_helpers_or_counselors(ready: Service) -> None:
    assert _suggest(ready) == {"helpers": [], "counselors": [], "counseling_due": False, "counseling_reason": ""}


def test_suggest_unknown_transaction_is_404(ready: Service) -> None:
    known = _pick(ready, "high")["txn"]["id"]
    for ids in (["no-such-txn"], [known, "no-such-txn"], ["no-such-txn", known]):
        e = _err(lambda: _suggest(ready, *ids))
        assert e.status == 404 and e.detail == "그 거래를 찾지 못했어요.", ids
    status, body = dispatch(ready, "POST", "/api/notify/suggest", {"txn_ids": [known, "nope"]})
    assert status == 404 and body == {"detail": "그 거래를 찾지 못했어요."}
    assert _suggest(ready, known, f" {known} ")["helpers"] == []        # 겹친 id·앞뒤 빈칸은 한 번만


@pytest.mark.parametrize("body", [
    {"txn_ids": [f"t{i}" for i in range(21)]},
    {"txn_ids": ["x" * 201]},
    {"txn_ids": "t1"},
    {"txn_ids": [1]},
    {"txn_ids": None},
])
def test_suggest_input_errors_are_korean(tmp_path: Path, body: dict[str, Any]) -> None:
    status, out = dispatch(_service(tmp_path), "POST", "/api/notify/suggest", body)
    assert status == 422 and out["detail"] == "입력한 값을 확인해 주세요: 거래", body
    status, out = dispatch(_service(tmp_path), "POST", "/api/notify/suggest", {"txn_ids": [], "to": "x"})
    assert status == 422 and out["detail"] == "입력한 값을 확인해 주세요: 받지 않는 항목(to)"


def test_suggest_allows_twenty_transactions(ready: Service) -> None:
    ids = [i["txn"]["id"] for i in ready.transactions("all", 20, 0)["items"]]
    assert len(ids) == 20
    assert _suggest(ready, *ids)["counseling_due"] is False


def _suggest_scenario(call: Callable[[str, str, Any], tuple[int, Any]]) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []

    def step(m: str, p: str, b: Any = None) -> Any:
        out.append(call(m, p, b))
        return out[-1][1]

    step("POST", "/api/notify/suggest", {"txn_ids": []})                                     # 403
    step("PUT", "/api/consent", {"monitoring": True, "helper_alerts": True, "counseling_referral": True})
    step("POST", "/api/data/sample", {"persona": "worker", "seed": 2, "scenarios": True})
    flagged = step("GET", "/api/transactions?level=caution&limit=20")["items"]
    payee = next(i["txn"] for i in flagged if "payee_surge" in i["signals"])
    step("PUT", "/api/helpers", [{"id": "mom", **MOM, "min_level": "caution"},
                                 {"id": "payee", "name": "받은 사람", "identifiers": [payee["counterparty"]]},
                                 {"id": "night", "name": "밤만", "signal_scope": ["night_repeat_transfer"]},
                                 {"id": "off", "name": "쉬는 사람", "active": False}])
    step("PUT", "/api/counselors", [{"id": "c1", "name": "센터"}, {"id": "c2", "name": "쉬는 곳", "active": False}])
    step("POST", "/api/notify/suggest", {"txn_ids": [i["txn"]["id"] for i in flagged]})
    step("POST", "/api/notify/suggest", {"txn_ids": [payee["id"]]})
    step("POST", "/api/notify/suggest", {"txn_ids": []})
    step("POST", "/api/notify/suggest", {})
    step("POST", "/api/notify/suggest", {"txn_ids": [payee["id"], "no-such"]})               # 404
    step("POST", "/api/notify/suggest", {"txn_ids": [f"t{i}" for i in range(21)]})          # 422
    step("POST", "/api/notify/suggest", {"txn_ids": "t1"})                                   # 422
    step("POST", "/api/notify/suggest", {"txn_ids": [], "more": 1})                          # 422
    step("PUT", "/api/consent", {"helper_alerts": False, "counseling_referral": False})
    step("POST", "/api/notify/suggest", {"txn_ids": [payee["id"]]})
    step("PUT", "/api/notify/suggest", {"txn_ids": []})                                      # 405
    return out


def test_router_matches_fastapi_suggest(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "pc", now=lambda: NOW), base_url=BASE, headers={"X-SafePause": "1"})

    def pc(m: str, p: str, b: Any) -> tuple[int, Any]:
        r = client.request(m, p, json=b) if b is not None else client.request(m, p)
        return r.status_code, r.json()

    svc = _service(tmp_path / "app")

    def mobile(m: str, p: str, b: Any) -> tuple[int, Any]:
        status, body = dispatch(svc, m, p, b)
        return status, json.loads(json.dumps(body, ensure_ascii=False))

    got_pc, got_app = _suggest_scenario(pc), _suggest_scenario(mobile)
    assert got_pc == got_app
    assert [s for s, _ in got_pc] == [403, 200, 200, 200, 200, 200, 200, 200, 200, 200, 404, 422, 422, 422, 200,
                                      200, 405]
    assert all(re.search(r"[가-힣]", b["detail"]) for s, b in got_pc if s != 200)
    first = got_pc[6][1]                     # 걱정되는 거래 모두
    assert first["counseling_due"] is True
    assert [(c["id"], c["suggested"]) for c in first["counselors"]] == [("c1", True), ("c2", False)]
    assert {h["id"]: (h["suggested"], h["conflict"]) for h in first["helpers"]} == {
        "mom": (True, False), "payee": (False, True), "night": (True, False), "off": (False, False)}
    last = got_pc[15][1]                     # 조력자 알림·상담 동의를 끈 뒤
    assert not any(h["suggested"] for h in last["helpers"]) and last["counseling_due"] is False
    assert {h["id"] for h in last["helpers"] if h["conflict"]} == {"payee"}


def test_suggest_needs_ai_packages_so_app_waits_for_full_engine(tmp_path: Path) -> None:
    """받는 사람 추천은 거래 판단(numpy·scikit-learn)이 필요하다: 앱의 가벼운 경로(worker.mjs BASIC)에 넣지 않는다."""
    worker = (ROOT / "safepause" / "web" / "engine" / "worker.mjs").read_text(encoding="utf-8")
    basic = re.search(r"const BASIC = new Set\(\[(.*?)\]\);", worker, re.S)
    assert basic is not None and "GET /api/consent" in basic.group(1)
    assert "/api/notify/suggest" not in basic.group(1)
    code = r'''
import sys
sys.modules["numpy"] = None                      # numpy를 싣지 못하는 상태(앱의 AI 준비 전)
from datetime import datetime
from safepause.api.router import dispatch
from safepause.api.service import Service
from safepause.models import Channel, Consent, Direction, Transaction
s = Service(sys.argv[1])
s.store.save_consent(Consent(monitoring=True))
s.store.save_transactions([Transaction(id="t1", ts=datetime(2026, 9, 1, 10), amount=1000,
                                       direction=Direction.OUT, channel=Channel.CARD, counterparty="가게")])
print(dispatch(s, "POST", "/api/notify/suggest", {"txn_ids": []})[0])
'''
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path / "s")], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", cwd=ROOT, check=True)
    assert out.stdout.strip().splitlines()[-1] == "500"   # numpy 없이는 처리하지 못함(앱은 AI 준비 뒤에 보냄)


# ---- 돈 보내기: check/decide 응답 글(docs/v03_spec_money.md 파이썬 문구) ------------------------------

def _strings(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings(v)]
    return []


MONEY_BANNED = ("연습", "실제로 돈이 나가지 않아요", "막지 않아요", "결정은 내가 해요", "AI 혼자서는", "안전 정지",
                "127.0.0.1")


@pytest.mark.parametrize("channel,to", [("transfer", "김*호"), ("card", "새로 연 전자상가"), ("micropay", "게임 아이템")])
def test_check_and_decide_texts_have_no_practice_words(ready: Service, channel: str, to: str) -> None:
    from safepause.api.schemas import DecideIn, PendingIn
    ready.put_consent(ConsentIn(helper_alerts=True, counseling_referral=True))
    ready.put_helpers([HelperIn(id="h1", min_level="caution", **MOM)])
    req = {"to": to, "amount": 300000, "channel": channel}          # 지금 시각: 날짜가 옮겨져 ts_note가 생김
    r = ready.check(PendingIn(**req))
    assert r["ts_note"] and r["practice_note"] == ""
    texts = _strings({k: v for k, v in r.items() if k != "assessment"})
    for decision in ("send", "cancel", "ask_helper"):
        d = ready.decide(DecideIn(pending=PendingIn(**r["pending"]), decision=decision))
        assert d["practice_note"] == ""
        assert d["pending"]["memo"] == "보내기 전 확인"
        texts += _strings({k: v for k, v in d.items() if k != "assessment"})
    for text in texts:
        for word in MONEY_BANNED:
            assert word not in text, (word, text)
    assert constants.PRACTICE_NOTE == "연습 화면이에요. 실제로 돈이 나가지 않아요."   # 상수는 평가·옛 호환용으로 남김


def test_decide_result_texts_for_money_flow(ready: Service) -> None:
    from safepause.api.schemas import DecideIn, PendingIn
    ready.put_helpers([HelperIn(id="h1", **MOM)])
    pending = PendingIn(to="김*호", amount=300000, channel="transfer", time="02:00")
    want = {
        "send": ("내 은행 앱에서 보내 주세요.", "내 은행 앱에서 보내 주세요", ["김*호에게 30만 원을 보내기 전에 확인했어요."]),
        "cancel": ("보내지 않았어요.", "보내지 않았어요", ["김*호에게 30만 원을 보내지 않았어요."]),
        "ask_helper": ("엄마에게 물어봐요.", "조력자에게 물어봐요",
                       ["김*호에게 30만 원을 보내기 전에 조력자에게 물어봐요.", "아직 보내지 않았어요."]),
    }
    for decision, (message, title, lines) in want.items():
        helper_ids = ["h1"] if decision == "ask_helper" else None
        d = ready.decide(DecideIn(pending=pending, decision=decision, helper_ids=helper_ids))
        assert (d["message"], d["result_title"], d["result_lines"]) == (message, title, lines), decision
        assert d["added_to_history"] is (decision == "send")               # 그래도 보낼래요만 내 거래 끝에 적힘
    card = ready.decide(DecideIn(pending=PendingIn(to="새로 연 전자상가", amount=800000, channel="card", time="15:00"),
                                 decision="send"))
    assert (card["message"], card["result_title"]) == ("결제는 직접 해 주세요.", "결제는 직접 해 주세요")
    assert card["result_lines"] == ["새로 연 전자상가에서 80만 원을 결제하기 전에 확인했어요."]


def test_live_ids_used_up_message_has_no_practice_word(svc: Service) -> None:
    svc._live_high = 10 ** constants.LIVE_ID_DIGITS - 1
    e = _err(lambda: svc.issue_live_id([]))
    assert e.status == 409 and e.detail == constants.LIVE_IDS_USED_UP and "연습" not in e.detail


def test_money_phrases_are_plain() -> None:
    from safepause.explain.easy_card import WORDS_BILL, WORDS_CASH, WORDS_OTHER, WORDS_PAY, WORDS_SEND
    quoted = re.compile(r"['\"‘’“”][^'\"‘’“”]*[가-힣][^'\"‘’“”]*['\"‘’“”]")
    texts = [constants.TS_NOTE, constants.LIVE_IDS_USED_UP, constants.CONFLICT_REASON, constants.PRACTICE_MEMO,
             *(w.self_do for w in (WORDS_SEND, WORDS_PAY, WORDS_BILL, WORDS_CASH, WORDS_OTHER))]
    for text in texts:
        assert text and not quoted.search(text), text
        for word in (*FORBIDDEN_WORDS, *MONEY_BANNED, "고위험", "푸시", "당사자님"):
            assert word not in text, (word, text)
    assert WORDS_SEND.self_do == "내 은행 앱에서 보내 주세요"
    assert constants.TS_NOTE.startswith("저장된 거래가 오래전 것이라 확인한 거래는 저장된 거래 끝에 이어서 적어요.")
    assert constants.CONFLICT_REASON == "이 거래에서 돈을 받은 사람이에요."



def test_old_practice_memo_is_shown_with_new_name(ready: Service) -> None:
    # v0.2 앱이 확인 거래에 적은 메모(안전 정지 연습)는 저장은 그대로 두고, 화면에 줄 때만 지금 이름으로 보인다
    txns = ready.store.load_transactions()
    last = txns[-1].ts
    old = Transaction(id="live-00001", ts=last + timedelta(minutes=5), amount=300000, direction=Direction.OUT,
                      channel=Channel.TRANSFER, counterparty="김*호", memo="안전 정지 연습")
    plain = Transaction(id="t-memo", ts=last + timedelta(minutes=6), amount=1000, direction=Direction.OUT,
                        channel=Channel.CARD, counterparty="가게", memo="안전 정지 연습")   # 확인 거래가 아니면 그대로
    ready.store.save_transactions([*txns, old, plain])
    items = {i["txn"]["id"]: i for i in ready.transactions("all", 5, 0)["items"]}
    assert items["live-00001"]["txn"]["memo"] == constants.PRACTICE_MEMO == "보내기 전 확인"
    assert items["live-00001"]["practice"] is True
    assert items["t-memo"]["txn"]["memo"] == "안전 정지 연습" and items["t-memo"]["practice"] is False
    stored = {t.id: t.memo for t in ready.store.load_transactions()}
    assert stored["live-00001"] == "안전 정지 연습"                                   # 저장은 바꾸지 않음
    for card in ready.cards(50)["items"]:
        if card["txn"]["id"] == "live-00001":
            assert card["txn"]["memo"] == constants.PRACTICE_MEMO


def test_upload_warning_and_results_csv_use_checked_name(ready: Service) -> None:
    # 파일 올리기 경고와 분석 결과 표의 열 이름도 화면 이름(보내기 전 확인)을 쓴다. 연습이라는 말은 쓰지 않는다
    header = ready.export_results_csv()["text"].lstrip("\ufeff").splitlines()[0]
    assert header.endswith(",보내기 전 확인") and "연습" not in header
    csv = ("id,ts,amount,direction,channel,counterparty\n"
           "live-00001,2026-09-01T10:00:00,5000,out,card,가게\n"
           "x2,2026-09-02T10:00:00,7000,out,card,가게\n").encode("utf-8")
    warnings = ready.upload(csv)["report"]["warnings"]
    assert "보내기 전 확인한 거래와 같은 모양의 번호 1건은 이름을 바꿔 저장했어요." in warnings
    assert not any("연습" in w for w in warnings)


# ---- 모두 지우기 -------------------------------------------------------------------------

def test_wipe_removes_new_files(ready: Service) -> None:
    ready.put_counselors([CounselorIn(name="센터")])
    ready.add_flag(FlagIn(txn_id=_ids(ready)[0]))
    ready.record_notice(_record())
    assert {COUNSELORS_FILE, FLAGS_FILE} <= set(STORE_FILES)
    removed = ready.wipe()["removed"]
    assert {COUNSELORS_FILE, FLAGS_FILE, NOTICES_FILE} <= set(removed)
    assert not any((ready.store.root / n).exists() for n in STORE_FILES)
    assert ready.get_counselors()["items"] == [] and ready.notices()["items"] == []


# ---- 라우터(앱) = FastAPI(PC) ------------------------------------------------------------

def _scenario(call: Callable[[str, str, Any], tuple[int, Any]]) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []

    def step(m: str, p: str, b: Any = None) -> Any:
        out.append(call(m, p, b))
        return out[-1][1]

    step("GET", "/api/counselors")
    step("PUT", "/api/counselors", [{"name": ""}])                                        # 422
    step("PUT", "/api/counselors", [{**constants.COUNSELOR_PRESETS[0]}, {"name": "우리 센터", "kind": "disability_center",
                                                                         "phone": "02-123-4567", "active": False}])
    step("PUT", "/api/counselors", [{"name": "x", "kind": "bank"}])                       # 422
    step("GET", "/api/flags")                                                               # 403
    step("GET", "/api/insights")                                                            # 403
    step("POST", "/api/flags", {"txn_id": "x"})                                             # 403
    step("PUT", "/api/consent", {"monitoring": True, "helper_alerts": True, "counseling_referral": True})
    step("POST", "/api/data/sample", {"persona": "worker", "seed": 3, "scenarios": True})
    high = step("GET", "/api/transactions?level=high&limit=2")
    for item in high["items"]:
        step("POST", "/api/flags", {"txn_id": item["txn"]["id"]})
    step("POST", "/api/flags", {"txn_id": "no-such"})                                       # 404
    step("POST", "/api/flags", {})                                                          # 422
    step("GET", "/api/flags")
    step("GET", "/api/transactions?level=flagged")
    step("POST", "/api/flags/remove", {"txn_id": high["items"][0]["txn"]["id"]})
    step("PUT", "/api/helpers", [{"id": "h1", **MOM}, {"name": "옛 조력자", "contact": "dad@example.org"}])
    step("PUT", "/api/helpers", [{"name": "엄마", "phone": "010-12ab"}])                    # 422
    step("GET", "/api/helpers")
    step("POST", "/api/notices/record", {"channel": "sms", "recipients": [{"kind": "helper", "id": "h1", "name": "엄마"}],
                                          "txn_ids": [high["items"][1]["txn"]["id"]], "message": "확인해 주세요. 010-1234-5678"})
    step("POST", "/api/notices/record", {"channel": "fax", "recipients": [], "message": ""})   # 422
    step("GET", "/api/notices")
    step("GET", "/api/cards?limit=2")
    step("GET", "/api/insights")
    step("POST", "/api/wipe")
    step("GET", "/api/counselors")
    return out


def test_router_matches_fastapi_v03(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "pc", now=lambda: NOW), base_url=BASE, headers={"X-SafePause": "1"})

    def pc(m: str, p: str, b: Any) -> tuple[int, Any]:
        r = client.request(m, p, json=b) if b is not None else client.request(m, p)
        return r.status_code, r.json()

    svc = _service(tmp_path / "app")

    def mobile(m: str, p: str, b: Any) -> tuple[int, Any]:
        status, body = dispatch(svc, m, p, b)
        return status, json.loads(json.dumps(body, ensure_ascii=False))

    got_pc, got_app = _scenario(pc), _scenario(mobile)
    assert got_pc == got_app
    statuses = [s for s, _ in got_pc]
    assert statuses.count(403) == 3 and statuses.count(404) == 1 and statuses.count(422) == 5
    assert all(s in (200, 403, 404, 422) for s in statuses)
    assert all(re.search(r"[가-힣]", b["detail"]) for s, b in got_pc if s != 200)


@pytest.mark.parametrize("method,path", [("PUT", "/api/counselors"), ("POST", "/api/flags"),
                                         ("POST", "/api/flags/remove"), ("POST", "/api/notices/record"),
                                         ("POST", "/api/notify/suggest")])
def test_router_missing_body_matches_fastapi_v03(tmp_path: Path, method: str, path: str) -> None:
    with TestClient(create_app(tmp_path / "pc", now=lambda: NOW), base_url=BASE, headers={"X-SafePause": "1"}) as c:
        pc = c.request(method, path)
    status, body = dispatch(_service(tmp_path / "app"), method, path, None)
    assert pc.status_code == status == 422
    assert pc.json()["detail"] == body["detail"] == "입력한 값을 확인해 주세요: 요청"


# ---- 가벼운 경로(앱이 AI 패키지를 싣기 전에도 처리) ----------------------------------------------

def test_light_routes_do_not_load_numpy(tmp_path: Path) -> None:
    code = r'''
import json, sys
from datetime import datetime
from safepause.api.router import dispatch
from safepause.api.service import Service
from safepause.models import Channel, Consent, Direction, Transaction
s = Service(sys.argv[1])
s.store.save_consent(Consent(monitoring=True))
s.store.save_transactions([Transaction(id="t1", ts=datetime(2026, 9, 1, 10), amount=1000,
                                       direction=Direction.OUT, channel=Channel.CARD, counterparty="가게")])
calls = [("GET", "/api/counselors", None), ("PUT", "/api/counselors", [{"name": "센터"}]),
         ("PUT", "/api/helpers", [{"name": "엄마", "phone": "010-1234-5678"}]), ("GET", "/api/helpers", None),
         ("POST", "/api/flags", {"txn_id": "t1"}), ("POST", "/api/flags/remove", {"txn_id": "t1"}),
         ("POST", "/api/notices/record", {"channel": "sms", "recipients": [{"kind": "helper", "name": "엄마"}],
                                          "message": "확인해 주세요."}),
         ("GET", "/api/notices", None), ("POST", "/api/wipe", None)]
print(json.dumps([dispatch(s, m, p, b)[0] for m, p, b in calls]))
print(int("numpy" in sys.modules), int("sklearn" in sys.modules))
'''
    out = subprocess.run([sys.executable, "-c", code, str(tmp_path / "s")], capture_output=True, text=True,
                         cwd=ROOT, check=True)
    statuses, loaded = out.stdout.strip().splitlines()
    assert json.loads(statuses) == [200] * 9
    assert loaded.split() == ["0", "0"]


# ---- 파일 올리기 안내(R7): 화면은 열 이름을 직접 알려 주지 않으므로 mapping 안내를 쉬운 말로 ----------------

def test_upload_without_mapping_has_plain_hints(svc: Service) -> None:
    svc.put_consent(ConsentIn(monitoring=True))
    with pytest.raises(ServiceError) as e:
        svc.upload("가,나\n1,2\n".encode("utf-8"))
    assert e.value.status == 400
    assert "mapping" not in e.value.detail and "거래내역 파일인지 확인해 주세요" in e.value.detail
    # 받는 사람 열이 없는 파일: 경고에 mapping 안내가 없다
    rows = "\n".join(f"2026-06-{d:02d} 10:00,{1000 * d},0" for d in range(1, 11))
    r = svc.upload(f"거래일시,출금액,입금액\n{rows}\n".encode("utf-8"))
    warnings = r["report"]["warnings"]
    assert any("받는 사람 열을 찾지 못해" in w for w in warnings)
    assert not any("mapping" in w for w in warnings)


def test_upload_with_mapping_keeps_mapping_hints(svc: Service) -> None:
    svc.put_consent(ConsentIn(monitoring=True))
    with pytest.raises(ServiceError) as e:
        svc.upload("가,나\n1,2\n".encode("utf-8"), '{"date_format": "%Y-%m-%d"}')
    assert "mapping" in e.value.detail   # CLI·API에서 mapping을 쓰는 사람에게는 원래 안내
    rows = "\n".join(f"2026-06-{d:02d} 10:00,{1000 * d},0" for d in range(1, 11))
    r = svc.upload(f"거래일시,출금액,입금액\n{rows}\n".encode("utf-8"), '{"date_format": "%Y-%m-%d %H:%M"}')
    assert any('mapping의 "counterparty"' in w for w in r["report"]["warnings"])
