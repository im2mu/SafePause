"""eval/metrics.py · eval/report.py 테스트."""
from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from safepause.data.loader import load_csv
from safepause.data.synth import ALL_SCENARIOS, DEFAULT_START, make_dataset
from safepause.eval import metrics, report
from safepause.eval.metrics import (
    DISCLAIMER,
    FILE_DISCLAIMER,
    aggregate,
    compare_modes,
    default_seeds,
    evaluate,
    evaluate_file,
    is_normal_label,
    score_case,
    split_baseline,
    synthetic_case,
)
from safepause.models import (
    Channel,
    Direction,
    RiskAssessment,
    RiskLevel,
    SignalCode,
    SignalHit,
    Transaction,
)

ROOT = Path(__file__).resolve().parents[1]
BANK_EXAMPLE = ROOT / "sample_data" / "bank_export_example.csv"
T0 = datetime(2026, 6, 1, 12, 0)


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------

def _txn(tid: str, minutes: int, label: str | None = "normal", amount: int = 10_000,
         channel: Channel = Channel.TRANSFER) -> Transaction:
    return Transaction(id=tid, ts=T0 + timedelta(minutes=minutes), amount=amount,
                       direction=Direction.OUT, channel=channel, counterparty="상대",
                       counterparty_id="acct", label=label)


def _assess(txn: Transaction, level: RiskLevel, codes: tuple[SignalCode, ...] = ()) -> RiskAssessment:
    hits = [SignalHit(code=c, severity=RiskLevel.CAUTION if level == RiskLevel.NONE else level,
                      evidence={}) for c in codes]
    return RiskAssessment(txn_id=txn.id, level=level, rule_hits=hits, anomaly_score=0.0, reasons=[])


@pytest.fixture(scope="module")
def comparison() -> dict:
    return compare_modes(["worker", "student"], [1, 2])


@pytest.fixture(scope="module")
def fused_single() -> dict:
    return evaluate(["worker"], [1], "fused")


# ---------------------------------------------------------------------------
# 기본 도우미
# ---------------------------------------------------------------------------

def test_is_normal_label():
    assert is_normal_label(None) and is_normal_label("") and is_normal_label("normal")
    assert not is_normal_label(SignalCode.PAYEE_SURGE.value)


def test_default_seeds():
    assert default_seeds(3) == [1, 2, 3]
    with pytest.raises(ValueError):
        default_seeds(0)


# ---------------------------------------------------------------------------
# 채점(손으로 만든 거래로 정확한 값 확인)
# ---------------------------------------------------------------------------

def test_score_case_scenario_detection_and_first_alert():
    night = SignalCode.NIGHT_REPEAT_TRANSFER
    s1 = _txn("s1", 0, night.value, amount=100_000)
    s2 = _txn("s2", 10, night.value, amount=200_000)
    s3 = _txn("s3", 20, night.value, amount=300_000)
    m1 = _txn("m1", 30, SignalCode.MICROPAY_SURGE.value, channel=Channel.MICROPAY)
    n1, n2 = _txn("n1", 40), _txn("n2", 50)
    txns = [s1, s2, s3, m1, n1, n2]
    assessed = [
        _assess(s1, RiskLevel.NONE),
        _assess(s2, RiskLevel.CAUTION, (night,)),
        _assess(s3, RiskLevel.HIGH, (night,)),
        _assess(m1, RiskLevel.NONE),
        _assess(n1, RiskLevel.HIGH, (SignalCode.PAYEE_SURGE,)),
        _assess(n2, RiskLevel.NONE),
    ]
    out = score_case(txns, assessed, eval_days=30)

    night_out = out.scenarios[night.value]
    assert night_out.n_txns == 3
    assert night_out.caution and night_out.high and night_out.matched
    assert night_out.first_alert_position == 2
    assert night_out.amount_before_first_alert == 100_000

    micro = out.scenarios[SignalCode.MICROPAY_SURGE.value]
    assert not micro.caution and not micro.high and not micro.matched
    assert micro.first_alert_position is None and micro.amount_before_first_alert is None

    assert out.n_normal == 2
    assert out.normal_alert_ids == {"n1"} and out.normal_high_ids == {"n1"}
    assert out.confusion["caution"] == {"tp": 2, "fp": 1, "fn": 2, "tn": 1}
    assert out.confusion["high"] == {"tp": 1, "fp": 1, "fn": 3, "tn": 1}


