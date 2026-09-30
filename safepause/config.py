"""경로와 판단 설정."""
from __future__ import annotations

import numbers
import os
from dataclasses import dataclass
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("SAFEPAUSE_HOME")
    if env:
        root = Path(env)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "SafePause"
    else:
        root = Path.home() / ".safepause"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _check_hour(name: str, value: object) -> int:
    """0~23 정수 시각인지 확인한다. 아니면 ValueError."""
    if isinstance(value, bool) or not isinstance(value, numbers.Integral) or not 0 <= value <= 23:
        raise ValueError(f"{name}는 0~23 사이의 정수여야 합니다: {value!r}")
    return int(value)


@dataclass
class Settings:
    night_start_hour: int = 23      # 23:00~05:59 를 심야로 본다
    night_end_hour: int = 6
    window_short_days: int = 7
    window_long_days: int = 30
    baseline_days: int = 90
    high_repeat_for_counseling: int = 3  # 30일 내 고위험 3건 이상이면 상담 연계 제안(동의 시)

    def __post_init__(self) -> None:
        _check_hour("night_start_hour", self.night_start_hour)
        _check_hour("night_end_hour", self.night_end_hour)

    def is_night(self, hour: int) -> bool:
        """심야 여부. 시작 > 끝이면 자정을 넘는 구간(기본 23~6시: 23:00~05:59),
        아니면 시작 ≤ 시 < 끝(예: 0~5 → 00:00~04:59, 시작 = 끝이면 심야 없음)."""
        _check_hour("hour", hour)
        start = _check_hour("night_start_hour", self.night_start_hour)
        end = _check_hour("night_end_hour", self.night_end_hour)
        if start > end:
            return hour >= start or hour < end
        return start <= hour < end
