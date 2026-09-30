"""guardian/outbox.py 테스트. store.Store 대신 append_notice만 가진 가짜 저장소를 쓴다."""
from __future__ import annotations

import socket
import urllib.request
from datetime import datetime
from typing import Any

import pytest

from safepause.guardian.outbox import DELIVERY_NOTE, NoticeStore, Outbox
from safepause.guardian.policy import decide
from safepause.models import (
    Channel,
    Consent,
    Direction,
    Helper,
    HelperNotice,
    RiskAssessment,
    RiskLevel,
    SignalCode,
    SignalHit,
    Transaction,
)


class FakeStore:
    def __init__(self) -> None:
        self.notices: list[HelperNotice] = []

    def append_notice(self, notice: HelperNotice) -> None:
        self.notices.append(notice)


def notice(i: int = 1) -> HelperNotice:
    return HelperNotice(helper_id=f"h{i}", helper_name=f"조력자{i}", txn_id="t1", level=RiskLevel.HIGH,
                        message="[SafePause] 민수님 거래에서 확인이 필요한 신호가 있어요. "
                                "결정은 민수님이 합니다. 먼저 민수님과 이야기해 주세요.",
                        created_at="2026-09-30T21:00:00")


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """발송 시도가 있으면 바로 실패하게 한다."""
    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("실제 발송(네트워크)이 있으면 안 돼요")

    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


def test_send_only_appends_to_store(no_network: None) -> None:
    store = FakeStore()
    outbox = Outbox(store)
    n = notice()
    assert outbox.send(n) is None
    assert store.notices == [n]


def test_send_all_and_count(no_network: None) -> None:
    store = FakeStore()
    count = Outbox(store).send_all([notice(1), notice(2), notice(3)])
    assert count == 3
    assert [x.helper_id for x in store.notices] == ["h1", "h2", "h3"]


def test_send_plan_records_policy_notices(no_network: None) -> None:
    helpers = [Helper(id="h1", name="엄마", relation="가족"), Helper(id="h2", name="센터", relation="센터")]
    txn = Transaction(id="t1", ts=datetime(2026, 9, 30, 2, 0), amount=300_000, direction=Direction.OUT,
                      channel=Channel.TRANSFER, counterparty="처음보는사람")
    assessment = RiskAssessment(txn_id="t1", level=RiskLevel.HIGH,
                                rule_hits=[SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, RiskLevel.HIGH, {})],
                                anomaly_score=0.5, reasons=[])
    plan = decide(assessment, txn, helpers, Consent(monitoring=True, helper_alerts=True), 0,
                  person_name="민수", now=datetime(2026, 9, 30, 2, 1))
    store = FakeStore()
    assert Outbox(store).send_plan(plan) == 2
    assert store.notices == plan.notices


def test_empty_plan_records_nothing() -> None:
    store = FakeStore()
    assert Outbox(store).send_all([]) == 0
    assert store.notices == []


def test_rejects_store_without_append_notice() -> None:
    with pytest.raises(TypeError):
        Outbox(object())  # type: ignore[arg-type]


def test_rejects_non_notice() -> None:
    with pytest.raises(TypeError):
        Outbox(FakeStore()).send({"helper_id": "h1"})  # type: ignore[arg-type]


def test_fake_store_satisfies_protocol() -> None:
    assert isinstance(FakeStore(), NoticeStore)


def test_delivery_note_states_record_only() -> None:
    assert "기록만" in DELIVERY_NOTE
    assert Outbox.delivery_note == DELIVERY_NOTE