def test_score_case_matched_needs_same_signal():
    code = SignalCode.PAYEE_SURGE
    s1 = _txn("s1", 0, code.value)
    out = score_case([s1], [_assess(s1, RiskLevel.HIGH, (SignalCode.NIGHT_REPEAT_TRANSFER,))],
                     eval_days=30)
    assert out.scenarios[code.value].caution and not out.scenarios[code.value].matched


def test_score_case_rejects_misaligned_results():
    a, b = _txn("a", 0), _txn("b", 1)
    with pytest.raises(ValueError):
        score_case([a, b], [_assess(a, RiskLevel.NONE)], eval_days=30)
    with pytest.raises(ValueError):
        score_case([a, b], [_assess(b, RiskLevel.NONE), _assess(a, RiskLevel.NONE)], eval_days=30)


def test_aggregate_rates_monthly_and_spillover():
    code = SignalCode.MULTI_LINE_TELECOM
    # 사례 1: 시나리오 탐지(고위험), 정상 2건 중 1건 알림(대조군에서는 알림 없음 → 겹침 1건)
    s, n1, n2 = _txn("s", 0, code.value), _txn("n1", 1), _txn("n2", 2)
    c1 = score_case([s, n1, n2],
                    [_assess(s, RiskLevel.HIGH, (code,)), _assess(n1, RiskLevel.CAUTION),
                     _assess(n2, RiskLevel.NONE)],
                    [n1, n2], [_assess(n1, RiskLevel.NONE), _assess(n2, RiskLevel.NONE)],
                    eval_days=30, persona="worker", seed=1, model_version="v")
    # 사례 2: 시나리오 놓침, 정상 2건 알림 없음, 대조군 1건 고위험
    t, m1, m2 = _txn("t", 0, code.value), _txn("m1", 1), _txn("m2", 2)
    c2 = score_case([t, m1, m2], [_assess(x, RiskLevel.NONE) for x in (t, m1, m2)],
                    [m1, m2], [_assess(m1, RiskLevel.HIGH), _assess(m2, RiskLevel.NONE)],
                    eval_days=30, persona="student", seed=1, model_version="v")
    agg = aggregate([c1, c2])

    sc = agg["scenario_recall"][code.value]
    assert (sc["n"], sc["caution"], sc["high"], sc["matched"]) == (2, 1, 1, 1)
    assert sc["recall_caution"] == 0.5 and sc["recall_high"] == 0.5
    assert agg["overall"]["n"] == 2 and agg["overall"]["recall_caution"] == 0.5

    nm = agg["normal"]
    assert (nm["n_txns"], nm["alerts"], nm["high"]) == (4, 1, 0)
    assert nm["alert_rate"] == 0.25 and nm["high_rate"] == 0.0
    assert nm["monthly_alerts"] == 0.5          # 알림 1건 / 60일 × 30
    assert nm["spillover_alerts"] == 1

    ctl = agg["control"]
    assert (ctl["n_txns"], ctl["alerts"], ctl["high"]) == (4, 1, 1)
    assert ctl["monthly_high"] == 0.5

    assert set(agg["by_persona"]) == {"worker", "student"}
    assert agg["by_persona"]["worker"]["recall_caution"] == 1.0
    assert agg["by_persona"]["student"]["recall_caution"] == 0.0
    assert agg["model_versions"] == ["v"]


def test_aggregate_without_control():
    s = _txn("s", 0, SignalCode.PAYEE_SURGE.value)
    agg = aggregate([score_case([s], [_assess(s, RiskLevel.NONE)], eval_days=30)])
    assert agg["control"] is None
    assert agg["normal"]["spillover_alerts"] is None
    assert agg["normal"]["alert_rate"] is None     # 정상 거래 0건 → 비율 없음


