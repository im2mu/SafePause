"""경로와 판단 설정."""
from __future__ import annotations

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


@dataclass
class Settings:
    night_start_hour: int = 23      # 23:00~05:59 를 심야로 본다
    night_end_hour: int = 6
    window_short_days: int = 7
    window_long_days: int = 30
    baseline_days: int = 90
    high_repeat_for_counseling: int = 3  # 30일 내 고위험 3건 이상이면 상담 연계 제안(동의 시)

    def is_night(self, hour: int) -> bool:
        return hour >= self.night_start_hour or hour < self.night_end_hour
