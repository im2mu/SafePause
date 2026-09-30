"""detect/features.py 테스트: 특징량 정의, 개인 기준 통계, 누수 방지, 증분 계산 일치."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from safepause.config import Settings
from safepause.detect.features import (
    FEATURE_NAMES,
    History,
    counterparty_key,
    feature_vector,
    iter_features,
    txn_features,
)
from safepause.models import Channel, Direction, Transaction

OUT, IN = Direction.OUT, Direction.IN
START = datetime(2026, 1, 1)
_seq = [0]


def mk(ts: datetime, amount: int, channel: Channel = Channel.CARD, direction: Direction = OUT,
       cp: str = "", cp_id: str = "", line: str = "", tid: str | None = None) -> Transaction:
    _seq[0] += 1
    return Transaction(id=tid or f"f{_seq[0]:05d}", ts=ts, amount=amount, direction=direction,
                       channel=channel, counterparty=cp, counterparty_id=cp_id, line_id=line)


def day(d: float, hour: int = 12, minute: int = 0) -> datetime:
    return START + timedelta(days=d, hours=hour, minutes=minute)


def baseline(days: int = 60) -> list[Transaction]:
    """규칙적인 정상 이력(난수 없음)."""
    out: list[Transaction] = []
    merchants = [("편의점", "M1"), ("분식집", "M2"), ("마트", "M3")]
    for d in range(days):
        name, mid = merchants[d % 3]
        out.append(mk(day(d, 12 + d % 6), 8_000 + (d % 12) * 2_000, Channel.CARD, OUT, name, mid))
        if d % 7 == 0:
            out.append(mk(day(d, 10), 50_000, Channel.TRANSFER, OUT, "엄마", "111-222"))
        if d % 30 == 5:
            out.append(mk(day(d, 9), 55_000, Channel.TELECOM_BILL, OUT, "통신사", "TEL",
                          "010-****-1111"))
        if d % 15 == 3:
            out.append(mk(day(d, 15), 3_000, Channel.MICROPAY, OUT, "게임", "G1", "010-****-1111"))
        if d % 30 == 25:
            out.append(mk(day(d, 9), 1_800_000, Channel.INCOME, IN, "회사", "CORP"))
    out.sort(key=lambda t: t.ts)
    return out


def test_feature_names_fixed_and_complete() -> None:
    required = {"log_amount", "amount_vs_p95", "hour_sin", "hour_cos", "is_night",
                "new_counterparty", "cp_count_7d", "cp_sum_7d_ratio", "channel_count_7d_ratio",
                "new_line"}
    assert required <= set(FEATURE_NAMES)
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    hist = baseline()
    feats = txn_features(mk(day(61), 20_000, cp="편의점", cp_id="M1"), hist)
    assert list(feats) == FEATURE_NAMES
    assert all(isinstance(v, float) and math.isfinite(v) for v in feats.values())
    assert feature_vector(feats) == [feats[n] for n in FEATURE_NAMES]


def test_basic_feature_values() -> None:
    hist = baseline()
    known = txn_features(mk(day(61, 14), 20_000, cp="편의점", cp_id="M1"), hist)
    new = txn_features(mk(day(61, 2), 20_000, cp="처음가게", cp_id="NEW"), hist)
    assert known["new_counterparty"] == 0.0 and new["new_counterparty"] == 1.0
    assert known["is_night"] == 0.0 and new["is_night"] == 1.0
    assert known["log_amount"] == pytest.approx(math.log1p(20_000))
    # 14시: 2π·14/24
    assert known["hour_sin"] == pytest.approx(math.sin(2 * math.pi * 14 / 24))
    assert known["hour_cos"] == pytest.approx(math.cos(2 * math.pi * 14 / 24))
    assert known["is_out"] == 1.0


def test_new_line_feature() -> None:
    hist = baseline()
    own = txn_features(mk(day(61), 55_000, Channel.TELECOM_BILL, cp="통신사",
                          line="010-****-1111"), hist)
    other = txn_features(mk(day(61), 55_000, Channel.TELECOM_BILL, cp="통신사",
                            line="010-****-9999"), hist)
    card = txn_features(mk(day(61), 55_000, Channel.CARD, cp="편의점", cp_id="M1",
                           line="010-****-9999"), hist)
    assert own["new_line"] == 0.0 and other["new_line"] == 1.0
    assert card["new_line"] == 0.0  # 회선은 통신 채널에서만 본다


def test_counterparty_window_features() -> None:
    hist = baseline()
    # 새 상대에게 최근 7일 2건(각 10만) + 대상 10만
    extra = [mk(day(58), 100_000, Channel.TRANSFER, cp="김철수", cp_id="999-1"),
             mk(day(59), 100_000, Channel.TRANSFER, cp="김철수", cp_id="999-1")]
    target = mk(day(60, 12), 100_000, Channel.TRANSFER, cp="김철수", cp_id="999-1")
    feats = txn_features(target, hist + extra)
    h = History(hist + extra, as_of=target.ts)
    usual = h.usual_7d_sum(Channel.TRANSFER, OUT)
    assert feats["cp_count_7d"] == 3.0
    assert feats["new_counterparty"] == 0.0  # 이틀 전부터 보낸 상대라 처음은 아님
    assert feats["cp_sum_7d_ratio"] == pytest.approx(300_000 / usual)


def test_counterparty_key_prefers_id() -> None:
    a = mk(day(0), 1, cp="홍 길동", cp_id=" 123-45 ")
    b = mk(day(0), 1, cp="다른이름", cp_id="123-45")
    c = mk(day(0), 1, cp="홍길동")
    assert counterparty_key(a) == counterparty_key(b) == "id:123-45"
    assert counterparty_key(c) == "name:홍길동"
    assert counterparty_key(mk(day(0), 1, Channel.ATM)) == ""


def test_history_summary_properties() -> None:
    hist = baseline(84)
    h = History(hist, as_of=day(84))
    assert "id:111-222" in h.known_payees
    assert {"id:m1", "id:m2", "id:m3"} == h.known_merchants
    assert h.known_lines == {"010-****-1111"}
    # 매주 5만 원 1건 송금 → 평소 7일 송금 합 약 5만 원
    assert h.transfer_7d_mean == pytest.approx(50_000, rel=0.15)
    cards = sorted(t.amount for t in hist if t.channel == Channel.CARD
                   and t.ts <= day(84) - timedelta(days=7))
    assert 0.9 * cards[-1] <= h.card_amount_p95 <= cards[-1]
    assert h.micropay_7d_mean == pytest.approx(7 / 15, rel=0.2)


def test_baseline_not_ready_gives_zero() -> None:
    short = [t for t in baseline(10)]
    h = History(short, as_of=day(10))
    assert not h.baseline_ready()
    assert h.transfer_7d_mean == 0.0
    assert h.usual_7d_count(Channel.CARD, OUT) == 0.0
    assert History([]).card_amount_p95 == 0.0


def test_history_rejects_time_travel_append() -> None:
    h = History([mk(day(5), 1_000)])
    with pytest.raises(ValueError):
        h.append(mk(day(1), 1_000))


def test_history_object_containing_target_raises() -> None:
    txns = baseline(20)
    h = History(txns)
    with pytest.raises(ValueError):
        txn_features(txns[-1], h)


# ---- 누수 방지 ----
def _future_noise(after: datetime) -> list[Transaction]:
    """대상 이후의 거래: 이 값들이 특징량에 들어가면 결과가 크게 달라진다."""
    return [
        mk(after + timedelta(minutes=5), 900_000, Channel.TRANSFER, cp="김철수", cp_id="999-1"),
        mk(after + timedelta(hours=1), 900_000, Channel.TRANSFER, cp="김철수", cp_id="999-1"),
        mk(after + timedelta(days=1), 70_000, Channel.CARD, cp="처음가게", cp_id="NEW"),
        mk(after + timedelta(days=2), 60_000, Channel.TELECOM_BILL, cp="통신사",
           line="010-****-9999"),
        mk(after + timedelta(days=3), 5_000, Channel.MICROPAY, cp="게임", line="010-****-1111"),
    ]


@pytest.mark.parametrize("target", [
    mk(day(60, 2), 300_000, Channel.TRANSFER, cp="김철수", cp_id="999-1"),
    mk(day(60, 14), 70_000, Channel.CARD, cp="처음가게", cp_id="NEW"),
    mk(day(60, 9), 60_000, Channel.TELECOM_BILL, cp="통신사", line="010-****-9999"),
])
def test_future_transactions_do_not_leak(target: Transaction) -> None:
    past = baseline(60)
    clean = txn_features(target, past)
    leaky_input = past + _future_noise(target.ts) + [target]  # 대상 자신과 미래 거래 포함
    assert txn_features(target, leaky_input) == clean
    # 섞인 순서여도 같다
    assert txn_features(target, list(reversed(leaky_input))) == clean


def test_history_object_is_bounded_by_as_of() -> None:
    past = baseline(60)
    target = mk(day(60, 2), 300_000, Channel.TRANSFER, cp="김철수", cp_id="999-1")
    clean = txn_features(target, past)
    with_future = History(past + _future_noise(target.ts))  # 미래 거래가 든 History 객체
    assert txn_features(target, with_future) == clean


def test_input_list_not_mutated() -> None:
    past = baseline(30)
    before = [t.to_dict() for t in past]
    txn_features(mk(day(31), 10_000, cp="편의점", cp_id="M1"), past)
    assert [t.to_dict() for t in past] == before


def test_incremental_matches_naive() -> None:
    txns = baseline(45)
    txns += [mk(day(40, 1), 200_000, Channel.TRANSFER, cp="김철수", cp_id="999-1"),
             mk(day(41, 2), 250_000, Channel.TRANSFER, cp="김철수", cp_id="999-1"),
             mk(day(42, 13), 150_000, Channel.CARD, cp="처음가게", cp_id="NEW")]
    txns.sort(key=lambda t: t.ts)
    settings = Settings()
    for idx, txn, feats in iter_features(txns, settings):
        assert feats == txn_features(txn, txns[:idx], settings), txn.id


def test_iter_features_with_context_uses_it_as_history() -> None:
    txns = baseline(40)
    ctx, rest = txns[:30], txns[30:]
    got = {t.id: f for _, t, f in iter_features(rest, context=ctx)}
    for i, t in enumerate(txns[30:], start=30):
        assert got[t.id] == txn_features(t, txns[:i])


def test_same_timestamp_order_matches_walk() -> None:
    """같은 시각 거래는 목록에서 대상보다 앞에 있는 것만 이력으로 본다(walk·assess_many와 같음)."""
    from safepause.detect.engine import RiskEngine
    from safepause.detect.features import as_history, txn_features

    noon = datetime(2026, 5, 1, 12, 0)
    xs = [Transaction(f"x{i}", noon, 200_000, Direction.OUT, Channel.TRANSFER, "김*호", "999-9")
          for i in range(1, 5)]
    assert len(as_history(xs[0], xs)) == 0
    assert len(as_history(xs[2], xs)) == 2
    assert txn_features(xs[0], xs)["cp_count_7d"] == 1.0
    assert txn_features(xs[3], xs)["cp_count_7d"] == 4.0
    engine = RiskEngine(seed=0)
    many = engine.assess_many(xs)
    one_by_one = [engine.assess(x, xs) for x in xs]
    assert [a.level for a in many] == [a.level for a in one_by_one]
    assert [[h.evidence["count_7d"] for h in a.rule_hits] for a in many] == \
        [[h.evidence["count_7d"] for h in a.rule_hits] for a in one_by_one]
    # 대상이 목록에 없으면 목록 전체가 과거 이력(같은 시각 포함, walk의 context와 같음)
    other = Transaction("y", noon, 1_000, Direction.OUT, Channel.TRANSFER, "김*호", "999-9")
    assert len(as_history(other, xs)) == 4
