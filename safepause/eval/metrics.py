"""성능 평가: 합성 데이터 시나리오 평가와 사용자 거래내역 오탐 근사.

합성 데이터 평가(``evaluate`` / ``compare_modes``, SPEC §8)
  (인물, seed)마다 ``make_dataset``(시나리오 5종 모두 주입) → 처음 ``baseline_days``일의 정상 거래로
  개인 기준 모델 학습 → 그 뒤 모든 거래를 시간순으로 평가한다. 학습/평가 경계는 날짜 단위
  (시작일 + baseline_days의 0시)로 자른다.
  - 시나리오 탐지율: 주입 거래 중 1건 이상이 주의(CAUTION) 이상이면 탐지. 고위험(HIGH) 기준도 따로.
  - 정상 거래 오탐: 평가 구간 정상 거래의 알림률·고위험률·월평균 알림 수.
  - 정상 전용 대조군: 같은 seed로 시나리오 없이 만든 데이터(정상 거래는 똑같음)의 알림.
  - ``intensity``: "standard"(기본, 룰 기준을 넉넉히 넘는 시나리오) 또는 "subtle"(룰 기준 경계 변형,
    SPEC §3·§8 [추가 r4] 사전 등록 정의). 대조군은 강도와 관계없이 같다.
  - 별도 검증 세트(SPEC §8 [추가 r5]): 룰 보완에 쓴 seed 1~20과 겹치지 않는 seed(``default_seeds(20, 21)``)로
    같은 절차를 돌린다. 평가 함수는 seed 목록만 받으므로 따로 바뀌는 것은 없다.
사용자 거래내역 평가(``evaluate_file``, 질의 답변서 권고)
  내려받은 실제 거래내역을 모두 정상 거래로 가정하고, 앞부분으로 학습한 뒤 뒷부분의 알림 비율을 잰다.

결과 dict는 기본 자료형만 담아 그대로 JSON으로 저장할 수 있다. 같은 입력·seed면 같은 결과가 나온다.
"""
from __future__ import annotations

import math
import platform
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from safepause import __version__
from safepause.config import Settings
from safepause.data.synth import (
    ALL_SCENARIOS,
    DEFAULT_START,
    NORMAL_LABEL,
    PERSONAS,
    SCENARIO_WINDOW_DAYS,
    check_intensity,
    make_dataset,
)
from safepause.detect import engine as engine_mod
from safepause.detect.anomaly import MIN_TRAIN
from safepause.detect.engine import MODES, RiskEngine, check_mode
from safepause.explain.easy_card import render_card
from safepause.models import LEVEL_ORDER, RiskAssessment, RiskLevel, SignalCode, Transaction

DISCLAIMER = "합성 데이터 기준, 실제 피해 데이터 검증 아님"
FILE_DISCLAIMER = ("내려받은 거래내역을 모두 정상 거래로 가정한 오탐 근사치이며, "
                   "실제 피해 데이터 검증 아님")
DAYS_PER_MONTH = 30                       # 월평균 알림 계산에 쓰는 한 달 일수
DEFAULT_PERSONAS: tuple[str, ...] = tuple(PERSONAS)
DEFAULT_DAYS = 120
DEFAULT_BASELINE_DAYS = 90
MIN_MONTHLY_DAYS = 14                     # evaluate_file: 이보다 짧은 확인 기간은 한 달 평균으로 늘리지 않음
DEFAULT_BASELINE_RATIO = 0.75             # evaluate_file: 앞 75%로 학습(서버 학습 규칙과 같음)
MAX_LISTED_ALERTS = 200                   # evaluate_file: 결과에 담는 알림 목록 최대 건수

_CAUTION = LEVEL_ORDER[RiskLevel.CAUTION]
_HIGH = LEVEL_ORDER[RiskLevel.HIGH]


# ---------------------------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------------------------

def is_normal_label(label: Optional[str]) -> bool:
    """정답 라벨이 정상(없음 포함)인지. 라벨은 평가에만 쓰고 탐지에는 쓰지 않는다."""
    return label in (None, "", NORMAL_LABEL)


