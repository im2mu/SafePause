"""경량 AI 이상탐지: 당사자 본인의 과거 정상 기간으로 학습하는 IsolationForest.

점수(0~1)는 학습 데이터 점수 분포 대비 백분위다. 대상보다 덜 이례적인 학습 거래의 비율이므로
1.0이면 학습한 어떤 평소 거래보다도 이례적이라는 뜻이다. 높을수록 이례적.
평가 시점에 평소 기준 구간이 아직 없으면(이력 초기) 개인 기준 비교가 불가능하므로 0.0을 준다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from safepause.config import Settings
from safepause.detect.features import (
    FEATURE_NAMES,
    UPPER_RISK_FEATURES,
    HistoryLike,
    as_history,
    compute_features,
    feature_vector,
    walk,
)
from safepause.models import Reason, Transaction

MIN_TRAIN = 30        # 학습 거래가 이보다 적으면 학습하지 않음(fitted=False)
N_ESTIMATORS = 200
MODEL_TAG = "iforest-v1"
_Z_CAP = 99.0         # 설명용 표준화 편차 표시 상한
MIN_EXPLAIN_Z = 1.0   # 이 값보다 작은 편차는 이유로 내지 않음


class PersonalAnomalyModel:
    """개인 기준 이상탐지 모델."""

    def __init__(self, settings: Settings | None = None, seed: int = 0) -> None:
        self.settings: Settings = settings or Settings()
        self.seed = seed
        self._reset()

    def _reset(self) -> None:
        self.fitted: bool = False
        self.n_train: int = 0
        self._forest: Optional[IsolationForest] = None
        self._train_sorted: Optional[np.ndarray] = None  # 학습 거래 이례도(오름차순)
        self._mean: Optional[np.ndarray] = None
        self._std: Optional[np.ndarray] = None

    @property
    def version(self) -> str:
        return f"{MODEL_TAG}-{self.n_train}" if self.fitted else f"{MODEL_TAG}-unfitted"

    def fit(self, train_txns: Iterable[Transaction], settings: Settings | None = None,
            seed: int | None = None) -> "PersonalAnomalyModel":
        """각 거래를 그 이전 이력(학습 거래 안에서)으로 특징화해 학습한다.

        평소 기준이 아직 없는 초기 구간(워밍업) 거래는 특징값이 극단적이라 학습 행에서 빼되,
        빼고 나서 MIN_TRAIN 건이 안 되면 전부 쓴다. 정답 라벨(label)은 쓰지 않는다.
        """
        if settings is not None:
            self.settings = settings
        if seed is not None:
            self.seed = seed
        self._reset()
        txns = list(train_txns)
        if len(txns) < MIN_TRAIN:
            return self

        rows_all: list[list[float]] = []
        rows_ready: list[list[float]] = []
        for _, txn, hist in walk(txns, self.settings):
            vec = feature_vector(compute_features(txn, hist, txn.ts))
            rows_all.append(vec)
            if hist.baseline_ready(txn.ts):
                rows_ready.append(vec)
        rows = rows_ready if len(rows_ready) >= MIN_TRAIN else rows_all
        x = np.asarray(rows, dtype=float)

        forest = IsolationForest(n_estimators=N_ESTIMATORS, contamination="auto",
                                 random_state=self.seed)
        forest.fit(x)
        self._forest = forest
        self._train_sorted = np.sort(-forest.score_samples(x))
        self._mean = x.mean(axis=0)
        self._std = x.std(axis=0)
        self.n_train = len(rows)
        self.fitted = True
        return self

    # ---- 점수 ----
    def score_matrix(self, x: np.ndarray) -> np.ndarray:
        """특징 행렬(FEATURE_NAMES 순서) → 0~1 점수 배열. 미학습이면 0."""
        x = np.asarray(x, dtype=float).reshape(-1, len(FEATURE_NAMES))
        if not self.fitted or self._forest is None or self._train_sorted is None:
            return np.zeros(len(x))
        anomaly = -self._forest.score_samples(x)
        below = np.searchsorted(self._train_sorted, anomaly, side="left")
        return np.clip(below / len(self._train_sorted), 0.0, 1.0)

    def score_features(self, feats: Mapping[str, float]) -> float:
        return float(self.score_matrix(np.asarray([feature_vector(feats)]))[0])

    def score(self, txn: Transaction, history_before: HistoryLike) -> float:
        """대상 거래의 이례성 점수(0~1). history_before의 txn.ts 이후 거래는 쓰지 않는다."""
        if not self.fitted:
            return 0.0
        hist = as_history(txn, history_before, self.settings)
        if not hist.baseline_ready(txn.ts):
            return 0.0
        return self.score_features(compute_features(txn, hist, txn.ts))

    # ---- 설명 ----
    def explain_features(self, feats: Mapping[str, float], top_k: int = 2) -> list[Reason]:
        """학습 분포 대비 표준화 편차(|z|)가 큰 특징 순으로 최대 top_k개.

        |z| < MIN_EXPLAIN_Z 인 특징과, UPPER_RISK_FEATURES(값이 클수록 위험)의 평소보다
        작은 쪽 편차는 이유로 내지 않는다.
        """
        if not self.fitted or self._mean is None or self._std is None or top_k <= 0:
            return []
        x = np.asarray(feature_vector(feats), dtype=float)
        scored: list[tuple[float, int]] = []
        for k in range(len(FEATURE_NAMES)):
            diff = float(x[k] - self._mean[k])
            std = float(self._std[k])
            if std > 1e-9:
                z = diff / std
            else:  # 학습 때 값이 한 가지뿐이던 특징
                z = 0.0 if abs(diff) < 1e-12 else math.copysign(_Z_CAP, diff)
            z = max(-_Z_CAP, min(_Z_CAP, z))
            if FEATURE_NAMES[k] in UPPER_RISK_FEATURES and z < 0:
                continue
            if abs(z) >= MIN_EXPLAIN_Z:
                scored.append((z, k))
        scored.sort(key=lambda item: (-abs(item[0]), item[1]))
        reasons: list[Reason] = []
        for z, k in scored[:top_k]:
            name = FEATURE_NAMES[k]
            reasons.append(Reason(code=f"anomaly:{name}", detail={
                "feature": name,
                "value": round(float(x[k]), 4),
                "baseline_mean": round(float(self._mean[k]), 4),
                "baseline_std": round(float(self._std[k]), 4),
                "z": round(z, 2),
            }))
        return reasons

    def explain(self, txn: Transaction, history_before: HistoryLike,
                top_k: int = 2) -> list[Reason]:
        if not self.fitted:
            return []
        hist = as_history(txn, history_before, self.settings)
        if not hist.baseline_ready(txn.ts):
            return []
        return self.explain_features(compute_features(txn, hist, txn.ts), top_k)