# ---------------------------------------------------------------------------
# 합성 사례 준비
# ---------------------------------------------------------------------------

def test_synthetic_case_splits_on_date_boundary():
    case = synthetic_case("worker", 1)
    cutoff = datetime.combine(DEFAULT_START + timedelta(days=90), datetime.min.time())
    assert case.eval_days == 30
    assert all(t.ts < cutoff for t in case.baseline)
    assert all(t.ts >= cutoff for t in case.evaluated)
    assert all(is_normal_label(t.label) for t in case.baseline)
    labels = {t.label for t in case.evaluated}
    assert {c.value for c in ALL_SCENARIOS} <= labels
    assert len(case.baseline) + len(case.evaluated) == len(make_dataset("worker", 1, 120, ALL_SCENARIOS))


def test_control_case_has_same_normal_transactions():
    case = synthetic_case("benefit", 4)
    ctrl = synthetic_case("benefit", 4, scenarios=False)
    assert [t.id for t in case.evaluated if is_normal_label(t.label)] == [t.id for t in ctrl.evaluated]
    assert [t.id for t in case.baseline_normal] == [t.id for t in ctrl.baseline_normal]


@pytest.mark.parametrize("days,baseline_days", [(30, 10), (120, 91), (120, 0), (60, 45)])
def test_period_validation(days, baseline_days):
    with pytest.raises(ValueError):
        synthetic_case("worker", 1, days, baseline_days)


# ---------------------------------------------------------------------------
# evaluate / compare_modes
# ---------------------------------------------------------------------------

def test_evaluate_structure(fused_single):
    r = fused_single
    assert r["kind"] == "synthetic" and r["mode"] == "fused" and r["data"] == "synthetic"
    assert r["note"] == DISCLAIMER
    assert r["personas"] == ["worker"] and r["seeds"] == [1] and r["n_cases"] == 1
    assert (r["days"], r["baseline_days"], r["eval_days"]) == (120, 90, 30)
    assert list(r["scenario_recall"]) == [c.value for c in SignalCode]
    for s in r["scenario_recall"].values():
        assert s["n"] == 1
        assert 0.0 <= s["recall_caution"] <= 1.0 and 0.0 <= s["recall_high"] <= s["recall_caution"]
    assert r["normal"]["n_txns"] == r["control"]["n_txns"] > 0
    for block in (r["normal"], r["control"]):
        assert 0.0 <= block["alert_rate"] <= 1.0
        assert block["high"] <= block["alerts"]
    assert set(r["confusion"]) == {"caution", "high"}
    assert r["settings"]["night_start_hour"] == 23
    assert {"python", "numpy", "scikit-learn", "safepause"} <= set(r["environment"])
    json.dumps(r)  # 기본 자료형만 담겨야 한다


def test_evaluate_is_deterministic(fused_single):
    assert evaluate(["worker"], [1], "fused") == fused_single


def test_confusion_totals_match_counts(fused_single):
    r = fused_single
    for key in ("caution", "high"):
        c = r["confusion"][key]
        assert c["fp"] + c["tn"] == r["normal"]["n_txns"]
    assert r["confusion"]["caution"]["fp"] == r["normal"]["alerts"]
    assert r["confusion"]["high"]["fp"] == r["normal"]["high"]


def test_compare_modes_matches_single_mode_runs(comparison):
    assert comparison["kind"] == "comparison"
    assert comparison["mode_order"] == ["fused", "rules", "anomaly"]
    assert set(comparison["modes"]) == {"fused", "rules", "anomaly"}
    for mode in ("rules", "anomaly"):
        single = evaluate(["worker", "student"], [1, 2], mode)
        assert comparison["modes"][mode] == single