def default_seeds(n: int, start: int = 1) -> list[int]:
    """seed 개수 → [start, start+1, ..., start+n-1] (기본 [1, 2, ..., n]).

    start를 바꾸면 별도 검증 세트(SPEC §8 [추가 r5], 예: start=21 → seed 21~40)를 만든다.
    """
    if n < 1:
        raise ValueError("seed 개수는 1 이상이어야 해요.")
    if start < 0:
        raise ValueError("seed 시작 번호는 0 이상이어야 해요.")
    return list(range(start, start + n))


def _ratio(num: float, den: float) -> Optional[float]:
    return round(num / den, 6) if den else None


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def _per_month(count: int, days: float) -> Optional[float]:
    return round(count * DAYS_PER_MONTH / days, 4) if days > 0 else None


def _is_alert(a: RiskAssessment) -> bool:
    return LEVEL_ORDER[a.level] >= _CAUTION


def _is_high(a: RiskAssessment) -> bool:
    return LEVEL_ORDER[a.level] >= _HIGH


def _environment() -> dict[str, str]:
    """결과 재현에 영향을 주는 실행 환경(버전만, 개인 정보 없음)."""
    import numpy
    import sklearn

    return {
        "safepause": __version__,
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "scikit-learn": sklearn.__version__,
    }


def _thresholds() -> dict[str, float]:
    return {
        "fused_escalate_score": engine_mod.FUSED_ESCALATE_SCORE,
        "anomaly_alone_caution_score": engine_mod.ANOMALY_ALONE_SCORE,
        "anomaly_mode_caution_score": engine_mod.ANOMALY_ONLY_CAUTION_SCORE,
        "anomaly_mode_high_score": engine_mod.ANOMALY_ONLY_HIGH_SCORE,
    }


# ---------------------------------------------------------------------------
# 합성 사례 준비
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SyntheticCase:
    """합성 데이터 한 사례: 기준 기간 거래(학습·이력)와 평가 구간 거래."""

    persona: str
    seed: int
    baseline: list[Transaction]
    evaluated: list[Transaction]
    eval_days: int

    @property
    def baseline_normal(self) -> list[Transaction]:
        return [t for t in self.baseline if is_normal_label(t.label)]


def check_period(days: int, baseline_days: int) -> None:
    """시나리오(마지막 30일)가 기준 기간에 섞이지 않도록 기간을 확인한다."""
    if days <= SCENARIO_WINDOW_DAYS:
        raise ValueError(f"days는 {SCENARIO_WINDOW_DAYS}보다 커야 해요: {days}")
    if not 1 <= baseline_days <= days - SCENARIO_WINDOW_DAYS:
        raise ValueError(f"baseline_days는 1 이상 {days - SCENARIO_WINDOW_DAYS} 이하여야 해요"
                         f"(시나리오는 마지막 {SCENARIO_WINDOW_DAYS}일 안에 들어가요): {baseline_days}")


def synthetic_case(persona: str, seed: int, days: int = DEFAULT_DAYS,
                   baseline_days: int = DEFAULT_BASELINE_DAYS, *, scenarios: bool = True,
                   start: date = DEFAULT_START, intensity: str = "standard") -> SyntheticCase:
    """합성 데이터를 만들어 기준 기간/평가 구간으로 나눈다(날짜 단위 경계)."""
    check_period(days, baseline_days)
    txns = make_dataset(persona, seed, days, ALL_SCENARIOS if scenarios else None, start=start,
                        intensity=intensity)
    cutoff = datetime.combine(start + timedelta(days=baseline_days), time.min)
    return SyntheticCase(
        persona=persona, seed=seed,
        baseline=[t for t in txns if t.ts < cutoff],
        evaluated=[t for t in txns if t.ts >= cutoff],
        eval_days=days - baseline_days,
    )


def _signature(txns: Iterable[Transaction]) -> list[tuple[Any, ...]]:
    return [(t.id, t.ts, t.amount, t.direction, t.channel, t.counterparty_id, t.line_id)
            for t in txns]


def _fitted_engine(train: list[Transaction], settings: Settings, seed: int,
                   modes: Sequence[str]) -> RiskEngine:
    engine = RiskEngine(settings, seed=seed)
    if any(m != "rules" for m in modes):  # 룰만 평가할 때는 학습이 필요 없다
        engine.fit(train)
    return engine


# ---------------------------------------------------------------------------
# 사례 채점
# ---------------------------------------------------------------------------

