"""별도 검증 세트(holdout) 평가 테스트(SPEC §8·§9 [추가 r5]).

- default_seeds(n, start)와 명령행 --seed-start
- 결과 파일 이름 분리(eval_results_holdout.json, eval_results_subtle_holdout.json)
- 검증 세트를 써도 표본 안 결과 파일(eval_results.json, eval_results_subtle.json)과 보고서의 기존 절이 그대로인지
- 보고서 7절(표본 안과 비교)이 수치를 그대로, 나쁘면 나쁘다고 쓰는지
탐지 성능 수치는 여기서 맞추지 않는다. 기계 동작 확인에는 seed 21~40이 아닌 seed를 쓴다.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from safepause import cli
from safepause.eval import report
from safepause.eval.metrics import compare_modes, default_seeds

ROOT = Path(__file__).resolve().parents[1]
DOCS_EVAL = ROOT / "docs" / "eval"
MODES = ["fused", "rules"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _strip_holdout(md: str) -> str:
    """보고서에서 r5가 더한 부분(맨 위 안내, 검증 세트 절, 유의점 한 줄)을 뺀다."""
    start = md.index("\n\n> 1~")
    end = md.index("\n\n", start + 2)
    md = md[:start] + md[end:]
    start = md.index("\n\n## 7. 별도 검증 세트")
    end = md.index("\n\n## 지표 정의")
    md = md[:start] + md[end:]
    return md.replace("\n" + report._HOLDOUT_CAVEAT, "")


# ---------------------------------------------------------------------------
# seed 목록·명령행
# ---------------------------------------------------------------------------

def test_default_seeds_start() -> None:
    assert default_seeds(3) == [1, 2, 3]                   # 기존 호출은 그대로
    assert default_seeds(20, 21) == list(range(21, 41))
    assert default_seeds(2, start=0) == [0, 1]
    with pytest.raises(ValueError):
        default_seeds(3, -1)
    with pytest.raises(ValueError):
        default_seeds(0, 21)


def test_cli_seed_start_command_and_file_names() -> None:
    parse = cli.build_parser().parse_args
    base = parse(["eval", "--seeds", "20", "--out", "docs/eval"])
    assert base.seed_start == 1 and not cli._is_holdout(base)
    assert cli._eval_command(base) == "python -m safepause eval --seeds 20 --out docs/eval"
    explicit_one = parse(["eval", "--seeds", "20", "--seed-start", "1", "--out", "docs/eval"])
    assert cli._eval_command(explicit_one) == cli._eval_command(base)
    held = parse(["eval", "--seeds", "20", "--seed-start", "21", "--out", "docs/eval"])
    assert cli._is_holdout(held)
    assert cli._eval_command(held) == "python -m safepause eval --seeds 20 --seed-start 21 --out docs/eval"
    held_sub = parse(["eval", "--seeds", "20", "--seed-start", "21", "--intensity", "subtle", "--out", "docs/eval"])
    assert cli._eval_command(held_sub) == ("python -m safepause eval --seeds 20 --seed-start 21 "
                                           "--intensity subtle --out docs/eval")
    assert cli._eval_json_name("standard") == "eval_results.json"
    assert cli._eval_json_name("subtle") == "eval_results_subtle.json"
    assert cli._eval_json_name("standard", True) == "eval_results_holdout.json"
    assert cli._eval_json_name("subtle", True) == "eval_results_subtle_holdout.json"
    assert cli.run(["eval", "--seed-start", "-1"]) == 2   # 음수는 인자 오류


def test_cli_holdout_keeps_in_sample_files(tmp_path, capsys) -> None:
    out = tmp_path / "eval"
    common = ["--seeds", "1", "--personas", "worker", "--modes", "rules", "--out", str(out)]
    assert cli.run(["eval", *common]) == 0
    assert cli.run(["eval", *common, "--intensity", "subtle"]) == 0
    std_path, sub_path = out / "eval_results.json", out / "eval_results_subtle.json"
    before = {p.name: p.read_bytes() for p in (std_path, sub_path)}
    md_before = (out / "eval_report.md").read_text(encoding="utf-8")

    assert cli.run(["eval", *common, "--seed-start", "3"]) == 0
    assert cli.run(["eval", *common, "--seed-start", "3", "--intensity", "subtle"]) == 0
    text = capsys.readouterr().out
    assert "별도 검증 세트" in text and "eval_results_holdout.json" in text

    # 표본 안 결과 파일은 바이트 단위로 그대로
    assert {p.name: p.read_bytes() for p in (std_path, sub_path)} == before
    for name, intensity in (("eval_results_holdout.json", "standard"),
                            ("eval_results_subtle_holdout.json", "subtle")):
        data = json.loads((out / name).read_text(encoding="utf-8"))
        assert data["seeds"] == [3] and data["split"] == "holdout" and data["intensity"] == intensity
        assert "--seed-start 3" in data["command"]
    assert "split" not in json.loads(std_path.read_text(encoding="utf-8"))

    # 보고서: 기존 절은 그대로, 7절이 더해짐
    md = (out / "eval_report.md").read_text(encoding="utf-8")
    assert "## 7. 별도 검증 세트(seed 3)" in md
    assert "| 표본 안 seed와 겹침 | 없음 |" in md
    assert _strip_holdout(md) == md_before
    _table_rows_consistent(md)
    assert not list(out.glob("*.tmp"))


def test_cli_guard_compares_holdout_file(tmp_path, capsys) -> None:
    submitted = tmp_path / "docs" / "eval"
    submitted.mkdir(parents=True)
    std = {"command": "python -m safepause eval --seeds 20 --out docs/eval"}
    held = {"command": "python -m safepause eval --seeds 20 --seed-start 21 --out docs/eval"}
    (submitted / "eval_results.json").write_text(json.dumps(std), encoding="utf-8")
    (submitted / "eval_results_holdout.json").write_text(json.dumps(held), encoding="utf-8")
    quick = ["eval", "--seeds", "1", "--seed-start", "21", "--personas", "worker", "--modes", "rules",
             "--out", str(submitted)]
    assert cli.run(quick) == 1                                  # 다른 설정의 검증 세트 결과는 덮어쓰지 않음
    assert "--out 다른폴더" in capsys.readouterr().err
    assert json.loads((submitted / "eval_results_holdout.json").read_text(encoding="utf-8")) == held
    assert json.loads((submitted / "eval_results.json").read_text(encoding="utf-8")) == std
    # 경계 변형 검증 세트 파일은 아직 없으므로 막지 않는다(표본 안 파일은 건드리지 않음)
    before = (submitted / "eval_results.json").read_bytes()
    assert cli.run([*quick, "--intensity", "subtle"]) == 0
    capsys.readouterr()
    assert (submitted / "eval_results.json").read_bytes() == before
    assert (submitted / "eval_results_subtle_holdout.json").is_file()


# ---------------------------------------------------------------------------
# 보고서
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def four() -> dict[str, dict]:
    def held(r: dict) -> dict:
        return {**r, "split": "holdout"}
    return {
        "std": compare_modes(["worker"], [1], MODES),
        "sub": compare_modes(["worker"], [1], MODES, intensity="subtle"),
        "h_std": held(compare_modes(["worker"], [2], MODES)),
        "h_sub": held(compare_modes(["worker"], [2], MODES, intensity="subtle")),
    }


def test_report_holdout_names_and_order(tmp_path, four) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    names = {k: report.write_report(four[k], a)["json"].name for k in ("std", "sub", "h_std", "h_sub")}
    assert names == {"std": "eval_results.json", "sub": "eval_results_subtle.json",
                     "h_std": "eval_results_holdout.json", "h_sub": "eval_results_subtle_holdout.json"}
    for k in ("h_sub", "std", "h_std", "sub"):                 # 순서를 바꿔 써도 같은 보고서
        report.write_report(four[k], b)
    md = (a / "eval_report.md").read_text(encoding="utf-8")
    assert md == (b / "eval_report.md").read_text(encoding="utf-8")
    assert md.index("## 6. 경계 변형") < md.index("## 7. 별도 검증 세트(seed 2)") < md.index("## 지표 정의")
    assert "> 1~6절은 seed 1 값입니다." in md and "SPEC.md §8 [추가 r5]" in md
    assert report._HOLDOUT_CAVEAT in md
    # 수치는 결과에서 온다(표본 안·검증 세트 모두)
    for key in ("std", "h_std", "sub", "h_sub"):
        o = four[key]["modes"]["fused"]["overall"]
        assert f"({o['caution']}/{o['n']})" in md
        c = four[key]["modes"]["rules"]["confusion"]["high"]
        assert f"({c['tp']}/{c['tp'] + c['fn']})" in md
    assert md.count("과 나란히 비교:") == 2 and "표본 안과 비교(수치 그대로)" in md
    _table_rows_consistent(md)
    # 검증 세트 절이 없던 보고서와 기존 절이 같다
    c = tmp_path / "c"
    report.write_report(four["std"], c)
    report.write_report(four["sub"], c)
    assert _strip_holdout(md) == (c / "eval_report.md").read_text(encoding="utf-8")


def test_report_holdout_states_worse_values(four) -> None:
    ins, h = four["std"], copy.deepcopy(four["h_std"])
    base = ins["modes"]["fused"]["control"]
    h["modes"]["fused"]["control"].update(monthly_alerts=base["monthly_alerts"] + 0.5,
                                          alerts=base["alerts"] + 1)
    md = report._synthetic_markdown(ins, None, holdout=h)
    assert "으로 검증 세트가 더 높습니다" in md
    assert "검증 세트에서 더 나쁨: " in md and "대조군 1인당 월평균 알림(주의 이상)" in md
    h["modes"]["fused"]["control"].update(monthly_alerts=0.0, alerts=0)
    ins2 = copy.deepcopy(ins)
    ins2["modes"]["fused"]["control"].update(monthly_alerts=1.0, alerts=3)
    md = report._synthetic_markdown(ins2, None, holdout=h)
    assert "으로 검증 세트가 더 낮습니다" in md


def test_report_holdout_overlap_and_missing_in_sample(tmp_path, four) -> None:
    overlap = {**four["std"], "split": "holdout"}           # 표본 안과 같은 seed
    md = report._synthetic_markdown(four["std"], None, holdout=overlap)
    assert "겹치는 seed가 있어 이 절은 별도 검증 세트가 아닙니다" in md
    alone = report.render_markdown(four["h_sub"])
    assert "## 1. 별도 검증 세트(seed 2)" in alone
    assert "표본 안 결과(eval_results_subtle.json)가 없어 비교 표를 싣지 않았습니다" in alone
    _table_rows_consistent(alone)
    with pytest.raises(ValueError):
        report.render_markdown(four["h_std"], subtle=four["sub"])
    # 읽지 못하는 검증 세트 JSON은 안내만 남긴다
    (tmp_path / "eval_results_holdout.json").write_text("{broken", encoding="utf-8")
    report.write_report(four["std"], tmp_path)
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "eval_results_holdout.json을(를) 읽지 못해" in md and "## 7." not in md


# ---------------------------------------------------------------------------
# 제출 보고서(docs/eval)
# ---------------------------------------------------------------------------

# r5 전 seed 1~20 결과의 SHA-256. 검증 세트는 이 파일들과 나란히 비교하므로 바뀌면 안 된다.
IN_SAMPLE_SHA256 = {
    "eval_results.json": "675e12fea0b74d45f99a3e70ae3f929424c18ba42ad3819e891a0f2063cf0c42",
    "eval_results_subtle.json": "46b85e5e55543604266a886df7150b40619a9c869417b60bcf65fabe4582e21d",
}


def test_submitted_in_sample_results_unchanged() -> None:
    for name, digest in IN_SAMPLE_SHA256.items():
        assert _sha(DOCS_EVAL / name) == digest, name
        data = json.loads((DOCS_EVAL / name).read_text(encoding="utf-8"))
        assert data["seeds"] == list(range(1, 21)) and "split" not in data


def test_submitted_holdout_results_match_registration(tmp_path) -> None:
    registered = {
        "eval_results_holdout.json": "python -m safepause eval --seeds 20 --seed-start 21 --out docs/eval",
        "eval_results_subtle_holdout.json": ("python -m safepause eval --seeds 20 --seed-start 21 "
                                             "--intensity subtle --out docs/eval"),
    }
    for name, command in registered.items():
        data = json.loads((DOCS_EVAL / name).read_text(encoding="utf-8"))
        assert data["command"] == command and data["split"] == "holdout"
        assert data["seeds"] == list(range(21, 41)) and data["personas"] == ["worker", "benefit", "student"]
        assert data["mode_order"] == ["fused", "rules", "anomaly"]
        assert (data["days"], data["baseline_days"]) == (120, 90)
    # 제출 보고서는 네 JSON으로 다시 만든 것과 같다(수치는 모두 JSON에서 옴)
    for name in [*IN_SAMPLE_SHA256, *registered]:
        shutil.copyfile(DOCS_EVAL / name, tmp_path / name)
    report.write_report(json.loads((tmp_path / "eval_results_holdout.json").read_text(encoding="utf-8")),
                        tmp_path)
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert md == (DOCS_EVAL / "eval_report.md").read_text(encoding="utf-8")
    assert "## 7. 별도 검증 세트(seed 21~40)" in md