def test_mode_specific_properties(comparison):
    rules = comparison["modes"]["rules"]
    anomaly = comparison["modes"]["anomaly"]
    assert rules["model_versions"] == ["rules-v1"]
    assert all(v.startswith("iforest-v1") for v in anomaly["model_versions"])
    # AI 이상탐지만 모드는 룰을 쓰지 않는다
    assert all(s["matched"] == 0 for s in anomaly["scenario_recall"].values())
    assert comparison["modes"]["fused"]["n_cases"] == 4


@pytest.mark.parametrize("kwargs", [
    {"persona_keys": ["nobody"], "seeds": [1]},
    {"persona_keys": [], "seeds": [1]},
    {"persona_keys": ["worker"], "seeds": []},
    {"persona_keys": ["worker"], "seeds": [-1]},
    {"persona_keys": ["worker"], "seeds": [1], "mode": "magic"},
    {"persona_keys": ["worker"], "seeds": [1], "baseline_days": 100},
])
def test_evaluate_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        evaluate(**kwargs)


def test_compare_modes_rejects_empty_or_bad_modes():
    with pytest.raises(ValueError):
        compare_modes(["worker"], [1], modes=[])
    with pytest.raises(ValueError):
        compare_modes(["worker"], [1], modes=["fused", "nope"])


# ---------------------------------------------------------------------------
# evaluate_file(사용자 거래내역 오탐 근사)
# ---------------------------------------------------------------------------

def test_split_baseline_rules():
    txns = make_dataset("student", 3, 60)
    shuffled = list(reversed(txns))
    base, ev = split_baseline(shuffled, 0.75)
    assert len(base) == math.ceil(len(txns) * 0.75) and len(base) + len(ev) == len(txns)
    assert max(t.ts for t in base) <= min(t.ts for t in ev)

    small = txns[:35]
    base, ev = split_baseline(small, 0.5)
    assert len(base) == 30 and len(ev) == 5        # 학습은 최소 30건

    with pytest.raises(ValueError):
        split_baseline(txns[:30], 0.75)             # 평가할 거래가 남지 않음
    for bad in (0.0, 1.0, 1.5):
        with pytest.raises(ValueError):
            split_baseline(txns, bad)


def test_evaluate_file_on_normal_data():
    txns = make_dataset("student", 3, 120)
    r = evaluate_file(txns)
    assert r["kind"] == "file" and r["note"] == FILE_DISCLAIMER
    assert r["n_total"] == len(txns) and r["n_baseline"] + r["n_eval"] == len(txns)
    assert r["fitted"] is True and r["model_version"].startswith("rules-v1+iforest-v1")
    assert 0 <= r["high"] <= r["alerts"] <= r["n_eval"]
    assert r["alert_rate"] == pytest.approx(r["alerts"] / r["n_eval"], abs=1e-6)
    assert sum(v["n"] for v in r["by_channel"].values()) == r["n_eval"]
    assert sum(v["alerts"] for v in r["by_channel"].values()) == r["alerts"]
    assert len(r["alert_list"]) == r["alerts"]
    for row in r["alert_list"]:
        assert row["level"] in ("caution", "high") and row["card_title"]
    json.dumps(r)


def test_evaluate_file_ignores_labels_and_is_deterministic():
    txns = make_dataset("worker", 5, 120, ALL_SCENARIOS)
    r1 = evaluate_file(txns)
    unlabeled = [replace(t, label=None) for t in txns]
    assert evaluate_file(unlabeled) == r1
    assert r1["alerts"] > 0                         # 시나리오가 섞인 파일이면 알림이 나온다


def test_evaluate_file_listing_limit_and_modes():
    txns = make_dataset("worker", 5, 120, ALL_SCENARIOS)
    r = evaluate_file(txns, max_listed=1)
    assert len(r["alert_list"]) == 1 and r["alert_list_truncated"] is True
    rules = evaluate_file(txns, mode="rules")
    assert rules["fitted"] is False and rules["model_version"] == "rules-v1"
    assert rules["anomaly_only"] == 0
    with pytest.raises(ValueError):
        evaluate_file(txns, mode="bad")


