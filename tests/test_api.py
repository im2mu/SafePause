"""server/app.py API 테스트 (FastAPI TestClient, 네트워크 없음)."""
from __future__ import annotations

import dataclasses
import json
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from safepause.data import synth
from safepause.explain.easy_card import PAST_QUESTION, PICTOGRAMS, readability_issues
from safepause.api.constants import NOTICES_NOTE
from safepause.guardian.outbox import DELIVERY_NOTE
from safepause.models import AlertCard, RiskLevel
from safepause.server.app import EvalUnavailable, create_app
from safepause.store import STORE_FILES, TRANSACTIONS_FILE, Store

BASE = "http://127.0.0.1:8765"
HEADERS = {"X-SafePause": "1"}
NOW = datetime(2026, 9, 30, 12, 0, 0)
ROOT = Path(__file__).resolve().parents[1]
BANK_EXAMPLE = ROOT / "sample_data" / "bank_export_example.csv"
WEB = ROOT / "safepause" / "web"


# ---- 준비 ------------------------------------------------------------------

def make_client(home: Path, **kwargs: Any) -> TestClient:
    app = create_app(home, now=lambda: NOW, **kwargs)
    return TestClient(app, base_url=BASE, headers=HEADERS)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def client(home: Path):
    with make_client(home) as c:
        yield c


def set_consent(client: TestClient, **values: Any) -> dict[str, Any]:
    r = client.put("/api/consent", json=values)
    assert r.status_code == 200, r.text
    return r.json()


def load_sample(client: TestClient, persona: str = "worker", seed: int = 1,
                scenarios: bool = False) -> dict[str, Any]:
    r = client.post("/api/data/sample", json={"persona": persona, "seed": seed, "scenarios": scenarios})
    assert r.status_code == 200, r.text
    return r.json()


