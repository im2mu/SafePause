"""로컬 JSON 저장소 테스트."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from safepause.models import (
    Channel,
    Consent,
    Decision,
    Direction,
    Helper,
    HelperNotice,
    RiskLevel,
    Transaction,
)
from safepause.store import (
    LOCK_FILE,
    STORE_FILES,
    TRANSACTIONS_FILE,
    WIPE_ORDER,
    FileLock,
    Store,
    StoreError,
    WipeIncomplete,
)


def _txn(i: int = 1) -> Transaction:
    return Transaction(
        id=f"t{i:05d}", ts=datetime(2026, 3, 2, 9, 30, i % 60), amount=12_000 + i,
        direction=Direction.OUT, channel=Channel.TRANSFER, counterparty="엄마",
        counterparty_id="900-0101-100001", memo="모바일이체", label="normal",
    )


def _helper() -> Helper:
    return Helper(id="h1", name="엄마", relation="가족", contact="010-****-0000",
                  identifiers=["900-0101-100001", "엄마"], min_level=RiskLevel.HIGH,
                  signal_scope=["night_repeat_transfer"], active=True)


def test_empty_store_returns_defaults(tmp_path) -> None:
    s = Store(tmp_path / "home")
    assert (tmp_path / "home").is_dir()
    assert s.load_consent() == Consent()
    assert s.load_consent().monitoring is False
    assert s.load_helpers() == []
    assert s.load_transactions() == []
    assert s.load_decisions() == []
    assert s.load_notices() == []


def test_consent_roundtrip(tmp_path) -> None:
    s = Store(tmp_path)
    c = Consent(monitoring=True, helper_alerts=True, counseling_referral=False,
                given_by="legal_representative", updated_at="2026-09-30T10:00:00")
    s.save_consent(c)
    assert Store(tmp_path).load_consent() == c


def test_consent_string_false_is_not_consent(tmp_path) -> None:
    (tmp_path / "consent.json").write_text(
        '{"monitoring": "false", "helper_alerts": "true", "counseling_referral": 0}', encoding="utf-8")
    c = Store(tmp_path).load_consent()
    assert c.monitoring is False and c.helper_alerts is True and c.counseling_referral is False


def test_helpers_roundtrip(tmp_path) -> None:
    s = Store(tmp_path)
    helpers = [_helper(), Helper(id="h2", name="센터 담당자", relation="지역발달장애인지원센터 전담 인력",
                                 min_level=RiskLevel.CAUTION, active=False)]
    s.save_helpers(helpers)
    back = s.load_helpers()
    assert [h.to_dict() for h in back] == [h.to_dict() for h in helpers]
    assert back[1].min_level is RiskLevel.CAUTION


def test_transactions_roundtrip_and_overwrite(tmp_path) -> None:
    s = Store(tmp_path)
    txns = [_txn(i) for i in range(1, 6)]
    s.save_transactions(txns)
    assert [t.to_dict() for t in s.load_transactions()] == [t.to_dict() for t in txns]
    s.save_transactions(txns[:2])  # 전체 교체
    assert len(s.load_transactions()) == 2


def test_decisions_append_and_load(tmp_path) -> None:
    s = Store(tmp_path)
    s.append_decision("t00001", Decision.CANCEL, RiskLevel.HIGH, "2026-09-30T10:00:00")
    s.append_decision("t00002", "send", "caution", "2026-09-30T10:05:00")  # 문자열 값도 허용
    rows = s.load_decisions()
    assert rows == [
        {"txn_id": "t00001", "decision": "cancel", "level": "high", "at": "2026-09-30T10:00:00"},
        {"txn_id": "t00002", "decision": "send", "level": "caution", "at": "2026-09-30T10:05:00"},
    ]
    with pytest.raises(ValueError):
        s.append_decision("t3", "block", "high", "x")  # 차단 같은 결정은 없다


def test_notices_append_and_load(tmp_path) -> None:
    s = Store(tmp_path)
    n = HelperNotice(helper_id="h1", helper_name="엄마", txn_id="t00001", level=RiskLevel.HIGH,
                     message="[SafePause] 확인이 필요한 신호가 있어요.", created_at="2026-09-30T10:00:00")
    s.append_notice(n)
    s.append_notice(n)
    rows = s.load_notices()
    assert len(rows) == 2
    assert rows[0] == n.to_dict()
    assert rows[0]["level"] == "high"


def test_files_are_utf8_json_without_escapes(tmp_path) -> None:
    s = Store(tmp_path)
    s.save_helpers([_helper()])
    raw = (tmp_path / "helpers.json").read_bytes()
    assert "엄마".encode("utf-8") in raw           # 한글을 그대로 저장
    assert json.loads(raw.decode("utf-8"))[0]["name"] == "엄마"


def test_atomic_write_leaves_no_temp_files(tmp_path) -> None:
    s = Store(tmp_path)
    for i in range(5):
        s.save_transactions([_txn(i)])
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted([LOCK_FILE, "transactions.json"])      # 잠금 파일은 빈 파일
    assert (tmp_path / LOCK_FILE).stat().st_size == 0


def test_failed_write_keeps_previous_file(tmp_path) -> None:
    s = Store(tmp_path)
    s.save_transactions([_txn(1)])

    class Boom:  # JSON으로 바꿀 수 없는 값
        pass

    with pytest.raises(TypeError):
        s._write("transactions.json", [Boom()])
    assert len(s.load_transactions()) == 1
    assert not list(tmp_path.glob(".sp-*.tmp"))


def test_wipe_removes_everything(tmp_path) -> None:
    s = Store(tmp_path)
    s.save_consent(Consent(monitoring=True))
    s.save_helpers([_helper()])
    s.save_transactions([_txn()])
    s.append_decision("t00001", Decision.SEND, RiskLevel.NONE, "2026-09-30T10:00:00")
    s.append_notice(HelperNotice("h1", "엄마", "t00001", RiskLevel.HIGH, "m", "2026-09-30T10:00:00"))
    (tmp_path / ".sp-leftover.tmp").write_text("x", encoding="utf-8")
    other = tmp_path / "user_file.txt"  # 저장소가 만들지 않은 파일은 건드리지 않는다
    other.write_text("keep", encoding="utf-8")

    removed = s.wipe()
    assert set(STORE_FILES) <= set(removed)
    assert ".sp-leftover.tmp" in removed
    assert other.exists()
    assert s.load_consent() == Consent()
    assert s.load_helpers() == [] and s.load_transactions() == []
    assert s.load_decisions() == [] and s.load_notices() == []
    assert s.wipe() == []  # 두 번 지워도 오류 없음


def test_store_works_after_root_deleted(tmp_path) -> None:
    root = tmp_path / "gone"
    s = Store(root)
    s.save_consent(Consent(monitoring=True))
    for p in root.iterdir():
        p.unlink()
    root.rmdir()
    assert s.load_consent() == Consent()
    s.save_consent(Consent(helper_alerts=True))
    assert s.load_consent().helper_alerts is True


@pytest.mark.parametrize("name,content", [
    ("consent.json", "{not json"),
    ("consent.json", "[1, 2]"),
    ("transactions.json", '{"a": 1}'),
    ("transactions.json", '[{"id": "x"}]'),
    ("helpers.json", '[{"name": "no id"}]'),
])
def test_corrupt_files_raise_store_error(tmp_path, name: str, content: str) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")
    s = Store(tmp_path)
    loader = {"consent.json": s.load_consent, "transactions.json": s.load_transactions,
              "helpers.json": s.load_helpers}[name]
    with pytest.raises(StoreError, match="저장 파일"):
        loader()


def test_empty_file_is_treated_as_missing(tmp_path) -> None:
    (tmp_path / "decisions.json").write_text("", encoding="utf-8")
    assert Store(tmp_path).load_decisions() == []


def test_concurrent_appends_are_not_lost(tmp_path) -> None:
    stores = [Store(tmp_path), Store(tmp_path)]  # 같은 폴더의 두 인스턴스

    def work(k: int) -> None:
        for i in range(20):
            stores[k % 2].append_decision(f"t{k}-{i}", Decision.SEND, RiskLevel.CAUTION, "2026-09-30")

    threads = [threading.Thread(target=work, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = Store(tmp_path).load_decisions()
    assert len(rows) == 80
    assert len({r["txn_id"] for r in rows}) == 80


def test_unicode_path(tmp_path) -> None:
    s = Store(tmp_path / "세이프 포즈")
    s.save_consent(Consent(monitoring=True))
    assert s.load_consent().monitoring is True


def test_wipe_deletes_transactions_first_and_continues(tmp_path, monkeypatch) -> None:
    """한 파일이 잠겨 있어도 나머지를 지우고, 남은 파일을 한국어로 알린다."""
    s = Store(tmp_path)
    s.save_consent(Consent(monitoring=True))
    s.save_helpers([_helper()])
    s.save_transactions([_txn(1)])
    s.append_decision("t00001", Decision.SEND, RiskLevel.NONE, "2026-09-30T10:00:00")
    order: list[str] = []
    real = Store._unlink

    def locked(path):
        order.append(path.name)
        if path.name == "helpers.json":
            raise PermissionError("잠김")
        return real(path)

    monkeypatch.setattr(Store, "_unlink", staticmethod(locked))
    with pytest.raises(WipeIncomplete) as info:
        s.wipe()
    assert order[0] == TRANSACTIONS_FILE == WIPE_ORDER[0]
    assert info.value.remaining == ["helpers.json"]
    assert "helpers.json" in str(info.value) and "지우지 못했어요" in str(info.value)
    assert isinstance(info.value, StoreError)
    assert not (tmp_path / TRANSACTIONS_FILE).exists() and not (tmp_path / "consent.json").exists()
    assert (tmp_path / "helpers.json").exists()


def test_unlink_retries_brief_lock(tmp_path, monkeypatch) -> None:
    path = tmp_path / "x.json"
    path.write_text("[]", encoding="utf-8")
    calls = {"n": 0}
    real_unlink = type(path).unlink

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("잠깐 잠김")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "unlink", flaky)
    assert Store._unlink(path) is True and calls["n"] == 3 and not path.exists()


def test_signature_changes_on_write_and_wipe(tmp_path) -> None:
    s = Store(tmp_path)
    empty = s.signature()
    assert empty[1:] == (None, None, None)
    s.save_transactions([_txn(1)])
    first = s.signature()
    assert first != empty
    s.save_transactions([_txn(1), _txn(2)])
    assert s.signature() != first
    s.wipe()
    assert s.signature() == empty


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

def test_write_failure_becomes_korean_store_error(tmp_path, monkeypatch) -> None:
    """os.replace가 계속 실패하면(백신 잠금·읽기 전용·디스크 부족) 한국어 StoreError로 바꾼다."""
    import os

    s = Store(tmp_path)
    s.save_transactions([_txn(1)])

    def always_locked(src, dst):
        raise PermissionError("잠김")

    monkeypatch.setattr(os, "replace", always_locked)
    monkeypatch.setattr("safepause.store.time.sleep", lambda _s: None)
    with pytest.raises(StoreError, match="저장 파일을 쓸 수 없어요"):
        s.save_transactions([_txn(1), _txn(2)])
    monkeypatch.undo()
    assert len(s.load_transactions()) == 1                 # 앞의 파일은 그대로
    assert not list(tmp_path.glob(".sp-*.tmp"))            # 임시 파일도 남기지 않음


def test_temp_file_creation_failure_is_store_error(tmp_path, monkeypatch) -> None:
    import tempfile

    def no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile, "mkstemp", no_space)
    with pytest.raises(StoreError, match="디스크가 가득"):
        Store(tmp_path).save_consent(Consent(monitoring=True))


def test_decision_records_asked_count_only_when_given(tmp_path) -> None:
    s = Store(tmp_path)
    s.append_decision("t1", Decision.ASK_HELPER, RiskLevel.HIGH, "2026-09-30T10:00:00", asked=0)
    s.append_decision("t2", Decision.SEND, RiskLevel.NONE, "2026-09-30T10:01:00")
    rows = s.load_decisions()
    assert rows[0]["asked"] == 0 and "asked" not in rows[1]


# ---- 리뷰 수정 확인(round 3) ------------------------------------------------

_APPEND_SCRIPT = """
import sys
from safepause.store import Store
store = Store(sys.argv[1])
for i in range(int(sys.argv[3])):
    store.append_decision(f"{sys.argv[2]}-{i}", "cancel", "high", "2026-01-01T00:00:00")
