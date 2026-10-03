"""룰 필터 + 경량 이상탐지 결합 → RiskAssessment.

결합 규칙(mode="fused", SPEC §5):
- 룰 HIGH 1개 이상 → HIGH
- 룰 CAUTION + 이상 점수 ≥ 0.90 → HIGH
  (단, CAUTION 근거가 모두 '처음인지 알 수 없음'(evidence.newness_unknown)이면 올리지 않는다:
  짧은 이력 때문에 룰이 CAUTION까지로 낮춘 판단을 모델 점수로 다시 HIGH로 만들지 않기 위함, S38)
- 룰 CAUTION → CAUTION
- 룰 없음 + 이상 점수 ≥ 0.98 + 출금 → CAUTION (모델 단독으로는 HIGH로 올리지 않음, S38)
- 그 외 NONE
평가 비교용 모드: "rules"(룰만), "anomaly"(모델만: 출금이고 ≥0.98 HIGH, ≥0.90 CAUTION).
모델이 학습되지 않았거나 평가 시점에 평소 기준 구간이 없으면 이상 점수는 0.0이다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal, Optional

import numpy as np

from safepause.config import Settings
from safepause.detect.anomaly import MIN_TRAIN, PersonalAnomalyModel
from safepause.detect.features import (
    FEATURE_NAMES,
    History,
    HistoryLike,
    as_history,
    compute_features,
    feature_vector,
    walk,
    walk_events,
    walk_order,
)
from safepause.detect.rules import evaluate_rules_on
from safepause.models import (
    LEVEL_ORDER,
    Direction,
    Reason,
    RiskAssessment,
    RiskLevel,
    SignalHit,
    Transaction,
)

Mode = Literal["fused", "rules", "anomaly"]
MODES: tuple[str, ...] = ("fused", "rules", "anomaly")

FUSED_ESCALATE_SCORE = 0.90        # 룰 CAUTION을 HIGH로 올리는 이상 점수
ANOMALY_ALONE_SCORE = 0.98         # 룰 없이 모델만으로 CAUTION을 내는 이상 점수(출금만)
EXPLAIN_SCORE = 0.90               # 이상탐지 설명을 근거에 붙이는 점수
ANOMALY_ONLY_CAUTION_SCORE = 0.90  # anomaly 모드(평가 비교용) CAUTION 기준
ANOMALY_ONLY_HIGH_SCORE = 0.98     # anomaly 모드(평가 비교용) HIGH 기준
EXPLAIN_TOP_K = 2
RULES_VERSION = "rules-v1"


def check_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode는 {', '.join(MODES)} 중 하나여야 합니다: {mode!r}")
    return mode


def _can_escalate(rule_hits: Sequence[SignalHit]) -> bool:
    """이상 점수로 HIGH로 올릴 수 있는 CAUTION 근거가 있는지(짧은 이력 때문에 낮춘 근거는 제외)."""
    return any(h.severity == RiskLevel.CAUTION and not (h.evidence or {}).get("newness_unknown")
               for h in rule_hits)


def combine_level(rule_hits: Sequence[SignalHit], anomaly_score: float,
                  direction: Direction, mode: str = "fused") -> RiskLevel:
    """룰 결과와 이상 점수를 결합해 위험 등급을 정한다."""
    check_mode(mode)
    is_out = direction == Direction.OUT
    if mode == "anomaly":
        if not is_out:
            return RiskLevel.NONE
        if anomaly_score >= ANOMALY_ONLY_HIGH_SCORE:
            return RiskLevel.HIGH
        if anomaly_score >= ANOMALY_ONLY_CAUTION_SCORE:
            return RiskLevel.CAUTION
        return RiskLevel.NONE

    top = max((LEVEL_ORDER[h.severity] for h in rule_hits), default=0)
    if mode == "rules":
        return (RiskLevel.NONE, RiskLevel.CAUTION, RiskLevel.HIGH)[top]

    if top >= LEVEL_ORDER[RiskLevel.HIGH]:
        return RiskLevel.HIGH
    if top == LEVEL_ORDER[RiskLevel.CAUTION]:
        escalate = anomaly_score >= FUSED_ESCALATE_SCORE and _can_escalate(rule_hits)
        return RiskLevel.HIGH if escalate else RiskLevel.CAUTION
    if is_out and anomaly_score >= ANOMALY_ALONE_SCORE:
        return RiskLevel.CAUTION
    return RiskLevel.NONE


def _rule_reasons(hits: Sequence[SignalHit]) -> list[Reason]:
    return [Reason(code=h.code.value, detail={**h.evidence, "severity": h.severity.value})
            for h in hits]


class RiskEngine:
    """당사자 한 명의 위험 판단기. 판단은 모두 로컬에서 이뤄진다."""

    def __init__(self, settings: Settings | None = None, seed: int = 0,
                 mode: Mode = "fused") -> None:
        self.settings: Settings = settings or Settings()
        self.seed = seed
        self.mode: str = check_mode(mode)
        self.model = PersonalAnomalyModel(self.settings, seed)

    # ---- 학습 ----
    def fit(self, baseline_txns: Iterable[Transaction]) -> "RiskEngine":
        """당사자 과거 정상 기준 기간 거래로 이상탐지 모델을 학습한다."""
        self.model.fit(baseline_txns, self.settings, self.seed)
        return self

    @property
    def fitted(self) -> bool:
        return self.model.fitted

    def model_version(self, mode: str | None = None) -> str:
        m = self._mode(mode)
        if m == "rules":
            return RULES_VERSION
        if m == "anomaly":
            return self.model.version
        return f"{RULES_VERSION}+{self.model.version}"

    # ---- 평가 ----
    def assess(self, txn: Transaction, history_before: HistoryLike,
               mode: str | None = None) -> RiskAssessment:
        """한 거래를 그 이전 이력으로 평가한다(txn.ts 이후 이력은 쓰지 않음)."""
        m = self._mode(mode)
        hist = as_history(txn, history_before, self.settings)
        return self._assess_one(txn, hist, txn.ts, m)

    def assess_pending(self, pending: Transaction, history: Sequence[Transaction],
                       mode: str | None = None) -> RiskAssessment:
        """보내기 전 거래를 이력 끝에 붙여 평가한다(안전 정지 실시간 경로).

        history는 바꾸지 않는다. pending.ts가 이력 마지막 시각보다 이르면 평가 시각은
        이력 마지막 시각으로 둔다(시각 특징은 pending.ts 그대로).
        """
        m = self._mode(mode)
        hist = History([t for t in history if t.id != pending.id], self.settings)
        last = hist.as_of
        as_of = pending.ts if last is None or pending.ts >= last else last
        return self._assess_one(pending, hist, as_of, m)

    def assess_many(self, txns: Sequence[Transaction],
                    history: Iterable[Transaction] | None = None,
                    mode: str | None = None) -> list[RiskAssessment]:
        """시간순으로 각 거래를 그 이전 이력으로 평가한다. 결과는 입력 순서와 같다.

        history: 평가하지 않고 이력으로만 쓰는 과거 거래(선택).
        이력을 증분으로 갱신하고 이상 점수는 한 번에 계산해 1,000건도 빠르게 처리한다.
        """
        m = self._mode(mode)
        return self._assess_batches(None, [(txns, history)], [m])[0][m]

    def assess_modes(self, batches: Sequence[tuple[Sequence[Transaction], Iterable[Transaction] | None]],
                     modes: Sequence[str]) -> list[dict[str, list[RiskAssessment]]]:
        """(평가할 거래, 이력) 묶음 여러 개를 여러 방식으로 평가한다.

        결과[k][mode]는 assess_many(묶음 k의 거래, 이력, mode)와 같다. 이력 걷기(룰·특징 계산)는 묶음마다
        한 번만 하고(방식마다 다시 걷지 않음), 이상 점수는 모든 묶음의 행을 모아 한 번에 계산한다.
        """
        return self._assess_batches(None, batches, modes)

    def fit_assess(self, train: Iterable[Transaction],
                   batches: Sequence[tuple[Sequence[Transaction], Iterable[Transaction] | None]],
                   modes: Sequence[str]) -> list[dict[str, list[RiskAssessment]]]:
        """fit(train) 다음 assess_modes(batches, modes)를 한 것과 같은 결과(엔진 상태도 같음).

        학습 거래가 첫 묶음의 이력 걷기 앞부분과 똑같으면(같은 거래 객체, 같은 순서: 내 거래 분석은 앞쪽 학습 구간,
        성능 확인은 기준 기간 이력) 학습 특징을 그 걷기에서 함께 계산한다(같은 이력·같은 시각이라 값이 같음).
        학습 거래 점수와 평가 점수는 한 번의 score_samples로 함께 계산한다.
        """
        return self._assess_batches(list(train), batches, modes)

    def _assess_batches(self, train: Optional[list[Transaction]],
                        batches: Sequence[tuple[Sequence[Transaction], Iterable[Transaction] | None]],
                        modes: Sequence[str]) -> list[dict[str, list[RiskAssessment]]]:
        mode_list = list(dict.fromkeys(self._mode(m) for m in modes))
        will_fit = train is not None and len(train) >= MIN_TRAIN   # PersonalAnomalyModel.fit과 같은 조건
        if train is not None:
            self.model.configure(self.settings, self.seed)   # fit()의 첫 단계(학습 상태 비움)
        model_on = will_fit or (train is None and self.model.fitted)
        need_rules = any(m != "anomaly" for m in mode_list)
        need_feats = model_on and any(m != "rules" for m in mode_list)

        # 학습 거래가 fit()에서 걷는 순서(walk(train))
        fit_order = [txn for _, _, txn in walk_order(train)] if will_fit else []
        train_rows: list[list[float]] = []
        train_ready: list[bool] = []
        shared = False
        prepared: list[tuple[list[Transaction], list[list[SignalHit]], list[Optional[dict[str, float]]]]] = []
        for b, (txns, history) in enumerate(batches):
            items = list(txns)
            n = len(items)
            order = walk_order(items, history or ())
            share = (b == 0 and will_fit and len(order) >= len(fit_order)
                     and all(e[2] is t for e, t in zip(order, fit_order)))
            shared = shared or share
            n_share = len(fit_order) if share else 0
            hits: list[list[SignalHit]] = [[] for _ in range(n)]
            feats: list[Optional[dict[str, float]]] = [None] * n
            for pos, (kind, idx, txn, hist) in enumerate(walk_events(order, self.settings)):
                f: Optional[dict[str, float]] = None
                if pos < n_share:   # 학습 거래: fit()의 걷기와 같은 이력(같은 거래를 같은 순서로 더함)
                    f = compute_features(txn, hist, txn.ts)
                    train_rows.append(feature_vector(f))
                    train_ready.append(hist.baseline_ready(txn.ts))
                if kind != 1:
                    continue
                if need_rules:
                    hits[idx] = evaluate_rules_on(txn, hist, txn.ts)
                if need_feats and hist.baseline_ready(txn.ts):
                    feats[idx] = f if f is not None else compute_features(txn, hist, txn.ts)
            prepared.append((items, hits, feats))
        if will_fit and not shared:   # 앞부분이 다르면 fit()처럼 학습 거래만 따로 걷는다
            assert train is not None
            for _, txn, hist in walk(train, self.settings):
                train_rows.append(feature_vector(compute_features(txn, hist, txn.ts)))
                train_ready.append(hist.baseline_ready(txn.ts))

        # 특징이 있는 행(평소 기준이 있는 거래)만 모아 한 번에 점수를 낸다. 기준 없는 거래는 0(assess_many와 같음)
        rows = [feature_vector(f) for _, _, feats in prepared for f in feats if f is not None]
        extra = np.asarray(rows, dtype=float).reshape(-1, len(FEATURE_NAMES))
        if will_fit:
            ranks = self.model.fit_rows(train_rows, train_ready, extra)
        elif need_feats and len(extra):
            ranks = self.model.score_matrix(extra)
        else:
            ranks = np.zeros(0)
        assert ranks is not None

        out: list[dict[str, list[RiskAssessment]]] = []
        k = 0
        for items, hits, feats in prepared:
            scores = [0.0] * len(items)
            for i, f in enumerate(feats):
                if f is not None:
                    scores[i] = float(ranks[k])
                    k += 1
            result: dict[str, list[RiskAssessment]] = {}
            for m in mode_list:
                use_rules = m != "anomaly"
                use_model = self._uses_model(m)
                result[m] = [self._build(txn, list(hits[i]) if use_rules else [],
                                         feats[i] if use_model else None,
                                         scores[i] if use_model else 0.0, m)
                             for i, txn in enumerate(items)]
            out.append(result)
        return out

    # ---- 내부 ----
    def _mode(self, mode: str | None) -> str:
        return self.mode if mode is None else check_mode(mode)

    def _uses_model(self, mode: str) -> bool:
        return mode != "rules" and self.model.fitted

    def _assess_one(self, txn: Transaction, hist: History, as_of: datetime,
                    mode: str) -> RiskAssessment:
        hits = evaluate_rules_on(txn, hist, as_of) if mode != "anomaly" else []
        feats: Optional[dict[str, float]] = None
        score = 0.0
        if self._uses_model(mode) and hist.baseline_ready(as_of):
            feats = compute_features(txn, hist, as_of)
            score = float(self.model.score_matrix(np.asarray([feature_vector(feats)]))[0])
        return self._build(txn, hits, feats, score, mode)

    def _build(self, txn: Transaction, hits: list[SignalHit],
               feats: Optional[dict[str, float]], score: float, mode: str) -> RiskAssessment:
        level = combine_level(hits, score, txn.direction, mode)
        reasons = _rule_reasons(hits)
        if feats is not None and score >= EXPLAIN_SCORE:
            reasons.extend(self.model.explain_features(feats, EXPLAIN_TOP_K))
        return RiskAssessment(txn_id=txn.id, level=level, rule_hits=hits,
                              anomaly_score=score, reasons=reasons,
                              model_version=self.model_version(mode))
