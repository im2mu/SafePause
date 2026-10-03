"""경량 AI 이상탐지: 당사자 본인의 과거 정상 기간으로 학습하는 IsolationForest.

점수(0~1)는 학습 데이터 점수 분포 대비 백분위다. 대상보다 덜 이례적인 학습 거래의 비율이므로
1.0이면 학습한 어떤 평소 거래보다도 이례적이라는 뜻이다. 높을수록 이례적.
평가 시점에 평소 기준 구간이 아직 없으면(이력 초기) 개인 기준 비교가 불가능하므로 0.0을 준다.

scikit-learn은 학습(fit)할 때 처음 불러온다. 룰만 쓰거나 학습 전(30건 미만)이면 sklearn·scipy를
싣지 않아 앱 시작이 가볍다(모바일 2단계 로딩). 학습된 모델을 pickle로 풀면 sklearn은 pickle이 부른다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Optional

import numpy as np

from safepause.config import Settings
from safepause.detect.features import (
    BINARY_FEATURES,
    FEATURE_NAMES,
    TIME_FEATURES,
    UPPER_RISK_FEATURES,
    HistoryLike,
    as_history,
    compute_features,
    feature_vector,
    walk,
)
from safepause.models import Reason, Transaction

if TYPE_CHECKING:  # 타입 검사 때만. 실행 중에는 fit()이 처음 부를 때 불러온다
    from sklearn.ensemble import IsolationForest

MIN_TRAIN = 30        # 학습 거래가 이보다 적으면 학습하지 않음(fitted=False)
N_ESTIMATORS = 200
MODEL_TAG = "iforest-v1"
_Z_CAP = 99.0         # 설명용 표준화 편차 표시 상한
MIN_EXPLAIN_Z = 1.0   # 이 값보다 작은 편차는 이유로 내지 않음
_STD_EPS = 1e-9       # 이보다 작은 표준편차는 분산 0(학습 때 값이 한 가지뿐)으로 본다
_FEATURE_INDEX = {name: k for k, name in enumerate(FEATURE_NAMES)}


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
        self.configure(settings, seed)
        txns = list(train_txns)
        if len(txns) < MIN_TRAIN:
            return self
        rows_all: list[list[float]] = []
        ready: list[bool] = []
        for _, txn, hist in walk(txns, self.settings):
            rows_all.append(feature_vector(compute_features(txn, hist, txn.ts)))
            ready.append(hist.baseline_ready(txn.ts))
        self.fit_rows(rows_all, ready)
        return self

    def configure(self, settings: Settings | None = None, seed: int | None = None) -> None:
        """fit()의 첫 단계: 설정·seed를 바꾸고 학습 상태를 비운다(fitted=False)."""
        if settings is not None:
            self.settings = settings
        if seed is not None:
            self.seed = seed
        self._reset()

    def fit_rows(self, rows_all: Sequence[Sequence[float]], ready: Sequence[bool],
                 extra: Optional[np.ndarray] = None) -> Optional[np.ndarray]:
        """학습 거래의 특징(walk 순서, rows_all)과 평소 기준 준비 여부(ready)로 학습한다. fit()과 같은 결과.

        extra(특징 행렬, FEATURE_NAMES 순서)를 주면 학습 거래 점수와 한 번의 score_samples로 함께 계산해
        학습 뒤 score_matrix(extra)와 같은 값을 돌려준다. IsolationForest 점수는 행마다 따로 계산되므로
        (나무 순서대로 더함) 행을 모아 계산해도 값이 같다. 나무 200개를 도는 호출 횟수만 줄인다.
        """
        self._reset()
        rows_ready = [vec for vec, ok in zip(rows_all, ready) if ok]
        rows = rows_ready if len(rows_ready) >= MIN_TRAIN else list(rows_all)
        x = np.asarray(rows, dtype=float)

        from sklearn.ensemble import IsolationForest  # 지연 불러오기(모듈 설명 참고)

        forest = IsolationForest(n_estimators=N_ESTIMATORS, contamination="auto",
                                 random_state=self.seed)
        forest.fit(x)
        more = (None if extra is None
                else np.asarray(extra, dtype=float).reshape(-1, len(FEATURE_NAMES)))
        if more is not None and len(more):
            anomaly = -forest.score_samples(np.vstack([x, more]))
        else:
            anomaly = -forest.score_samples(x)
        self._forest = forest
        self._train_sorted = np.sort(anomaly[:len(x)])
        self._mean = x.mean(axis=0)
        self._std = x.std(axis=0)
        self.n_train = len(rows)
        self.fitted = True
        if more is None:
            return None
        return self._percentile(anomaly[len(x):])

    # ---- 점수 ----
    def score_matrix(self, x: np.ndarray) -> np.ndarray:
        """특징 행렬(FEATURE_NAMES 순서) → 0~1 점수 배열. 미학습이면 0."""
        x = np.asarray(x, dtype=float).reshape(-1, len(FEATURE_NAMES))
        if not self.fitted or self._forest is None or self._train_sorted is None:
            return np.zeros(len(x))
        return self._percentile(-self._forest.score_samples(x))

    def _percentile(self, anomaly: np.ndarray) -> np.ndarray:
        """이례도(-score_samples) → 학습 거래 이례도 분포 대비 백분위(0~1)."""
        assert self._train_sorted is not None
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
    def time_known(self) -> bool:
        """학습 거래의 시각이 한 가지가 아닌지(hour_sin·hour_cos 중 하나라도 분산이 있음).

        False면(예: 날짜만 있는 CSV라 모두 12:00) 평소 시간을 알 수 없어 시각 이유를 내지 않는다.
        """
        if not self.fitted or self._std is None:
            return False
        return any(float(self._std[_FEATURE_INDEX[name]]) > _STD_EPS
                   for name in ("hour_sin", "hour_cos"))

    def explain_features(self, feats: Mapping[str, float], top_k: int = 2) -> list[Reason]:
        """학습 분포 대비 표준화 편차(|z|)가 큰 특징 순으로 최대 top_k개.

        |z| < MIN_EXPLAIN_Z 인 특징과, UPPER_RISK_FEATURES(값이 클수록 위험)의 평소보다
        작은 쪽 편차는 이유로 내지 않는다. 학습 때 값이 한 가지뿐이던(분산 0) 연속 특징은 z를 구할 수
        없고 모델 점수에도 쓰이지 않으므로 이유로 내지 않는다(z=0). 0/1 사실 특징(BINARY_FEATURES:
        처음 보는 상대·회선 등)은 분산 0이어도 값이 다르면 ±_Z_CAP으로 남긴다. 학습 시각이 모두
        같으면(time_known()이 False) 시각 특징(TIME_FEATURES)은 이유로 내지 않는다.
        시각 특징 이유의 detail에는 심야 여부(is_night, 모델 설정 기준)를 함께 담는다(카드 아이콘용).
        """
        if not self.fitted or self._mean is None or self._std is None or top_k <= 0:
            return []
        x = np.asarray(feature_vector(feats), dtype=float)
        time_known = self.time_known()
        scored: list[tuple[float, int]] = []
        for k, name in enumerate(FEATURE_NAMES):
            if name in TIME_FEATURES and not time_known:
                continue
            diff = float(x[k] - self._mean[k])
            std = float(self._std[k])
            if std > _STD_EPS:
                z = diff / std
            elif name in BINARY_FEATURES:  # 학습 때 값이 한 가지뿐이던 0/1 사실 특징
                z = 0.0 if abs(diff) < 1e-12 else math.copysign(_Z_CAP, diff)
            else:  # 분산 0 연속 특징: 설명하지 않는다
                z = 0.0
            z = max(-_Z_CAP, min(_Z_CAP, z))
            if name in UPPER_RISK_FEATURES and z < 0:
                continue
            if abs(z) >= MIN_EXPLAIN_Z:
                scored.append((z, k))
        scored.sort(key=lambda item: (-abs(item[0]), item[1]))
        reasons: list[Reason] = []
        night = bool(x[_FEATURE_INDEX["is_night"]] >= 0.5)
        for z, k in scored[:top_k]:
            name = FEATURE_NAMES[k]
            detail = {
                "feature": name,
                "value": round(float(x[k]), 4),
                "baseline_mean": round(float(self._mean[k]), 4),
                "baseline_std": round(float(self._std[k]), 4),
                "z": round(z, 2),
            }
            if name in TIME_FEATURES:
                detail["is_night"] = night
            reasons.append(Reason(code=f"anomaly:{name}", detail=detail))
        return reasons

    def explain(self, txn: Transaction, history_before: HistoryLike,
                top_k: int = 2) -> list[Reason]:
        if not self.fitted:
            return []
        hist = as_history(txn, history_before, self.settings)
        if not hist.baseline_ready(txn.ts):
            return []
        return self.explain_features(compute_features(txn, hist, txn.ts), top_k)
