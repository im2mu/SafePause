"""detect/engine.py 테스트: 결합 규칙 표의 각 분기, 모드, assess_many·assess_pending, 성능."""
from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import datetime, timedelta

import numpy as np
import pytest

from safepause.detect.anomaly import PersonalAnomalyModel
from safepause.detect.engine import RiskEngine, combine_level
from safepause.models import (
    Channel,
    Direction,
    Reason,
    RiskLevel,
    SignalCode,
    SignalHit,
    Transaction,
)

OUT, IN = Direction.OUT, Direction.IN
START = datetime(2026, 1, 1)
OWN_LINE = "010-****-1111"
NONE, CAUTION, HIGH = RiskLevel.NONE, RiskLevel.CAUTION, RiskLevel.HIGH


def normal_history(days: int = 90, seed: int = 7, cards: tuple[int, int] = (1, 4)
                   ) -> list[Transaction]:
    """난수 seed로 만든 정상 거래 이력(테스트 전용)."""
    rng = np.random.default_rng(seed)
    merchants = [("편의점", "M1"), ("분식집", "M2"), ("마트", "M3"), ("약국", "M4")]
    out: list[Transaction] = []

    def add(ts: datetime, amount: int, direction: Direction, channel: Channel,
            cp: str = "", cp_id: str = "", line: str = "") -> None:
        out.append(Transaction(f"n{len(out):05d}", ts, int(amount), direction, channel,
                               cp, cp_id, line))

    for d in range(days):
        base = START + timedelta(days=d)
        for _ in range(int(rng.integers(*cards))):
            name, mid = merchants[int(rng.integers(len(merchants)))]
            ts = base.replace(hour=int(rng.integers(9, 21)), minute=int(rng.integers(60)))
            add(ts, int(rng.integers(3, 30)) * 1000, OUT, Channel.CARD, name, mid)
        if d % 7 == 3:
            add(base.replace(hour=10), 50_000 + int(rng.integers(0, 3)) * 10_000, OUT,
                Channel.TRANSFER, "엄마", "111-222")
        if d % 30 == 25:
            add(base.replace(hour=9), 1_800_000, IN, Channel.INCOME, "회사", "CORP")
        if d % 30 == 20:
            add(base.replace(hour=8), 55_000, OUT, Channel.TELECOM_BILL, "통신사", "TEL", OWN_LINE)
        if d % 15 == 7:
            add(base.replace(hour=int(rng.integers(12, 20))), int(rng.integers(1, 5)) * 1000,
                OUT, Channel.MICROPAY, "게임", "G1", OWN_LINE)
    out.sort(key=lambda t: t.ts)
    return out


def hit(severity: RiskLevel) -> SignalHit:
    return SignalHit(SignalCode.PAYEE_SURGE, severity, {"count_7d": 3})


class FixedScoreModel(PersonalAnomalyModel):
    """이상 점수를 고정값으로 돌려주는 대역(결합 규칙 분기 확인용)."""

    def __init__(self, value: float) -> None:
        super().__init__()
        self.value = value
        self.fitted = True
        self.n_train = 99

    def score_matrix(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(np.atleast_2d(x)), self.value)

    def explain_features(self, feats: Mapping[str, float], top_k: int = 2) -> list[Reason]:
        return [Reason("anomaly:amount_vs_p95", {"feature": "amount_vs_p95", "z": 5.0})][:top_k]


# ---- 결합 규칙 표 (순수 함수) ----
@pytest.mark.parametrize("hits, score, direction, expected", [
    ([hit(HIGH)], 0.0, OUT, HIGH),                    # 룰 HIGH → HIGH
    ([hit(CAUTION), hit(HIGH)], 0.0, IN, HIGH),       # HIGH가 하나라도 있으면 HIGH
    ([hit(CAUTION)], 0.90, OUT, HIGH),                # 룰 CAUTION + 0.90 이상 → HIGH
    ([hit(CAUTION)], 0.8999, OUT, CAUTION),           # 룰 CAUTION → CAUTION
    ([], 0.98, OUT, CAUTION),                         # 룰 없음 + 0.98 이상 + 출금 → CAUTION
    ([], 1.0, OUT, CAUTION),                          # 모델 단독으로는 HIGH가 되지 않음
    ([], 0.99, IN, NONE),                             # 입금은 모델 단독 알림 없음
    ([], 0.9799, OUT, NONE),                          # 그 외 NONE
    ([], 0.0, OUT, NONE),
])
def test_fused_table(hits: list[SignalHit], score: float, direction: Direction,
                     expected: RiskLevel) -> None:
    assert combine_level(hits, score, direction, "fused") == expected


