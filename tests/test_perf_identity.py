"""속도·메모리 개선의 동일성 시험(2026-10-03).

- 저장 파일: 목록을 한 조각씩 이어 써도(store._json_list_chunks) json.dumps(indent=2)와 바이트까지 같고,
  거래 수천 건을 저장할 때 원소 dict 목록·파일 글 전체를 한꺼번에 들지 않는다(메모리 최대치).
- 파일 올리기: 응답 키·순서는 그대로이고, 읽은 거래 목록은 분석 전에 놓는다.
- 앱 엔진: 준비 단계 겹치기·쉬는 동안 미리 불러오기(bridge.warm_more)가 단계 순서·문구와 요청 우선을 바꾸지 않는다.
"""
from __future__ import annotations

import json
import random
import re
import sys
import tracemalloc
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import safepause.store as store_mod
from safepause.api import bridge
from safepause.api.service import Service
from safepause.models import Channel, Consent, Direction, Transaction
from safepause.store import TRANSACTIONS_FILE, Store

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "safepause" / "web" / "engine" / "worker.mjs"


def _txns(n: int) -> list[Transaction]:
    start = datetime(2026, 1, 1, 9, 0, 0)
    names = ["엄마", "편의점 \"24\"", "가게\\뒤", "줄\n바꿈", "", "통신사\t요금"]
    out = []
    for i in range(n):
        out.append(Transaction(
            id=f"t{i:05d}", ts=start + timedelta(minutes=37 * i), amount=1_000 + (i * 7919) % 900_000,
            direction=Direction.OUT if i % 5 else Direction.IN,
            channel=(Channel.TRANSFER, Channel.CARD, Channel.MICROPAY, Channel.TELECOM_BILL)[i % 4],
            counterparty=names[i % len(names)], counterparty_id=f"900-0101-{i % 97:06d}" if i % 3 else "",
            line_id="010-****-1234" if i % 4 >= 2 else "", memo="메모" if i % 2 else "",
            label=None if i % 7 else "normal",
        ))
    return out


def _value(rnd: random.Random, depth: int = 0):
    kind = rnd.randrange(9 if depth < 3 else 6)
    if kind == 0:
        return None
    if kind == 1:
        return rnd.choice([True, False])
    if kind == 2:
        return rnd.randrange(-10**12, 10**12)
    if kind == 3:
        return rnd.choice([0.1, 1e300, -2.5, float("nan"), float("inf"), 3.0])
    if kind == 4:
        return "".join(rnd.choice('ab가힣"\\\n\t\r  \x00\x1f/<>') for _ in range(rnd.randrange(8)))
    if kind == 5:
        return ""
    if kind == 6:
        return [_value(rnd, depth + 1) for _ in range(rnd.randrange(4))]
    if kind == 7:
        return {str(_value(rnd, depth + 1)): _value(rnd, depth + 1) for _ in range(rnd.randrange(4))}
    return {}


# ---- 저장 파일: 바이트까지 같음 ------------------------------------------------------------

@pytest.mark.parametrize("chunk", [1, 2, 3, 256])
def test_list_chunks_match_json_dumps_bytes(monkeypatch: pytest.MonkeyPatch, chunk: int) -> None:
    monkeypatch.setattr(store_mod, "_ROWS_PER_CHUNK", chunk)
    rnd = random.Random(chunk)
    for _ in range(400):
        obj = [_value(rnd) for _ in range(rnd.randrange(12))]
        want = json.dumps(obj, ensure_ascii=False, indent=2)
        assert "".join(store_mod._json_list_chunks(obj)) == want
        assert "".join(store_mod._json_list_chunks(iter(obj))) == want   # 만들면서 쓰는 목록도 같다


@pytest.mark.parametrize("n", [0, 1, 255, 256, 257, 600])
def test_save_transactions_bytes_unchanged(tmp_path: Path, n: int) -> None:
    txns = _txns(n)
    Store(tmp_path).save_transactions(txns)
    want = json.dumps([t.to_dict() for t in txns], ensure_ascii=False, indent=2).encode("utf-8")
    assert (tmp_path / TRANSACTIONS_FILE).read_bytes() == want
    assert [t.to_dict() for t in Store(tmp_path).load_transactions()] == [t.to_dict() for t in txns]


def test_other_store_files_bytes_unchanged(tmp_path: Path) -> None:
    s = Store(tmp_path)
    flags = [{"txn_id": f"t{i}", "created_at": "2026-10-03T10:00:00"} for i in range(300)]
    s.save_flags(flags)
    s.save_notices([])
    assert (tmp_path / "flags.json").read_bytes() == json.dumps(flags, ensure_ascii=False, indent=2).encode("utf-8")
    assert (tmp_path / "notices.json").read_bytes() == b"[]"


def test_save_transactions_does_not_hold_whole_file_in_memory(tmp_path: Path) -> None:
    """거래 5,000건 저장: 한 번에 json.dumps 하던 때보다 메모리 최대치가 훨씬 작다(앱 안 엔진의 WASM 메모리 최대치)."""
    txns = _txns(5000)
    s = Store(tmp_path)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        json.dumps([t.to_dict() for t in txns], ensure_ascii=False, indent=2)
        whole = tracemalloc.get_traced_memory()[1] - base
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        s.save_transactions(txns)
        streamed = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert streamed * 4 < whole, (streamed, whole)


