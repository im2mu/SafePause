"""detect/anomaly.py 테스트: 결정론, 점수 범위, 학습 최소 건수, 설명, 누수 방지."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from safepause.detect.anomaly import MIN_TRAIN, PersonalAnomalyModel
from safepause.detect.features import FEATURE_NAMES, UPPER_RISK_FEATURES
from safepause.models import Channel, Direction, Transaction

OUT, IN = Direction.OUT, Direction.IN
START = datetime(2026, 1, 1)
OWN_LINE = "010-****-1111"


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


def probes(after: datetime) -> list[Transaction]:
    """점수 확인용 다양한 거래(평범 ~ 극단)."""
    at = after + timedelta(days=1)
    return [
        Transaction("p1", at.replace(hour=13), 15_000, OUT, Channel.CARD, "편의점", "M1"),
        Transaction("p2", at.replace(hour=15), 8_000, OUT, Channel.CARD, "마트", "M3"),
        Transaction("p3", at.replace(hour=10), 60_000, OUT, Channel.TRANSFER, "엄마", "111-222"),
        Transaction("p4", at.replace(hour=3), 3_000_000, OUT, Channel.TRANSFER, "모르는사람", "999"),
        Transaction("p5", at.replace(hour=2), 900_000, OUT, Channel.CARD, "처음가게", "NEW"),
        Transaction("p6", at.replace(hour=4), 70_000, OUT, Channel.TELECOM_BILL, "통신사", "TEL",
                    "010-****-9999"),
        Transaction("p7", at.replace(hour=9), 1_800_000, IN, Channel.INCOME, "회사", "CORP"),
        Transaction("p8", at.replace(hour=12), 1, OUT, Channel.OTHER),
    ]


@pytest.fixture(scope="module")
def history() -> list[Transaction]:
    return normal_history()


@pytest.fixture(scope="module")
def model(history: list[Transaction]) -> PersonalAnomalyModel:
    return PersonalAnomalyModel(seed=0).fit(history)


def test_fit_marks_fitted_and_version(model: PersonalAnomalyModel) -> None:
    assert model.fitted
    assert model.n_train >= MIN_TRAIN
    assert model.version == f"iforest-v1-{model.n_train}"


def test_forest_parameters(model: PersonalAnomalyModel) -> None:
    forest = model._forest
    assert forest is not None
    assert forest.n_estimators == 200
    assert forest.contamination == "auto"
    assert forest.random_state == 0


def test_same_seed_is_deterministic(history: list[Transaction]) -> None:
    a = PersonalAnomalyModel(seed=3).fit(history)
    b = PersonalAnomalyModel(seed=3).fit(history)
    ps = probes(history[-1].ts)
    assert [a.score(p, history) for p in ps] == [b.score(p, history) for p in ps]
    assert [a.explain(p, history) for p in ps] == [b.explain(p, history) for p in ps]


def test_fit_seed_argument_overrides(history: list[Transaction]) -> None:
    m = PersonalAnomalyModel(seed=0).fit(history, seed=5)
    assert m.seed == 5 and m._forest is not None and m._forest.random_state == 5


def test_scores_are_within_0_and_1(model: PersonalAnomalyModel,
                                   history: list[Transaction]) -> None:
    for p in probes(history[-1].ts):
        s = model.score(p, history)
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0
    x = np.vstack([np.zeros(len(FEATURE_NAMES)), np.full(len(FEATURE_NAMES), 1e9),
                   np.full(len(FEATURE_NAMES), -1e9)])
    s = model.score_matrix(x)
    assert s.shape == (3,) and np.all((s >= 0) & (s <= 1))


def test_extreme_is_more_anomalous_than_typical(model: PersonalAnomalyModel,
                                                history: list[Transaction]) -> None:
    ps = {p.id: p for p in probes(history[-1].ts)}
    typical = model.score(ps["p1"], history)
    extreme = model.score(ps["p4"], history)  # 새벽 3시, 처음 보는 상대에게 300만 원
    assert extreme >= 0.98
    assert typical < 0.9
    assert extreme > typical


def test_training_scores_look_like_percentiles(model: PersonalAnomalyModel,
                                               history: list[Transaction]) -> None:
    # 학습 기간 거래 점수는 0~1에 고르게 퍼진 백분위여야 한다
    assert model._train_sorted is not None
    n = len(model._train_sorted)
    assert np.all(np.diff(model._train_sorted) >= 0)
    below = np.searchsorted(model._train_sorted, model._train_sorted, side="left") / n
    assert below.min() == 0.0 and below.max() < 1.0


@pytest.mark.parametrize("n", [0, 1, MIN_TRAIN - 1])
def test_too_few_transactions_not_fitted(history: list[Transaction], n: int) -> None:
    m = PersonalAnomalyModel().fit(history[:n])
    assert not m.fitted
    assert m.version == "iforest-v1-unfitted"
    p = probes(history[-1].ts)[3]
    assert m.score(p, history) == 0.0
    assert m.explain(p, history) == []
    assert np.all(m.score_matrix(np.ones((2, len(FEATURE_NAMES)))) == 0.0)


def test_exactly_min_train_is_fitted(history: list[Transaction]) -> None:
    m = PersonalAnomalyModel().fit(history[:MIN_TRAIN])
    assert m.fitted and m.n_train == MIN_TRAIN  # 기준 미확보 구간뿐이라 전부 사용


def test_refit_with_too_few_resets(history: list[Transaction]) -> None:
    m = PersonalAnomalyModel().fit(history)
    assert m.fitted
    m.fit(history[:5])
    assert not m.fitted and m.score(probes(history[-1].ts)[0], history) == 0.0


def test_no_score_before_personal_baseline(model: PersonalAnomalyModel,
                                           history: list[Transaction]) -> None:
    # 이력 초기(평소 기준 구간 없음)에는 개인 기준 비교를 하지 않는다
    early = [t for t in history if t.ts < START + timedelta(days=5)]
    p = Transaction("e1", START + timedelta(days=5, hours=3), 3_000_000, OUT,
                    Channel.TRANSFER, "모르는사람", "999")
    assert model.score(p, early) == 0.0
    assert model.explain(p, early) == []


def test_explain_orders_by_deviation(model: PersonalAnomalyModel,
                                     history: list[Transaction]) -> None:
    p = probes(history[-1].ts)[3]
    reasons = model.explain(p, history, top_k=3)
    assert 1 <= len(reasons) <= 3
    zs = [abs(r.detail["z"]) for r in reasons]
    assert zs == sorted(zs, reverse=True)
    for r in reasons:
        assert r.code == f"anomaly:{r.detail['feature']}"
        assert r.detail["feature"] in FEATURE_NAMES
        assert {"value", "baseline_mean", "baseline_std", "z"} <= set(r.detail)
    assert model.explain(p, history, top_k=0) == []


def test_explain_skips_lower_than_usual_for_risk_features(model: PersonalAnomalyModel,
                                                          history: list[Transaction]) -> None:
    # 아주 작은 금액: '평소보다 작다'는 위험 이유가 아니다
    p = probes(history[-1].ts)[7]
    for r in model.explain(p, history, top_k=len(FEATURE_NAMES)):
        if r.detail["feature"] in UPPER_RISK_FEATURES:
            assert r.detail["z"] > 0


def test_score_ignores_future_transactions(model: PersonalAnomalyModel,
                                           history: list[Transaction]) -> None:
    cut = START + timedelta(days=60)
    past = [t for t in history if t.ts < cut]
    target = Transaction("x", cut + timedelta(hours=3), 400_000, OUT, Channel.TRANSFER,
                         "모르는사람", "999")
    future = [t for t in history if t.ts > target.ts]
    future += [Transaction(f"fx{i}", target.ts + timedelta(hours=i + 1), 400_000, OUT,
                           Channel.TRANSFER, "모르는사람", "999") for i in range(5)]
    assert model.score(target, past + future + [target]) == model.score(target, past)
    assert model.explain(target, past + future) == model.explain(target, past)


def test_label_is_not_used(history: list[Transaction]) -> None:
    import dataclasses
    relabeled = [dataclasses.replace(t, label="payee_surge") for t in history]
    a = PersonalAnomalyModel(seed=1).fit(history)
    b = PersonalAnomalyModel(seed=1).fit(relabeled)
    p = probes(history[-1].ts)[3]
    assert a.score(p, history) == b.score(p, relabeled)


# ---- 리뷰 2: 분산 0 특징과 시각 이유 ----
TIME_NAMES = {"hour_sin", "hour_cos", "is_night"}


def _date_only(txns: list[Transaction]) -> list[Transaction]:
    """날짜만 있는 CSV처럼 모든 거래를 12:00으로."""
    import dataclasses
    return [dataclasses.replace(t, ts=t.ts.replace(hour=12, minute=0)) for t in txns]


def test_date_only_history_gives_no_time_reasons(history: list[Transaction]) -> None:
    """학습 시각이 모두 같으면 평소 시간을 모르므로 '평소와 다른 시간' 이유를 내지 않는다(리뷰 12 재현)."""
    dated = _date_only(history)
    m = PersonalAnomalyModel(seed=0).fit(dated)
    assert m.fitted and not m.time_known()
    assert PersonalAnomalyModel(seed=0).fit(history).time_known()   # 시각이 여러 가지면 True
    for p in probes(dated[-1].ts):                        # 새벽 2~4시 거래 포함
        names = {r.detail["feature"] for r in m.explain(p, dated, top_k=len(FEATURE_NAMES))}
        assert not names & TIME_NAMES, (p.id, names)
    # 점수는 그대로 계산된다(설명만 바뀜)
    assert 0.0 <= m.score(probes(dated[-1].ts)[3], dated) <= 1.0


def test_zero_variance_continuous_feature_is_not_explained(model: PersonalAnomalyModel,
                                                           history: list[Transaction]) -> None:
    import copy
    m = copy.deepcopy(model)
    assert m._mean is not None and m._std is not None
    k_cont = FEATURE_NAMES.index("cp_count_7d")
    k_bin = FEATURE_NAMES.index("new_line")
    m._mean[k_cont], m._std[k_cont] = 1.0, 0.0        # 학습 때 늘 1이던 연속 특징
    m._mean[k_bin], m._std[k_bin] = 0.0, 0.0          # 학습 때 늘 0이던 0/1 특징
    feats = dict(zip(FEATURE_NAMES, [float(v) for v in m._mean]))
    feats["cp_count_7d"] = 5.0
    feats["new_line"] = 1.0
    reasons = {r.detail["feature"]: r for r in m.explain_features(feats, top_k=len(FEATURE_NAMES))}
    assert "cp_count_7d" not in reasons                  # z를 구할 수 없고 점수에도 쓰이지 않음
    assert reasons["new_line"].detail["z"] == 99.0       # 사실인 0/1 특징은 남긴다


def test_time_reason_carries_night_flag(model: PersonalAnomalyModel,
                                        history: list[Transaction]) -> None:
    found = 0
    for p in probes(history[-1].ts):
        for r in model.explain(p, history, top_k=len(FEATURE_NAMES)):
            if r.detail["feature"] in TIME_NAMES:
                assert r.detail["is_night"] is model.settings.is_night(p.ts.hour)
                found += 1
            else:
                assert "is_night" not in r.detail
    assert found > 0


# ---- 리뷰 6: sklearn 지연 불러오기 ----
def _run_python(code: str) -> str:
    """새 파이썬 프로세스에서 code를 실행하고 출력(앞뒤 공백 제거)을 돌려준다."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_engine_import_does_not_load_sklearn() -> None:
    out = _run_python(
        "import sys\n"
        "import safepause.detect.engine, safepause.explain.easy_card\n"
        "print('sklearn' in sys.modules, 'scipy' in sys.modules)\n"
    )
    assert out == "False False"