@pytest.mark.parametrize("hits, score, direction, expected", [
    ([hit(HIGH)], 0.0, OUT, HIGH),
    ([hit(CAUTION)], 1.0, OUT, CAUTION),   # 점수 무시
    ([], 1.0, OUT, NONE),
])
def test_rules_mode_table(hits: list[SignalHit], score: float, direction: Direction,
                          expected: RiskLevel) -> None:
    assert combine_level(hits, score, direction, "rules") == expected


@pytest.mark.parametrize("hits, score, direction, expected", [
    ([hit(HIGH)], 0.0, OUT, NONE),         # 룰 무시
    ([], 0.98, OUT, HIGH),
    ([], 0.90, OUT, CAUTION),
    ([], 0.89, OUT, NONE),
    ([], 1.0, IN, NONE),
])
def test_anomaly_mode_table(hits: list[SignalHit], score: float, direction: Direction,
                            expected: RiskLevel) -> None:
    assert combine_level(hits, score, direction, "anomaly") == expected


def test_newness_unknown_caution_is_not_escalated_by_anomaly() -> None:
    """[변경 r3] 짧은 이력 때문에 룰이 CAUTION까지로 낮춘 근거(newness_unknown)는 모델 점수로 올리지 않는다."""
    unknown = SignalHit(SignalCode.NEW_MERCHANT_HIGH_VALUE, CAUTION, {"newness_unknown": True})
    known = SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, CAUTION, {"count_7d": 2})
    assert combine_level([unknown], 0.99, OUT, "fused") == CAUTION
    assert combine_level([unknown, known], 0.99, OUT, "fused") == HIGH   # 다른 CAUTION 근거는 올린다
    assert combine_level([hit(CAUTION)], 0.99, OUT, "fused") == HIGH


def test_invalid_mode_raises() -> None:
    with pytest.raises(ValueError):
        combine_level([], 0.0, OUT, "magic")
    with pytest.raises(ValueError):
        RiskEngine(mode="magic")  # type: ignore[arg-type]


# ---- 엔진 통합: 각 분기 ----
@pytest.fixture(scope="module")
def history() -> list[Transaction]:
    return normal_history()


def _at(history: list[Transaction], hour: int) -> datetime:
    return (history[-1].ts + timedelta(days=1)).replace(hour=hour, minute=0)


def night_transfers(history: list[Transaction], n_prior: int) -> tuple[list[Transaction], Transaction]:
    """아는 상대(엄마)에게 심야 이체: n_prior=1 → CAUTION, 2 → HIGH."""
    at = _at(history, 2)
    prior = [Transaction(f"nt{i}", at - timedelta(days=i + 1), 50_000, OUT, Channel.TRANSFER,
                         "엄마", "111-222") for i in range(n_prior)]
    target = Transaction("nt-target", at, 50_000, OUT, Channel.TRANSFER, "엄마", "111-222")
    return history + prior, target


def engine_with(score: float) -> RiskEngine:
    engine = RiskEngine(seed=0)
    engine.model = FixedScoreModel(score)
    return engine


def test_engine_rule_high(history: list[Transaction]) -> None:
    hist, target = night_transfers(history, 2)
    a = engine_with(0.0).assess(target, hist)
    assert a.level == HIGH
    assert [h.code for h in a.rule_hits] == [SignalCode.NIGHT_REPEAT_TRANSFER]
    assert a.reasons[0].code == SignalCode.NIGHT_REPEAT_TRANSFER.value
    assert a.reasons[0].detail["count_7d"] == 3 and a.reasons[0].detail["severity"] == "high"


