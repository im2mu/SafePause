"""합성 데이터 생성기 테스트: 결정론, 정상 이력의 성질, 시나리오 주입 규칙(SPEC §3)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
import pytest

from safepause.data import synth
from safepause.models import Channel, Direction, SignalCode, Transaction

START = synth.DEFAULT_START
SEEDS = range(8)


def _dicts(txns: list[Transaction]) -> list[dict]:
    return [t.to_dict() for t in txns]


def _before(txns: list[Transaction], at: date) -> list[Transaction]:
    cutoff = datetime.combine(at, time(0, 0))
    return [t for t in txns if t.ts < cutoff]


def _injected(txns: list[Transaction], code: SignalCode) -> list[Transaction]:
    return [t for t in txns if t.label == code.value]


# ---------------------------------------------------------------------------
# 정상 이력
# ---------------------------------------------------------------------------

def test_personas_exist_with_required_fields() -> None:
    assert {"worker", "benefit", "student"} <= set(synth.PERSONAS)
    for p in synth.PERSONAS.values():
        assert p.monthly_income > 0 and 1 <= p.income_day <= 31
        assert p.known_payees and p.known_merchants and p.telecom_line
        assert p.active_hours == (8, 22)


def test_generate_history_is_deterministic() -> None:
    p = synth.PERSONAS["worker"]
    a = synth.generate_history(p, START, 60, seed=5)
    b = synth.generate_history(p, START, 60, seed=5)
    c = synth.generate_history(p, START, 60, seed=6)
    assert _dicts(a) == _dicts(b)
    assert _dicts(a) != _dicts(c)


@pytest.mark.parametrize("key", list(synth.PERSONAS))
def test_history_is_normal_sorted_and_unique(key: str) -> None:
    p = synth.PERSONAS[key]
    txns = synth.generate_history(p, START, 120, seed=1)
    assert txns
    assert all(t.label == "normal" for t in txns)
    assert [t.ts for t in txns] == sorted(t.ts for t in txns)
    assert len({t.id for t in txns}) == len(txns)
    assert all(t.amount > 0 and t.ts.microsecond == 0 for t in txns)
    assert all(START <= t.ts.date() < START + timedelta(days=120) for t in txns)


@pytest.mark.parametrize("key", list(synth.PERSONAS))
def test_history_has_expected_channels(key: str) -> None:
    p = synth.PERSONAS[key]
    txns = synth.generate_history(p, START, 120, seed=2)
    by = {c: [t for t in txns if t.channel == c] for c in Channel}

    # 월 1회 입금(120일 = 4개 달 안팎)
    income = by[Channel.INCOME]
    assert 3 <= len(income) <= 5
    assert all(t.direction == Direction.IN for t in income)
    assert len({(t.ts.year, t.ts.month) for t in income}) == len(income)

    # 통신요금: 월 1회, 단일 회선
    bills = by[Channel.TELECOM_BILL]
    assert 3 <= len(bills) <= 5
    assert {t.line_id for t in bills} == {p.telecom_line}

    # 카드결제는 단골 위주
    cards = by[Channel.CARD]
    known = {m[1] for m in p.known_merchants}
    assert len(cards) > 50
    assert sum(t.counterparty_id in known for t in cards) / len(cards) > 0.8

    # 송금은 대부분 알려진 상대
    transfers = by[Channel.TRANSFER]
    payees = {acct for _, acct in p.known_payees}
    assert transfers and sum(t.counterparty_id in payees for t in transfers) / len(transfers) > 0.7

    # 모든 출금 방향이 맞다
    for c in (Channel.CARD, Channel.TRANSFER, Channel.MICROPAY, Channel.TELECOM_BILL, Channel.ATM):
        assert all(t.direction == Direction.OUT for t in by[c])


def test_history_mostly_in_active_hours_with_some_night_noise() -> None:
    total = night_cards = new_small = 0
    in_active = 0
    for key, p in synth.PERSONAS.items():
        for seed in SEEDS:
            txns = synth.generate_history(p, START, 120, seed=seed)
            known = {m[1] for m in p.known_merchants}
            total += len(txns)
            in_active += sum(p.active_hours[0] <= t.ts.hour < p.active_hours[1] for t in txns)
            night_cards += sum(t.channel == Channel.CARD and (t.ts.hour >= 23 or t.ts.hour < 2)
                               for t in txns)
            new_small += sum(t.channel == Channel.CARD and t.counterparty_id not in known
                             and t.amount <= 30_000 for t in txns)
    assert in_active / total > 0.9      # 주로 활동 시간
    assert night_cards > 0              # 가끔 밤 결제(잡음)
    assert new_small > 0                # 가끔 새 가맹점 소액(잡음)


def test_history_normal_micropay_is_rare_and_small() -> None:
    for key, p in synth.PERSONAS.items():
        txns = synth.generate_history(p, START, 120, seed=3)
        mp = [t for t in txns if t.channel == Channel.MICROPAY]
        assert all(t.amount <= 15_000 and t.line_id == p.telecom_line for t in mp)
        assert len(mp) <= p.micropay_per_month * 4 * 3


def test_generate_history_rejects_bad_days() -> None:
    with pytest.raises(ValueError):
        synth.generate_history(synth.PERSONAS["worker"], START, 0, seed=0)


# ---------------------------------------------------------------------------
# 시나리오 주입
# ---------------------------------------------------------------------------

def _base(key: str = "worker", seed: int = 0, days: int = 100) -> list[Transaction]:
    return synth.generate_history(synth.PERSONAS[key], START, days, seed=seed)


AT = START + timedelta(days=85)


def test_inject_does_not_mutate_and_is_deterministic() -> None:
    hist = _base()
    snapshot = _dicts(hist)
    for code in SignalCode:
        a = synth.inject_scenario(hist, code, AT, seed=11)
        b = synth.inject_scenario(hist, code, AT, seed=11)
        assert _dicts(hist) == snapshot           # 원본 그대로
        assert a is not hist and len(a) > len(hist)
        assert _dicts(a) == _dicts(b)
        assert [t.ts for t in a] == sorted(t.ts for t in a)
        assert len({t.id for t in a}) == len(a)
        inj = _injected(a, code)
        assert len(a) == len(hist) + len(inj)
        assert all(t.ts >= datetime.combine(AT, time(0, 0)) for t in inj)


def test_inject_accepts_string_code() -> None:
    a = synth.inject_scenario(_base(), "micropay_surge", AT, seed=1)
    assert _injected(a, SignalCode.MICROPAY_SURGE)


def test_inject_same_scenario_twice_keeps_ids_unique() -> None:
    a = synth.inject_scenario(_base(), SignalCode.MICROPAY_SURGE, AT, seed=1)
    b = synth.inject_scenario(a, SignalCode.MICROPAY_SURGE, AT, seed=1)
    assert len({t.id for t in b}) == len(b)


@pytest.mark.parametrize("key", list(synth.PERSONAS))
@pytest.mark.parametrize("seed", SEEDS)
def test_night_repeat_transfer_definition(key: str, seed: int) -> None:
    hist = _base(key, seed)
    out = synth.inject_scenario(hist, SignalCode.NIGHT_REPEAT_TRANSFER, AT, seed=seed)
    inj = _injected(out, SignalCode.NIGHT_REPEAT_TRANSFER)
    assert 4 <= len(inj) <= 6
    assert all(t.channel == Channel.TRANSFER and t.direction == Direction.OUT for t in inj)
    assert all(0 <= t.ts.hour <= 4 for t in inj)                      # 00~04시
    assert all(100_000 <= t.amount <= 500_000 for t in inj)           # 10만~50만 원
    span = (inj[-1].ts.date() - inj[0].ts.date()).days + 1
    assert 3 <= span <= 5                                             # 3~5일에 걸쳐
    assert inj[0].ts.date() == AT
    # 처음 보는 상대(이름·계좌 모두)
    assert len({t.counterparty_id for t in inj}) == 1
    assert inj[0].counterparty_id not in {t.counterparty_id for t in hist}
    assert inj[0].counterparty not in {t.counterparty for t in hist}
    # SPEC §5 임계: 7일 안 심야 이체 3건 이상
    assert (inj[2].ts - inj[0].ts) < timedelta(days=7)


@pytest.mark.parametrize("key", list(synth.PERSONAS))
@pytest.mark.parametrize("seed", SEEDS)
def test_payee_surge_definition(key: str, seed: int) -> None:
    hist = _base(key, seed)
    out = synth.inject_scenario(hist, SignalCode.PAYEE_SURGE, AT, seed=seed)
    inj = _injected(out, SignalCode.PAYEE_SURGE)
    assert 4 <= len(inj) <= 7
    assert all(t.channel == Channel.TRANSFER and t.direction == Direction.OUT for t in inj)
    assert len({t.counterparty_id for t in inj}) == 1
    assert inj[0].counterparty_id not in {t.counterparty_id for t in hist}
    assert inj[-1].ts - inj[0].ts < timedelta(days=7)
    # 평소 7일 송금 합계(시작일 이전 이력 기준) 대비 5배 이상
    before = _before(hist, AT)
    weeks = max(1.0, (AT - hist[0].ts.date()).days / 7)
    baseline = sum(t.amount for t in before if t.channel == Channel.TRANSFER) / weeks
    total = sum(t.amount for t in inj)
    assert total >= 5 * baseline
    assert total >= 300_000
    # 시나리오 거래가 '평소' 기준에 섞여도 5배 이상 유지(여유 설계)
    assert total >= 5 * (baseline + total / weeks)


@pytest.mark.parametrize("key", list(synth.PERSONAS))
@pytest.mark.parametrize("seed", SEEDS)
def test_micropay_surge_definition(key: str, seed: int) -> None:
    p = synth.PERSONAS[key]
    hist = _base(key, seed)
    out = synth.inject_scenario(hist, SignalCode.MICROPAY_SURGE, AT, seed=seed)
    inj = _injected(out, SignalCode.MICROPAY_SURGE)
    assert 8 <= len(inj) <= 15
    assert all(t.channel == Channel.MICROPAY and t.direction == Direction.OUT for t in inj)
    assert all(10_000 <= t.amount <= 100_000 for t in inj)
    assert all(t.line_id == p.telecom_line for t in inj)
    assert inj[-1].ts - inj[0].ts < timedelta(days=7)
    # SPEC §5 임계: max(5, 평소 7일 평균×3) 이상
    before = _before(hist, AT)
    weeks = max(1.0, (AT - hist[0].ts.date()).days / 7)
    usual = sum(t.channel == Channel.MICROPAY for t in before) / weeks
    assert len(inj) >= max(5, usual * 3)


@pytest.mark.parametrize("key", list(synth.PERSONAS))
@pytest.mark.parametrize("seed", SEEDS)
def test_new_merchant_high_value_definition(key: str, seed: int) -> None:
    hist = _base(key, seed)
    out = synth.inject_scenario(hist, SignalCode.NEW_MERCHANT_HIGH_VALUE, AT, seed=seed)
    inj = _injected(out, SignalCode.NEW_MERCHANT_HIGH_VALUE)
    assert 2 <= len(inj) <= 4
    assert all(t.channel == Channel.CARD and t.direction == Direction.OUT for t in inj)
    ids = [t.counterparty_id for t in inj]
    assert len(set(ids)) == len(ids)                                   # 서로 다른 가맹점
    assert not set(ids) & {t.counterparty_id for t in hist}           # 처음 보는 가맹점
    cards = [t.amount for t in _before(hist, AT) if t.channel == Channel.CARD]
    p95 = float(np.percentile(cards, 95))
    assert all(t.amount >= 3 * p95 for t in inj)
    assert all(t.amount >= 100_000 for t in inj)                       # SPEC §5 하한
    assert inj[-1].ts - inj[0].ts < timedelta(days=7)                  # 7일 안 2건 이상


@pytest.mark.parametrize("key", list(synth.PERSONAS))
@pytest.mark.parametrize("seed", SEEDS)
def test_multi_line_telecom_definition(key: str, seed: int) -> None:
    p = synth.PERSONAS[key]
    hist = _base(key, seed)
    out = synth.inject_scenario(hist, SignalCode.MULTI_LINE_TELECOM, AT, seed=seed)
    inj = _injected(out, SignalCode.MULTI_LINE_TELECOM)
    assert 2 <= len(inj) <= 3
    assert all(t.channel == Channel.TELECOM_BILL and t.direction == Direction.OUT for t in inj)
    lines = [t.line_id for t in inj]
    assert len(set(lines)) == len(lines)                               # 서로 다른 회선
    assert p.telecom_line not in lines
    assert not set(lines) & {t.line_id for t in hist}                  # 새 회선
    assert inj[-1].ts - inj[0].ts < timedelta(days=30)                 # 30일 안


def test_scenario_counterparty_not_in_future_history_either() -> None:
    hist = _base(days=120)
    out = synth.inject_scenario(hist, SignalCode.PAYEE_SURGE, START + timedelta(days=60), seed=3)
    inj = _injected(out, SignalCode.PAYEE_SURGE)
    assert inj[0].counterparty_id not in {t.counterparty_id for t in hist}


# ---------------------------------------------------------------------------
# make_dataset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(synth.PERSONAS))
def test_make_dataset_all_scenarios(key: str) -> None:
    days = 120
    txns = synth.make_dataset(key, seed=4, days=days, scenarios=list(SignalCode))
    assert [t.ts for t in txns] == sorted(t.ts for t in txns)
    assert len({t.id for t in txns}) == len(txns)
    window_start = START + timedelta(days=days - synth.SCENARIO_WINDOW_DAYS)
    end = START + timedelta(days=days)
    for code in SignalCode:
        inj = _injected(txns, code)
        assert inj, code
        assert all(window_start <= t.ts.date() < end for t in inj)     # 마지막 30일 안
    labels = {t.label for t in txns}
    assert labels == {"normal", *(c.value for c in SignalCode)}


def test_make_dataset_none_or_empty_means_normal_only() -> None:
    a = synth.make_dataset("worker", seed=1)
    b = synth.make_dataset("worker", seed=1, scenarios=[])
    assert _dicts(a) == _dicts(b)
    assert {t.label for t in a} == {"normal"}


def test_make_dataset_normal_part_matches_control_group() -> None:
    control = synth.make_dataset("benefit", seed=9)
    full = synth.make_dataset("benefit", seed=9, scenarios=synth.ALL_SCENARIOS)
    assert _dicts([t for t in full if t.label == "normal"]) == _dicts(control)
    assert _dicts(control) == _dicts(synth.generate_history(synth.PERSONAS["benefit"], START, 120, 9))


def test_make_dataset_deterministic_and_order_independent() -> None:
    codes = list(SignalCode)
    a = synth.make_dataset("student", seed=2, scenarios=codes)
    b = synth.make_dataset("student", seed=2, scenarios=list(reversed(codes)))
    c = synth.make_dataset("student", seed=3, scenarios=codes)
    assert _dicts(a) == _dicts(b)
    assert _dicts(a) != _dicts(c)


def test_make_dataset_scenarios_differ_between_personas() -> None:
    w = synth.make_dataset("worker", seed=0, scenarios=synth.ALL_SCENARIOS)
    b = synth.make_dataset("benefit", seed=0, scenarios=synth.ALL_SCENARIOS)
    sig = lambda txns: [(t.label, t.ts.date(), t.amount) for t in txns if t.label != "normal"]
    assert sig(w) != sig(b)


def test_make_dataset_validates_arguments() -> None:
    with pytest.raises(ValueError):
        synth.make_dataset("nobody", seed=0)
    with pytest.raises(ValueError):
        synth.make_dataset("worker", seed=-1)
    with pytest.raises(ValueError):
        synth.make_dataset("worker", seed=0, days=20, scenarios=[SignalCode.PAYEE_SURGE])
    with pytest.raises(ValueError):
        synth.make_dataset("worker", seed=0, scenarios=["not_a_signal"])


def test_make_dataset_scenario_thresholds_hold_in_full_dataset() -> None:
    """시나리오를 모두 넣은 데이터에서도 각 시나리오가 자기 정의를 지킨다."""
    for key in synth.PERSONAS:
        for seed in range(5):
            txns = synth.make_dataset(key, seed=seed, scenarios=synth.ALL_SCENARIOS)
            night = _injected(txns, SignalCode.NIGHT_REPEAT_TRANSFER)
            assert len(night) >= 4 and all(t.ts.hour <= 4 for t in night)
            micro = _injected(txns, SignalCode.MICROPAY_SURGE)
            assert len(micro) >= 8 and micro[-1].ts - micro[0].ts < timedelta(days=7)
            hv = _injected(txns, SignalCode.NEW_MERCHANT_HIGH_VALUE)
            cards = [t.amount for t in txns if t.channel == Channel.CARD and t.ts < hv[0].ts]
            assert all(t.amount >= max(3 * np.percentile(cards, 95), 100_000) for t in hv)
            lines = {t.line_id for t in _injected(txns, SignalCode.MULTI_LINE_TELECOM)}
            assert len(lines) >= 2
            payee = _injected(txns, SignalCode.PAYEE_SURGE)
            assert len(payee) >= 4 and len({t.counterparty_id for t in payee}) == 1


# ---------------------------------------------------------------------------
# 표준 CSV
# ---------------------------------------------------------------------------

def test_csv_roundtrip(tmp_path) -> None:
    txns = synth.make_dataset("worker", seed=1, scenarios=synth.ALL_SCENARIOS)
    path = synth.to_csv(txns, tmp_path / "sub" / "data.csv")
    assert path.exists()
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header == ",".join(synth.STANDARD_COLUMNS)
    back = synth.from_csv(path)
    assert _dicts(back) == _dicts(txns)


def test_csv_roundtrip_none_label_and_commas(tmp_path) -> None:
    t = Transaction(id="a,1", ts=datetime(2026, 1, 2, 3, 4, 5), amount=1234,
                    direction=Direction.OUT, channel=Channel.CARD, counterparty='가게, "본점"',
                    counterparty_id="M-1", memo="줄\n바꿈", label=None)
    path = synth.to_csv([t], tmp_path / "one.csv")
    back = synth.from_csv(path)
    assert back[0].to_dict() == t.to_dict()
    assert back[0].label is None


def test_from_csv_rejects_non_standard(tmp_path) -> None:
    path = tmp_path / "bank.csv"
    path.write_text("거래일시,출금액\n2026-01-01 10:00,1000\n", encoding="utf-8")
    with pytest.raises(ValueError, match="표준 CSV"):
        synth.from_csv(path)


def test_from_csv_reports_bad_line(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(",".join(synth.STANDARD_COLUMNS) + "\n"
                    "x1,2026-01-01T10:00:00,1000,sideways,card,,,,,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2번째 줄"):
        synth.from_csv(path)


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

def test_parse_standard_ts_is_naive_and_range_checked() -> None:
    from datetime import datetime

    assert synth.parse_standard_ts("2026-09-01T10:00:00.123").microsecond == 0
    aware = synth.parse_standard_ts("2026-09-01T10:00:00+09:00")
    assert aware.tzinfo is None
    assert synth.parse_standard_ts("2026-09-01T01:00:00Z") == (
        datetime.fromisoformat("2026-09-01T01:00:00+00:00").astimezone().replace(tzinfo=None))
    for bad in ("0001-01-01T00:00:00", "9999-12-31T23:59:59", "1899-12-31T00:00:00+09:00"):
        with pytest.raises(synth.DateRangeError):
            synth.parse_standard_ts(bad)


# ---- 리뷰 수정 확인(round 3) ------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("2026-09-01T10:00:00+0900", "2026-09-01T10:00:00+09:00"),
    ("2026-09-01T10:00:00+09", "2026-09-01T10:00:00+09:00"),
    ("2026-09-01T10:00:00.5", "2026-09-01T10:00:00.500000"),
    ("2026-09-01T10:00:00.1234567", "2026-09-01T10:00:00.123456"),
    ("20260901T100000", "2026-09-01T10:00:00"),
    ("2026-09-01 10:00", "2026-09-01T10:00:00"),
    ("2026-09-01T01:00:00z", "2026-09-01T01:00:00+00:00"),
    ("2026-09-01", "2026-09-01"),
    ("not a date", "not a date"),
])
def test_normalize_iso_ts_for_python_310(text: str, expected: str) -> None:
    """[변경 r3] Python 3.10 fromisoformat이 읽는 모양으로 맞춘다(3.11+와 같은 결과)."""
    assert synth.normalize_iso_ts(text) == expected


def test_parse_standard_ts_reads_iso_variants_same_on_every_python() -> None:
    from datetime import datetime

    base = synth.parse_standard_ts("2026-09-01T10:00:00+09:00")
    assert synth.parse_standard_ts("2026-09-01T10:00:00+0900") == base
    assert synth.parse_standard_ts("2026-09-01T10:00:00.5") == datetime(2026, 9, 1, 10, 0, 0)
    assert synth.parse_standard_ts("20260901T100000") == datetime(2026, 9, 1, 10, 0, 0)
    with pytest.raises(ValueError):
        synth.parse_standard_ts("2026-13-01T10:00:00")
