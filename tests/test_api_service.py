"""v0.2 서비스 계층·라우터·모바일 브리지·세션 토큰 테스트.

- 라우터(dispatch, 안드로이드 앱이 씀)와 FastAPI(PC)가 같은 요청에 같은 응답을 주는지
- 브리지(Pyodide 진입점) JSON 입출력, 가벼운 import(numpy 없이 기본 기능)
- 세션 토큰·본문 한도, 저장 경쟁(store.transaction), 파일 형식 검증, 새 기능(쪽 나눔·자동완성·내보내기)
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from safepause.api import bridge, constants
from safepause.api.router import ROUTES, dispatch
from safepause.api.service import LIVE_ID_RE, Service, ServiceError, _live_number
from safepause.models import Helper, Transaction
from safepause.server.app import create_app
from safepause.store import DECISIONS_FILE, HELPERS_FILE, TRANSACTIONS_FILE, Store, StoreError

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
NOW = datetime(2026, 9, 30, 12, 0, 0)
BANK_EXAMPLE = ROOT / "sample_data" / "bank_export_example.csv"


# ---- 상수가 원래 모듈과 같은지 --------------------------------------------------------

def test_light_constants_match_original_modules() -> None:
    from safepause.data import synth
    from safepause.detect import anomaly
    assert (constants.MIN_YEAR, constants.MAX_YEAR) == (synth.MIN_YEAR, synth.MAX_YEAR)
    assert constants.NORMAL_LABEL == synth.NORMAL_LABEL
    assert constants.SCENARIO_WINDOW_DAYS == synth.SCENARIO_WINDOW_DAYS
    assert constants.PERSONA_KEYS == tuple(synth.PERSONAS)
    assert constants.MIN_TRAIN == anomaly.MIN_TRAIN


def test_bridge_import_is_light() -> None:
    # 앱은 AI 패키지를 싣기 전에 동의·조력자 화면을 먼저 쓴다: bridge import가 numpy·sklearn을 싣지 않아야 한다
    code = ("import sys; import safepause.api.bridge as b; "
            "print(int('numpy' in sys.modules), int('sklearn' in sys.modules), int('fastapi' in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=True)
    assert out.stdout.split() == ["0", "0", "0"]


# ---- 라우터 = FastAPI -------------------------------------------------------------

def _scenario(call: Any) -> list[tuple[int, Any]]:
    """같은 요청 순서를 PC(FastAPI)와 앱(router)에 보내 응답을 모은다."""
    steps = [
        ("GET", "/api/health", None),
        ("GET", "/api/consent", None),
        ("GET", "/api/transactions", None),                          # 동의 없음 → 403
        ("PUT", "/api/consent", {"monitoring": True, "helper_alerts": True}),
        ("PUT", "/api/consent", {"monitoring": "yes"}),              # 422
        ("POST", "/api/data/sample", {"persona": "worker", "seed": 3, "scenarios": True}),
        ("PUT", "/api/helpers", [{"name": "엄마", "relation": "가족", "contact": "010-1234-5678"}]),
        ("GET", "/api/transactions?level=high&limit=5&offset=1", None),
        ("GET", "/api/transactions?level=bad", None),                # 422
        ("GET", "/api/payees", None),
        ("POST", "/api/safepause/check", {"to": "김*호", "amount": 300000, "channel": "transfer", "time": "02:00"}),
        ("POST", "/api/safepause/check", {"to": "", "amount": -1}),  # 422
        ("GET", "/api/cards?limit=3", None),
        ("GET", "/api/decisions", None),
        ("GET", "/api/notices", None),
        ("GET", "/api/export/validation", None),
        ("POST", "/api/wipe", None),
        ("GET", "/api/data/summary", None),
    ]
    return [call(m, p, b) for m, p, b in steps]


def _normalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items() if k not in ("elapsed_sec", "created_at")}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj


def test_router_matches_fastapi(tmp_path: Path) -> None:
    app = create_app(tmp_path / "pc", now=lambda: NOW)
    client = TestClient(app, base_url=BASE, headers={"X-SafePause": "1"})

    def pc(m: str, p: str, b: Any) -> tuple[int, Any]:
        r = client.request(m, p, json=b) if b is not None else client.request(m, p)
        return r.status_code, r.json()

    svc = Service(tmp_path / "app", now=lambda: NOW)

    def mobile(m: str, p: str, b: Any) -> tuple[int, Any]:
        status, body = dispatch(svc, m, p, b)
        return status, json.loads(json.dumps(body, ensure_ascii=False))

    got_pc, got_app = _scenario(pc), _scenario(mobile)
    assert [s for s, _ in got_pc] == [s for s, _ in got_app]
    for (s1, b1), (s2, b2) in zip(got_pc, got_app):
        assert _normalize(b1) == _normalize(b2), (s1, b1, b2)
    statuses = [s for s, _ in got_pc]
    assert statuses[2] == 403 and statuses[4] == 422 and statuses[8] == 422 and statuses[11] == 422


def test_router_unknown_and_wrong_method(tmp_path: Path) -> None:
    svc = Service(tmp_path)
    assert dispatch(svc, "GET", "/api/nope")[0] == 404
    assert dispatch(svc, "DELETE", "/api/consent")[0] == 405
    assert all(p.startswith("/api/") for (_, p) in ROUTES)


def test_router_catches_unexpected_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    svc = Service(tmp_path)
    monkeypatch.setattr(svc, "get_consent", lambda: 1 / 0)
    status, body = dispatch(svc, "GET", "/api/consent")
    assert status == 500 and body["detail"] == "처리하다 문제가 생겼어요. 다시 해 주세요."


# ---- 브리지(Pyodide 진입점) ---------------------------------------------------------

def test_bridge_handle_roundtrip(tmp_path: Path) -> None:
    bridge.init(str(tmp_path / "store"))
    r = json.loads(bridge.handle("GET", "/api/consent", "null", None))
    assert r["status"] == 200 and r["body"]["monitoring"] is False
    r = json.loads(bridge.handle("PUT", "/api/consent", json.dumps({"monitoring": True}), None))
    assert r["status"] == 200 and r["body"]["monitoring"] is True
    raw = BANK_EXAMPLE.read_bytes()
    r = json.loads(bridge.handle("POST", "/api/data/upload", json.dumps({"mapping": ""}), raw))
    assert r["status"] == 200 and r["body"]["report"]["loaded"] > 0
    r = json.loads(bridge.handle("POST", "/api/consent", "{bad json", None))
    assert r["status"] == 400
    bridge.warm()


def test_bridge_not_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_service", None)
    assert json.loads(bridge.handle("GET", "/api/health"))["status"] == 503


# ---- 세션 토큰·본문 한도(PC 서버) ------------------------------------------------------

def test_session_token_required_for_all_api(tmp_path: Path) -> None:
    app = create_app(tmp_path, now=lambda: NOW, token="t0ken-ABCDEFGHIJKLMNOP")
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/api/consent").status_code == 403                                  # 읽기도 막힘
        assert c.get("/api/consent", headers={"X-SafePause": "1"}).status_code == 403     # 고정값 "1"은 안 됨
        assert c.get("/api/consent", headers={"X-SafePause": "wrong"}).status_code == 403
        ok = {"X-SafePause": "t0ken-ABCDEFGHIJKLMNOP"}
        assert c.get("/api/consent", headers=ok).status_code == 200
        assert c.put("/api/consent", json={"monitoring": True}, headers=ok).status_code == 200
        assert c.get("/").status_code == 200 and c.get("/js/main.js").status_code == 200   # 화면 파일은 토큰 없이


def test_json_body_limit_and_chunked(tmp_path: Path) -> None:
    app = create_app(tmp_path, now=lambda: NOW)
    with TestClient(app, base_url=BASE, headers={"X-SafePause": "1"}) as c:
        big = [{"name": "가" * 30, "relation": "x" * 40, "identifiers": ["1" * 60] * 20}] * 60
        r = c.put("/api/helpers", json=big)
        assert r.status_code == 413
        r = c.put("/api/consent", content=b'{"monitoring": true}',
                  headers={"Transfer-Encoding": "chunked", "Content-Type": "application/json"})
        assert r.status_code == 411


def test_global_error_handler_is_korean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app(tmp_path, now=lambda: NOW)
    monkeypatch.setattr(app.state.safepause, "get_helpers", lambda: 1 / 0)
    with TestClient(app, base_url=BASE, headers={"X-SafePause": "1"}, raise_server_exceptions=False) as c:
        r = c.get("/api/helpers")
    assert r.status_code == 500 and r.json()["detail"] == "처리하다 문제가 생겼어요. 다시 해 주세요."


# ---- 저장 경쟁·파일 형식 ---------------------------------------------------------------

def test_store_transaction_is_reentrant_and_exclusive(tmp_path: Path) -> None:
    store = Store(tmp_path)
    with store.transaction():
        store.save_consent(store.load_consent())
        with store.transaction():
            store.load_helpers()
    assert (tmp_path / "consent.json").exists()


def test_broken_record_files_give_korean_error(tmp_path: Path) -> None:
    store = Store(tmp_path)
    (tmp_path / DECISIONS_FILE).write_text('["x"]', encoding="utf-8")
    with pytest.raises(StoreError):
        store.load_decisions()


def test_timezone_ts_and_active_string(tmp_path: Path) -> None:
    t = Transaction.from_dict({"id": "a", "ts": "2026-09-01T13:05:00+09:00", "amount": 1000,
                               "direction": "out", "channel": "card"})
    assert t.ts.tzinfo is None
    assert Helper.from_dict({"id": "h1", "name": "엄마", "active": "false"}).active is False
    with pytest.raises(ValueError):
        Transaction.from_dict({"id": "b", "ts": "2026-09-01T13:05:00", "amount": -5, "direction": "out", "channel": "card"})


def test_live_id_rule_is_shared() -> None:
    assert _live_number("live-00012") == 12
    assert _live_number("live-999999999") == 999999999
    assert _live_number("live-1000000000") == 0           # 10자리: 연습 거래 id가 아님(발급·판정 같은 규칙)
    assert _live_number("live-" + "9" * 5000) == 0         # 아주 긴 id도 500 없이 0
    assert LIVE_ID_RE.fullmatch("live-00001")


def test_uploaded_live_ids_are_renamed(tmp_path: Path) -> None:
    svc = Service(tmp_path, now=lambda: NOW)
    svc.store.save_consent(svc.store.load_consent().__class__(monitoring=True))
    csv = ("id,ts,amount,direction,channel,counterparty\n"
           "live-00001,2026-09-01T10:00:00,5000,out,card,가게\n"
           "x2,2026-09-02T10:00:00,7000,out,card,가게\n").encode("utf-8")
    out = svc.upload(csv)
    ids = [t.id for t in svc.store.load_transactions()]
    assert "live-00001" not in ids and "csv-live-00001" in ids
    assert any("이름을 바꿔 저장" in w for w in out["report"]["warnings"])


def test_mapping_too_long_or_nested(tmp_path: Path) -> None:
    svc = Service(tmp_path, now=lambda: NOW)
    svc.store.save_consent(svc.store.load_consent().__class__(monitoring=True))
    raw = BANK_EXAMPLE.read_bytes()
    with pytest.raises(ServiceError) as e1:
        svc.upload(raw, "[" * 100000)
    assert e1.value.status == 400 and "너무 길어요" in e1.value.detail
    with pytest.raises(ServiceError) as e2:
        svc.upload(raw, "[" * 2000)
    assert e2.value.status == 400


# ---- 새 기능 -------------------------------------------------------------------------

@pytest.fixture
def ready(tmp_path: Path) -> Service:
    from safepause.api.schemas import ConsentIn, SampleIn
    svc = Service(tmp_path, now=lambda: NOW)
    svc.put_consent(ConsentIn(monitoring=True))
    svc.data_sample(SampleIn(persona="worker", seed=2, scenarios=True))
    return svc


def test_transactions_pagination(ready: Service) -> None:
    whole = ready.transactions("all", 0, 0)
    page1 = ready.transactions("all", 50, 0)
    page2 = ready.transactions("all", 50, 50)
    assert len(page1["items"]) == 50 and page1["matched"] == whole["matched"]
    assert [i["txn"]["id"] for i in page1["items"] + page2["items"]] == [i["txn"]["id"] for i in whole["items"][:100]]
    assert ready.transactions("all", 10, whole["matched"])["items"] == []


def test_payees_are_recent_transfer_names(ready: Service) -> None:
    names = ready.payees()["items"]
    assert names and len(names) == len(set(names)) and len(names) <= 30


def test_export_validation_has_no_personal_details(ready: Service) -> None:
    out = ready.export_validation()
    text = out["text"]
    payload = json.loads(text)
    assert payload["kind"] == "safepause-validation-summary"
    assert payload["data"]["n_transactions"] > 0
    for t in ready.store.load_transactions()[:200]:
        if t.counterparty:
            assert t.counterparty not in text
        if t.counterparty_id:
            assert t.counterparty_id not in text
    assert "2026-0" not in text.replace(payload["created_at"], "")   # 거래 날짜 없음(만든 시각만)


def test_export_results_csv(ready: Service) -> None:
    out = ready.export_results_csv()
    lines = out["text"].lstrip("﻿").splitlines()
    assert lines[0].startswith("거래일시,") and len(lines) == out["rows"] + 1
    assert "나만 보고" in out["note"]


def test_analysis_after_revoke_is_refused(ready: Service) -> None:
    from safepause.api.schemas import ConsentIn
    ready.put_consent(ConsentIn(monitoring=False))
    with pytest.raises(ServiceError) as e:
        ready.transactions()
    assert e.value.status == 403
