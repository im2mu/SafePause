"""config.py 테스트: 심야 판단(Settings.is_night)과 시각 범위 검사."""
from __future__ import annotations

import pytest

from safepause.config import Settings


def test_default_night_wraps_midnight() -> None:
    s = Settings()   # 23:00~05:59
    assert s.is_night(23) and s.is_night(0) and s.is_night(5)
    assert not s.is_night(6) and not s.is_night(22) and not s.is_night(12)


@pytest.mark.parametrize("start, end, nights", [
    (23, 6, [0, 1, 2, 3, 4, 5, 23]),     # 시작 > 끝: 자정을 넘는 구간
    (22, 5, [0, 1, 2, 3, 4, 22, 23]),
    (0, 5, [0, 1, 2, 3, 4]),             # 시작 < 끝: 시작 ≤ 시 < 끝 (전에는 하루 종일 심야)
    (1, 4, [1, 2, 3]),
    (20, 23, [20, 21, 22]),
    (3, 3, []),                          # 시작 = 끝: 심야 없음
])
def test_is_night_ranges(start: int, end: int, nights: list[int]) -> None:
    s = Settings(night_start_hour=start, night_end_hour=end)
    assert sorted(h for h in range(24) if s.is_night(h)) == nights


@pytest.mark.parametrize("field, value", [
    ("night_start_hour", 24), ("night_start_hour", -1), ("night_end_hour", 25),
    ("night_end_hour", 6.5), ("night_start_hour", True), ("night_end_hour", "6"),
])
def test_night_hours_must_be_0_to_23(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(**{field: value})


def test_is_night_rejects_bad_hour_and_changed_settings() -> None:
    s = Settings()
    for bad in (-1, 24):
        with pytest.raises(ValueError):
            s.is_night(bad)
    s.night_end_hour = 30          # 만든 뒤 바꾼 값도 판단 때 검사한다
    with pytest.raises(ValueError):
        s.is_night(3)


def test_settings_fields_unchanged_for_reports() -> None:
    """평가 JSON의 settings(asdict)가 바뀌지 않게 필드 이름·기본값을 고정한다."""
    from dataclasses import asdict
    assert asdict(Settings()) == {"night_start_hour": 23, "night_end_hour": 6, "window_short_days": 7,
                                  "window_long_days": 30, "baseline_days": 90,
                                  "high_repeat_for_counseling": 3}
