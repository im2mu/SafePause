"""detect/features.py 테스트: 특징량 정의, 개인 기준 통계, 누수 방지, 증분 계산 일치."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from safepause.config import Settings
from safepause.detect.features import (
    FEATURE_NAMES,
    History,
    compute_features,
    counterparty_key,
    feature_vector,
    identifiers_match,
    iter_features,
    line_key,
    normalize_identifier,
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
    assert counterparty_key(a) == counterparty_key(b) == "id:12345"  # 공백·하이픈 무시(정책과 같은 규칙)
    assert counterparty_key(c) == "name:홍길동"
    assert counterparty_key(mk(day(0), 1, Channel.ATM)) == ""


def test_history_summary_properties() -> None:
    hist = baseline(84)
    h = History(hist, as_of=day(84))
    assert "id:111222" in h.known_payees             # 계좌는 숫자만(정책과 같은 규칙)
    assert {"id:m1", "id:m2", "id:m3"} == h.known_merchants
    assert h.known_lines == {"010****1111"}           # 회선 키는 가림표를 남기고 하이픈을 뺀다
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



# ---- 식별값 정규화(조력자 정책과 같은 규칙, 리뷰 1) ----
@pytest.mark.parametrize("typed", [
    "900-0101-100001", "9000101100001", "900.0101.100001", "900 0101 100001", " 900-0101-100001 ",
    "농협 900-0101-100001", "900-0101-100001 (농협)",
])
def test_same_account_in_any_format_is_same_counterparty(typed: str) -> None:
    stored = mk(day(0), 50_000, Channel.TRANSFER, cp="엄마", cp_id="900-0101-100001")
    live = mk(day(40), 300_000, Channel.TRANSFER, cp="엄마", cp_id=typed)
    assert counterparty_key(live) == counterparty_key(stored) == "id:9000101100001"
    h = History([stored], as_of=live.ts)
    assert h.is_known(Channel.TRANSFER, OUT, counterparty_key(live))
    assert txn_features(live, [stored])["new_counterparty"] == 0.0


def test_non_account_ids_ignore_separators_and_case() -> None:
    assert normalize_identifier("M-1001") == normalize_identifier("m.1001") == "m1001"
    assert normalize_identifier("PAY 1001") == "pay1001"
    assert normalize_identifier("") == ""
    assert counterparty_key(mk(day(0), 1, cp="PC 방")) == "name:pc방"   # 이름은 공백·대소문자만 무시


@pytest.mark.parametrize("stored, typed, same", [
    ("900-0101-100001", "900-****-100001", True),     # 가린 표기(보이는 숫자 모두 같음)
    ("900-****-100001", "900-0101-100001", True),     # 이력이 가려져 있고 새로 적은 값은 전체
    ("900-****-100001", "900-****-100001", True),
    ("900-0101-100001", "900-****-100002", False),    # 보이는 숫자가 다름
    ("900-0101-100001", "900-****-10001", False),     # 길이가 다름
    ("900-0101-100001", "*******100001", True),       # 같은 길이, 보이는 숫자 6개가 모두 같음
    ("900-0101-100001", "***-****-**0001", False),    # 숫자가 6개 미만이면 계좌로 보지 않음
    ("900-0101-******", "***-****-100001", False),    # 둘 다 보이는 자리가 없음(4개 미만)
])
def test_masked_accounts_follow_policy_rule(stored: str, typed: str, same: bool) -> None:
    old = mk(day(0), 50_000, Channel.TRANSFER, cp="엄마", cp_id=stored)
    live = mk(day(40), 300_000, Channel.TRANSFER, cp="엄마", cp_id=typed)
    h = History([old], as_of=live.ts)
    assert h.is_known(Channel.TRANSFER, OUT, counterparty_key(live)) is same
    assert identifiers_match(normalize_identifier(stored), normalize_identifier(typed)) is same


def test_detection_agrees_with_guardian_policy_on_same_account() -> None:
    """탐지의 '아는 상대'와 정책의 '이 조력자가 이번 거래 상대'가 같은 결론이어야 한다(리뷰 11 재현)."""
    from safepause.guardian.policy import is_conflict
    from safepause.models import Helper

    stored_forms = ["900-0101-100001", "900.0101.100001", "9000101100001", "900-****-100001"]
    typed_forms = stored_forms + ["900 0101 100001", "900-0101-100002", "900-****-100002",
                                  "111-222-333444", "농협 900-0101-100001", "*******100001",
                                  "***-****-**0001", "***-****-100002", "900-0101-10001"]
    for stored in stored_forms:
        old = mk(day(0), 50_000, Channel.TRANSFER, cp="엄마", cp_id=stored)
        helper = Helper(id="h1", name="엄마", relation="가족", identifiers=[stored])
        for typed in typed_forms:
            live = mk(day(40), 300_000, Channel.TRANSFER, cp="", cp_id=typed)
            known = History([old], as_of=live.ts).is_known(Channel.TRANSFER, OUT,
                                                         counterparty_key(live))
            assert known == is_conflict(helper, live), (stored, typed)


def test_masked_match_prefers_first_seen_and_keeps_one_series() -> None:
    a = mk(day(0), 50_000, Channel.TRANSFER, cp="엄마", cp_id="900-****-100001")
    b = mk(day(1), 60_000, Channel.TRANSFER, cp="엄마", cp_id="900-0101-100001")  # 같은 상대로 묶임
    c = mk(day(2), 70_000, Channel.TRANSFER, cp="동생", cp_id="900-0101-100002")  # 다른 상대
    h = History([a, b, c], as_of=day(3))
    assert h.known_payees == {"id:900****100001", "id:9000101100002"}
    assert h.counterparty_window(Channel.TRANSFER, OUT, "id:9000101100001", days=7) == (2, 110_000)
    assert h.first_seen(Channel.TRANSFER, OUT, "id:9000101100001") == a.ts


def test_line_ids_follow_same_rule() -> None:
    bill = mk(day(0), 55_000, Channel.TELECOM_BILL, cp="통신사", line="010-****-1111")
    h = History([bill], as_of=day(1))
    assert line_key("010 **** 1111") == line_key("010.****.1111") == "010****1111"
    for same in ("010-****-1111", "010 **** 1111", "010-1234-1111", "01012341111"):
        assert h.line_known(same), same
    for other in ("010-****-2222", "010-1234-2222", "011-****-1111"):
        assert not h.line_known(other), other
    assert h.line_label(h.first_line()) == "010-****-1111"   # 근거에는 처음 본 표기를 쓴다
    micro = mk(day(1), 3_000, Channel.MICROPAY, cp="게임", line="010-5678-1111")
    assert txn_features(micro, [bill])["new_line"] == 0.0


# ---- 평소 금액 95백분위: 평소 구간 7일 미만이면 0 (리뷰 3) ----
def test_amount_p95_needs_baseline_span() -> None:
    # 1.5일 동안 6만 원 6건: 표본은 5건 이상이지만 평소 구간이 7일보다 짧다
    early = [mk(START + timedelta(hours=6 * i), 60_000, Channel.CARD, cp="편의점", cp_id="M1")
             for i in range(6)]
    t = START + timedelta(days=10)          # 평소 구간 = [첫 거래, t-7일] = 약 3일
    h = History(early, as_of=t)
    assert h.baseline_bounds() is None
    assert h.amount_p95(Channel.CARD, OUT) == 0.0
    # 평소 구간이 7일 이상이면 같은 표본으로 p95를 계산한다
    later = START + timedelta(days=15)
    assert History(early, as_of=later).amount_p95(Channel.CARD, OUT) == pytest.approx(60_000)
    feats = txn_features(mk(t, 150_000, Channel.CARD, cp="처음가게", cp_id="NEW"), early)
    assert feats["amount_vs_p95"] == pytest.approx(150_000 / 10_000)   # 분모 하한 1만 원


# ---- 금액 검사: 음수 ValueError, 0원은 통계·건수에서 뺀다 (리뷰 4) ----
def test_negative_amount_is_rejected() -> None:
    neg = mk(day(1), -50_000, Channel.TRANSFER, cp="홍길동", cp_id="110-111-111111")
    with pytest.raises(ValueError):
        History([neg])
    h = History([mk(day(0), 1_000)])
    with pytest.raises(ValueError):
        h.append(neg)
    assert len(h) == 1                       # 실패한 추가는 이력을 바꾸지 않는다
    with pytest.raises(ValueError):
        txn_features(neg, baseline(20))
    with pytest.raises(ValueError):
        compute_features(neg, History(baseline(20)), neg.ts)


def test_zero_amount_kept_in_history_but_not_counted() -> None:
    zeros = [mk(day(d, 1), 0, Channel.TRANSFER, cp="홍길동", cp_id="110-111-111111")
             for d in (1, 2, 3)]
    h = History(zeros, as_of=day(3, 2))
    assert len(h) == 3 and h.start == zeros[0].ts         # 이력 기간에는 들어간다
    assert h.night_transfers_recent() == []
    assert h.channel_window(Channel.TRANSFER, OUT) == (0, 0)
    assert not h.is_known(Channel.TRANSFER, OUT, "id:110111111111")   # 0원만 오간 상대는 모르는 상대
    feats = txn_features(mk(day(3, 3), 50_000, Channel.TRANSFER, cp="홍길동",
                            cp_id="110-111-111111"), zeros)
    assert feats["cp_count_7d"] == 1.0 and feats["new_counterparty"] == 1.0
