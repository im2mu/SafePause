"""성능 확인 API(POST /api/eval/run)의 seed 시작 번호·시나리오 종류(v0.3, claims C6).

- 입력: seed_start(1~10000, 기본 1)·intensity(standard|subtle, 기본 standard)·seeds(1~20, 기본 5)
- 응답: 실제로 쓴 seed_start·seed_end·intensity, 보고서 검증 세트와 같은 설정인지(report_set)
- PC(FastAPI)와 앱(router, Pyodide)이 같은 응답·같은 한국어 오류를 준다
- 같은 설정(인물 3명 × seed 21~40, 세 방식)으로 PC(numpy)에서 앱 경로(router)로 다시 계산한 값이
  제출 보고서 원자료(docs/eval/eval_results_holdout.json·eval_results_subtle_holdout.json)와
  화면 기준값(safepause/web/data/eval_reference.json)과 정확히 같은지(test_eval_run_reproduces_report_set)

탐지 성능 수치는 여기서 맞추지 않는다(같은 코드로 같은 값이 나오는지만 본다). 기계 동작 확인에는 seed 21~40이 아닌 seed를 쓴다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from safepause.api import constants
from safepause.api.router import dispatch
from safepause.api.schemas import EvalIn, EvalIntensity
from safepause.api.service import Service
from safepause.server.app import create_app

ROOT = Path(__file__).resolve().parents[1]
DOCS_EVAL = ROOT / "docs" / "eval"
WEB_REFERENCE = ROOT / "safepause" / "web" / "data" / "eval_reference.json"
HOLDOUT = {"standard": DOCS_EVAL / "eval_results_holdout.json",
           "subtle": DOCS_EVAL / "eval_results_subtle_holdout.json"}
BASE = "http://127.0.0.1:8765"
NOW = datetime(2026, 9, 30, 12, 0, 0)
ALL_MODES = ["fused", "rules", "anomaly"]

# 화면 기준값(eval_reference.json sets.<intensity>.modes.<mode>.<키>) → eval/run 응답 results.<mode> 안의 경로.
# 화면이 일치 표시를 만들 때 쓰는 대응표와 같다(아래 테스트가 이 표로 값이 같은지 본다).
REFERENCE_PATHS: dict[str, tuple[str, ...]] = {
    "scenario_caution": ("overall", "recall_caution"),
    "scenario_high": ("overall", "recall_high"),
    "scenario_caution_n": ("overall", "caution"),
    "scenario_high_n": ("overall", "high"),
    "scenario_n": ("overall", "n"),
    "txn_high_recall": ("confusion", "high", "recall"),
    "txn_caution_recall": ("confusion", "caution", "recall"),
    "normal_alert_rate": ("normal", "alert_rate"),
    "normal_high_rate": ("normal", "high_rate"),
    "control_monthly_alerts": ("control", "monthly_alerts"),
    "control_monthly_high": ("control", "monthly_high"),
    "amount_before_first_alert_mean": ("overall", "amount_before_first_alert_mean"),
}
# by_scenario.<code>.{caution, high, n} → scenario_recall.<code>.{caution, high, n}
# test_static_ui.py가 화면 기준값과 원자료를 맞춰 보는 네 지표
SCREEN_FOUR = ("scenario_high", "txn_high_recall", "normal_high_rate", "control_monthly_alerts")


def _at(d: Any, path: tuple[str, ...]) -> Any:
    for k in path:
        d = d[k]
    return d


def _fake(calls: list[tuple[Any, ...]]):
    def run(personas: list[str], seeds: list[int], modes: list[str], *, intensity: str) -> dict[str, Any]:
        calls.append((personas, seeds, modes, intensity))
        return {m: {"mode": m, "intensity": intensity, "seeds": seeds} for m in modes}
    return run


# ---- 입력 규칙 ----------------------------------------------------------------------

def test_eval_in_defaults_and_limits() -> None:
    req = EvalIn()
    assert (req.seeds, req.seed_start, req.intensity, req.modes, req.personas) == (5, 1, "standard", ["fused"], None)
    assert EvalIn(seeds=20, seed_start=10_000, intensity="subtle").seeds == 20
    for bad in ({"seeds": 21}, {"seed_start": 0}, {"seed_start": -1}, {"seed_start": 10_001},
                {"intensity": "hard"}, {"intensity": "Standard"}, {"intensity": None}, {"seed_start": None}):
        with pytest.raises(ValueError):
            EvalIn.model_validate(bad)


def test_eval_constants_match_report_files() -> None:
    from safepause.data import synth
    assert constants.EVAL_INTENSITIES == synth.INTENSITIES == get_args(EvalIntensity)
    assert constants.MAX_EVAL_SEEDS >= constants.REPORT_SEEDS
    seeds = list(range(constants.REPORT_SEED_START, constants.REPORT_SEED_START + constants.REPORT_SEEDS))
    for intensity, path in HOLDOUT.items():
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["seeds"] == seeds and doc["intensity"] == intensity
        assert set(doc["personas"]) == set(constants.PERSONA_KEYS)
    ref = json.loads(WEB_REFERENCE.read_text(encoding="utf-8"))
    assert ref["seeds"] == f"{seeds[0]}~{seeds[-1]}"
    assert {k: v["intensity"] for k, v in ref["sets"].items()} == {"standard": "standard", "subtle": "subtle"}


# ---- 응답: 쓴 seed 범위·시나리오 종류·보고서 설정 여부 ------------------------------------

@pytest.mark.parametrize("body,seeds,intensity,report_set", [
    (None, [1, 2, 3, 4, 5], "standard", False),
    ({"seeds": 20, "seed_start": 21}, list(range(21, 41)), "standard", True),
    ({"seeds": 20, "seed_start": 21, "intensity": "subtle"}, list(range(21, 41)), "subtle", True),
    ({"seeds": 20, "seed_start": 21, "personas": ["student", "worker", "benefit"]}, list(range(21, 41)), "standard", True),
    ({"seeds": 20, "seed_start": 21, "personas": ["worker"]}, list(range(21, 41)), "standard", False),
    ({"seeds": 19, "seed_start": 21}, list(range(21, 40)), "standard", False),
    ({"seeds": 20, "seed_start": 22, "intensity": "subtle"}, list(range(22, 42)), "subtle", False),
    ({"seeds": 1, "seed_start": 10_000}, [10_000], "standard", False),
])
def test_eval_run_reports_seed_range_and_intensity(tmp_path: Path, body: Any, seeds: list[int], intensity: str,
                                                   report_set: bool) -> None:
    calls: list[tuple[Any, ...]] = []
    svc = Service(tmp_path, now=lambda: NOW, evaluator=_fake(calls))
    status, out = dispatch(svc, "POST", "/api/eval/run", body)
    assert status == 200, out
    assert calls[-1][1:] == (seeds, out["modes"], intensity)
    assert out["seeds"] == seeds and (out["seed_start"], out["seed_end"]) == (seeds[0], seeds[-1])
    assert out["intensity"] == intensity and out["report_set"] is report_set
    assert out["note"] == "합성 데이터 기준, 실제 피해 데이터 검증 아님"


def test_eval_run_router_matches_fastapi(tmp_path: Path) -> None:
    pc_calls: list[tuple[Any, ...]] = []
    app_calls: list[tuple[Any, ...]] = []
    client = TestClient(create_app(tmp_path / "pc", now=lambda: NOW, evaluator=_fake(pc_calls)),
                        base_url=BASE, headers={"X-SafePause": "1"})
    svc = Service(tmp_path / "app", now=lambda: NOW, evaluator=_fake(app_calls))
    bodies = [None, {"seeds": 20, "seed_start": 21, "intensity": "subtle", "modes": ALL_MODES},
              {"seeds": 3, "seed_start": 41, "personas": ["benefit"], "modes": ["rules", "rules"]},
              {"seed_start": 0}, {"seed_start": 10_001}, {"seed_start": "x"}, {"seeds": 21},
              {"intensity": "hard"}, {"intensity": 1}, {"seed_start": 21, "intensity": "subtle", "seeds": 0},
              {"seedstart": 21}]
    for body in bodies:
        r = client.post("/api/eval/run", json=body) if body is not None else client.post("/api/eval/run")
        status, out = dispatch(svc, "POST", "/api/eval/run", body)
        out = json.loads(json.dumps(out, ensure_ascii=False))
        pc = r.json()
        pc.pop("elapsed_sec", None)
        out.pop("elapsed_sec", None)
        assert (r.status_code, pc) == (status, out), body
    assert pc_calls == app_calls and len(pc_calls) == 3


@pytest.mark.parametrize("body,label", [
    ({"seed_start": 0}, "시작 번호(seed)"),
    ({"seed_start": 10_001}, "시작 번호(seed)"),
    ({"intensity": "hard"}, "시나리오 종류"),
    ({"seeds": 21, "intensity": "x"}, "반복 횟수, 시나리오 종류"),
])
def test_eval_run_errors_are_korean(tmp_path: Path, body: dict[str, Any], label: str) -> None:
    svc = Service(tmp_path, now=lambda: NOW, evaluator=_fake([]))
    status, out = dispatch(svc, "POST", "/api/eval/run", body)
    assert status == 422
    assert out["detail"] == f"입력한 값을 확인해 주세요: {label}"


# ---- 실제 계산(작은 설정): 시나리오 종류가 계산까지 전해지는지, 방식을 함께 골라도 값이 같은지 ----------

def test_eval_run_real_subtle_small(tmp_path: Path) -> None:
    pytest.importorskip("safepause.eval.metrics")
    from safepause.eval.metrics import compare_modes
    svc = Service(tmp_path, now=lambda: NOW)
    body = {"seeds": 1, "seed_start": 3, "personas": ["worker"], "modes": ["rules"], "intensity": "subtle"}
    status, alone = dispatch(svc, "POST", "/api/eval/run", body)
    assert status == 200, alone
    alone = json.loads(json.dumps(alone, ensure_ascii=False))
    assert (alone["seeds"], alone["intensity"], alone["report_set"]) == ([3], "subtle", False)
    direct = json.loads(json.dumps(compare_modes(["worker"], [3], ["rules"], intensity="subtle")["modes"],
                                   ensure_ascii=False))
    assert alone["results"] == direct
    assert alone["results"]["rules"]["intensity"] == "subtle"
    # 방식을 여럿 골라도 방식마다 값은 같다(보고서는 세 방식을 함께 계산했다)
    status, both = dispatch(svc, "POST", "/api/eval/run", {**body, "modes": ["fused", "rules"]})
    assert status == 200
    assert json.loads(json.dumps(both["results"]["rules"], ensure_ascii=False)) == alone["results"]["rules"]


# ---- 보고서 검증 세트 재현(PC, numpy): 인물 3명 × seed 21~40 × 세 방식 ----------------------------------

@pytest.mark.parametrize("intensity", ["standard", "subtle"])
def test_eval_run_reproduces_report_set(tmp_path: Path, intensity: str) -> None:
    """앱 경로(router → Service.eval_run → metrics.compare_modes)로 다시 계산한 값 = 제출 원자료 = 화면 기준값.

    PC(numpy 2.5.3·scikit-learn 1.9.1)에서 표준·경계 변형 각각 약 10초라 늘 돌린다. environment(설치 버전)는 비교하지 않는다.
    """
    pytest.importorskip("safepause.eval.metrics")
    svc = Service(tmp_path, now=lambda: NOW)
    status, out = dispatch(svc, "POST", "/api/eval/run",
                           {"seeds": 20, "seed_start": 21, "intensity": intensity, "modes": ALL_MODES})
    assert status == 200, out
    out = json.loads(json.dumps(out, ensure_ascii=False))
    assert (out["seed_start"], out["seed_end"], out["intensity"], out["report_set"]) == (21, 40, intensity, True)

    # 1) 원자료의 모든 지표(방식별 결과 전체)
    doc = json.loads(HOLDOUT[intensity].read_text(encoding="utf-8"))
    assert out["personas"] == doc["personas"] and out["seeds"] == doc["seeds"]
    for mode in ALL_MODES:
        got = {k: v for k, v in out["results"][mode].items() if k != "environment"}
        want = {k: v for k, v in doc["modes"][mode].items() if k != "environment"}
        assert got == want, mode

    # 2) 화면 기준값(eval_reference.json): 화면 네 지표를 포함한 모든 값이 응답의 해당 경로와 같다
    ref = json.loads(WEB_REFERENCE.read_text(encoding="utf-8"))["sets"][intensity]
    for mode in ALL_MODES:
        res, want = out["results"][mode], ref["modes"][mode]
        assert set(want) == set(REFERENCE_PATHS) | {"by_scenario"}
        for key, path in REFERENCE_PATHS.items():
            assert _at(res, path) == want[key], (mode, key)
        for key in SCREEN_FOUR:
            assert _at(res, REFERENCE_PATHS[key]) == want[key]
        for code, v in want["by_scenario"].items():
            assert {k: res["scenario_recall"][code][k] for k in ("caution", "high", "n")} == v, (mode, code)
        assert res["n_cases"] == ref["n_cases"]