def test_engine_caution_escalates_with_anomaly(history: list[Transaction]) -> None:
    hist, target = night_transfers(history, 1)
    a = engine_with(0.95).assess(target, hist)
    assert a.level == HIGH
    assert a.anomaly_score == pytest.approx(0.95)
    assert [r.code for r in a.reasons] == ["night_repeat_transfer", "anomaly:amount_vs_p95"]


def test_engine_caution_stays_caution(history: list[Transaction]) -> None:
    hist, target = night_transfers(history, 1)
    a = engine_with(0.5).assess(target, hist)
    assert a.level == CAUTION
    assert [r.code for r in a.reasons] == ["night_repeat_transfer"]  # 0.90 미만이면 설명 없음


def test_engine_anomaly_alone_is_caution_for_out(history: list[Transaction]) -> None:
    card = Transaction("c1", _at(history, 13), 15_000, OUT, Channel.CARD, "편의점", "M1")
    a = engine_with(0.99).assess(card, history)
    assert a.rule_hits == [] and a.level == CAUTION
    assert [r.code for r in a.reasons] == ["anomaly:amount_vs_p95"]


def test_engine_anomaly_alone_ignores_income(history: list[Transaction]) -> None:
    income = Transaction("i1", _at(history, 9), 1_800_000, IN, Channel.INCOME, "회사", "CORP")
    assert engine_with(0.99).assess(income, history).level == NONE


def test_engine_none(history: list[Transaction]) -> None:
    card = Transaction("c1", _at(history, 13), 15_000, OUT, Channel.CARD, "편의점", "M1")
    a = engine_with(0.97).assess(card, history)
    assert a.level == NONE and a.rule_hits == []
    assert [r.code for r in a.reasons] == ["anomaly:amount_vs_p95"]  # 0.90 이상이면 설명은 붙음
    quiet = engine_with(0.5).assess(card, history)
    assert quiet.level == NONE and quiet.reasons == []


def test_engine_modes(history: list[Transaction]) -> None:
    hist, target = night_transfers(history, 1)
    engine = engine_with(0.99)
    rules = engine.assess(target, hist, mode="rules")
    assert rules.level == CAUTION and rules.anomaly_score == 0.0
    assert rules.model_version == "rules-v1"
    anomaly = engine.assess(target, hist, mode="anomaly")
    assert anomaly.level == HIGH and anomaly.rule_hits == []
    assert anomaly.model_version == engine.model.version
    fused = engine.assess(target, hist)
    assert fused.level == HIGH and fused.model_version.startswith("rules-v1+")
    only_rules = RiskEngine(mode="rules")
    only_rules.model = FixedScoreModel(0.99)
    assert only_rules.assess(target, hist).level == CAUTION  # 생성자 mode 적용


def test_unfitted_engine_falls_back_to_rules(history: list[Transaction]) -> None:
    engine = RiskEngine(seed=0).fit(history[:10])
    assert not engine.fitted
    hist, target = night_transfers(history, 1)
    a = engine.assess(target, hist)
    assert a.level == CAUTION and a.anomaly_score == 0.0
    card = Transaction("c1", _at(history, 13), 15_000, OUT, Channel.CARD, "편의점", "M1")
    assert engine.assess(card, history).level == NONE


# ---- 실제 모델 ----
@pytest.fixture(scope="module")
def fitted(history: list[Transaction]) -> RiskEngine:
    return RiskEngine(seed=0).fit(history)


def test_real_model_scores_extreme_transfer(fitted: RiskEngine,
                                            history: list[Transaction]) -> None:
    extreme = Transaction("x1", _at(history, 3), 3_000_000, OUT, Channel.TRANSFER,
                          "모르는사람", "999")
    a = fitted.assess(extreme, history)
    assert a.anomaly_score >= 0.98
    assert a.level == HIGH  # 새 상대 고액(룰 CAUTION 이상) + 이상 점수
    assert any(r.code.startswith("anomaly:") for r in a.reasons)
    assert any(h.code == SignalCode.PAYEE_SURGE for h in a.rule_hits)