@dataclass
class ScenarioOutcome:
    """시나리오 1회(주입 거래 묶음)의 탐지 결과."""

    code: str
    n_txns: int
    caution: bool                          # 주의 이상 1건 이상
    high: bool                             # 고위험 1건 이상
    matched: bool                          # 같은 시그널 룰이 1건 이상에서 발동
    first_alert_position: Optional[int]    # 처음 알린 주입 거래 순번(1부터)
    amount_before_first_alert: Optional[int]  # 처음 알리기 전까지 나간 주입 거래 금액(원)


@dataclass
class CaseOutcome:
    """(인물, seed, 모드) 한 사례의 채점 결과."""

    persona: str
    seed: int
    mode: str
    eval_days: float
    model_version: str
    scenarios: dict[str, ScenarioOutcome]
    n_normal: int
    normal_alert_ids: set[str]
    normal_high_ids: set[str]
    control_n: Optional[int] = None
    control_alert_ids: set[str] = field(default_factory=set)
    control_high_ids: set[str] = field(default_factory=set)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)


def _pairs(txns: Sequence[Transaction], assessments: Sequence[RiskAssessment]
           ) -> list[tuple[Transaction, RiskAssessment]]:
    if len(txns) != len(assessments):
        raise ValueError("거래 수와 평가 결과 수가 달라요.")
    for t, a in zip(txns, assessments):
        if a.txn_id != t.id:
            raise ValueError(f"평가 결과 순서가 거래와 달라요: {t.id} != {a.txn_id}")
    return list(zip(txns, assessments))


def _scenario_outcome(code: str, rows: list[tuple[Transaction, RiskAssessment]]) -> ScenarioOutcome:
    rows = sorted(rows, key=lambda p: p[0].ts)
    first = next((i for i, (_, a) in enumerate(rows) if _is_alert(a)), None)
    return ScenarioOutcome(
        code=code,
        n_txns=len(rows),
        caution=first is not None,
        high=any(_is_high(a) for _, a in rows),
        matched=any(h.code.value == code for _, a in rows for h in a.rule_hits),
        first_alert_position=None if first is None else first + 1,
        amount_before_first_alert=None if first is None else sum(t.amount for t, _ in rows[:first]),
    )


def _confusion(pairs: Sequence[tuple[Transaction, RiskAssessment]],
               predicate) -> dict[str, int]:
    c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for t, a in pairs:
        positive = not is_normal_label(t.label)
        flagged = predicate(a)
        c[("t" if positive == flagged else "f") + ("p" if flagged else "n")] += 1
    return c


def score_case(evaluated: Sequence[Transaction], assessments: Sequence[RiskAssessment],
               control_evaluated: Sequence[Transaction] | None = None,
               control_assessments: Sequence[RiskAssessment] | None = None, *,
               eval_days: float, persona: str = "", seed: int = 0, mode: str = "fused",
               model_version: str = "") -> CaseOutcome:
    """평가 구간 거래와 평가 결과(같은 순서)로 한 사례를 채점한다."""
    pairs = _pairs(evaluated, assessments)
    by_code: dict[str, list[tuple[Transaction, RiskAssessment]]] = {}
    normal: list[tuple[Transaction, RiskAssessment]] = []
    for t, a in pairs:
        if is_normal_label(t.label):
            normal.append((t, a))
        else:
            by_code.setdefault(str(t.label), []).append((t, a))

    outcome = CaseOutcome(
        persona=persona, seed=seed, mode=mode, eval_days=float(eval_days),
        model_version=model_version,
        scenarios={code: _scenario_outcome(code, rows) for code, rows in sorted(by_code.items())},
        n_normal=len(normal),
        normal_alert_ids={t.id for t, a in normal if _is_alert(a)},
        normal_high_ids={t.id for t, a in normal if _is_high(a)},
        confusion={"caution": _confusion(pairs, _is_alert), "high": _confusion(pairs, _is_high)},
    )
    if control_evaluated is not None and control_assessments is not None:
        ctrl = _pairs(control_evaluated, control_assessments)
        outcome.control_n = len(ctrl)
        outcome.control_alert_ids = {t.id for t, a in ctrl if _is_alert(a)}
        outcome.control_high_ids = {t.id for t, a in ctrl if _is_high(a)}
    return outcome


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------