def test_evaluate_file_on_bank_example():
    txns, _ = load_csv(BANK_EXAMPLE)
    r = evaluate_file(txns)
    assert r["n_total"] == 46
    # 예시 파일 끝의 새 상대 심야 이체가 고위험으로 잡힌다
    assert any(a["counterparty"] == "김*호" and a["level"] == "high"
               and SignalCode.NIGHT_REPEAT_TRANSFER.value in a["signals"] for a in r["alert_list"])


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def _table_rows_consistent(markdown: str) -> None:
    """각 표의 모든 행이 머리글과 같은 칸 수인지."""
    block: list[str] = []
    for line in markdown.splitlines() + [""]:
        if line.startswith("|"):
            block.append(line)
            continue
        if block:
            widths = {row.replace("\\|", "").count("|") for row in block}
            assert len(widths) == 1, block
            assert set(block[1].replace("|", "")) == {"-"}
            block = []


def test_write_report_comparison(tmp_path, comparison):
    paths = report.write_report(comparison, tmp_path / "out")
    assert paths["json"].name == "eval_results.json" and paths["markdown"].name == "eval_report.md"
    assert json.loads(paths["json"].read_text(encoding="utf-8")) == comparison
    md = paths["markdown"].read_text(encoding="utf-8")
    assert DISCLAIMER in md and "실제 피해 데이터 검증 아님" in md
    for m in ("fused", "rules", "anomaly"):
        assert report.mode_name(m) in md
    for name in report.SIGNAL_NAMES_KO.values():
        assert name in md
    o = comparison["modes"]["fused"]["overall"]
    assert f"({o['caution']}/{o['n']})" in md          # 수치는 결과에서 온다
    assert "대조군" in md and "seed | 1, 2 (2개)" in md
    # AI 단독 '확인해요'가 알림 대상이 되는 조건은 둘 다(등급 '확인할 때도' + 범위 '모든 것', policy.in_signal_scope)
    assert "'확인할 때도'로 바꾸고 '무엇을 알릴까요?'를 '모든 것'으로 두면" in md
    _table_rows_consistent(md)
    assert not list((tmp_path / "out").glob("*.tmp"))


def test_write_report_single_mode(tmp_path, fused_single):
    paths = report.write_report(fused_single, tmp_path)
    md = paths["markdown"].read_text(encoding="utf-8")
    assert report.mode_name("fused") in md
    assert report.mode_name("anomaly") + " (anomaly)" not in md
    _table_rows_consistent(md)


def test_write_report_file_result(tmp_path):
    txns, _ = load_csv(BANK_EXAMPLE)
    result = evaluate_file(txns)
    paths = report.write_report(result, tmp_path)
    assert paths["json"].name == "file_eval_results.json"
    assert paths["markdown"].name == "file_eval_report.md"
    md = paths["markdown"].read_text(encoding="utf-8")
    assert FILE_DISCLAIMER in md and "김*호" in md
    _table_rows_consistent(md)


def test_write_report_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        report.write_report({"kind": "mystery"}, tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_report_formatting_helpers():
    assert report.pct(None) == "-" and report.pct(0.1234) == "12.3%" and report.pct(1.0, 0) == "100%"
    assert report.num(None) == "-" and report.num(3.0) == "3" and report.num(1234.5) == "1,234.50"
    assert report.won(57880.4) == "57,880원"
    assert report.seeds_text([1, 2, 3, 4]) == "1~4 (4개)"
    assert report.seeds_text([5, 9]) == "5, 9 (2개)"
    table = report.md_table(["a", "b"], [["x|y", 1]])
    assert "x\\|y" in table and table.splitlines()[1] == "|---|---|"
    assert report.signal_name("payee_surge") == "특정 계좌 송금 급증"
    assert report.signal_name("unknown") == "unknown"


def test_metrics_module_has_no_network_imports():
    src = Path(metrics.__file__).read_text(encoding="utf-8") + Path(report.__file__).read_text(encoding="utf-8")
    for banned in ("urllib", "requests", "http.client", "socket"):
        assert f"import {banned}" not in src and f"from {banned}" not in src