def test_failed_streamed_write_keeps_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """앞 조각을 쓴 뒤 JSON으로 바꿀 수 없는 값이 나와도 예전 파일이 그대로이고 임시 파일이 남지 않는다."""
    monkeypatch.setattr(store_mod, "_ROWS_PER_CHUNK", 2)
    s = Store(tmp_path)
    s.save_transactions(_txns(3))
    before = (tmp_path / TRANSACTIONS_FILE).read_bytes()

    def rows():
        yield from (t.to_dict() for t in _txns(5))
        yield {"bad": object()}

    with pytest.raises(TypeError):
        s._write_rows(TRANSACTIONS_FILE, rows())
    assert (tmp_path / TRANSACTIONS_FILE).read_bytes() == before
    assert not list(tmp_path.glob(".sp-*.tmp"))


# ---- 파일 올리기: 응답 모양 그대로 ----------------------------------------------------------

def test_upload_response_keys_and_order_unchanged(tmp_path: Path) -> None:
    svc = Service(tmp_path / "store")
    svc.store.save_consent(Consent(monitoring=True))
    rows = ["id,ts,amount,direction,channel,counterparty"]
    rows += [f"t{i},2026-0{1 + i // 40}-{1 + i % 28:02d}T1{i % 10}:00:00,{1000 + i * 37},out,card,가게{i % 9}"
             for i in range(120)]
    out = svc.upload("\n".join(rows).encode("utf-8"))
    assert list(out) == ["source", "mode", "added", "duplicates", "report", "summary", "levels", "ai_only"]
    assert out["summary"]["count"] == 120 and out["added"] == 120
    assert sum(out["levels"].values()) == 120   # 분석은 저장 파일에서 다시 읽은 거래로 한다


# ---- 앱 엔진: 쉬는 동안 미리 불러오기 ---------------------------------------------------------

def test_warm_more_imports_idle_modules_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_idle_next", 0)
    seen: list[str] = []
    real = bridge.importlib.import_module
    monkeypatch.setattr(bridge.importlib, "import_module", lambda name: (seen.append(name), real(name))[1])
    results = [bridge.warm_more() for _ in range(len(bridge.IDLE_MODULES) + 2)]
    assert seen == list(bridge.IDLE_MODULES)
    assert results == [True] * (len(bridge.IDLE_MODULES) - 1) + [False, False, False]
    for name in bridge.IDLE_MODULES:
        assert name in sys.modules
    # 첫 학습이 부르는 모듈(IsolationForest)과 올리기·연습 거래가 부르는 모듈이 모두 들어 있다
    assert "sklearn.ensemble" in bridge.IDLE_MODULES and "safepause.data.loader" in bridge.IDLE_MODULES


def test_warm_more_failure_raises_and_moves_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge, "_idle_next", 0)
    monkeypatch.setattr(bridge, "IDLE_MODULES", ("safepause_no_such_module_xyz", "json"))
    with pytest.raises(ImportError):
        bridge.warm_more()          # 워커는 예외면 미리 불러오기를 그만둔다(분석 때 같은 오류가 그대로 난다)
    assert bridge.warm_more() is False


def test_worker_boot_overlap_keeps_stage_contract() -> None:
    w = WORKER.read_text(encoding="utf-8")
    # 단계 순서·문구 그대로(loading → basic → basic → full, 시간은 'NNNms')
    order = [m.group(1) for m in re.finditer(r'stage\("(loading|basic|full)", "([^"]+)"', w)]
    assert order == ["loading", "basic", "basic", "full"]
    for text in ("AI 엔진을 준비하고 있어요", "기본 기능을 쓸 수 있어요", "AI 분석 준비 중이에요", "AI 분석까지 준비됐어요"):
        assert text in w
    assert w.count("`${Math.round(performance.now() - t0)}ms`") == 2
    assert w.count("fullStdLib: false })") == 1
    # zip은 파이썬을 켜기 전에 받기 시작하고 pydantic은 파이썬을 켜는 동안 싣는다(loadPyodide packages).
    # AI 패키지는 기본 준비(모듈 불러오기) 전에 내려받기 시작한다
    assert w.index("../py/safepause.zip") < w.index("await loadPyodide(")
    assert 'packages: ["pydantic"], fullStdLib: false })' in w
    load_ai = w.index('py.loadPackage(["numpy", "scipy", "scikit-learn"]')
    assert w.index("await syncfs(true);") < load_ai < w.index('py.pyimport("safepause.api.bridge")')
    # 실패 처리: 미리 시작한 약속의 거부는 기다리는 곳(fullReady·booted)에서 그대로 난다
    assert "zipBytes.catch(() => {});" in w and "aiPackages.catch(() => {});" in w
    assert "await aiPackages;" in w and "py.unpackArchive(await zipBytes" in w
    assert 'stage("error", "AI 분석 부분을 켜지 못했어요", String(e && e.message || e), false)' in w


def test_worker_idle_warm_yields_to_requests() -> None:
    w = WORKER.read_text(encoding="utf-8")
    body = w[w.index("function scheduleIdleWarm()"):w.index("async function pump()")]
    assert "if (!idleWarm || running || queue.length) return;" in body     # 줄에 요청이 있거나 처리 중이면 하지 않음
    assert "bridge.warm_more()" in body and "idleWarm = false;" in body       # 실패하면 그만둠
    pump = w[w.index("async function pump()"):w.index("function enqueue(")]
    assert "if (!msg) { scheduleIdleWarm(); return; }" in pump              # 줄이 빈 뒤에만 다음 조각
    full = w[w.index("fullReady = (async () => {"):w.index("const booted = boot()")]
    assert full.index('stage("full"') < full.index("idleWarm = true;")       # full 뒤에만 시작