def test_rules_mode_and_unfitted_work_without_sklearn() -> None:
    out = _run_python(
        "import sys\n"
        "sys.modules['sklearn'] = None  # import sklearn 이 ImportError를 내게 막는다\n"
        "from datetime import datetime, timedelta\n"
        "from safepause.detect.engine import RiskEngine\n"
        "from safepause.models import Channel, Direction, Transaction\n"
        "t0 = datetime(2026, 1, 1, 1)\n"
        "txns = [Transaction(f'x{i}', t0 + timedelta(days=i), 100_000, Direction.OUT,\n"
        "                    Channel.TRANSFER, '김*호', '999-000-111') for i in range(3)]\n"
        "rules = RiskEngine(mode='rules').assess_many(txns)\n"
        "eng = RiskEngine().fit(txns)  # 30건 미만: 학습하지 않음\n"
        "fused = eng.assess_many(txns)\n"
        "one = eng.assess_pending(txns[-1], txns[:-1])\n"
        "print(rules[-1].level.value, fused[-1].level.value, one.level.value, eng.fitted,\n"
        "      eng.model_version())\n"
    )
    assert out == "high high high False rules-v1+iforest-v1-unfitted"


def test_pickled_model_keeps_scores_and_version(model: PersonalAnomalyModel,
                                                history: list[Transaction]) -> None:
    import pickle
    restored = pickle.loads(pickle.dumps(model))
    assert restored.version == model.version and restored.fitted
    ps = probes(history[-1].ts)
    assert [restored.score(p, history) for p in ps] == [model.score(p, history) for p in ps]
    assert [restored.explain(p, history) for p in ps] == [model.explain(p, history) for p in ps]