def test_assess_many_matches_single_assess(fitted: RiskEngine) -> None:
    txns = normal_history(days=100, seed=11)
    at = START + timedelta(days=95, hours=1)
    txns += [Transaction(f"s{i}", at + timedelta(hours=i), 150_000, OUT, Channel.TRANSFER,
                         "모르는사람", "999") for i in range(4)]
    txns.sort(key=lambda t: t.ts)
    many = fitted.assess_many(txns)
    assert [a.txn_id for a in many] == [t.id for t in txns]
    for i, t in enumerate(txns):
        if t.ts < START + timedelta(days=88):
            continue
        single = fitted.assess(t, txns[:i])
        assert single.level == many[i].level, t.id
        assert single.rule_hits == many[i].rule_hits
        assert single.anomaly_score == pytest.approx(many[i].anomaly_score, abs=1e-12)
        assert [r.code for r in single.reasons] == [r.code for r in many[i].reasons]
    assert HIGH in {a.level for a in many if a.txn_id.startswith("s")}


def test_assess_many_keeps_input_order_and_uses_context(fitted: RiskEngine) -> None:
    txns = normal_history(days=100, seed=11)
    ctx, rest = txns[:-40], txns[-40:]
    shuffled = list(reversed(rest))
    got = fitted.assess_many(shuffled, history=ctx)
    assert [a.txn_id for a in got] == [t.id for t in shuffled]
    full = {a.txn_id: a for a in fitted.assess_many(txns)}
    for a in got:
        assert a.level == full[a.txn_id].level
        assert a.anomaly_score == pytest.approx(full[a.txn_id].anomaly_score, abs=1e-12)


def test_assess_many_is_deterministic(history: list[Transaction]) -> None:
    txns = normal_history(days=100, seed=11)
    a = RiskEngine(seed=4).fit(history).assess_many(txns)
    b = RiskEngine(seed=4).fit(history).assess_many(txns)
    assert [x.to_dict() for x in a] == [y.to_dict() for y in b]


def test_assess_many_empty(fitted: RiskEngine) -> None:
    assert fitted.assess_many([]) == []


def test_assess_pending_does_not_modify_history(fitted: RiskEngine,
                                                history: list[Transaction]) -> None:
    hist = list(reversed(history))  # 정렬되지 않은 목록도 그대로 둬야 한다
    snapshot = [t.to_dict() for t in hist]
    identity = [id(t) for t in hist]
    pending = Transaction("pending-1", _at(history, 2), 500_000, OUT, Channel.TRANSFER,
                          "모르는사람", "999")
    first = fitted.assess_pending(pending, hist)
    second = fitted.assess_pending(pending, hist)
    assert [t.to_dict() for t in hist] == snapshot
    assert [id(t) for t in hist] == identity
    assert all(t.id != pending.id for t in hist)
    assert first.to_dict() == second.to_dict()


def test_assess_pending_equals_assess_for_latest(fitted: RiskEngine,
                                                 history: list[Transaction]) -> None:
    pending = Transaction("pending-2", _at(history, 14), 250_000, OUT, Channel.TRANSFER,
                          "처음보는분", "555")
    assert fitted.assess_pending(pending, history).to_dict() == \
        fitted.assess(pending, history).to_dict()


def test_assess_pending_before_last_history_uses_whole_history(fitted: RiskEngine,
                                                               history: list[Transaction]) -> None:
    # 연습 화면 등에서 시각이 이력 마지막보다 이르더라도 전체 이력을 이전 이력으로 본다
    early = Transaction("pending-3", history[-1].ts - timedelta(days=2), 15_000, OUT,
                        Channel.CARD, "편의점", "M1")
    a = fitted.assess_pending(early, history)
    assert a.txn_id == "pending-3" and a.level in (NONE, CAUTION, HIGH)
    dup = fitted.assess_pending(history[-1], history)  # 같은 id는 이력에서 빼고 평가
    assert dup.txn_id == history[-1].id


def test_assess_many_performance_1000() -> None:
    txns = normal_history(days=120, seed=21, cards=(7, 11))[:1000]
    assert len(txns) == 1000
    baseline = [t for t in txns if t.ts < START + timedelta(days=90)]
    t0 = time.perf_counter()
    engine = RiskEngine(seed=0).fit(baseline)
    results = engine.assess_many(txns)
    elapsed = time.perf_counter() - t0
    assert len(results) == 1000
    assert elapsed < 5.0, f"학습+1,000건 평가가 {elapsed:.2f}초 걸림"