def put_helpers(client: TestClient, helpers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    r = client.put("/api/helpers", json=helpers)
    assert r.status_code == 200, r.text
    return r.json()


def night(to: str = "김*호", **extra: Any) -> dict[str, Any]:
    return {"to": to, "amount": 300_000, "channel": "transfer", "time": "02:00", **extra}


def check(client: TestClient, pending: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/api/safepause/check", json=pending)
    assert r.status_code == 200, r.text
    return r.json()


def decide(client: TestClient, pending: dict[str, Any], decision: str) -> dict[str, Any]:
    r = client.post("/api/safepause/decide", json={"pending": pending, "decision": decision})
    assert r.status_code == 200, r.text
    return r.json()


def night_high(client: TestClient, **extra: Any) -> dict[str, Any]:
    """새벽 이체 두 번을 보낸 뒤 세 번째를 check한다 → 심야 반복 이체 고위험."""
    for _ in range(2):
        decide(client, night(**extra), "send")
    r = check(client, night(**extra))
    hits = {h["code"]: h["severity"] for h in r["assessment"]["rule_hits"]}
    assert r["assessment"]["level"] == "high"
    assert hits.get("night_repeat_transfer") == "high"
    return r


def card_from(d: dict[str, Any]) -> AlertCard:
    return AlertCard(**{**d, "level": RiskLevel(d["level"])})


# ---- 상태·화면·보안 ---------------------------------------------------------

def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["offline"] is True
    assert body["version"] == "0.3.0"
    assert r.headers["cache-control"] == "no-store"


def test_index_and_static_files(client: TestClient) -> None:
    # v0.2: 새 화면(safepause/web)을 PC 서버와 안드로이드 앱이 같이 쓴다
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="js/main.js">' in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "script-src 'self';" in r.headers["content-security-policy"]   # PC는 wasm 실행도 허용하지 않음
    for path, kind in (("/js/main.js", "javascript"), ("/css/app.css", "css"), ("/data/eval_reference.json", "json")):
        res = client.get(path)
        assert res.status_code == 200 and kind in res.headers["content-type"], path
    tabs = client.get("/js/main.js").text
    for label in ("홈", "내 거래", "보내기", "알림", "전체"):
        assert f'label: "{label}"' in tabs


def test_ui_has_no_external_resources() -> None:
    # 외부 CDN·글꼴 금지(오프라인). SVG의 xmlns 이름공간은 주소 호출이 아니므로 제외.
    for path in sorted(WEB.rglob("*")):
        if path.suffix not in (".html", ".js", ".mjs", ".css"):
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), path.name
        assert "@import" not in text and "fonts.googleapis" not in text, path.name


@pytest.mark.parametrize("name", sorted(PICTOGRAMS))
def test_all_pictograms_served(client: TestClient, name: str) -> None:
    r = client.get(f"/icons/{name}.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.text.startswith("<svg") and 'viewBox="0 0 64 64"' in r.text
    assert "currentColor" in r.text and "<script" not in r.text


def test_rejects_non_loopback_host(client: TestClient) -> None:
    r = client.get("/api/health", headers={"host": "evil.example"})
    assert r.status_code == 400
    assert "127.0.0.1" in r.json()["detail"]
    assert client.get("/api/health", headers={"host": "localhost:8765"}).status_code == 200


def test_write_requires_client_header_and_same_origin(home: Path) -> None:
    app = create_app(home, now=lambda: NOW)
    with TestClient(app, base_url=BASE) as bare:   # X-SafePause 머리글 없음
        r = bare.post("/api/wipe")
        assert r.status_code == 403 and "SafePause 화면에서 보낸 요청이 아니에요" in r.json()["detail"]
        assert bare.put("/api/consent", json={"monitoring": True}).status_code == 403
        assert bare.get("/api/consent").status_code == 200   # 읽기는 허용
    with TestClient(app, base_url=BASE, headers=HEADERS) as c:
        r = c.put("/api/consent", json={"monitoring": True}, headers={"origin": "http://evil.example"})
        assert r.status_code == 403
        r = c.put("/api/consent", json={"monitoring": True}, headers={"origin": BASE})
        assert r.status_code == 200


def test_docs_ui_disabled(client: TestClient) -> None:
    # Swagger 화면은 외부 CDN을 쓰므로 끈다.
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


# ---- 동의 ------------------------------------------------------------------

def test_consent_defaults_off(client: TestClient) -> None:
    c = client.get("/api/consent").json()
    assert c == {"monitoring": False, "helper_alerts": False, "counseling_referral": False,
                 "given_by": "self", "updated_at": ""}


def test_consent_toggled_independently_and_revoked_immediately(client: TestClient) -> None:
    load_sample(client)
    c = set_consent(client, monitoring=True)
    assert c["monitoring"] is True and c["helper_alerts"] is False
    assert c["updated_at"] == NOW.isoformat()
    c = set_consent(client, helper_alerts=True)
    assert c["monitoring"] is True and c["helper_alerts"] is True
    c = set_consent(client, counseling_referral=True, given_by="legal_representative")
    assert c["counseling_referral"] is True and c["given_by"] == "legal_representative"

    assert client.get("/api/transactions").status_code == 200
    assert client.app.state.safepause._snap is not None
    c = set_consent(client, monitoring=False)             # 즉시 철회
    assert c["monitoring"] is False and c["helper_alerts"] is True
    assert client.app.state.safepause._snap is None       # 메모리 분석 결과도 버림
    assert client.get("/api/transactions").status_code == 403
    assert client.get("/api/consent").json()["monitoring"] is False


@pytest.mark.parametrize("body", [
    {"monitoring": "yes"}, {"monitoring": 1}, {"given_by": "friend"}, {"unknown": True},
])
def test_consent_rejects_bad_values(client: TestClient, body: dict[str, Any]) -> None:
    r = client.put("/api/consent", json=body)
    assert r.status_code == 422
    assert r.json()["detail"].startswith("입력한 값을 확인해 주세요")
    assert client.get("/api/consent").json()["monitoring"] is False


# ---- 조력자 -----------------------------------------------------------------

def test_helpers_roundtrip_and_ids(client: TestClient) -> None:
    assert client.get("/api/helpers").json() == []
    saved = put_helpers(client, [
        {"name": " 엄마 ", "relation": "가족", "identifiers": [" 엄마 ", "900-0101-100001", "", "엄마"]},
        {"id": "center", "name": "센터 선생님", "relation": "지역발달장애인지원센터 전담 인력",
         "min_level": "caution", "signal_scope": ["payee_surge", "night_repeat_transfer"], "active": False},
        {"id": "center", "name": "중복 번호"},
    ])
    assert [h["id"] for h in saved] == ["h1", "center", "h2"]
    mom = saved[0]
    assert mom["name"] == "엄마" and mom["identifiers"] == ["엄마", "900-0101-100001"]
    assert mom["min_level"] == "high"           # 기본: 고위험만
    assert mom["signal_scope"] == [] and mom["active"] is True
    assert saved[1]["min_level"] == "caution" and saved[1]["active"] is False
    assert saved[1]["signal_scope"] == ["payee_surge", "night_repeat_transfer"]
    assert client.get("/api/helpers").json() == saved

    assert put_helpers(client, []) == []        # 전체 교체
    assert client.get("/api/helpers").json() == []


@pytest.mark.parametrize("helper", [
    {"name": "   "}, {"name": "엄마", "min_level": "none"}, {"name": "엄마", "signal_scope": ["foo"]},
    {"name": "엄마", "active": "yes"}, {"name": "엄마", "id": "나쁜 id"}, {"name": "엄마", "extra": 1},
])
def test_helpers_reject_bad_values(client: TestClient, helper: dict[str, Any]) -> None:
    r = client.put("/api/helpers", json=[helper])
    assert r.status_code == 422
    assert "입력한 값을 확인해 주세요" in r.json()["detail"]


def test_helpers_limit(client: TestClient) -> None:
    r = client.put("/api/helpers", json=[{"name": f"조력자{i}"} for i in range(11)])
    assert r.status_code == 422 and "10명" in r.json()["detail"]


# ---- 데이터 ------------------------------------------------------------------

def test_sample_data_saved_and_summarized(client: TestClient) -> None:
    body = load_sample(client, "worker", 1, scenarios=True)
    expected = synth.make_dataset("worker", 1, scenarios=synth.ALL_SCENARIOS)
    assert body["count"] == len(expected)
    assert body["persona_name"] == synth.PERSONAS["worker"].name
    assert set(body["scenario_labels"]) == {c.value for c in synth.ALL_SCENARIOS}
    assert body["first_ts"] == expected[0].ts.isoformat(timespec="seconds")
    assert client.get("/api/data/summary").json()["count"] == len(expected)

    plain = load_sample(client, "student", 3, scenarios=False)   # 교체 저장
    assert plain["scenario_labels"] == {}
    assert plain["count"] == len(synth.make_dataset("student", 3))
    assert client.get("/api/data/summary").json()["count"] == plain["count"]


@pytest.mark.parametrize("body", [
    {"persona": "nobody"}, {"seed": -1}, {"days": 10}, {"scenarios": "yes"},
])
def test_sample_rejects_bad_values(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/api/data/sample", json=body).status_code == 422


def test_upload_requires_consent(client: TestClient) -> None:
    files = {"file": ("bank.csv", BANK_EXAMPLE.read_bytes(), "text/csv")}
    r = client.post("/api/data/upload", files=files)
    assert r.status_code == 403 and "동의" in r.json()["detail"]
    assert client.get("/api/data/summary").json()["count"] == 0


def test_upload_bank_example_returns_loader_report(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    files = {"file": ("bank.csv", BANK_EXAMPLE.read_bytes(), "text/csv")}
    r = client.post("/api/data/upload", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    report = body["report"]
    assert report["loaded"] == 46 and report["skipped"] == 0
    assert report["format"] == "mapped"
    assert any("추정" in w for w in report["warnings"])
    assert body["summary"]["count"] == 46
    txns = client.get("/api/transactions").json()
    assert txns["count"] == 46
    assert all(it["txn"]["id"].startswith("imp-") for it in txns["items"])


def test_upload_with_explicit_mapping(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    mapping = ('{"datetime": "거래일시", "out_amount": "출금액", "in_amount": "입금액", '
               '"counterparty": "내용", "memo": "적요"}')
    files = {"file": ("bank.csv", BANK_EXAMPLE.read_bytes(), "text/csv")}
    r = client.post("/api/data/upload", files=files, data={"mapping": mapping})
    assert r.status_code == 200, r.text
    assert r.json()["report"]["loaded"] == 46


@pytest.mark.parametrize("content,mapping,fragment", [
    ("가,나\n1,2\n".encode("utf-8"), None, "거래내역 파일인지 확인해 주세요"),   # 화면은 열 이름을 알려 주지 않는다(v0.3)
    (b"", None, "비어"),
    ("거래일시,출금액,입금액\n".encode("utf-8"), "{bad json", "JSON"),
    ("거래일시,출금액,입금액\n".encode("utf-8"), "[1, 2]", "모양"),
])
def test_upload_errors_are_korean(client: TestClient, content: bytes, mapping: str | None,
                                  fragment: str) -> None:
    set_consent(client, monitoring=True)
    data = {"mapping": mapping} if mapping is not None else None
    r = client.post("/api/data/upload", files={"file": ("x.csv", content, "text/csv")}, data=data)
    assert r.status_code == 400
    assert fragment in r.json()["detail"]


def test_upload_too_large(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    big = b"a" * (5 * 1024 * 1024 + 1)
    r = client.post("/api/data/upload", files={"file": ("big.csv", big, "text/csv")})
    assert r.status_code == 413


# ---- 동의 없을 때 403 --------------------------------------------------------

@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/transactions", None),
    ("get", "/api/cards", None),
    ("post", "/api/safepause/check", night()),
    ("post", "/api/safepause/decide", {"pending": night(), "decision": "send"}),
    ("post", "/api/eval/file", None),
])
def test_analysis_needs_monitoring_consent(client: TestClient, method: str, path: str,
                                           body: dict[str, Any] | None) -> None:
    load_sample(client)
    set_consent(client, helper_alerts=True, counseling_referral=True)   # 분석 동의만 없음
    r = client.request(method.upper(), path, json=body)
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "동의" in detail and "거래 살펴보기" in detail
    # 기록은 남지 않는다
    assert client.get("/api/decisions").json()["items"] == []
    assert client.get("/api/notices").json()["items"] == []


# ---- 내 거래 -----------------------------------------------------------------

def test_transactions_with_assessments(client: TestClient) -> None:
    sample = load_sample(client, "worker", 1, scenarios=True)
    set_consent(client, monitoring=True)
    body = client.get("/api/transactions").json()
    n = sample["count"]
    assert body["count"] == n == len(body["items"]) == body["matched"]
    assert sum(body["summary"].values()) == n
    assert body["model"]["fitted"] is True
    # [변경 r2] 걱정되는 거래를 섞은 샘플은 ⑥ 성능 확인과 같은 날짜 경계(마지막 30일 이전)로 배운다
    metrics = pytest.importorskip("safepause.eval.metrics")
    case = metrics.synthetic_case("worker", 1)
    assert body["model"]["train_count"] == len(case.baseline)
    # 실제 학습 행 수(모델 버전의 숫자)는 학습 구간 거래 수 이하(평소 기준이 없는 맨 앞 거래는 뺌)
    rows = body["model"]["train_rows"]
    assert body["model"]["version"].endswith(f"iforest-v1-{rows}")
    assert 30 <= rows <= body["model"]["train_count"]
    oldest_first = list(reversed(body["items"]))
    trained = oldest_first[:body["model"]["train_count"]]
    assert all(it["txn"]["label"] == "normal" for it in trained)   # 섞은 거래는 배우지 않음
    ts = [it["txn"]["ts"] for it in body["items"]]
    assert ts == sorted(ts, reverse=True)                       # 최근 거래부터
    for it in body["items"]:
        assert it["level"] in ("none", "caution", "high")
        assert 0.0 <= it["anomaly_score"] <= 1.0
    labeled_high = [it for it in body["items"]
                    if it["txn"]["label"] not in (None, "normal") and it["level"] == "high"]
    assert labeled_high, "주입 시나리오 중 고위험이 하나 이상 있어야 한다"

    high = client.get("/api/transactions", params={"level": "high"}).json()
    assert high["matched"] == body["summary"]["high"]
    assert all(it["level"] == "high" for it in high["items"])
    caution = client.get("/api/transactions", params={"level": "caution"}).json()
    assert caution["matched"] == body["summary"]["caution"] + body["summary"]["high"]
    limited = client.get("/api/transactions", params={"limit": 5}).json()
    assert len(limited["items"]) == 5 and limited["matched"] == n


def test_transactions_empty_store(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    body = client.get("/api/transactions").json()
    assert body["count"] == 0 and body["items"] == []
    assert body["model"]["fitted"] is False


# ---- 안전 정지: check ---------------------------------------------------------

def test_check_safe_payment_stores_nothing(client: TestClient) -> None:
    sample = load_sample(client, "worker", 1)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마", "identifiers": ["엄마"]}])
    r = check(client, {"to": "엄마", "amount": 50_000, "time": "15:00"})
    assert r["assessment"]["level"] == "none"
    assert r["card"] is None
    assert r["notify_plan_preview"]["notices"] == []
    assert r["practice_note"] == ""                           # v0.3: 연습 안내를 쓰지 않는다(키만 호환용)
    p = r["pending"]
    assert p["id"] == "live-00001" and p["direction"] == "out"
    assert p["counterparty_id"] == "900-0101-100001"          # 예전에 보낸 계좌를 이어 씀
    # v0.3 수정 계획 A: 저장된 거래가 45일보다 오래됐으면 마지막 실제 거래 날짜에 고른 시각, 그 시각이 마지막 거래보다
    # 이르면 다음 날(실제 거래 사이에 끼지 않게). 확인을 거듭해도 더 밀리지 않는다
    assert p["ts"] > sample["last_ts"] and p["ts"].endswith("T15:00:00")
    # 저장하지 않음
    assert client.get("/api/data/summary").json()["count"] == sample["count"]
    assert client.get("/api/decisions").json()["items"] == []
    assert client.get("/api/notices").json()["items"] == []
    # 같은 입력 → 같은 결과. [변경 r3] 다만 연습 거래 id는 check마다 새로 준다(두 탭이 겹치지 않게)
    again = check(client, {"to": "엄마", "amount": 50_000, "time": "15:00"})
    assert again["pending"]["id"] == "live-00002"

    def without_ids(res: dict[str, Any]) -> dict[str, Any]:
        out = json.loads(json.dumps(res))
        out["pending"].pop("id")
        out["assessment"].pop("txn_id")
        return out

    assert without_ids(again) == without_ids(r)


def test_check_risky_payment_returns_card(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    r = night_high(client)
    card = r["card"]
    assert card["level"] == "high"
    assert card["title"] == "밤에 돈을 자주 보냈어요"
    assert [c["decision"] for c in card["choices"]] == ["send", "cancel", "ask_helper"]
    assert card["question"] == "이 돈을 정말 보내는 것이 맞나요?"
    assert set(card["pictograms"]) <= PICTOGRAMS
    assert readability_issues(card_from(card)) == []
    assert card["speak_text"].startswith(card["title"])


def test_check_time_and_ts_resolution(client: TestClient) -> None:
    sample = load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    last = datetime.fromisoformat(sample["last_ts"])
    r = check(client, night(time="23:30"))
    ts = datetime.fromisoformat(r["pending"]["ts"])
    assert ts > last and (ts - last).days <= 1 and (ts.hour, ts.minute) == (23, 30)
    r = check(client, night(ts="2026-07-01T10:15:00"))
    assert r["pending"]["ts"] == "2026-07-01T10:15:00"
    r = check(client, night(ts="2026-07-01T10:15:00+09:00"))       # 시간대가 있으면 이 컴퓨터 시각으로
    assert "+" not in r["pending"]["ts"]


@pytest.mark.parametrize("body,field", [
    ({"to": "김*호", "amount": -5}, "금액"),
    ({"to": "김*호", "amount": 0}, "금액"),
    ({"to": "   ", "amount": 1000}, "받는 사람"),
    ({"to": "김*호", "amount": 1000, "channel": "income"}, "보내는 방법"),
    ({"to": "김*호", "amount": 1000, "time": "25:00"}, "시각"),
])
def test_check_validation_errors_korean(client: TestClient, body: dict[str, Any], field: str) -> None:
    load_sample(client)
    set_consent(client, monitoring=True)
    r = client.post("/api/safepause/check", json=body)
    assert r.status_code == 422
    assert field in r.json()["detail"]


# ---- 안전 정지: decide --------------------------------------------------------

def test_decide_send_is_never_blocked(client: TestClient) -> None:
    sample = load_sample(client, "worker", 1)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마", "identifiers": ["엄마", "900-0101-100001"]}])
    r = night_high(client)
    # 화면처럼 check가 준 id와 시각을 그대로 보낸다(같은 시도)
    d = decide(client, {**night(), "ts": r["pending"]["ts"], "id": r["pending"]["id"]}, "send")
    assert d["assessment"]["level"] == "high"
    assert d["added_to_history"] is True                         # 고위험이어도 막지 않음
    assert d["message"] == "내 은행 앱에서 보내 주세요."       # v0.3: SafePause는 돈을 옮기지 않는다
    assert d["delivery_note"] == DELIVERY_NOTE
    assert d["pending"]["id"] == r["pending"]["id"] == "live-00003"
    assert client.get("/api/data/summary").json()["count"] == sample["count"] + 3

    decisions = client.get("/api/decisions").json()["items"]     # 최근 것부터
    assert [x["decision"] for x in decisions] == ["send", "send", "send"]
    assert decisions[0] == {"txn_id": "live-00003", "decision": "send", "level": "high",
                            "at": NOW.isoformat()}
    # 고위험 + 조력자 알림 동의 → 알림 기록(실제 발송 없음)
    assert d["notices_recorded"] == 1
    notices = client.get("/api/notices").json()
    assert notices["delivery_note"] == NOTICES_NOTE              # v0.3: 자동·직접 기록을 함께 보여 주는 안내
    latest = notices["items"][0]
    assert latest["kind"] == "auto"
    assert latest["helper_name"] == "엄마" and latest["txn_id"] == "live-00003"
    assert latest["level"] == "high"
    # 당사자 화면에 보이는 적어 둔 기록 글에는 결정 문장을 넣지 않는다(v0.3 수정 RF-11)
    assert "결정은" not in latest["message"] and "이야기해 주세요" in latest["message"]

    txns = client.get("/api/transactions").json()["items"]
    practice = [it for it in txns if it["practice"]]
    assert len(practice) == 3 and all(it["txn"]["memo"] == "보내기 전 확인" for it in practice)


def test_decide_cancel_records_without_adding(client: TestClient) -> None:
    sample = load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    d = decide(client, night(), "cancel")
    assert d["added_to_history"] is False and d["recorded"] is True
    assert d["message"] == "보내지 않았어요."
    assert client.get("/api/data/summary").json()["count"] == sample["count"]
    items = client.get("/api/decisions").json()["items"]
    assert len(items) == 1 and items[0]["decision"] == "cancel"


def test_practice_ids_stay_unique_after_cancel(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    first = decide(client, night(), "cancel")
    second = decide(client, night(), "send")
    assert first["pending"]["id"] == "live-00001"
    assert second["pending"]["id"] == "live-00002"
    assert [d["txn_id"] for d in client.get("/api/decisions").json()["items"]] == ["live-00002", "live-00001"]


def test_decide_accepts_check_pending_dict(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    r = check(client, night())
    d = decide(client, r["pending"], "cancel")                  # check 응답의 거래 dict 그대로
    assert d["pending"] == r["pending"]
    assert d["assessment"] == r["assessment"]


def test_helper_alerts_off_means_no_auto_notice(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)                        # 조력자 알림 동의 없음
    put_helpers(client, [{"name": "엄마"}])
    r = night_high(client)
    assert r["notify_plan_preview"]["notices"] == []
    d = decide(client, night(ts=r["pending"]["ts"]), "send")
    assert d["notices_recorded"] == 0
    assert client.get("/api/notices").json()["items"] == []


def test_ask_helper_records_notice_on_request(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)                        # 자동 알림은 꺼짐
    put_helpers(client, [{"name": "엄마", "min_level": "high"}])
    sample_count = client.get("/api/data/summary").json()["count"]
    d = decide(client, {"to": "엄마", "amount": 50_000, "time": "15:00"}, "ask_helper")
    assert d["added_to_history"] is False
    assert d["notices_recorded"] == 1
    assert d["message"] == "엄마에게 물어봐요."
    notice = client.get("/api/notices").json()["items"][0]
    assert notice["helper_name"] == "엄마" and "함께 확인" in notice["message"]
    assert client.get("/api/data/summary").json()["count"] == sample_count


def test_caution_level_helper_gets_caution_notices(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"id": "hi", "name": "엄마"},
                         {"id": "ca", "name": "센터 선생님", "min_level": "caution"}])
    # 신규 가맹점 고액 결제 1건 → 룰 주의(모델 점수에 따라 고위험으로 오를 수 있음)
    r = check(client, {"to": "처음 가는 가게", "amount": 800_000, "channel": "card", "time": "15:00"})
    level = r["assessment"]["level"]
    ids = {n["helper_id"] for n in r["notify_plan_preview"]["notices"]}
    assert level in ("caution", "high")
    assert ids == ({"hi", "ca"} if level == "high" else {"ca"})


# ---- 이해충돌 ----------------------------------------------------------------

def test_conflicted_helper_is_excluded(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [
        {"id": "a", "name": "김*호", "identifiers": ["김*호"]},      # 이번 거래의 받는 사람
        {"id": "b", "name": "센터 선생님", "identifiers": ["900-9999-000001"]},
    ])
    r = night_high(client)
    plan = r["notify_plan_preview"]
    assert plan["excluded_conflict"] == ["a"]
    assert [n["helper_id"] for n in plan["notices"]] == ["b"]
    assert plan["note_to_person"] == "김*호는 돈을 받는 사람이에요. 그래서 센터 선생님에게만 알릴 수 있어요."
    decide(client, night(ts=r["pending"]["ts"]), "send")
    notices = client.get("/api/notices").json()["items"]
    assert notices and {n["helper_id"] for n in notices} == {"b"}


def test_conflict_by_account_digits(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"id": "a", "name": "삼촌", "identifiers": ["123-456-789012"]},
                         {"id": "b", "name": "엄마"}])
    r = night_high(client, to_id="123456789012")
    assert r["notify_plan_preview"]["excluded_conflict"] == ["a"]
    assert [n["helper_id"] for n in r["notify_plan_preview"]["notices"]] == ["b"]


def test_only_helper_conflicted_suggests_counseling_with_consent(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    put_helpers(client, [{"id": "a", "name": "김*호", "identifiers": ["김*호"]}])
    set_consent(client, monitoring=True, helper_alerts=True, counseling_referral=True)
    r = night_high(client)
    plan = r["notify_plan_preview"]
    assert plan["notices"] == [] and plan["excluded_conflict"] == ["a"]
    assert plan["suggest_counseling"] is True
    assert plan["counseling_orgs"] == ["지역발달장애인지원센터", "장애인권익옹호기관"]
    assert client.get("/api/notices").json()["items"] == []

    set_consent(client, counseling_referral=False)             # 상담 연결 동의 철회
    r = check(client, night())
    assert r["notify_plan_preview"]["suggest_counseling"] is False
    assert r["notify_plan_preview"]["counseling_orgs"] == []


def test_ask_helper_skips_conflicted_helper(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    put_helpers(client, [{"id": "a", "name": "김*호", "identifiers": ["김*호"]},
                         {"id": "b", "name": "엄마"}])
    d = decide(client, night(), "ask_helper")
    assert d["notify_plan"]["excluded_conflict"] == ["a"]
    assert [n["helper_id"] for n in d["notify_plan"]["notices"]] == ["b"]


# ---- 카드·기록 ---------------------------------------------------------------

def test_cards_are_readable_and_recent_first(client: TestClient) -> None:
    load_sample(client, "benefit", 2, scenarios=True)
    set_consent(client, monitoring=True)
    body = client.get("/api/cards").json()
    assert body["total"] > 0
    assert 0 < len(body["items"]) <= 20
    ts = [it["txn"]["ts"] for it in body["items"]]
    assert ts == sorted(ts, reverse=True)
    for it in body["items"]:
        card = it["card"]
        assert card["level"] in ("caution", "high")
        assert readability_issues(card_from(card)) == []
        # 이미 끝난 거래의 기록 카드: 지금 보낼지 묻지 않고, '이번 주'라고 하지 않는다
        assert card["question"] == PAST_QUESTION and card["choices"] == []
        assert all("이번 주" not in line and "이번이" not in line for line in card["lines"])
        assert card["speak_text"].endswith(PAST_QUESTION)
    assert len(client.get("/api/cards", params={"limit": 3}).json()["items"]) == 3


def test_records_empty_initially(client: TestClient) -> None:
    assert client.get("/api/notices").json() == {"items": [], "delivery_note": NOTICES_NOTE}
    assert client.get("/api/decisions").json() == {"items": []}


# ---- 성능 확인 ---------------------------------------------------------------

def test_eval_run_uses_evaluator_and_sanitizes(home: Path) -> None:
    calls: list[tuple[list[str], list[int], list[str], str]] = []

    def fake(personas: list[str], seeds: list[int], modes: list[str], *, intensity: str) -> dict[str, Any]:
        calls.append((personas, seeds, modes, intensity))
        return {m: {"overall": {"recall_caution": np.float64(0.5), "n": np.int64(3)},
                    "bad": float("nan")} for m in modes}

    with make_client(home, evaluator=fake) as c:
        r = c.post("/api/eval/run", json={"seeds": 2, "modes": ["fused", "rules", "fused"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert calls == [(list(synth.PERSONAS), [1, 2], ["fused", "rules"], "standard")]
        assert body["seeds"] == [1, 2] and body["modes"] == ["fused", "rules"]
        assert (body["seed_start"], body["seed_end"], body["intensity"], body["report_set"]) == (1, 2, "standard", False)
        assert body["results"]["fused"]["overall"] == {"recall_caution": 0.5, "n": 3}
        assert body["results"]["rules"]["bad"] is None
        assert body["note"] == "합성 데이터 기준, 실제 피해 데이터 검증 아님"

        r = c.post("/api/eval/run")                              # 본문 없으면 기본값
        assert r.status_code == 200
        assert calls[-1] == (list(synth.PERSONAS), [1, 2, 3, 4, 5], ["fused"], "standard")

        # 제출 보고서 검증 세트와 같은 설정(seed 21~40, 경계 변형)
        r = c.post("/api/eval/run", json={"seeds": 20, "seed_start": 21, "intensity": "subtle",
                                          "modes": ["fused", "rules", "anomaly"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert calls[-1] == (list(synth.PERSONAS), list(range(21, 41)), ["fused", "rules", "anomaly"], "subtle")
        assert (body["seed_start"], body["seed_end"], body["intensity"], body["report_set"]) == (21, 40, "subtle", True)

        for bad in ({"seeds": 0}, {"seeds": 21}, {"modes": ["magic"]}, {"modes": []},
                    {"personas": ["nobody"]}, {"seed_start": 0}, {"seed_start": 10_001},
                    {"intensity": "hard"}, {"intensity": ""}, {"seed": 21}):
            assert c.post("/api/eval/run", json=bad).status_code == 422, bad


def test_eval_run_unavailable_returns_503(home: Path) -> None:
    def broken(personas: list[str], seeds: list[int], modes: list[str], *, intensity: str) -> dict[str, Any]:
        raise EvalUnavailable("성능 평가 모듈을 찾을 수 없어요.")

    with make_client(home, evaluator=broken) as c:
        r = c.post("/api/eval/run", json={"seeds": 1})
        assert r.status_code == 503 and "평가 모듈" in r.json()["detail"]


def test_eval_run_real_quick(client: TestClient) -> None:
    pytest.importorskip("safepause.eval.metrics")
    r = client.post("/api/eval/run", json={"seeds": 1, "personas": ["worker"], "modes": ["fused"]})
    assert r.status_code == 200, r.text
    fused = r.json()["results"]["fused"]
    assert fused["mode"] == "fused"
    assert fused["overall"]["n"] == len(synth.ALL_SCENARIOS)
    assert 0.0 <= fused["overall"]["recall_caution"] <= 1.0


def test_eval_file_matches_server_assessments(client: TestClient) -> None:
    pytest.importorskip("safepause.eval.metrics")
    sample = load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    r = client.post("/api/eval/file")
    assert r.status_code == 200, r.text
    body = r.json()
    n = sample["count"]
    assert body["n_total"] == n and body["has_scenario_labels"] is False
    assert body["labeled_note"] == ""
    txns = client.get("/api/transactions").json()
    assert body["n_baseline"] == txns["model"]["train_count"]
    assert body["n_train_rows"] == txns["model"]["train_rows"]
    assert body["model_version"].endswith(f"iforest-v1-{body['n_train_rows']}")
    # 서버가 보여 주는 평가(앞 75%로 학습)와 같은 모델·같은 결과여야 한다
    oldest_first = list(reversed(txns["items"]))
    later = oldest_first[txns["model"]["train_count"]:]
    assert body["alerts"] == sum(1 for it in later if it["level"] != "none")
    assert body["high"] == sum(1 for it in later if it["level"] == "high")

    load_sample(client, "worker", 1, scenarios=True)
    body = client.post("/api/eval/file").json()
    assert body["has_scenario_labels"] is True and body["labeled_note"]


def test_eval_file_without_data(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    r = client.post("/api/eval/file")
    assert r.status_code == 400 and "거래가 없어요" in r.json()["detail"]


# ---- 지우기 ------------------------------------------------------------------

def test_wipe_removes_everything(client: TestClient, home: Path) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마"}])
    night_high(client)
    decide(client, night(), "send")
    assert client.get("/api/notices").json()["items"]
    assert client.put("/api/counselors", json=[{"name": "센터"}]).status_code == 200
    first = client.get("/api/transactions", params={"limit": 1}).json()["items"][0]["txn"]["id"]
    assert client.post("/api/flags", json={"txn_id": first}).status_code == 200
    assert client.post("/api/reviews", json={"txn_id": first}).status_code == 200

    r = client.post("/api/wipe")
    assert r.status_code == 200
    assert set(r.json()["removed"]) == set(STORE_FILES)
    assert not any((home / name).exists() for name in STORE_FILES)
    assert client.app.state.safepause._snap is None

    assert client.get("/api/consent").json()["monitoring"] is False
    assert client.get("/api/helpers").json() == []
    assert client.get("/api/notices").json()["items"] == []
    assert client.get("/api/decisions").json()["items"] == []
    assert client.get("/api/data/summary").json()["count"] == 0
    assert client.get("/api/transactions").status_code == 403    # 동의도 지워짐
    set_consent(client, monitoring=True)
    body = client.get("/api/transactions").json()
    assert body["count"] == 0 and body["items"] == []
    cards = client.get("/api/cards").json()
    assert cards["total"] == 0 and cards["items"] == [] and cards["counseling"]["suggest"] is False
    assert client.get("/api/counselors").json()["items"] == []
    assert client.get("/api/flags").json() == {"items": []}

    assert client.post("/api/wipe").json()["removed"] == ["consent.json"]   # 다시 지워도 안전


# ---- 오류 처리 ---------------------------------------------------------------

def test_corrupt_store_gives_korean_error(client: TestClient, home: Path) -> None:
    (home / "transactions.json").write_text("{not json", encoding="utf-8")
    r = client.get("/api/data/summary")
    assert r.status_code == 500
    assert "저장 파일" in r.json()["detail"]


def test_model_retrains_after_data_change(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    v1 = client.get("/api/transactions").json()["model"]
    load_sample(client, "benefit", 2)
    v2 = client.get("/api/transactions").json()["model"]
    assert v1["train_count"] != v2["train_count"]
    decide(client, night(), "send")                            # 이력 추가 → 다시 학습
    v3 = client.get("/api/transactions").json()
    assert v3["model"]["train_count"] == max(30, math.ceil(v3["count"] * 0.75))


# ---- 리뷰 수정 확인(round 1) ------------------------------------------------

def test_external_wipe_does_not_revive_transactions(client: TestClient, home: Path) -> None:
    """서버가 켜진 채 밖에서(`python -m safepause wipe`처럼) 지워도 지운 거래가 되살아나지 않는다."""
    load_sample(client, "worker", 1, scenarios=True)
    set_consent(client, monitoring=True)
    assert client.get("/api/transactions", params={"limit": 1}).json()["count"] > 200
    Store(home).wipe()                                         # 다른 프로세스의 지우기와 같은 동작
    assert client.get("/api/data/summary").json()["count"] == 0
    set_consent(client, monitoring=True)                       # 동의를 다시 켬
    assert client.get("/api/transactions").json()["count"] == 0
    d = decide(client, {"to": "엄마", "amount": 50_000, "time": "15:00"}, "send")
    assert d["added_to_history"] is True
    saved = json.loads((home / TRANSACTIONS_FILE).read_text(encoding="utf-8"))
    assert len(saved) == 1 and saved[0]["id"] == d["pending"]["id"]


def test_external_file_change_is_picked_up(client: TestClient, home: Path) -> None:
    """저장 파일이 밖에서 바뀌면 메모리 결과를 버리고 다시 읽는다."""
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    before = client.get("/api/transactions").json()["count"]
    txns = Store(home).load_transactions()
    Store(home).save_transactions(txns[:40])
    assert client.get("/api/transactions").json()["count"] == 40 != before


def test_consent_revoked_while_decide_waits_blocks_analysis(home: Path) -> None:
    """decide가 잠금을 기다리는 사이 동의를 철회하면, 철회가 먼저 적용된다(분석·알림 기록 없음)."""
    app = create_app(home, now=lambda: NOW)
    c = TestClient(app, base_url=BASE, headers=HEADERS)
    load_sample(c, "worker", 1)
    set_consent(c, monitoring=True, helper_alerts=True)
    put_helpers(c, [{"name": "엄마", "min_level": "caution"}])
    state = app.state.safepause
    result: dict[str, Any] = {}

    def run() -> None:
        t = TestClient(app, base_url=BASE, headers=HEADERS)
        result["r"] = t.post("/api/safepause/decide", json={"pending": night(), "decision": "ask_helper"})

    with state.lock:
        worker = threading.Thread(target=run)
        worker.start()
        time.sleep(0.5)                                        # decide가 잠금 앞에서 기다리게 둔다
        consent = state.store.load_consent()
        consent.monitoring = consent.helper_alerts = False
        state.store.save_consent(consent)
        state.reset()
    worker.join(timeout=30)
    assert result["r"].status_code == 403
    assert c.get("/api/notices").json()["items"] == []
    assert c.get("/api/decisions").json()["items"] == []


def test_upload_size_checked_before_body_is_read(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    too_big = b"a" * (5 * 1024 * 1024 + 70 * 1024)
    r = client.post("/api/data/upload", content=too_big,
                    headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413 and "5MB" in r.json()["detail"]

    def chunks():                                              # 길이를 알 수 없는(chunked) 요청
        yield b"--x\r\n"

    r = client.post("/api/data/upload", content=chunks(),
                    headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411 and "크기" in r.json()["detail"]


def test_upload_non_string_mapping_is_korean_400(client: TestClient) -> None:
    set_consent(client, monitoring=True)
    content = "거래일시,금액,구분\n2026-09-01 10:00,1000,출금\n".encode("utf-8")
    r = client.post("/api/data/upload", files={"file": ("x.csv", content, "text/csv")},
                    data={"mapping": json.dumps({"datetime": "거래일시", "amount": "금액", "kind": 3})})
    assert r.status_code == 400
    assert "열 이름(글자)" in r.json()["detail"]


def test_helper_contact_is_masked(client: TestClient) -> None:
    saved = put_helpers(client, [
        {"name": "엄마", "contact": "010-1234-5678"},
        {"name": "센터", "contact": "center.kim@example.org"},
        {"name": "아빠", "contact": "01098765432"},
    ])
    assert [h["contact"] for h in saved] == ["010-****-5678", "ce***@example.org", "010-****-5432"]
    assert [(h["phone"], h["email"]) for h in saved] == [("010-1234-5678", ""), ("", "center.kim@example.org"),
                                                         ("01098765432", "")]
    assert [h["phone_masked"] or h["email_masked"] for h in saved] == [h["contact"] for h in saved]
    again = put_helpers(client, saved)                          # GET 모양 그대로 다시 저장해도 같음
    assert again == saved
    raw = (client.app.state.safepause.store.root / "helpers.json").read_text(encoding="utf-8")
    assert '"phone": "010-1234-5678"' in raw                   # 원본은 이 기기 저장 파일에만


def test_ask_helper_respects_scope_and_choice(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)                        # 자동 알림 꺼짐: 직접 묻기만
    put_helpers(client, [
        {"id": "mom", "name": "엄마"},
        {"id": "dad", "name": "아빠", "signal_scope": ["multi_line_telecom"]},
    ])
    r = check(client, night())
    cands = {c["id"]: c for c in r["ask_helper_preview"]["candidates"]}
    assert cands["mom"]["default"] is True and cands["dad"]["default"] is False
    # 고르지 않으면(helper_ids 없음) 범위 안의 엄마에게만
    d = decide(client, night(ts=r["pending"]["ts"]), "ask_helper")
    assert [n["helper_id"] for n in d["notify_plan"]["notices"]] == ["mom"]
    # 당사자가 아빠만 고르면 아빠에게만
    r2 = client.post("/api/safepause/decide", json={"pending": night(), "decision": "ask_helper",
                                                     "helper_ids": ["dad"]})
    assert r2.status_code == 200
    assert [n["helper_id"] for n in r2.json()["notify_plan"]["notices"]] == ["dad"]


def test_decide_result_uses_channel_words(client: TestClient) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    d = decide(client, {"to": "새로 연 전자상가", "amount": 800_000, "channel": "card", "time": "15:00"},
               "cancel")
    assert d["result_title"] == "결제하지 않았어요"
    assert d["result_lines"] == ["새로 연 전자상가에서 80만 원을 결제하지 않았어요."]
    if d["card"]:
        assert d["card"]["question"] == "이 돈을 정말 내는 것이 맞나요?"


def test_ts_note_when_practice_date_moves(client: TestClient) -> None:
    load_sample(client, "worker", 1)                           # 저장된 거래는 NOW(9/30)보다 앞 날짜
    set_consent(client, monitoring=True)
    r = check(client, {"to": "엄마", "amount": 50_000})        # '지금 시각'
    assert r["pending"]["ts"][:10] != NOW.date().isoformat()
    assert "저장된 거래 끝에 이어서 적어요" in r["ts_note"]
    r2 = check(client, {"to": "엄마", "amount": 50_000, "ts": NOW.isoformat()})
    assert r2["ts_note"] == ""


def test_wipe_partial_failure_is_korean_and_resets(client: TestClient, home: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    load_sample(client, "worker", 1)
    set_consent(client, monitoring=True)
    put_helpers(client, [{"name": "엄마"}])
    client.get("/api/transactions")
    assert client.app.state.safepause._snap is not None
    real_unlink = Store._unlink

    def flaky(p: Path) -> bool:
        if p.name == "helpers.json":
            raise PermissionError("다른 프로그램이 쓰는 중")
        return real_unlink(p)

    monkeypatch.setattr(Store, "_unlink", staticmethod(flaky))
    r = client.post("/api/wipe")
    assert r.status_code == 500
    assert "helpers.json" in r.json()["detail"] and "지우지 못했어요" in r.json()["detail"]
    assert not (home / TRANSACTIONS_FILE).exists()             # 거래 기록은 먼저 지워짐
    assert not (home / "consent.json").exists()                # 실패 뒤에도 나머지를 계속 지움
    assert (home / "helpers.json").exists()
    assert client.app.state.safepause._snap is None


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

@pytest.mark.parametrize("revoke", ["wipe", "consent_off"])
def test_upload_racing_wipe_or_revoke_is_not_saved(home: Path, monkeypatch: pytest.MonkeyPatch,
                                                   revoke: str) -> None:
    """파일을 읽는 사이 지우기·동의 끄기가 먼저 끝나면 올린 거래를 저장하지 않는다(S37 즉시 철회)."""
    import safepause.server.app as appmod

    app = create_app(home, now=lambda: NOW)
    c = TestClient(app, base_url=BASE, headers=HEADERS)
    set_consent(c, monitoring=True)
    started, release = threading.Event(), threading.Event()
    import safepause.api.service as svc
    real_load = svc._load_upload

    def slow_load(raw: bytes, mapping: Any) -> Any:   # 큰 파일을 읽는 동안을 흉내 낸다
        started.set()
        release.wait(10)
        return real_load(raw, mapping)

    monkeypatch.setattr(svc, "_load_upload", slow_load)
    result: dict[str, Any] = {}

    def upload() -> None:
        t = TestClient(app, base_url=BASE, headers=HEADERS)
        result["r"] = t.post("/api/data/upload",
                             files={"file": ("bank.csv", BANK_EXAMPLE.read_bytes(), "text/csv")})

    worker = threading.Thread(target=upload)
    worker.start()
    assert started.wait(10)
    if revoke == "wipe":
        assert c.post("/api/wipe").status_code == 200
    else:
        assert c.put("/api/consent", json={"monitoring": False}).status_code == 200
    release.set()
    worker.join(timeout=30)
    r = result["r"]
    assert r.status_code == 409 and "저장하지 않았어요" in r.json()["detail"]
    assert Store(home).load_transactions() == []
    assert not (home / TRANSACTIONS_FILE).exists()


def test_sample_racing_wipe_is_not_saved(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(home, now=lambda: NOW)
    c = TestClient(app, base_url=BASE, headers=HEADERS)
    started, release = threading.Event(), threading.Event()
    real = synth.make_dataset

    def slow(*args: Any, **kwargs: Any) -> Any:
        started.set()
        release.wait(10)
        return real(*args, **kwargs)

    monkeypatch.setattr(synth, "make_dataset", slow)
    result: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: result.update(
        r=TestClient(app, base_url=BASE, headers=HEADERS).post("/api/data/sample", json={})))
    worker.start()
    assert started.wait(10)
    assert c.post("/api/wipe").status_code == 200
    release.set()
    worker.join(timeout=30)
    assert result["r"].status_code == 409
    assert c.get("/api/data/summary").json()["count"] == 0


def test_upload_is_parsed_in_memory(client: TestClient, tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """1MB가 넘는 파일도 시스템 임시 폴더에 쓰지 않는다(메모리에서만 읽음)."""
    import tempfile

    spill = tmp_path / "system-temp"
    spill.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(spill))

    def no_spool(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("업로드가 임시 파일을 만들었어요")

    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", no_spool)
    monkeypatch.setattr(tempfile, "TemporaryFile", no_spool)
    set_consent(client, monitoring=True)
    rows = ["id,ts,amount,direction,channel,counterparty"]
    rows += [f"r{i},2026-0{1 + i % 8}-{1 + i % 28:02d}T12:00:00,{1000 + i},out,card,가게{i % 50}"
             for i in range(40_000)]
    content = ("\n".join(rows) + "\n").encode("utf-8")
    assert len(content) > 1024 * 1024
    r = client.post("/api/data/upload", files={"file": ("big.csv", content, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["report"]["loaded"] == 40_000
    assert list(spill.iterdir()) == []


def test_upload_limit_counts_bytes_not_headers(client: TestClient) -> None:
    """Content-Length를 속이거나 chunked를 함께 보내도 크기 한도가 지켜진다."""
    set_consent(client, monitoring=True)
    big = b"--x\r\n" + b"a" * (MAX_BODY + 10)
    r = client.post("/api/data/upload", content=big,
                    headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": "1000"})
    assert r.status_code == 413 and "5MB" in r.json()["detail"]
    r = client.post("/api/data/upload", content=b"--x\r\n",
                    headers={"Content-Type": "multipart/form-data; boundary=x", "Content-Length": "100",
                             "Transfer-Encoding": "chunked"})
    assert r.status_code == 411


@pytest.mark.parametrize("body,headers", [
    (b"not a form", {"Content-Type": "text/plain"}),
    (b"--x\r\nContent-Disposition: form-data; name=\"other\"\r\n\r\nabc\r\n--x--\r\n",
     {"Content-Type": "multipart/form-data; boundary=x"}),
])
def test_upload_without_file_field_is_korean_400(client: TestClient, body: bytes,
                                                 headers: dict[str, str]) -> None:
    set_consent(client, monitoring=True)
    r = client.post("/api/data/upload", content=body, headers=headers)
    assert r.status_code == 400 and "파일" in r.json()["detail"]


@pytest.mark.parametrize("content,loaded,skipped", [
    # 시간대가 있는 행과 없는 행이 섞인 표준 CSV(전에는 정렬에서 TypeError → 500)
    ("id,ts,amount,direction,channel\na,2026-09-01T10:00:00+09:00,1000,out,card\n"
     "b,2026-09-02T10:00:00,2000,out,card\nc,2026-09-03T01:00:00Z,3000,out,card\n", 3, 0),
    # 연도가 이상한 행(빈 날짜 대용값)은 건너뛰고 알린다
    ("거래일시,출금액,입금액,적요\n0001-01-01 00:00,1000,,a\n2026-01-01 10:00,1000,,b\n"
     "9999-12-31 23:59,1000,,c\n", 1, 2),
    ("id,ts,amount,direction,channel\na,0001-01-01T00:00:00,1000,out,card\n"
     "b,2026-09-02T10:00:00,2000,out,card\n", 1, 1),
])
def test_upload_odd_timestamps_do_not_break_later_screens(client: TestClient, content: str,
                                                          loaded: int, skipped: int) -> None:
    set_consent(client, monitoring=True)
    r = client.post("/api/data/upload", files={"file": ("x.csv", content.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    report = r.json()["report"]
    assert report["loaded"] == loaded and report["skipped"] == skipped
    if skipped:
        assert any("1900~2100년 밖" in w or "형식" in w for w in report["warnings"])
    for t in Store(client.app.state.safepause.store.root).load_transactions():
        assert t.ts.tzinfo is None                       # 계약: 시각은 모두 naive
    assert client.get("/api/transactions").status_code == 200
    assert client.get("/api/cards").status_code == 200
    assert client.post("/api/safepause/check", json=night()).status_code == 200


def test_check_rejects_out_of_range_ts(client: TestClient) -> None:
    load_sample(client)
    set_consent(client, monitoring=True)
    r = client.post("/api/safepause/check", json={**night(), "ts": "0001-01-01T00:00:00"})
    assert r.status_code == 422 and "시각" in r.json()["detail"]


def test_helper_contact_masks_common_phone_formats(client: TestClient) -> None:
    raw = ["(010)1234-5678", "+82-10-1234-5678", "+82 10 1234 5678", "010 - 1234 - 5678",
           "010–1234–5678", "엄마(010-1234-5678)", "02-123-4567"]
    saved = put_helpers(client, [{"name": f"사람{i}", "contact": c} for i, c in enumerate(raw)])
    got = [h["contact"] for h in saved]
    assert got[:5] == ["010-****-5678"] * 5
    assert got[5] == "010-****-5678"                             # v0.3: 옛 contact에서 번호만 꺼내 phone에
    assert saved[5]["phone"] == "010-1234-5678"
    assert got[6] == "02-****-4567"
    assert [h["contact"] for h in put_helpers(client, saved)] == got   # 다시 저장해도 그대로


def test_plain_turns_numpy_numbers_into_builtins() -> None:
    from safepause.server.app import _plain

    out = _plain({"a": np.float64(0.5), "b": np.int64(3), "c": [np.float32(1.5)], "d": np.float64("nan")})
    assert out == {"a": 0.5, "b": 3, "c": [1.5], "d": None}
    assert type(out["a"]) is float and type(out["b"]) is int and type(out["c"][0]) is float


def test_ask_helper_without_helpers_says_so(client: TestClient) -> None:
    """물어볼 조력자가 없으면 '물어봐요'라고 하지 않는다(쉬운 정보: 정확한 말)."""
    load_sample(client)
    set_consent(client, monitoring=True)
    d = decide(client, night(), "ask_helper")
    assert d["notices_recorded"] == 0 and d["asked_count"] == 0
    assert d["result_title"] == "물어볼 조력자가 없어요"
    assert d["result_lines"][0] == "김*호에게 30만 원을 아직 보내지 않았어요."
    assert "조력자 화면" in d["result_lines"][1]
    assert "물어봐요" not in " ".join([d["result_title"], *d["result_lines"]])
    record = client.get("/api/decisions").json()["items"][0]
    assert record["decision"] == "ask_helper" and record["asked"] == 0

    # 고른 조력자가 모두 돈을 받는 사람일 때도 같다
    put_helpers(client, [{"id": "a", "name": "김*호", "identifiers": ["김*호"]}])
    d2 = decide(client, night(), "ask_helper")
    assert d2["result_title"] == "물어볼 조력자가 없어요"
    assert d2["notify_plan"]["excluded_conflict"] == ["a"]


def test_ask_step_marks_auto_notified_helpers_and_notes_are_exact(client: TestClient) -> None:
    """자동 알림 대상은 미리 보기에 표시되고, 결과 안내에 이름이 두 번 나오지 않는다."""
    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"id": "mom", "name": "엄마"}, {"id": "dad", "name": "아빠"}])
    r = night_high(client)
    cands = {c["id"]: c for c in r["ask_helper_preview"]["candidates"]}
    assert cands["mom"]["auto"] is True and cands["dad"]["auto"] is True
    # 화면이 체크를 풀 수 없는 자동 알림 대상까지 보낸 경우: 두 사람 모두에게 물어봄
    both = client.post("/api/safepause/decide", json={
        "pending": r["pending"], "decision": "ask_helper", "helper_ids": ["mom", "dad"]}).json()
    assert both["notify_plan"]["note_to_person"] == "엄마, 아빠에게 물어봐요."
    # API로 엄마만 고른 경우: 아빠는 자동 알림. 안내에 엄마가 두 번 나오지 않는다
    r2 = check(client, night())
    only_mom = client.post("/api/safepause/decide", json={
        "pending": r2["pending"], "decision": "ask_helper", "helper_ids": ["mom"]}).json()
    assert only_mom["notify_plan"]["note_to_person"] == "엄마에게 물어봐요. 아빠에게도 알릴 수 있게 적어 두었어요."
    assert sorted(n["helper_id"] for n in only_mom["notify_plan"]["notices"]) == ["dad", "mom"]


def test_preview_note_is_present_tense_with_reason(client: TestClient) -> None:
    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"id": "a", "name": "엄마", "identifiers": ["김*호"]}])
    r = night_high(client)
    note = r["notify_plan_preview"]["note_to_person"]
    assert note == "엄마는 돈을 받는 사람이에요. 그래서 이번에는 엄마에게 알리지 않아요."
    assert "않았어요" not in note


def test_stopped_high_attempts_count_for_counseling(client: TestClient) -> None:
    """[변경 r2] '안 보낼래요'로 멈춘 고위험 시도도 30일 반복 고위험(S23)에 센다."""
    load_sample(client, "worker", 3)
    set_consent(client, monitoring=True, counseling_referral=True)
    pending = {"to": "박*수", "amount": 300_000, "channel": "transfer", "time": "02:00"}
    seen = []
    for _ in range(4):
        r = check(client, pending)
        assert r["assessment"]["level"] == "high"
        seen.append(r["notify_plan_preview"]["suggest_counseling"])
        d = decide(client, {**pending, "id": r["pending"]["id"], "ts": r["pending"]["ts"]}, "cancel")
        assert d["added_to_history"] is False
    assert seen == [False, False, True, True]
    # 결정 기록의 실제 시각이 30일보다 오래되면 세지 않는다
    home = client.app.state.safepause.store.root
    rows = json.loads((home / "decisions.json").read_text(encoding="utf-8"))
    for row in rows:
        row["at"] = "2026-08-01T12:00:00"
    (home / "decisions.json").write_text(json.dumps(rows), encoding="utf-8")
    assert check(client, pending)["notify_plan_preview"]["suggest_counseling"] is False


def test_decide_retry_with_same_id_records_once(client: TestClient) -> None:
    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마"}])
    r = night_high(client)
    body = {**night(), "id": r["pending"]["id"], "ts": r["pending"]["ts"]}
    before = client.get("/api/data/summary").json()["count"]
    first = decide(client, body, "send")
    again = decide(client, body, "send")                       # 같은 요청을 다시 보냄
    assert first["pending"]["id"] == again["pending"]["id"] == r["pending"]["id"]
    assert client.get("/api/data/summary").json()["count"] == before + 1
    decisions = [d for d in client.get("/api/decisions").json()["items"] if d["txn_id"] == body["id"]]
    notices = [n for n in client.get("/api/notices").json()["items"] if n["txn_id"] == body["id"]]
    assert len(decisions) == 1 and len(notices) == 1
    # 같은 시도를 '안 보낼래요'로 바꾸면 이력에서 빠지고 결정이 하나 더 적힌다
    decide(client, body, "cancel")
    assert client.get("/api/data/summary").json()["count"] == before


def test_decide_write_failure_is_korean_and_leaves_no_partial_records(
        client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """저장 파일을 쓸 수 없으면 한국어 안내(500 JSON). 거래를 먼저 쓰므로 결정·알림만 남지 않는다."""
    import os

    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마"}])
    r = night_high(client)
    body = {**night(), "id": r["pending"]["id"], "ts": r["pending"]["ts"]}
    n_dec = len(client.get("/api/decisions").json()["items"])
    n_not = len(client.get("/api/notices").json()["items"])
    real_replace = os.replace

    def locked(src: Any, dst: Any) -> None:
        if str(dst).endswith(TRANSACTIONS_FILE):
            raise PermissionError("백신이 잡고 있음")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", locked)
    res = client.post("/api/safepause/decide", json={"pending": body, "decision": "send"})
    assert res.status_code == 500 and "저장 파일을 쓸 수 없어요" in res.json()["detail"]
    assert len(client.get("/api/decisions").json()["items"]) == n_dec
    assert len(client.get("/api/notices").json()["items"]) == n_not
    assert not list(client.app.state.safepause.store.root.glob(".sp-*.tmp"))
    monkeypatch.setattr(os, "replace", real_replace)
    decide(client, body, "send")                                # 다시 하면 한 번만 적힌다
    assert len(client.get("/api/decisions").json()["items"]) == n_dec + 1
    assert len(client.get("/api/notices").json()["items"]) == n_not + 1


MAX_BODY = 5 * 1024 * 1024 + 64 * 1024


# ---- 리뷰 수정 확인(round 3) ------------------------------------------------

def _pend(chk: dict[str, Any], to: str, amount: int) -> dict[str, Any]:
    """화면이 decide에 보내는 모양(check가 준 id·시각)."""
    return {"id": chk["pending"]["id"], "to": to, "amount": amount, "channel": "transfer",
            "to_id": "", "ts": chk["pending"]["ts"]}


def _practice(client: TestClient) -> list[tuple[str, int, str]]:
    items = client.get("/api/transactions").json()["items"]
    return sorted((i["txn"]["counterparty"], i["txn"]["amount"], i["txn"]["id"]) for i in items if i["practice"])


def test_two_checks_get_different_live_ids(client: TestClient) -> None:
    """[변경 r3] 결정 전에 check가 두 번 있어도(탭 두 개) 서로 다른 연습 거래 id를 준다."""
    load_sample(client)
    set_consent(client, monitoring=True)
    a = check(client, {"to": "모르는사람", "amount": 400_000, "time": "02:00"})
    b = check(client, {"to": "동생", "amount": 10_000, "time": "15:00"})
    assert a["pending"]["id"] != b["pending"]["id"]


def test_other_tab_cancel_does_not_remove_sent_practice(client: TestClient) -> None:
    """[변경 r3] 탭 B가 보낸 거래를 탭 A의 '안 보낼래요'가 이력에서 지우지 않는다(리뷰 재현 1)."""
    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True, counseling_referral=True)
    put_helpers(client, [{"name": "엄마", "relation": "가족"}])
    a = check(client, {"to": "모르는사람", "amount": 400_000, "time": "02:00"})
    b = check(client, {"to": "동생", "amount": 10_000, "time": "15:00"})
    decide(client, _pend(b, "동생", 10_000), "send")
    decide(client, _pend(a, "모르는사람", 400_000), "cancel")
    assert _practice(client) == [("동생", 10_000, b["pending"]["id"])]


def test_other_tab_send_does_not_replace_high_risk_practice(client: TestClient) -> None:
    """[변경 r3] 탭 A의 고위험 거래를 탭 B의 거래가 바꿔 놓지 않고, 결정·알림도 따로 적힌다(리뷰 재현 2)."""
    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마", "relation": "가족"}])
    for _ in range(2):
        decide(client, night(), "send")
    a = check(client, night())
    assert a["assessment"]["level"] == "high"
    b = check(client, {"to": "동생", "amount": 10_000, "time": "15:00"})
    ra = decide(client, _pend(a, "김*호", 300_000), "send")
    assert ra["notices_recorded"] == 1
    rb = decide(client, _pend(b, "동생", 10_000), "send")
    assert rb["pending"]["id"] == b["pending"]["id"] != ra["pending"]["id"]
    practice = _practice(client)
    assert ("김*호", 300_000, a["pending"]["id"]) in practice and ("동생", 10_000, b["pending"]["id"]) in practice
    decisions = {(d["txn_id"], d["decision"], d["level"]) for d in client.get("/api/decisions").json()["items"]}
    assert (a["pending"]["id"], "send", "high") in decisions and (b["pending"]["id"], "send", "none") in decisions


def test_same_id_with_other_content_gets_new_id(client: TestClient) -> None:
    """[변경 r3] 같은 id·다른 내용의 decide는 기존 거래를 바꾸거나 지우지 않고 따로 기록한다."""
    load_sample(client)
    set_consent(client, monitoring=True, helper_alerts=True)
    put_helpers(client, [{"name": "엄마", "relation": "가족"}])
    a = check(client, {"to": "동생", "amount": 10_000, "time": "15:00"})
    first = decide(client, _pend(a, "동생", 10_000), "send")
    for _ in range(2):
        decide(client, night(), "send")
    forged = {**_pend(a, "김*호", 300_000), "ts": None, "time": "02:00"}   # 같은 id, 다른 거래(고위험)
    other = decide(client, forged, "cancel")
    assert other["pending"]["id"] not in (a["pending"]["id"],)
    assert other["assessment"]["level"] == "high"
    assert ("동생", 10_000, first["pending"]["id"]) in _practice(client)     # 먼저 보낸 거래는 그대로
    items = client.get("/api/decisions").json()["items"]
    assert {(d["txn_id"], d["decision"]) for d in items} >= {
        (first["pending"]["id"], "send"), (other["pending"]["id"], "cancel")}
    # 같은 내용 재시도는 지금처럼 한 번만
    decide(client, _pend(a, "동생", 10_000), "send")
    assert [d["txn_id"] for d in client.get("/api/decisions").json()["items"]].count(a["pending"]["id"]) == 1


def test_null_origin_is_rejected(client: TestClient) -> None:
    """[변경 r3] Origin이 있으면 같은 출처여야 한다. 'null' 출처로 지우기를 보내도 거절한다."""
    set_consent(client, monitoring=True)
    r = client.post("/api/wipe", headers={"origin": "null"})
    assert r.status_code == 403
    assert client.get("/api/consent").json()["monitoring"] is True        # 지워지지 않음
    assert client.post("/api/wipe", headers={"origin": BASE}).status_code == 200


@pytest.mark.parametrize("raw", ["010ㆍ1234ㆍ5678", "010·1234·5678", "010ㅡ1234ㅡ5678", "010/1234/5678",
                                 "010_1234_5678", "010~1234~5678", "010,1234,5678"])
def test_helper_contact_masks_any_separator(client: TestClient, raw: str) -> None:
    """[변경 r3] 구분 기호와 관계없이 숫자 7개 이상이면 가린다(010으로 시작하면 010-****-5678)."""
    saved = put_helpers(client, [{"name": "엄마", "contact": raw}])
    assert saved[0]["contact"] == "010-****-5678"
    assert saved[0]["phone"] == "01012345678"                     # v0.3: 문자 앱을 열 수 있게 숫자만 남긴 원본


def test_helper_contact_masking_keeps_other_text() -> None:
    from safepause.server.app import _mask_contact

    assert _mask_contact("010-1234-5678, 010-9876-5432") == "010-****-5678, 010-****-5432"
    assert _mask_contact("02-123-4567 내선 123") == "02-****-4567 내선 123"
    assert _mask_contact("010번 1234번 5678번") == "***번 ****번 5678번"   # 글자 사이에 끼운 번호도
    assert _mask_contact("ab***@x.kr 010-****-5678") == "ab***@x.kr 010-****-5678"


def test_one_month_file_does_not_raise_high_or_counseling_count(client: TestClient) -> None:
    """[변경 r3] 1개월치 정상 CSV: 파일 시작 효과로 고위험이 생기지 않고, S23 반복 고위험 건수도 늘지 않는다."""
    from test_loader import one_month_bank_csv

    from safepause.models import RiskAssessment
    from safepause.server import app as appmod

    set_consent(client, monitoring=True, helper_alerts=True, counseling_referral=True)
    put_helpers(client, [{"name": "엄마", "relation": "가족"}])
    r = client.post("/api/data/upload", files={"file": ("a.csv", one_month_bank_csv().encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    assert client.get("/api/transactions").json()["summary"]["high"] == 0
    state = client.app.state.safepause
    snap = state.snapshot()
    pending = snap.txns[-1]
    high = RiskAssessment(txn_id="x", level=RiskLevel.HIGH, rule_hits=[], anomaly_score=0.0, reasons=[])
    later = dataclasses.replace(pending, id="live-09999")
    assert appmod._recent_high(snap, later, high, state.settings, [], NOW) == 1   # 이번 건만
    res = check(client, {"to": "알뜰폰 요금", "amount": 20_000, "channel": "telecom_bill",
                         "line_id": "010-****-9999", "time": "14:00"})
    assert res["assessment"]["level"] != "high"
    assert res["notify_plan_preview"]["suggest_counseling"] is False