def _scenario_summary(items: list[ScenarioOutcome]) -> dict[str, Any]:
    n = len(items)
    caution = sum(o.caution for o in items)
    high = sum(o.high for o in items)
    matched = sum(o.matched for o in items)
    detected = [o for o in items if o.caution]
    return {
        "n": n,
        "caution": caution,
        "high": high,
        "matched": matched,
        "recall_caution": _ratio(caution, n),
        "recall_high": _ratio(high, n),
        "matched_rate": _ratio(matched, n),
        "txns_mean": _mean([o.n_txns for o in items]),
        "first_alert_position_mean": _mean([o.first_alert_position or 0 for o in detected]),
        "amount_before_first_alert_mean": _mean(
            [o.amount_before_first_alert or 0 for o in detected]),
    }


def _normal_summary(outcomes: Sequence[CaseOutcome]) -> dict[str, Any]:
    n = sum(o.n_normal for o in outcomes)
    alerts = sum(len(o.normal_alert_ids) for o in outcomes)
    high = sum(len(o.normal_high_ids) for o in outcomes)
    days = sum(o.eval_days for o in outcomes)
    with_control = [o for o in outcomes if o.control_n is not None]
    spill = sum(len(o.normal_alert_ids - o.control_alert_ids) for o in with_control)
    spill_high = sum(len(o.normal_high_ids - o.control_high_ids) for o in with_control)
    return {
        "n_txns": n,
        "alerts": alerts,
        "high": high,
        "alert_rate": _ratio(alerts, n),
        "high_rate": _ratio(high, n),
        "monthly_alerts": _per_month(alerts, days),
        "monthly_high": _per_month(high, days),
        # 대조군에서는 알리지 않았는데 시나리오가 있을 때만 알린 정상 거래(시나리오 기간 겹침)
        "spillover_alerts": spill if with_control else None,
        "spillover_high": spill_high if with_control else None,
    }


def _control_summary(outcomes: Sequence[CaseOutcome]) -> Optional[dict[str, Any]]:
    items = [o for o in outcomes if o.control_n is not None]
    if not items:
        return None
    n = sum(o.control_n or 0 for o in items)
    alerts = sum(len(o.control_alert_ids) for o in items)
    high = sum(len(o.control_high_ids) for o in items)
    days = sum(o.eval_days for o in items)
    return {
        "n_txns": n,
        "alerts": alerts,
        "high": high,
        "alert_rate": _ratio(alerts, n),
        "high_rate": _ratio(high, n),
        "monthly_alerts": _per_month(alerts, days),
        "monthly_high": _per_month(high, days),
    }