"""


def test_two_processes_appending_keep_every_record(tmp_path) -> None:
    """[변경 r3] 같은 폴더에 두 프로세스(serve 두 창 등)가 동시에 기록을 더해도 하나도 잃지 않는다."""
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    n = 80
    procs = [subprocess.Popen([sys.executable, "-c", _APPEND_SCRIPT, str(tmp_path), tag, str(n)], cwd=root)
             for tag in ("a", "b")]
    assert [p.wait(timeout=120) for p in procs] == [0, 0]
    rows = Store(tmp_path).load_decisions()
    assert len(rows) == 2 * n
    assert {tag: sum(r["txn_id"].startswith(tag) for r in rows) for tag in "ab"} == {"a": n, "b": n}


def test_file_lock_excludes_other_holders(tmp_path) -> None:
    first, second = FileLock(tmp_path / "x.lock"), FileLock(tmp_path / "x.lock")
    assert first.acquire(timeout=0)
    assert second.acquire(timeout=0) is False         # 같은 프로세스의 다른 잠금과도 겹치지 않음
    first.release()
    assert second.acquire(timeout=0)
    second.release()


def test_store_waits_for_lock_then_reports_korean_error(tmp_path, monkeypatch) -> None:
    import safepause.store as store_mod

    s = Store(tmp_path)
    s.save_consent(Consent(monitoring=True))
    other = FileLock(tmp_path / LOCK_FILE)             # 다른 프로세스가 잠금을 오래 잡은 경우
    assert other.acquire(timeout=0)
    monkeypatch.setattr(store_mod, "LOCK_TIMEOUT_SEC", 0.05)
    try:
        with pytest.raises(StoreError, match="다른 SafePause 창"):
            s.append_decision("t1", Decision.CANCEL, RiskLevel.HIGH, "2026-01-01T00:00:00")
    finally:
        other.release()
    s.append_decision("t1", Decision.CANCEL, RiskLevel.HIGH, "2026-01-01T00:00:00")
    assert len(s.load_decisions()) == 1
