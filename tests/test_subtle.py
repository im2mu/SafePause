"""경계 변형(subtle) 시나리오 테스트(SPEC §3·§8·§9 [추가 r4], 사전 등록 정의).

- subtle 주입이 정의대로인지(건수·금액·시각·처음 보는 상대/가게/회선·기간)
- standard 동작이 바꾸기 전과 똑같은지(바꾸기 전 출력의 SHA-256과 비교)
- eval·보고서·명령행이 intensity를 나눠 다루는지
탐지 성능 수치는 여기서 검사하지 않는다(결과는 docs/eval에서 본다).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timedelta

import numpy as np
import pytest

from safepause import cli
from safepause.data import synth
from safepause.eval import report
from safepause.eval.metrics import compare_modes, evaluate, synthetic_case
from safepause.models import Channel, Direction, SignalCode, Transaction

START = synth.DEFAULT_START
AT = START + timedelta(days=85)
SEEDS = range(8)
PERSONAS = list(synth.PERSONAS)


def _dicts(txns: list[Transaction]) -> list[dict]:
    return [t.to_dict() for t in txns]


def _fp(txns: list[Transaction]) -> str:
    text = json.dumps(_dicts(txns), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _base(key: str, seed: int, days: int = 100) -> list[Transaction]:
    return synth.generate_history(synth.PERSONAS[key], START, days, seed=seed)


def _before(txns: list[Transaction], at: date) -> list[Transaction]:
    cutoff = datetime.combine(at, time(0, 0))
    return [t for t in txns if t.ts < cutoff]


def _subtle(hist: list[Transaction], code: SignalCode, seed: int) -> list[Transaction]:
    out = synth.inject_scenario(hist, code, AT, seed=seed, intensity="subtle")
    return [t for t in out if t.label == code.value]


# ---------------------------------------------------------------------------
# standard 불변
# ---------------------------------------------------------------------------

# 이 변경(r4) 전의 코드로 만든 출력의 SHA-256. standard 동작이 바뀌면 달라진다.
STANDARD_FINGERPRINTS = {
    "worker-1": "ae57585e7672bac1f446c27083ca1fa6199108a0dc5d12335fdf432ccadb9557",
    "worker-7": "c65d443772501c3ea6da58074c905b43c9c74a75fbd1cd0fc19ee4899d43ef54",
    "benefit-1": "d61168a038df6f8b9b4fadca67011107bc5a0ee92335921bd4587b215c9f8b02",
    "benefit-7": "fcd1affa7bb1461c276c75de094f31032d3f290de88554e320233fc145895c52",
    "student-1": "41d03d4b4bd966b1d8d74d46e14bba115ab4019c7b713c64f7bcf857cb5283fd",
    "student-7": "29d2b9541343ee2b3b57a1dd8b62fbf90ef6a2550831e6f861d5bd8196df0fdb",
    "inject-night_repeat_transfer": "67c34f9d3038d7451a4cabc6d5774b1cda294555f02f80f8835380f7b605eee4",
    "inject-payee_surge": "8e5e084ab0c665f5de56f47acafdb4a8bbfd823cc57b41d43a61bf9fd272a951",
    "inject-micropay_surge": "9977e07651de4c547bb101cef4cfa1726b5afdfeed57bcae3515a26ac49745d2",
    "inject-new_merchant_high_value": "04a28ab8b7d6177b02f776b9a87f432c94144799a99cd2c1b401e7e731d19003",
    "inject-multi_line_telecom": "b3d0a43cd2dacc001bcc48fbc1aa10504338fab4d1671a8648c97bfb93ad5abd",
}


def test_standard_output_is_unchanged_by_r4() -> None:
    for key in PERSONAS:
        for seed in (1, 7):
            txns = synth.make_dataset(key, seed, scenarios=synth.ALL_SCENARIOS)
            assert _fp(txns) == STANDARD_FINGERPRINTS[f"{key}-{seed}"]
            explicit = synth.make_dataset(key, seed, scenarios=synth.ALL_SCENARIOS, intensity="standard")
            assert _dicts(explicit) == _dicts(txns)
    hist = _base("worker", 0)
    for code in SignalCode:
        out = synth.inject_scenario(hist, code, AT, seed=11)
        assert _fp(out) == STANDARD_FINGERPRINTS[f"inject-{code.value}"]
        assert _dicts(synth.inject_scenario(hist, code, AT, seed=11, intensity="standard")) == _dicts(out)


def test_invalid_intensity_is_rejected() -> None:
    hist = _base("worker", 0)
    with pytest.raises(ValueError):
        synth.inject_scenario(hist, SignalCode.PAYEE_SURGE, AT, seed=1, intensity="weak")
    with pytest.raises(ValueError):
        synth.make_dataset("worker", 1, scenarios=synth.ALL_SCENARIOS, intensity="")
    with pytest.raises(ValueError):
        synthetic_case("worker", 1, intensity="hard")
    with pytest.raises(ValueError):
        evaluate(["worker"], [1], "rules", intensity="hard")
    with pytest.raises(ValueError):
        compare_modes(["worker"], [1], intensity="hard")


# ---------------------------------------------------------------------------
# subtle 정의(SPEC §3 [추가 r4])
# ---------------------------------------------------------------------------

def _is_new_payee(inj: list[Transaction], hist: list[Transaction]) -> bool:
    return (len({t.counterparty_id for t in inj}) == 1
            and inj[0].counterparty_id not in {t.counterparty_id for t in hist}
            and inj[0].counterparty not in {t.counterparty for t in hist})


@pytest.mark.parametrize("key", PERSONAS)
@pytest.mark.parametrize("seed", SEEDS)
def test_subtle_night_repeat_definition(key: str, seed: int) -> None:
    hist = _base(key, seed)
    inj = _subtle(hist, SignalCode.NIGHT_REPEAT_TRANSFER, seed)
    assert len(inj) == 2
    assert all(t.channel == Channel.TRANSFER and t.direction == Direction.OUT for t in inj)
    assert all(0 <= t.ts.hour <= 4 for t in inj)                            # 00~04시
    assert all(300_000 <= t.amount <= 800_000 and t.amount % 10_000 == 0 for t in inj)
    assert inj[0].ts.date() == AT and inj[-1].ts.date() <= AT + timedelta(days=6)   # 7일 안
    assert inj[-1].ts - inj[0].ts < timedelta(days=7)
    assert _is_new_payee(inj, hist)                                          # 처음 보는 상대 한 사람


@pytest.mark.parametrize("key", PERSONAS)
@pytest.mark.parametrize("seed", SEEDS)
def test_subtle_payee_surge_definition(key: str, seed: int) -> None:
    hist = _base(key, seed)
    inj = _subtle(hist, SignalCode.PAYEE_SURGE, seed)
    assert len(inj) == 2
    assert all(t.channel == Channel.TRANSFER and t.direction == Direction.OUT for t in inj)
    assert all(9 <= t.ts.hour <= 20 for t in inj)
    assert all(t.amount >= 1_000 for t in inj)
    assert inj[0].ts.date() == AT and inj[-1].ts - inj[0].ts < timedelta(days=7)
    assert _is_new_payee(inj, hist)
    # 합계 = 평소 7일 송금 합계(standard와 같은 synth 기준값) × 2.0~2.9
    before = _before(hist, AT)
    weeks = max(1.0, (AT - hist[0].ts.date()).days / 7)
    baseline = sum(t.amount for t in before if t.channel == Channel.TRANSFER) / weeks
    total = sum(t.amount for t in inj)
    if baseline > 0:
        assert 2.0 * baseline <= total <= 2.9 * baseline
    else:
        assert 200_000 <= total <= 290_000


def test_subtle_payee_surge_without_transfer_history() -> None:
    hist = [t for t in _base("worker", 3) if t.channel != Channel.TRANSFER]
    for seed in range(10):
        inj = _subtle(hist, SignalCode.PAYEE_SURGE, seed)
        total = sum(t.amount for t in inj)
        assert len(inj) == 2 and 200_000 <= total <= 290_000 and total % 10_000 == 0


@pytest.mark.parametrize("key", PERSONAS)
@pytest.mark.parametrize("seed", SEEDS)
def test_subtle_micropay_surge_definition(key: str, seed: int) -> None:
    p = synth.PERSONAS[key]
    hist = _base(key, seed)
    inj = _subtle(hist, SignalCode.MICROPAY_SURGE, seed)
    assert len(inj) == 4
    assert all(t.channel == Channel.MICROPAY and t.direction == Direction.OUT for t in inj)
    assert all(50_000 <= t.amount <= 100_000 and t.amount % 1_000 == 0 for t in inj)
    assert all(t.line_id == p.telecom_line for t in inj)                     # 본인 회선
    assert all(9 <= t.ts.hour <= 22 for t in inj)
    assert inj[0].ts.date() == AT and inj[-1].ts - inj[0].ts < timedelta(days=7)


@pytest.mark.parametrize("key", PERSONAS)
@pytest.mark.parametrize("seed", SEEDS)
def test_subtle_new_merchant_definition(key: str, seed: int) -> None:
    hist = _base(key, seed)
    inj = _subtle(hist, SignalCode.NEW_MERCHANT_HIGH_VALUE, seed)
    assert len(inj) == 1
    t = inj[0]
    assert t.channel == Channel.CARD and t.direction == Direction.OUT
    assert t.counterparty_id not in {x.counterparty_id for x in hist}        # 처음 보는 가맹점
    assert t.counterparty not in {x.counterparty for x in hist}
    assert t.ts.date() == AT and 10 <= t.ts.hour <= 20
    cards = [x.amount for x in _before(hist, AT) if x.channel == Channel.CARD]
    p95 = float(np.percentile(cards, 95))
    # 금액 = max(p95 × 2.0~2.9, 10만 원)
    assert t.amount >= 100_000 and t.amount % 100 == 0
    if t.amount > 100_000:
        assert 2.0 * p95 <= t.amount <= 2.9 * p95
    else:
        assert 2.0 * p95 <= 100_000


def test_subtle_new_merchant_without_card_history_is_floor() -> None:
    hist = [t for t in _base("benefit", 2) if t.channel != Channel.CARD]
    inj = _subtle(hist, SignalCode.NEW_MERCHANT_HIGH_VALUE, 5)
    assert [t.amount for t in inj] == [100_000]


def test_subtle_new_merchant_scales_with_high_p95() -> None:
    """p95 × 2.0이 10만 원을 넘는 사람은 배율 구간 [2.0, 2.9] 안의 금액이 된다."""
    hist = [t if t.channel != Channel.CARD else Transaction(
        id=t.id, ts=t.ts, amount=t.amount * 10, direction=t.direction, channel=t.channel,
        counterparty=t.counterparty, counterparty_id=t.counterparty_id, label=t.label)
        for t in _base("worker", 1)]
    cards = [x.amount for x in _before(hist, AT) if x.channel == Channel.CARD]
    p95 = float(np.percentile(cards, 95))
    assert 2.0 * p95 > 100_000
    for seed in range(10):
        (t,) = _subtle(hist, SignalCode.NEW_MERCHANT_HIGH_VALUE, seed)
        assert 2.0 * p95 <= t.amount <= 2.9 * p95


@pytest.mark.parametrize("key", PERSONAS)
@pytest.mark.parametrize("seed", SEEDS)
def test_subtle_multi_line_definition(key: str, seed: int) -> None:
    p = synth.PERSONAS[key]
    hist = _base(key, seed)
    inj = _subtle(hist, SignalCode.MULTI_LINE_TELECOM, seed)
    assert len(inj) == 1
    t = inj[0]
    assert t.channel == Channel.TELECOM_BILL and t.direction == Direction.OUT
    assert t.line_id != p.telecom_line and t.line_id not in {x.line_id for x in hist}   # 새 회선 1개
    assert t.ts.date() == AT and 9 <= t.ts.hour <= 18
    assert 35_000 <= t.amount <= 98_990


def test_subtle_inject_does_not_mutate_and_is_deterministic() -> None:
    hist = _base("student", 2)
    snapshot = _dicts(hist)
    for code in SignalCode:
        a = synth.inject_scenario(hist, code, AT, seed=4, intensity="subtle")
        b = synth.inject_scenario(hist, code, AT, seed=4, intensity="subtle")
        assert _dicts(hist) == snapshot
        assert _dicts(a) == _dicts(b)
        assert [t.ts for t in a] == sorted(t.ts for t in a)
        assert len({t.id for t in a}) == len(a)
        inj = [t for t in a if t.label == code.value]
        assert len(a) == len(hist) + len(inj)
        assert all(t.ts >= datetime.combine(AT, time(0, 0)) for t in inj)


@pytest.mark.parametrize("lo,hi,unit", [(2_000.0, 2_900.0, 1_000), (24_130.5, 34_989.2, 1_000),
                                        (1_200.3, 1_900.1, 1_000), (57_000.0, 82_650.0, 100)])
def test_amount_between_stays_inside(lo: float, hi: float, unit: int) -> None:
    rng = np.random.default_rng(0)
    for _ in range(200):
        v = synth._amount_between(rng, lo, hi, unit)
        assert lo <= v <= hi
        if math.ceil(lo / unit) * unit <= hi:
            assert v % unit == 0


# ---------------------------------------------------------------------------
# make_dataset(subtle)
# ---------------------------------------------------------------------------

SUBTLE_COUNTS = {
    SignalCode.NIGHT_REPEAT_TRANSFER: 2,
    SignalCode.PAYEE_SURGE: 2,
    SignalCode.MICROPAY_SURGE: 4,
    SignalCode.NEW_MERCHANT_HIGH_VALUE: 1,
    SignalCode.MULTI_LINE_TELECOM: 1,
}


@pytest.mark.parametrize("key", PERSONAS)
@pytest.mark.parametrize("seed", [1, 4, 13])
def test_make_dataset_subtle(key: str, seed: int) -> None:
    days = 120
    txns = synth.make_dataset(key, seed, days, synth.ALL_SCENARIOS, intensity="subtle")
    assert [t.ts for t in txns] == sorted(t.ts for t in txns)
    assert len({t.id for t in txns}) == len(txns)
    window_start = START + timedelta(days=days - synth.SCENARIO_WINDOW_DAYS)
    end = START + timedelta(days=days)
    for code, n in SUBTLE_COUNTS.items():
        inj = [t for t in txns if t.label == code.value]
        assert len(inj) == n, code
        assert all(window_start <= t.ts.date() < end for t in inj)        # 마지막 30일 안
    # 정상 부분은 standard·대조군과 똑같다
    control = synth.make_dataset(key, seed, days)
    standard = synth.make_dataset(key, seed, days, synth.ALL_SCENARIOS)
    normal = lambda xs: _dicts([t for t in xs if t.label == "normal"])  # noqa: E731
    assert normal(txns) == _dicts(control) == normal(standard)


def test_make_dataset_subtle_deterministic_and_order_independent() -> None:
    codes = list(SignalCode)
    a = synth.make_dataset("worker", 2, scenarios=codes, intensity="subtle")
    b = synth.make_dataset("worker", 2, scenarios=list(reversed(codes)), intensity="subtle")
    c = synth.make_dataset("worker", 3, scenarios=codes, intensity="subtle")
    assert _dicts(a) == _dicts(b)
    assert _dicts(a) != _dicts(c)
    assert set(synth.SUBTLE_SPAN_DAYS) == set(SignalCode)


# ---------------------------------------------------------------------------
# eval·보고서·명령행
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def standard_small() -> dict:
    return compare_modes(["worker"], [1])


@pytest.fixture(scope="module")
def subtle_small() -> dict:
    return compare_modes(["worker"], [1], intensity="subtle")


def test_evaluate_records_intensity(standard_small, subtle_small) -> None:
    assert standard_small["intensity"] == "standard"
    assert subtle_small["intensity"] == "subtle"
    for mode in ("fused", "rules", "anomaly"):
        res = subtle_small["modes"][mode]
        assert res["intensity"] == "subtle"
        assert {c: s["txns_mean"] for c, s in res["scenario_recall"].items()} == {
            c.value: float(n) for c, n in SUBTLE_COUNTS.items()}
        # 대조군(시나리오 없음)은 강도와 관계없이 같은 데이터
        assert res["control"] == standard_small["modes"][mode]["control"]
    single = evaluate(["worker"], [1], "rules", intensity="subtle")
    assert single == subtle_small["modes"]["rules"]


def test_fused_never_below_rules(subtle_small) -> None:
    """결합 규칙상 거래마다 fused ≥ rules라, 시나리오 탐지 수도 fused ≥ rules(구조 성질)."""
    fused, rules = subtle_small["modes"]["fused"], subtle_small["modes"]["rules"]
    for code, r in rules["scenario_recall"].items():
        f = fused["scenario_recall"][code]
        assert f["caution"] >= r["caution"] and f["high"] >= r["high"]
    assert fused["normal"]["alerts"] >= rules["normal"]["alerts"]


def _table_rows_consistent(markdown: str) -> None:
    block: list[str] = []
    for line in markdown.splitlines() + [""]:
        if line.startswith("|"):
            block.append(line)
            continue
        if block:
            widths = {row.replace("\\|", "").count("|") for row in block}
            assert len(widths) == 1, block
            block = []


def test_report_combines_standard_and_subtle(tmp_path, standard_small, subtle_small) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    pa1 = report.write_report(standard_small, a)
    pa2 = report.write_report(subtle_small, a)
    assert pa1["json"].name == "eval_results.json"
    assert pa2["json"].name == "eval_results_subtle.json"
    assert pa1["markdown"] == pa2["markdown"] == a / "eval_report.md"
    assert json.loads(pa1["json"].read_text(encoding="utf-8")) == standard_small
    assert json.loads(pa2["json"].read_text(encoding="utf-8")) == subtle_small
    # 순서를 바꿔 써도 같은 보고서
    report.write_report(subtle_small, b)
    report.write_report(standard_small, b)
    md = (a / "eval_report.md").read_text(encoding="utf-8")
    assert md == (b / "eval_report.md").read_text(encoding="utf-8")
    assert "## 1. 모드 비교 요약" in md and "## 6. 경계 변형(subtle)" in md
    assert "SPEC.md §3·§8 [추가 r4]" in md and "결합 모드는 룰만 대비" in md
    assert "주의 이상 차이(결합 − 룰만)" in md and "정상 거래 알림률·고위험률(오탐)" in md
    for text in report.SUBTLE_DEFINITIONS_KO.values():
        assert text in md
    o = subtle_small["modes"]["rules"]["overall"]
    assert f"({o['high']}/{o['n']})" in md                                  # 수치는 결과에서 온다
    assert "표준 결과와 다른 설정" not in md
    _table_rows_consistent(md)
    assert not list(a.glob("*.tmp"))


def test_report_subtle_only_and_mismatch(tmp_path, subtle_small) -> None:
    only = tmp_path / "only"
    report.write_report(subtle_small, only)
    md = (only / "eval_report.md").read_text(encoding="utf-8")
    assert "## 1. 경계 변형(subtle)" in md and "모드 비교 요약" not in md
    assert not (only / "eval_results.json").exists()
    _table_rows_consistent(md)
    # 설정이 다른 표준 결과와 합치면 그 사실을 적는다
    other = compare_modes(["worker"], [2], modes=["rules"])
    report.write_report(other, only)
    md = (only / "eval_report.md").read_text(encoding="utf-8")
    assert "표준 결과와 다른 설정" in md and "seed" in md


def test_report_notes_unreadable_subtle_json(tmp_path, standard_small) -> None:
    (tmp_path / "eval_results_subtle.json").write_text("{broken", encoding="utf-8")
    report.write_report(standard_small, tmp_path)
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "eval_results_subtle.json을(를) 읽지 못해" in md


def test_change_text_states_zero_difference() -> None:
    same = {"recall_caution": 0.5, "recall_high": 0.25, "caution": 2, "high": 1, "n": 4}
    text = report._change_text("전체", same, same)
    assert "0.0%p" in text and "더한 탐지는 없습니다" in text
    more = {**same, "recall_high": 0.5, "high": 2}
    text = report._change_text("전체", more, same)
    assert "+25.0%p" in text and "(1/4 → 2/4)" in text and "더한 탐지는 없습니다" not in text


def test_render_markdown_rejects_wrong_subtle(standard_small) -> None:
    with pytest.raises(ValueError):
        report.render_markdown(standard_small, subtle=standard_small)


def test_cli_eval_subtle_writes_separate_json(tmp_path, capsys) -> None:
    out = tmp_path / "eval"
    assert cli.run(["eval", "--seeds", "1", "--personas", "worker", "--modes", "rules",
                    "--intensity", "subtle", "--out", str(out)]) == 0
    capsys.readouterr()
    assert not (out / "eval_results.json").exists()
    results = json.loads((out / "eval_results_subtle.json").read_text(encoding="utf-8"))
    assert results["intensity"] == "subtle"
    assert "--intensity subtle --out" in results["command"]
    md = (out / "eval_report.md").read_text(encoding="utf-8")
    assert "경계 변형(subtle)" in md and results["command"] in md


def test_cli_standard_command_is_unchanged() -> None:
    args = cli.build_parser().parse_args(["eval", "--seeds", "20", "--out", "docs/eval"])
    assert args.intensity == "standard"
    assert cli._eval_command(args) == "python -m safepause eval --seeds 20 --out docs/eval"


def test_cli_guard_compares_subtle_file(tmp_path, capsys) -> None:
    submitted = tmp_path / "docs" / "eval"
    submitted.mkdir(parents=True)
    std = {"command": "python -m safepause eval --seeds 20 --out docs/eval"}
    sub = {"command": "python -m safepause eval --seeds 20 --intensity subtle --out docs/eval"}
    (submitted / "eval_results.json").write_text(json.dumps(std), encoding="utf-8")
    (submitted / "eval_results_subtle.json").write_text(json.dumps(sub), encoding="utf-8")
    quick = ["eval", "--seeds", "1", "--personas", "worker", "--modes", "rules",
             "--intensity", "subtle", "--out", str(submitted)]
    assert cli.run(quick) == 1                                   # 다른 설정의 subtle 결과는 덮어쓰지 않음
    assert "--out 다른폴더" in capsys.readouterr().err
    assert json.loads((submitted / "eval_results_subtle.json").read_text(encoding="utf-8")) == sub
    assert json.loads((submitted / "eval_results.json").read_text(encoding="utf-8")) == std