def _confusion_summary(outcomes: Sequence[CaseOutcome]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in ("caution", "high"):
        total = Counter()
        for o in outcomes:
            total.update(o.confusion.get(key, {}))
        tp, fp, fn, tn = (int(total[k]) for k in ("tp", "fp", "fn", "tn"))
        out[key] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                    "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}
    return out


def aggregate(outcomes: Sequence[CaseOutcome]) -> dict[str, Any]:
    """여러 사례 채점 결과 → 지표 dict(시나리오별 탐지율·오탐·대조군·혼동 요약·인물별)."""
    by_code: dict[str, list[ScenarioOutcome]] = {}
    for o in outcomes:
        for code, s in o.scenarios.items():
            by_code.setdefault(code, []).append(s)
    order = [c.value for c in SignalCode] + sorted(set(by_code) - {c.value for c in SignalCode})
    all_items = [s for items in by_code.values() for s in items]

    personas = list(dict.fromkeys(o.persona for o in outcomes))
    by_persona: dict[str, Any] = {}
    for p in personas:
        group = [o for o in outcomes if o.persona == p]
        items = [s for o in group for s in o.scenarios.values()]
        normal = _normal_summary(group)
        control = _control_summary(group)
        by_persona[p] = {
            "n_cases": len(group),
            "recall_caution": _scenario_summary(items)["recall_caution"],
            "recall_high": _scenario_summary(items)["recall_high"],
            "normal_alert_rate": normal["alert_rate"],
            "normal_high_rate": normal["high_rate"],
            "monthly_alerts": normal["monthly_alerts"],
            "control_monthly_alerts": control["monthly_alerts"] if control else None,
        }

    return {
        "n_cases": len(outcomes),
        "scenario_recall": {code: _scenario_summary(by_code[code]) for code in order if code in by_code},
        "overall": _scenario_summary(all_items),
        "normal": _normal_summary(outcomes),
        "control": _control_summary(outcomes),
        "confusion": _confusion_summary(outcomes),
        "by_persona": by_persona,
        "model_versions": sorted({o.model_version for o in outcomes if o.model_version}),
    }


# ---------------------------------------------------------------------------
# 합성 데이터 평가
# ---------------------------------------------------------------------------

def _check_inputs(persona_keys: Sequence[str], seeds: Sequence[int]) -> tuple[list[str], list[int]]:
    personas = list(dict.fromkeys(str(p) for p in persona_keys))
    if not personas:
        raise ValueError("평가할 인물 설정이 없어요.")
    unknown = [p for p in personas if p not in PERSONAS]
    if unknown:
        raise ValueError(f"알 수 없는 인물 설정이에요: {', '.join(unknown)} (가능: {', '.join(PERSONAS)})")
    seed_list = list(dict.fromkeys(int(s) for s in seeds))
    if not seed_list:
        raise ValueError("seed가 하나 이상 있어야 해요.")
    if any(s < 0 for s in seed_list):
        raise ValueError("seed는 0 이상의 정수여야 해요.")
    return personas, seed_list


def _run_cases(personas: list[str], seeds: list[int], modes: list[str], days: int,
               baseline_days: int, settings: Settings, start: date,
               intensity: str = "standard") -> dict[str, list[CaseOutcome]]:
    """(인물, seed)마다 한 번 학습하고 모든 모드로 평가한다(모드 간 같은 모델)."""
    results: dict[str, list[CaseOutcome]] = {m: [] for m in modes}
    for persona in personas:
        for seed in seeds:
            case = synthetic_case(persona, seed, days, baseline_days, scenarios=True, start=start,
                                  intensity=intensity)
            ctrl = synthetic_case(persona, seed, days, baseline_days, scenarios=False, start=start)
            # 기준 기간이 똑같으면(기본 설정) 같은 모델을 대조군에도 쓴다.
            same = _signature(case.baseline_normal) == _signature(ctrl.baseline_normal)
            # 모든 방식을 한 번에 평가한다(이력 걷기는 묶음마다 한 번, 점수는 학습·사례·대조군을 모아 한 번).
            # 결과는 방식마다 _fitted_engine 뒤 assess_many를 따로 부른 것과 같다
            case_batch = (case.evaluated, case.baseline)
            ctrl_batch = (ctrl.evaluated, ctrl.baseline)
            engine = RiskEngine(settings, seed=seed)
            if same:
                assessed, control = _assess_all(engine, case.baseline_normal, [case_batch, ctrl_batch], modes)
            else:
                (assessed,) = _assess_all(engine, case.baseline_normal, [case_batch], modes)
                (control,) = _assess_all(RiskEngine(settings, seed=seed), ctrl.baseline_normal, [ctrl_batch],
                                         modes)
            for mode in modes:
                results[mode].append(score_case(
                    case.evaluated, assessed[mode], ctrl.evaluated, control[mode],
                    eval_days=case.eval_days, persona=persona, seed=seed, mode=mode,
                    model_version=engine.model_version(mode),
                ))
    return results


def _assess_all(engine: RiskEngine, train: list[Transaction],
                batches: Sequence[tuple[Sequence[Transaction], Sequence[Transaction]]],
                modes: Sequence[str]) -> list[dict[str, list[RiskAssessment]]]:
    """_fitted_engine(train, …, modes) 뒤 묶음마다·방식마다 assess_many를 부른 것과 같은 결과."""
    if any(m != "rules" for m in modes):  # 룰만 평가할 때는 학습이 필요 없다
        return engine.fit_assess(train, batches, modes)
    return engine.assess_modes(batches, modes)


def _meta(personas: list[str], seeds: list[int], days: int, baseline_days: int,
          settings: Settings, start: date, intensity: str = "standard") -> dict[str, Any]:
    return {
        "data": "synthetic",
        "note": DISCLAIMER,
        "intensity": intensity,
        "personas": personas,
        "seeds": seeds,
        "days": days,
        "baseline_days": baseline_days,
        "eval_days": days - baseline_days,
        "start": start.isoformat(),
        "scenarios": [c.value for c in ALL_SCENARIOS],
        "settings": asdict(settings),
        "thresholds": _thresholds(),
        "environment": _environment(),
    }


def evaluate(persona_keys: Sequence[str], seeds: Sequence[int], mode: str = "fused",
             days: int = DEFAULT_DAYS, baseline_days: int = DEFAULT_BASELINE_DAYS, *,
             settings: Settings | None = None, start: date = DEFAULT_START,
             intensity: str = "standard") -> dict[str, Any]:
    """합성 데이터 평가(모드 하나). SPEC §8. intensity는 "standard" 또는 "subtle"."""
    mode = check_mode(mode)
    intensity = check_intensity(intensity)
    check_period(days, baseline_days)
    personas, seed_list = _check_inputs(persona_keys, seeds)
    settings = settings or Settings()
    outcomes = _run_cases(personas, seed_list, [mode], days, baseline_days, settings, start,
                          intensity)[mode]
    return {"kind": "synthetic", "mode": mode,
            **_meta(personas, seed_list, days, baseline_days, settings, start, intensity),
            **aggregate(outcomes)}


def compare_modes(persona_keys: Sequence[str], seeds: Sequence[int],
                  modes: Sequence[str] = MODES, days: int = DEFAULT_DAYS,
                  baseline_days: int = DEFAULT_BASELINE_DAYS, *,
                  settings: Settings | None = None, start: date = DEFAULT_START,
                  intensity: str = "standard") -> dict[str, Any]:
    """fused/rules/anomaly 모드 비교. 각 모드 결과는 ``evaluate``와 같은 모양이다."""
    mode_list = list(dict.fromkeys(check_mode(m) for m in modes))
    if not mode_list:
        raise ValueError("비교할 모드가 없어요.")
    intensity = check_intensity(intensity)
    check_period(days, baseline_days)
    personas, seed_list = _check_inputs(persona_keys, seeds)
    settings = settings or Settings()
    meta = _meta(personas, seed_list, days, baseline_days, settings, start, intensity)
    runs = _run_cases(personas, seed_list, mode_list, days, baseline_days, settings, start,
                      intensity)
    return {
        "kind": "comparison",
        **meta,
        "mode_order": mode_list,
        "modes": {m: {"kind": "synthetic", "mode": m, **meta, **aggregate(runs[m])}
                  for m in mode_list},
    }


# ---------------------------------------------------------------------------
# 사용자 거래내역 평가(오탐 근사)
# ---------------------------------------------------------------------------

def split_baseline(txns: Iterable[Transaction], baseline_ratio: float = DEFAULT_BASELINE_RATIO,
                   min_baseline: int = MIN_TRAIN) -> tuple[list[Transaction], list[Transaction]]:
    """시간순 앞 baseline_ratio(최소 min_baseline건)는 학습용, 나머지는 평가용."""
    if not 0 < baseline_ratio < 1:
        raise ValueError("baseline_ratio는 0보다 크고 1보다 작아야 해요.")
    ordered = sorted(txns, key=lambda t: t.ts)
    n = len(ordered)
    if n < min_baseline + 1:
        raise ValueError(f"거래가 {n}건이에요. 평가하려면 최소 {min_baseline + 1}건이 필요해요.")
    k = min(n - 1, max(min_baseline, math.ceil(n * baseline_ratio)))
    return ordered[:k], ordered[k:]


def _span_days(txns: Sequence[Transaction]) -> int:
    """거래가 걸친 달력 일수(첫날·마지막 날 포함)."""
    if not txns:
        return 0
    return (txns[-1].ts.date() - txns[0].ts.date()).days + 1


def alert_row(t: Transaction, a: RiskAssessment) -> dict[str, Any]:
    card = render_card(a, t, past=True)  # 이미 끝난 거래: 과거형 기록 카드
    return {
        "txn_id": t.id,
        "ts": t.ts.isoformat(timespec="seconds"),
        "amount": t.amount,
        "direction": t.direction.value,
        "channel": t.channel.value,
        "counterparty": t.counterparty,
        "level": a.level.value,
        "signals": [h.code.value for h in a.rule_hits],
        "anomaly_score": round(float(a.anomaly_score), 4),
        "card_title": card.title if card else "",
    }


def evaluate_file(txns: Iterable[Transaction], baseline_ratio: float = DEFAULT_BASELINE_RATIO, *,
                  mode: str = "fused", settings: Settings | None = None, seed: int = 0,
                  max_listed: Optional[int] = MAX_LISTED_ALERTS) -> dict[str, Any]:
    """사용자 거래내역(정상으로 가정)의 알림 비율 = 정상 거래 오탐 근사(질의 답변서 권고).

    앞 baseline_ratio로 개인 기준을 학습하고 뒷부분을 시간순으로 평가한다. 라벨은 쓰지 않는다.
    """
    mode = check_mode(mode)
    settings = settings or Settings()
    baseline, evaluated = split_baseline(txns, baseline_ratio)
    engine = RiskEngine(settings, seed=seed)
    # fit(baseline) 뒤 assess_many(evaluated, history=baseline)와 같은 결과(학습 구간은 평가 걷기의 앞부분이라 한 번만 걷는다)
    batch = [(evaluated, baseline)]
    runs = engine.fit_assess(baseline, batch, [mode]) if mode != "rules" else engine.assess_modes(batch, [mode])
    assessed = runs[0][mode]
    pairs = _pairs(evaluated, assessed)
    alerts = [(t, a) for t, a in pairs if _is_alert(a)]
    high = [(t, a) for t, a in alerts if _is_high(a)]
    eval_days = _span_days(evaluated)

    by_signal: Counter[str] = Counter()
    anomaly_only = 0
    for _, a in alerts:
        codes = {h.code.value for h in a.rule_hits}
        by_signal.update(codes)
        anomaly_only += not codes
    by_channel: dict[str, dict[str, int]] = {}
    for t, a in pairs:
        row = by_channel.setdefault(t.channel.value, {"n": 0, "alerts": 0})
        row["n"] += 1
        row["alerts"] += int(_is_alert(a))

    listed = alerts if max_listed is None else alerts[:max(0, max_listed)]
    return {
        "kind": "file",
        "data": "user_file",
        "note": FILE_DISCLAIMER,
        "mode": mode,
        "seed": seed,
        "baseline_ratio": baseline_ratio,
        "settings": asdict(settings),
        "environment": _environment(),
        "model_version": engine.model_version(mode),
        "fitted": engine.fitted,
        "n_total": len(baseline) + len(evaluated),
        "n_baseline": len(baseline),
        # 실제 학습 행 수: 평소 기준이 아직 없는 초기 거래를 빼서 n_baseline보다 적을 수 있다(룰만이면 0)
        "n_train_rows": engine.model.n_train if mode != "rules" else 0,
        "n_eval": len(evaluated),
        "period": {
            "baseline_start": baseline[0].ts.isoformat(timespec="seconds"),
            "baseline_end": baseline[-1].ts.isoformat(timespec="seconds"),
            "eval_start": evaluated[0].ts.isoformat(timespec="seconds"),
            "eval_end": evaluated[-1].ts.isoformat(timespec="seconds"),
        },
        "eval_days": eval_days,
        "alerts": len(alerts),
        "high": len(high),
        "alert_rate": _ratio(len(alerts), len(evaluated)),
        "high_rate": _ratio(len(high), len(evaluated)),
        # 확인 기간이 너무 짧으면(14일 미만) 한 달로 늘려 말하지 않는다(하루 3건 → '한 달 90건' 같은 부풀림 방지, v0.2)
        "monthly_alerts": _per_month(len(alerts), eval_days) if eval_days >= MIN_MONTHLY_DAYS else None,
        "monthly_high": _per_month(len(high), eval_days) if eval_days >= MIN_MONTHLY_DAYS else None,
        "by_signal": {c.value: by_signal[c.value] for c in SignalCode if by_signal[c.value]},
        "anomaly_only": anomaly_only,
        "by_channel": dict(sorted(by_channel.items())),
        "alert_list": [alert_row(t, a) for t, a in listed],
        "alert_list_truncated": len(listed) < len(alerts),
    }


__all__ = [
    "DISCLAIMER", "FILE_DISCLAIMER", "DEFAULT_PERSONAS", "MODES",
    "CaseOutcome", "ScenarioOutcome", "SyntheticCase",
    "aggregate", "alert_row", "check_period", "compare_modes", "default_seeds", "evaluate", "evaluate_file",
    "is_normal_label", "score_case", "split_baseline", "synthetic_case",
]
