"""평가 보고서(JSON + Markdown 표).

``write_report(results, out_dir)``는 ``metrics.evaluate`` / ``compare_modes`` / ``evaluate_file`` 결과를
받아 JSON(원자료)과 Markdown(표)을 쓴다. 보고서의 모든 수치는 결과 dict에서만 가져온다.
합성 데이터 결과에는 "합성 데이터 기준, 실제 피해 데이터 검증 아님"을 맨 위에 적는다.

합성 결과 JSON은 강도(standard·subtle)와 표본(표본 안·별도 검증 세트, SPEC §8 [추가 r5])으로 이름을 나눈다.
Markdown(eval_report.md)은 하나로, 같은 폴더의 네 JSON을 읽어 모든 절을 다시 만든다.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional

from safepause.data.synth import PERSONAS
from safepause.eval.metrics import DISCLAIMER, FILE_DISCLAIMER

SIGNAL_NAMES_KO: dict[str, str] = {
    "night_repeat_transfer": "심야 반복 이체",
    "payee_surge": "특정 계좌 송금 급증",
    "micropay_surge": "통신 소액결제 급증",
    "new_merchant_high_value": "신규 가맹점 고액 결제",
    "multi_line_telecom": "단기간 다회선 통신요금",
}
MODE_NAMES_KO: dict[str, str] = {
    "fused": "결합(룰+AI)",
    "rules": "룰만",
    "anomaly": "AI 이상탐지만",
}
LEVEL_NAMES_KO: dict[str, str] = {"none": "알림 없음", "caution": "주의", "high": "고위험"}
CHANNEL_NAMES_KO: dict[str, str] = {
    "transfer": "이체", "card": "카드", "micropay": "소액결제", "telecom_bill": "통신요금",
    "atm": "현금 인출", "income": "입금", "other": "기타",
}

SYNTHETIC_STEM = "eval"        # eval_results.json, eval_report.md
SUBTLE_SUFFIX = "_subtle"      # 경계 변형(subtle) 결과: eval_results_subtle.json (보고서는 eval_report.md 하나)
HOLDOUT_SUFFIX = "_holdout"    # 별도 검증 세트: eval_results_holdout.json, eval_results_subtle_holdout.json
IN_SAMPLE, HOLDOUT = "in_sample", "holdout"
FILE_STEM = "file_eval"        # file_eval_results.json, file_eval_report.md
MAX_REPORT_ALERTS = 50         # 거래내역 보고서 표에 싣는 알림 최대 건수


# ---------------------------------------------------------------------------
# 서식 도우미
# ---------------------------------------------------------------------------

def signal_name(code: str) -> str:
    return SIGNAL_NAMES_KO.get(code, code)


def mode_name(mode: str) -> str:
    return MODE_NAMES_KO.get(mode, mode)


def level_name(level: str) -> str:
    return LEVEL_NAMES_KO.get(level, level)


def channel_name(channel: str) -> str:
    return CHANNEL_NAMES_KO.get(channel, channel)


def pct(value: Optional[float], digits: int = 1) -> str:
    """0.1234 → '12.3%'. 값이 없으면 '-'."""
    return "-" if value is None else f"{value * 100:.{digits}f}%"


def num(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "-"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"


def won(value: Optional[float]) -> str:
    return "-" if value is None else f"{int(round(value)):,}원"


def _frac(rate: Optional[float], k: int, n: int) -> str:
    return f"{pct(rate)} ({k}/{n})"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Markdown 표 한 개."""
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def seeds_text(seeds: Sequence[int]) -> str:
    """[1..20] → '1~20 (20개)', 그 밖에는 나열."""
    seeds = list(seeds)
    if len(seeds) > 2 and seeds == list(range(seeds[0], seeds[0] + len(seeds))):
        return f"{seeds[0]}~{seeds[-1]} ({len(seeds)}개)"
    return f"{', '.join(str(s) for s in seeds)} ({len(seeds)}개)"


def _persona_text(keys: Sequence[str]) -> str:
    return ", ".join(f"{k}({PERSONAS[k].name})" if k in PERSONAS else k for k in keys)


def _env_text(env: dict[str, str] | None) -> str:
    if not env:
        return "-"
    return ", ".join(f"{k} {v}" for k, v in env.items())


# ---------------------------------------------------------------------------
# 합성 데이터 보고서
# ---------------------------------------------------------------------------

def _as_comparison(results: dict[str, Any]) -> dict[str, Any]:
    """모드 하나짜리 결과도 비교 결과 모양으로 맞춘다."""
    if results.get("kind") == "comparison":
        return results
    mode = results["mode"]
    return {**results, "kind": "comparison", "mode_order": [mode], "modes": {mode: results}}


def _settings_section(r: dict[str, Any]) -> str:
    s = r.get("settings", {})
    th = r.get("thresholds", {})
    n_p, n_s = len(r["personas"]), len(r["seeds"])
    rows = [
        ["데이터", f"합성 데이터(safepause.data.synth), 시작일 {r.get('start', '-')}"],
        ["인물 설정", _persona_text(r["personas"])],
        ["seed", seeds_text(r["seeds"])],
        ["사례 수", f"{n_p * n_s} (인물 {n_p} × seed {n_s})"],
        ["기간", f"{r['days']}일 = 학습 기준 {r['baseline_days']}일 + 평가 {r['eval_days']}일"],
        ["시나리오", f"사례마다 {len(r.get('scenarios', []))}종 각 1회, 평가 구간 안에 주입"],
        ["판단 설정", (f"심야 {s.get('night_start_hour', '-')}시~{s.get('night_end_hour', '-')}시 전, "
                   f"짧은 창 {s.get('window_short_days', '-')}일, 긴 창 {s.get('window_long_days', '-')}일, "
                   f"평소 기준 {s.get('baseline_days', '-')}일")],
    ]
    if th:
        rows.append(["결합 모드 기준",
                     f"룰 주의 + 이상 점수 ≥ {th['fused_escalate_score']:.2f} → 고위험, "
                     f"룰 없음 + 출금 + 이상 점수 ≥ {th['anomaly_alone_caution_score']:.2f} → 주의"])
        rows.append(["AI 이상탐지만 모드 기준",
                     f"출금 + 이상 점수 ≥ {th['anomaly_mode_high_score']:.2f} → 고위험, "
                     f"≥ {th['anomaly_mode_caution_score']:.2f} → 주의 (명세에 없어 비교용으로 정한 값)"])
    rows.append(["실행 환경", _env_text(r.get("environment"))])
    if r.get("command"):
        rows.append(["재현 명령", f"`{r['command']}`"])
    return "## 평가 설정\n\n" + md_table(["항목", "값"], rows)


def _summary_section(r: dict[str, Any]) -> str:
    rows = []
    for m in r["mode_order"]:
        res = r["modes"][m]
        o, nm, ctl = res["overall"], res["normal"], res.get("control") or {}
        rows.append([
            mode_name(m),
            _frac(o["recall_caution"], o["caution"], o["n"]),
            _frac(o["recall_high"], o["high"], o["n"]),
            pct(nm["alert_rate"], 2), pct(nm["high_rate"], 2),
            num(nm["monthly_alerts"]), num(nm["monthly_high"]),
            num(ctl.get("monthly_alerts")), num(ctl.get("monthly_high")),
        ])
    headers = ["모드", "시나리오 탐지율(주의 이상)", "시나리오 탐지율(고위험)", "정상 거래 알림률",
               "정상 거래 고위험률", "정상 월평균 알림", "정상 월평균 고위험",
               "대조군 월평균 알림", "대조군 월평균 고위험"]
    return "## 1. 모드 비교 요약\n\n" + md_table(headers, rows)


def _scenario_section(r: dict[str, Any]) -> str:
    parts = ["## 2. 시나리오별 탐지율"]
    headers = ["시나리오", "사례", "탐지(주의 이상)", "탐지(고위험)", "같은 시그널로 탐지",
               "주입 거래 수(평균)", "첫 알림 순번(평균)", "첫 알림 전 금액(평균)"]
    for m in r["mode_order"]:
        res = r["modes"][m]
        rows = []
        for code, s in res["scenario_recall"].items():
            rows.append([
                signal_name(code), s["n"],
                _frac(s["recall_caution"], s["caution"], s["n"]),
                _frac(s["recall_high"], s["high"], s["n"]),
                _frac(s["matched_rate"], s["matched"], s["n"]),
                num(s["txns_mean"]), num(s["first_alert_position_mean"]),
                won(s["amount_before_first_alert_mean"]),
            ])
        parts.append(f"### {mode_name(m)} ({m})\n\n" + md_table(headers, rows))
    return "\n\n".join(parts)


def _normal_section(r: dict[str, Any]) -> str:
    rows, ctl_rows = [], []
    for m in r["mode_order"]:
        res = r["modes"][m]
        nm = res["normal"]
        rows.append([mode_name(m), nm["n_txns"], nm["alerts"], nm["high"],
                     pct(nm["alert_rate"], 2), pct(nm["high_rate"], 2),
                     num(nm["monthly_alerts"]), num(nm["monthly_high"]),
                     num(nm.get("spillover_alerts")), num(nm.get("spillover_high"))])
        ctl = res.get("control")
        if ctl:
            ctl_rows.append([mode_name(m), ctl["n_txns"], ctl["alerts"], ctl["high"],
                             pct(ctl["alert_rate"], 2), pct(ctl["high_rate"], 2),
                             num(ctl["monthly_alerts"]), num(ctl["monthly_high"])])
    out = ["## 3. 정상 거래 오탐",
           "### 3.1 시나리오가 들어간 데이터의 정상 거래\n\n" + md_table(
               ["모드", "평가 정상 거래", "알림(주의 이상)", "고위험", "알림률", "고위험률",
                "월평균 알림", "월평균 고위험", "시나리오와 겹쳐 함께 알림", "그중 고위험"], rows)]
    if ctl_rows:
        out.append("### 3.2 정상 전용 대조군(같은 seed, 시나리오 없음)\n\n" + md_table(
            ["모드", "평가 정상 거래", "알림(주의 이상)", "고위험", "알림률", "고위험률",
             "월평균 알림", "월평균 고위험"], ctl_rows))
    return "\n\n".join(out)


def _confusion_section(r: dict[str, Any]) -> str:
    rows = []
    for m in r["mode_order"]:
        conf = r["modes"][m]["confusion"]
        for key, label in (("caution", "주의 이상"), ("high", "고위험")):
            c = conf[key]
            rows.append([mode_name(m), label, c["tp"], c["fp"], c["fn"], c["tn"],
                         pct(c["precision"]), pct(c["recall"])])
    return ("## 4. 거래 단위 혼동 요약(평가 구간 전체 거래)\n\n"
            + md_table(["모드", "알림 기준", "TP", "FP", "FN", "TN", "정밀도", "재현율"], rows)
            + "\n\nTP: 시나리오 거래를 알림, FP: 정상 거래를 알림, FN: 시나리오 거래를 알리지 않음, "
              "TN: 정상 거래를 알리지 않음.")


def _persona_section(r: dict[str, Any]) -> str:
    rows = []
    for m in r["mode_order"]:
        for p, v in r["modes"][m]["by_persona"].items():
            rows.append([mode_name(m), p, v["n_cases"], pct(v["recall_caution"]), pct(v["recall_high"]),
                         pct(v["normal_alert_rate"], 2), pct(v["normal_high_rate"], 2),
                         num(v["monthly_alerts"]), num(v["control_monthly_alerts"])])
    return "## 5. 인물 설정별 요약\n\n" + md_table(
        ["모드", "인물", "사례", "탐지율(주의 이상)", "탐지율(고위험)", "정상 알림률", "정상 고위험률",
         "정상 월평균 알림", "대조군 월평균 알림"], rows)


_DEFINITIONS = """## 지표 정의

- 시나리오 탐지(주의 이상): 한 사례의 한 시나리오(주입 거래 묶음) 중 1건 이상이 주의 또는 고위험이면 탐지로 셉니다.
- 시나리오 탐지(고위험): 주입 거래 중 1건 이상이 고위험이면 탐지로 셉니다. 고위험은 당사자가 동의하고 지정한 신뢰 조력자에게 2차 알림이 갈 수 있는 등급입니다.
- 같은 시그널로 탐지: 주입한 시나리오와 같은 종류의 룰이 주입 거래 1건 이상에서 발동한 비율입니다. AI 이상탐지만 모드는 룰을 쓰지 않아 0입니다.
- 첫 알림 순번·첫 알림 전 금액: 탐지된 시나리오에서 처음 알린 주입 거래가 몇 번째였는지, 그 전까지 나간 주입 거래 금액이 얼마였는지의 평균입니다.
- 정상 거래 알림률·고위험률: 평가 구간 정상 거래(입금 포함) 중 주의 이상·고위험 판단 비율입니다.
- 월평균 알림: 인물 1명의 평가 구간 30일당 정상 거래 알림 건수입니다.
- 정상 전용 대조군: 같은 seed로 시나리오 없이 만든 데이터입니다. 정상 거래는 시나리오 데이터와 똑같습니다.
- 시나리오와 겹쳐 함께 알림: 대조군에서는 알리지 않았는데 시나리오 거래가 이력에 있을 때 알린 정상 거래 수입니다."""

_CAVEATS = f"""## 해석 시 유의점

- **{DISCLAIMER}.** 합성 데이터는 제안서 S19 시그널을 재현하려고 설계한 가정 기반 시나리오이며, 공개 통계로 보정하지 않았습니다. 가정은 docs/dataset_card.md에 있습니다.
- 표준(standard) 시나리오 거래는 명세(SPEC §5)의 룰 기준을 넘도록 여유를 두고 만들었습니다. 따라서 표준 시나리오에서 룰 탐지율이 높은 것은 설계에 따른 결과이며, 실제 착취 사례의 탐지율을 뜻하지 않습니다.
- 시나리오가 들어간 데이터의 정상 거래 알림에는 시나리오 기간과 겹친 정상 거래가 포함됩니다. 시나리오가 없을 때의 알림 수준은 대조군 값을 보십시오.
- AI 이상탐지만 모드의 등급 기준은 명세에 없어 비교용으로 정한 값입니다. 앱은 결합 모드로 판단합니다.
- 결합 모드에서 AI 모델 단독으로는 고위험을 내지 않습니다. 기본 설정(조력자에게 '꼭 확인할 때만' 알림)에서 오탐으로 조력자 알림이 가는 것을 막기 위한 설계입니다(S38). 당사자가 ⑤에서 알림 등급을 '확인할 때도'로 바꾸고 '무엇을 알릴까요?'를 '모든 것'으로 두면 AI만 걱정한 '확인해요' 거래도 그 조력자에게 알립니다.
- 알림은 안내일 뿐 거래를 막지 않습니다. 조력자 알림은 기록만 되고 실제로 발송하지 않습니다."""


_SUBTLE_CAVEAT = ("- 경계 변형(subtle) 시나리오는 룰 기준에 못 미치거나 겨우 닿게 줄인 가정 기반 변형입니다"
                  "(SPEC §3 [추가 r4]). 실제 착취 거래가 이런 모양이라는 근거는 없으며, 이 결과도 실제 착취 "
                  "사례의 탐지율을 뜻하지 않습니다.")

# 경계 변형 정의 요약(SPEC §3 [추가 r4]와 같은 내용)
SUBTLE_DEFINITIONS_KO: dict[str, str] = {
    "night_repeat_transfer": "7일 안 00~04시, 처음 보는 상대 1명에게 이체 2건(각 30만~80만 원)",
    "payee_surge": ("처음 보는 상대 1명에게 7일 안 이체 2건, 합계 = 평소 7일 송금 합계의 2.0~2.9배"
                    "(평소 합계 0이면 20만~29만 원)"),
    "micropay_surge": "7일 안 휴대폰 소액결제 4건(각 5만~10만 원)",
    "new_merchant_high_value": "처음 보는 가맹점 1곳 결제 1건, 금액 = max(개인 카드 p95의 2.0~2.9배, 10만 원)",
    "multi_line_telecom": "처음 보는 회선 1개의 통신요금 청구 1건",
}
_COMPARED_KEYS: tuple[tuple[str, str], ...] = (
    ("personas", "인물"), ("seeds", "seed"), ("days", "기간"), ("baseline_days", "학습 기준 기간"),
    ("start", "시작일"), ("mode_order", "모드"), ("settings", "판단 설정"), ("thresholds", "결합 기준"),
)


def intensity_of(results: dict[str, Any]) -> str:
    """합성 결과의 시나리오 강도(예전 결과처럼 값이 없으면 standard)."""
    return str(results.get("intensity") or "standard")


def pp(delta: Optional[float], digits: int = 1) -> str:
    """비율 차이 → '+12.5%p'. 0이면 '0.0%p', 값이 없으면 '-'."""
    if delta is None:
        return "-"
    value = round(delta * 100, digits)
    return f"{0:.{digits}f}%p" if value == 0 else f"{value:+.{digits}f}%p"


def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else a - b


def _subtle_settings_rows(sub: dict[str, Any], std: Optional[dict[str, Any]]) -> list[list[str]]:
    n_p, n_s = len(sub["personas"]), len(sub["seeds"])
    rows = [
        ["데이터", f"합성 데이터(safepause.data.synth, intensity=subtle), 시작일 {sub.get('start', '-')}"],
        ["인물 설정", _persona_text(sub["personas"])],
        ["seed", seeds_text(sub["seeds"])],
        ["사례 수", f"{n_p * n_s} (인물 {n_p} × seed {n_s})"],
        ["기간", f"{sub['days']}일 = 학습 기준 {sub['baseline_days']}일 + 평가 {sub['eval_days']}일"],
        ["모드", ", ".join(f"{mode_name(m)} ({m})" for m in sub["mode_order"])],
    ]
    for code in sub.get("scenarios", []):
        rows.append([f"시나리오: {signal_name(code)}", SUBTLE_DEFINITIONS_KO.get(code, "-")])
    rows.append(["실행 환경", _env_text(sub.get("environment"))])
    if sub.get("command"):
        rows.append(["재현 명령", f"`{sub['command']}`"])
    if std is not None:
        differ = [label for key, label in _COMPARED_KEYS if std.get(key) != sub.get(key)]
        if differ:
            rows.append(["표준 결과와 다른 설정", ", ".join(differ)])
    return rows


def _subtle_recall_table(sub: dict[str, Any]) -> str:
    modes = sub["mode_order"]
    headers = ["시나리오", "사례"]
    for m in modes:
        headers += [f"{mode_name(m)} 주의 이상", f"{mode_name(m)} 고위험"]
    first = sub["modes"][modes[0]]
    rows = []
    for code in first["scenario_recall"]:
        row: list[Any] = [signal_name(code), first["scenario_recall"][code]["n"]]
        for m in modes:
            s = sub["modes"][m]["scenario_recall"][code]
            row += [_frac(s["recall_caution"], s["caution"], s["n"]),
                    _frac(s["recall_high"], s["high"], s["n"])]
        rows.append(row)
    row = ["전체", first["overall"]["n"]]
    for m in modes:
        o = sub["modes"][m]["overall"]
        row += [_frac(o["recall_caution"], o["caution"], o["n"]),
                _frac(o["recall_high"], o["high"], o["n"])]
    rows.append(row)
    return md_table(headers, rows)


def _subtle_normal_table(sub: dict[str, Any]) -> str:
    rows = []
    for m in sub["mode_order"]:
        nm = sub["modes"][m]["normal"]
        ctl = sub["modes"][m].get("control") or {}
        rows.append([mode_name(m), nm["n_txns"], nm["alerts"], nm["high"],
                     pct(nm["alert_rate"], 2), pct(nm["high_rate"], 2),
                     num(nm["monthly_alerts"]), num(nm["monthly_high"]),
                     num(ctl.get("monthly_alerts")), num(ctl.get("monthly_high"))])
    return md_table(["모드", "평가 정상 거래", "알림(주의 이상)", "고위험", "알림률", "고위험률",
                     "월평균 알림", "월평균 고위험", "대조군 월평균 알림", "대조군 월평균 고위험"], rows)


def _subtle_matched_table(sub: dict[str, Any]) -> Optional[str]:
    rule_modes = [m for m in sub["mode_order"] if m != "anomaly"]
    if not rule_modes:
        return None
    res = sub["modes"][rule_modes[0]]
    rows = []
    for code, s in res["scenario_recall"].items():
        rows.append([signal_name(code), s["n"], num(s["txns_mean"]),
                     _frac(s["matched_rate"], s["matched"], s["n"])])
    return md_table(["시나리오", "사례", "주입 거래 수(평균)",
                     "같은 시그널 룰 발동(룰만·결합 공통)"], rows)


def _change_text(label: str, f: dict[str, Any], r: dict[str, Any]) -> str:
    """결합 − 룰만 차이 한 줄(수치 그대로)."""
    dc = _diff(f["recall_caution"], r["recall_caution"])
    dh = _diff(f["recall_high"], r["recall_high"])
    text = (f"{label}: 결합 모드는 룰만 대비 주의 이상 탐지율 {pp(dc)} "
            f"({r['caution']}/{r['n']} → {f['caution']}/{f['n']}), 고위험 탐지율 {pp(dh)} "
            f"({r['high']}/{r['n']} → {f['high']}/{f['n']}).")
    if f["caution"] == r["caution"] and f["high"] == r["high"]:
        text += " 이 시나리오에서 AI 이상탐지가 더한 탐지는 없습니다."
    return text


def _subtle_interpretation(sub: dict[str, Any]) -> str:
    modes = sub["modes"]
    lines: list[str] = []
    table = ""
    if "fused" in modes and "rules" in modes:
        fused, rules = modes["fused"], modes["rules"]
        rows = [[signal_name(code), pp(_diff(f["recall_caution"], rules["scenario_recall"][code]["recall_caution"])),
                 pp(_diff(f["recall_high"], rules["scenario_recall"][code]["recall_high"]))]
                for code, f in fused["scenario_recall"].items() if code in rules["scenario_recall"]]
        rows.append(["전체", pp(_diff(fused["overall"]["recall_caution"], rules["overall"]["recall_caution"])),
                     pp(_diff(fused["overall"]["recall_high"], rules["overall"]["recall_high"]))])
        rows.append(["정상 거래 알림률·고위험률(오탐)",
                     pp(_diff(fused["normal"]["alert_rate"], rules["normal"]["alert_rate"]), 2),
                     pp(_diff(fused["normal"]["high_rate"], rules["normal"]["high_rate"]), 2)])
        table = md_table(["구분", "주의 이상 차이(결합 − 룰만)", "고위험 차이(결합 − 룰만)"], rows) + "\n\n"
        lines.append("- " + _change_text("전체", fused["overall"], rules["overall"]))
        for code, f in fused["scenario_recall"].items():
            r = rules["scenario_recall"].get(code)
            if r is not None:
                lines.append("- " + _change_text(signal_name(code), f, r))
        fn, rn = fused["normal"], rules["normal"]
        lines.append(f"- 정상 거래: 결합 모드의 알림률은 룰만 대비 {pp(_diff(fn['alert_rate'], rn['alert_rate']), 2)} "
                     f"({rn['alerts']}건 → {fn['alerts']}건 / {fn['n_txns']}건), 고위험률 "
                     f"{pp(_diff(fn['high_rate'], rn['high_rate']), 2)} ({rn['high']}건 → {fn['high']}건).")
    if "anomaly" in modes:
        a = modes["anomaly"]
        o, nm = a["overall"], a["normal"]
        lines.append(f"- AI 이상탐지만 모드: 전체 주의 이상 탐지율 {_frac(o['recall_caution'], o['caution'], o['n'])}, "
                     f"고위험 탐지율 {_frac(o['recall_high'], o['high'], o['n'])}, 정상 거래 알림률 "
                     f"{pct(nm['alert_rate'], 2)}, 고위험률 {pct(nm['high_rate'], 2)}.")
    if not lines:
        return ""
    return ("아래 문장은 결과 수치로 자동으로 만들었습니다. 결합 규칙상 거래마다 결합 모드의 등급은 룰만 모드 "
            "이상이라, 결합 − 룰만 차이는 AI 이상탐지가 룰 판단에 더한 몫입니다(룰 주의를 고위험으로 올림: "
            "이상 점수 ≥ 0.90, 룰 없이 주의: 출금이고 이상 점수 ≥ 0.98).\n\n" + table + "\n".join(lines))


def _subtle_section(sub: dict[str, Any], std: Optional[dict[str, Any]], number: int) -> str:
    n = number
    intro = (f"## {n}. 경계 변형(subtle) 시나리오: 사전 등록 실험\n\n"
             f"> **{DISCLAIMER}.** 표준 시나리오는 룰 기준을 넉넉히 넘게 만들어 룰만으로도 탐지됩니다. 이 절은 "
             "룰 기준에 못 미치거나 겨우 닿게 줄인 변형에서 룰만·결합·AI 이상탐지만 모드를 비교한 값입니다. "
             "변형 정의와 비교 방법은 결과를 보기 전에 SPEC.md §3·§8 [추가 r4]에 적었고, 결과를 본 뒤 정의와 "
             "기준값을 바꾸지 않았습니다. 라벨은 표준과 같은 시그널 값이며, 대조군(시나리오 없음)은 표준과 같은 데이터입니다.")
    parts = [intro,
             f"### {n}.1 설정\n\n" + md_table(["항목", "값"], _subtle_settings_rows(sub, std)),
             f"### {n}.2 모드별 시나리오 탐지율\n\n" + _subtle_recall_table(sub),
             f"### {n}.3 정상 거래 알림(경계 변형 데이터)\n\n" + _subtle_normal_table(sub)]
    matched = _subtle_matched_table(sub)
    if matched:
        parts.append(f"### {n}.4 같은 시그널 룰이 발동한 비율\n\n" + matched
                     + "\n\n주입한 시나리오와 같은 종류의 룰이 주입 거래 1건 이상에서 발동한 사례 비율입니다. "
                       "탐지는 됐는데 이 비율이 낮으면 다른 룰(또는 AI 이상탐지)이 알린 것입니다.")
    interp = _subtle_interpretation(sub)
    if interp:
        parts.append(f"### {n}.{5 if matched else 4} 결합 − 룰만 차이(수치 그대로)\n\n" + interp)
    return "\n\n".join(parts)


def _synthetic_markdown(results: Optional[dict[str, Any]],
                        subtle: Optional[dict[str, Any]] = None, subtle_note: str = "", *,
                        holdout: Optional[dict[str, Any]] = None,
                        holdout_subtle: Optional[dict[str, Any]] = None,
                        holdout_notes: Sequence[str] = ()) -> str:
    """표준 결과(results), 경계 변형 결과(subtle), 별도 검증 세트 결과(holdout·holdout_subtle)를
    한 보고서로 만든다. 표본 안 절(표준·경계 변형)은 검증 세트가 있어도 같은 글로 만든다."""
    head = ("# SafePause 성능 평가 보고서\n\n"
            f"> **{DISCLAIMER}.** 제안서 S19의 착취 시그널 5종을 재현하려고 설계한 가정 기반 합성 "
            "시나리오에서 잰 값입니다. 공개 통계로 보정한 데이터가 아니며, 실제 착취 피해 거래로 "
            "검증한 결과가 아닙니다.")
    sections = [head]
    std = _as_comparison(results) if results is not None else None
    sub = _as_comparison(subtle) if subtle is not None else None
    h_std = _as_comparison(holdout) if holdout is not None else None
    h_sub = _as_comparison(holdout_subtle) if holdout_subtle is not None else None
    has_holdout = h_std is not None or h_sub is not None
    last = (5 if std is not None else 0) + (1 if sub is not None else 0)
    if has_holdout and last:
        sections.append(_in_sample_note(std, sub, h_std, h_sub, last))
    if std is not None:
        sections += [_settings_section(std), _summary_section(std), _scenario_section(std),
                     _normal_section(std), _confusion_section(std), _persona_section(std)]
    if sub is not None:
        sections.append(_subtle_section(sub, std, 6 if std is not None else 1))
    elif subtle_note:
        sections.append(subtle_note)
    if has_holdout:
        sections.append(_holdout_section(h_std, h_sub, std, sub, last + 1, holdout_notes))
    elif holdout_notes:
        sections += list(holdout_notes)
    caveats = _CAVEATS if sub is None else _CAVEATS + "\n" + _SUBTLE_CAVEAT
    if has_holdout:
        caveats += "\n" + _HOLDOUT_CAVEAT
    sections += [_DEFINITIONS, caveats]
    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# 별도 검증 세트(holdout, SPEC §8 [추가 r5])
# ---------------------------------------------------------------------------

_VARIANTS: tuple[tuple[str, str], ...] = (
    ("standard", IN_SAMPLE), ("subtle", IN_SAMPLE), ("standard", HOLDOUT), ("subtle", HOLDOUT))
_INTENSITY_NAMES_KO = {"standard": "표준", "subtle": "경계 변형(subtle)"}
_IN_SAMPLE_JSON = {"standard": "eval_results.json", "subtle": "eval_results_subtle.json"}

_HOLDOUT_CAVEAT = ("- 별도 검증 세트도 같은 합성 생성기·같은 인물 설정에서 seed만 바꾼 데이터입니다. 룰 보완에 쓰지 "
                   "않은 표본이라는 뜻일 뿐, 다른 분포나 실제 거래로 검증했다는 뜻이 아닙니다. 두 표본의 차이에는 "
                   "seed에 따른 표본 변동이 섞여 있습니다.")

# (키, 이름, 종류, 좋은 방향: +1 높을수록 좋음, -1 낮을수록 좋음)
_HOLDOUT_METRICS: tuple[tuple[str, str, str, int], ...] = (
    ("scn_caution", "시나리오 탐지율(주의 이상)", "rate", 1),
    ("scn_high", "시나리오 탐지율(고위험)", "rate", 1),
    ("txn_high_recall", "거래 단위 고위험 재현율", "rate", 1),
    ("normal_alert_rate", "정상 거래 알림률", "rate2", -1),
    ("normal_high_rate", "정상 거래 고위험률", "rate2", -1),
    ("ctrl_monthly_alerts", "대조군 1인당 월평균 알림(주의 이상)", "monthly", -1),
    ("ctrl_monthly_high", "대조군 1인당 월평균 고위험", "monthly", -1),
)


def split_of(results: dict[str, Any]) -> str:
    """합성 결과의 표본: 별도 검증 세트면 "holdout", 값이 없으면 표본 안("in_sample")."""
    return HOLDOUT if results.get("split") == HOLDOUT else IN_SAMPLE


def synthetic_json_name(stem: str, intensity: str, split: str = IN_SAMPLE) -> str:
    """합성 결과 JSON 이름: eval_results.json, eval_results_subtle.json,
    eval_results_holdout.json, eval_results_subtle_holdout.json."""
    suffix = (SUBTLE_SUFFIX if intensity == "subtle" else "") + (HOLDOUT_SUFFIX if split == HOLDOUT else "")
    return f"{stem}_results{suffix}.json"


def _seed_range(seeds: Sequence[int]) -> str:
    """[21..40] → '21~40', 이어지지 않으면 나열."""
    seeds = list(seeds)
    if len(seeds) > 2 and seeds == list(range(seeds[0], seeds[0] + len(seeds))):
        return f"{seeds[0]}~{seeds[-1]}"
    return ", ".join(str(s) for s in seeds)


def _first(*items: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    return next((x for x in items if x is not None), None)


def _metric(res: Optional[dict[str, Any]], key: str) -> tuple[Optional[float], str]:
    """(값, 표시 글). 결과가 없으면 (None, '-')."""
    if res is None:
        return None, "-"
    o, nm, ctl = res["overall"], res["normal"], res.get("control") or {}
    if key == "scn_caution":
        return o["recall_caution"], _frac(o["recall_caution"], o["caution"], o["n"])
    if key == "scn_high":
        return o["recall_high"], _frac(o["recall_high"], o["high"], o["n"])
    if key == "txn_high_recall":
        c = res["confusion"]["high"]
        return c["recall"], _frac(c["recall"], c["tp"], c["tp"] + c["fn"])
    if key == "normal_alert_rate":
        return nm["alert_rate"], f"{pct(nm['alert_rate'], 2)} ({nm['alerts']}/{nm['n_txns']})"
    if key == "normal_high_rate":
        return nm["high_rate"], f"{pct(nm['high_rate'], 2)} ({nm['high']}/{nm['n_txns']})"
    if key == "ctrl_monthly_alerts":
        v = ctl.get("monthly_alerts")
        return v, "-" if v is None else f"{num(v)} (총 {ctl['alerts']}건)"
    if key == "ctrl_monthly_high":
        v = ctl.get("monthly_high")
        return v, "-" if v is None else f"{num(v)} (총 {ctl['high']}건)"
    raise KeyError(key)


def _delta_text(kind: str, before: Optional[float], after: Optional[float]) -> str:
    """검증 세트 − 표본 안. 비율은 %p, 월평균은 건."""
    d = _diff(after, before)
    if d is None:
        return "-"
    if kind == "monthly":
        v = round(d, 2)
        return "0.00건" if v == 0 else f"{v:+.2f}건"
    digits = 2 if kind == "rate2" else 1
    if d != 0 and round(d * 100, digits) == 0:
        digits += 2                      # 반올림하면 0으로 보이는 작은 차이도 드러낸다
    return pp(d, digits)


def _direction(better: int, before: Optional[float], after: Optional[float]) -> str:
    if before is None or after is None:
        return "-"
    if after == before:
        return "같음"
    return "더 좋음" if (after - before) * better > 0 else "더 나쁨"


def _mode_res(r: Optional[dict[str, Any]], mode: str) -> Optional[dict[str, Any]]:
    return None if r is None else r["modes"].get(mode)


def _holdout_metric_table(h: dict[str, Any]) -> str:
    headers = ["모드"] + [label for _, label, _, _ in _HOLDOUT_METRICS]
    rows = []
    for m in h["mode_order"]:
        res = h["modes"][m]
        rows.append([mode_name(m)] + [_metric(res, key)[1] for key, _, _, _ in _HOLDOUT_METRICS])
    return md_table(headers, rows)


def _holdout_compare_table(h: dict[str, Any], ins: Optional[dict[str, Any]], in_label: str,
                           h_label: str) -> str:
    headers = ["모드", "지표", in_label, h_label, "차이(검증 − 표본 안)", "검증 세트 쪽"]
    rows = []
    for m in h["mode_order"]:
        for key, label, kind, better in _HOLDOUT_METRICS:
            a, a_text = _metric(_mode_res(ins, m), key)
            b, b_text = _metric(h["modes"][m], key)
            rows.append([mode_name(m), label, a_text, b_text, _delta_text(kind, a, b),
                         _direction(better, a, b)])
    return md_table(headers, rows)


def _gain_cells(r: Optional[dict[str, Any]], code: Optional[str]) -> tuple[str, str]:
    """결합 − 룰만 차이(주의 이상, 고위험). code가 None이면 전체, "normal"이면 정상 거래 알림률·고위험률."""
    if r is None or "fused" not in r["modes"] or "rules" not in r["modes"]:
        return "-", "-"
    f, ru = r["modes"]["fused"], r["modes"]["rules"]
    if code == "normal":
        return (f"{pp(_diff(f['normal']['alert_rate'], ru['normal']['alert_rate']), 2)} "
                f"({ru['normal']['alerts']}→{f['normal']['alerts']}건)",
                f"{pp(_diff(f['normal']['high_rate'], ru['normal']['high_rate']), 2)} "
                f"({ru['normal']['high']}→{f['normal']['high']}건)")
    if code is None:
        a, b = f["overall"], ru["overall"]
    else:
        a, b = f["scenario_recall"].get(code), ru["scenario_recall"].get(code)
        if a is None or b is None:
            return "-", "-"
    return (f"{pp(_diff(a['recall_caution'], b['recall_caution']))} ({b['caution']}→{a['caution']})",
            f"{pp(_diff(a['recall_high'], b['recall_high']))} ({b['high']}→{a['high']})")


def _holdout_gain_table(h: dict[str, Any], ins: Optional[dict[str, Any]], in_range: str,
                        h_range: str) -> Optional[str]:
    if "fused" not in h["modes"] or "rules" not in h["modes"]:
        return None
    codes: list[Optional[str]] = [*h["modes"]["fused"]["scenario_recall"], None, "normal"]
    rows = []
    for code in codes:
        name = ("전체" if code is None else "정상 거래 알림률·고위험률(오탐)" if code == "normal"
                else signal_name(code))
        ic, ih = _gain_cells(ins, code)
        hc, hh = _gain_cells(h, code)
        rows.append([name, ic, hc, ih, hh])
    return md_table(["구분", f"주의 이상: seed {in_range}", f"주의 이상: seed {h_range}",
                     f"고위험: seed {in_range}", f"고위험: seed {h_range}"], rows)


def _value_text(kind: str, value: Optional[float]) -> str:
    if kind == "monthly":
        return f"{num(value)}건"
    return pct(value, 2 if kind == "rate2" else 1)


def _holdout_sentences(h: dict[str, Any], ins: Optional[dict[str, Any]], intensity: str) -> list[str]:
    """모드마다 검증 세트에서 더 나쁜·더 좋은·같은 지표를 수치 그대로 적는다."""
    lines = []
    for m in h["mode_order"]:
        groups: dict[str, list[str]] = {"더 나쁨": [], "더 좋음": [], "같음": []}
        for key, label, kind, good in _HOLDOUT_METRICS:
            a, _ = _metric(_mode_res(ins, m), key)
            b, _ = _metric(h["modes"][m], key)
            direction = _direction(good, a, b)
            if direction == "-":
                continue
            groups[direction].append(label if direction == "같음" else
                                     f"{label} {_value_text(kind, a)} → {_value_text(kind, b)}"
                                     f"({_delta_text(kind, a, b)})")
        parts = [f"{title}: {', '.join(items)}" for title, items in
                 (("검증 세트에서 더 나쁨", groups["더 나쁨"]), ("더 좋음", groups["더 좋음"]),
                  ("같음", groups["같음"])) if items]
        if parts:
            lines.append(f"- {_INTENSITY_NAMES_KO.get(intensity, intensity)} · {mode_name(m)}: "
                         + ". ".join(parts) + ".")
    return lines


def _compare_word(before: float, after: float) -> str:
    if after == before:
        return "같습니다"
    return "검증 세트가 더 높습니다" if after > before else "검증 세트가 더 낮습니다"


def _holdout_headline(h: Optional[dict[str, Any]], ins: Optional[dict[str, Any]], in_range: str,
                      h_range: str) -> Optional[str]:
    """앱 기본(결합) 모드의 대조군 오탐 비교 한 문장."""
    f_h, f_i = _mode_res(h, "fused"), _mode_res(ins, "fused")
    if f_h is None or f_i is None or not f_h.get("control") or not f_i.get("control"):
        return None
    ci, ch = f_i["control"], f_h["control"]
    return (f"- 앱 기본인 결합 모드의 정상 전용 대조군(시나리오 없음, 두 강도에서 같은 데이터) 1인당 월평균 알림은 "
            f"seed {in_range}에서 {num(ci['monthly_alerts'])}건(총 {ci['alerts']}건), seed {h_range}에서 "
            f"{num(ch['monthly_alerts'])}건(총 {ch['alerts']}건)으로 "
            f"{_compare_word(ci['monthly_alerts'], ch['monthly_alerts'])}. 월평균 고위험(조력자 알림 대상)은 "
            f"{num(ci['monthly_high'])}건(총 {ci['high']}건)에서 {num(ch['monthly_high'])}건(총 {ch['high']}건)으로 "
            f"{_compare_word(ci['monthly_high'], ch['monthly_high'])}.")


def _holdout_settings_rows(h_std: Optional[dict[str, Any]], h_sub: Optional[dict[str, Any]],
                           in_std: Optional[dict[str, Any]], in_sub: Optional[dict[str, Any]]
                           ) -> list[list[str]]:
    base = _first(h_std, h_sub)
    assert base is not None
    in_base = _first(in_std, in_sub)
    present = [(x, name) for x, name in ((h_std, "표준"), (h_sub, "경계 변형")) if x is not None]
    rows: list[list[str]] = []
    if len({tuple(x["seeds"]) for x, _ in present}) == 1:
        rows.append(["검증 세트 seed", seeds_text(base["seeds"])])
    else:
        rows += [[f"검증 세트 seed({name})", seeds_text(x["seeds"])] for x, name in present]
    rows.append(["비교한 표본 안 seed", seeds_text(in_base["seeds"]) if in_base is not None
                 else "없음(이 폴더에 표본 안 결과 JSON이 없어요)"])
    h_seeds = {s for x, _ in present for s in x["seeds"]}
    in_seeds = {s for x in (in_std, in_sub) if x is not None for s in x["seeds"]}
    overlap = sorted(h_seeds & in_seeds)
    rows.append(["표본 안 seed와 겹침", "없음" if not overlap else
                 f"{len(overlap)}개({_seed_range(overlap)}). 겹치는 seed가 있어 이 절은 별도 검증 세트가 아닙니다"])
    n_p, n_s = len(base["personas"]), len(base["seeds"])
    rows += [
        ["사례 수", f"{n_p * n_s} (인물 {n_p} × seed {n_s})"],
        ["인물 설정", _persona_text(base["personas"])],
        ["기간", f"{base['days']}일 = 학습 기준 {base['baseline_days']}일 + 평가 {base['eval_days']}일"],
        ["모드", ", ".join(f"{mode_name(m)} ({m})" for m in base["mode_order"])],
    ]
    rows += [[f"재현 명령({name})", f"`{x['command']}`"] for x, name in present if x.get("command")]
    rows.append(["실행 환경", _env_text(base.get("environment"))])
    differ: list[str] = []
    for x, ins, name in ((h_std, in_std, "표준"), (h_sub, in_sub, "경계 변형")):
        if x is None or ins is None:
            continue
        keys = [label for key, label in _COMPARED_KEYS if key != "seeds" and x.get(key) != ins.get(key)]
        if x.get("environment") != ins.get("environment"):
            keys.append("실행 환경")
        if keys:
            differ.append(f"{name}: {', '.join(keys)}")
    if differ:
        rows.append(["표본 안 결과와 다른 설정", "; ".join(differ)])
    return rows


def _in_sample_note(std: Optional[dict[str, Any]], sub: Optional[dict[str, Any]],
                    h_std: Optional[dict[str, Any]], h_sub: Optional[dict[str, Any]], last: int) -> str:
    """검증 세트가 있을 때 보고서 맨 위에 붙이는 안내: 앞 절은 표본 안 값."""
    ins, h = _first(std, sub), _first(h_std, h_sub)
    assert ins is not None and h is not None
    span = "1절은" if last == 1 else f"1~{last}절은"
    return (f"> {span} seed {_seed_range(ins['seeds'])} 값입니다. r1~r3의 룰 보완은 이 seed들의 평가(특히 시나리오 "
            "없는 대조군)를 보며 했으므로 표본 안(in-sample) 값입니다. 룰 보완에 쓰지 않은 seed "
            f"{_seed_range(h['seeds'])}(별도 검증 세트)의 값은 {last + 1}절에 있습니다.")


def _holdout_section(h_std: Optional[dict[str, Any]], h_sub: Optional[dict[str, Any]],
                     in_std: Optional[dict[str, Any]], in_sub: Optional[dict[str, Any]], number: int,
                     notes: Sequence[str] = ()) -> str:
    n = number
    base = _first(h_std, h_sub)
    assert base is not None
    in_base = _first(in_std, in_sub)
    h_range = _seed_range(base["seeds"])
    in_range = _seed_range(in_base["seeds"]) if in_base is not None else "-"
    in_text = f"seed {in_range}" if in_base is not None else "기본 실행(seed 1부터)"
    intro = (f"## {n}. 별도 검증 세트(seed {h_range})\n\n"
             f"> **{DISCLAIMER}.** r1~r3의 룰 보완은 {in_text} 평가(특히 시나리오 없는 대조군)를 보며 했으므로, "
             f"{in_text}의 수치는 룰을 맞추는 데 쓴 표본 안(in-sample) 값입니다. 이 절은 룰 보완에 쓰지 않은 "
             f"seed {h_range}(별도 검증 세트)에서 같은 룰·기준값·모델·합성 정의와 같은 절차·지표로 잰 값입니다. "
             "검증 세트와 지표는 결과를 보기 전에 SPEC.md §8 [추가 r5]에 적었고, 결과를 본 뒤 룰·기준값·모델·"
             "합성 정의를 바꾸지 않았습니다. 같은 합성 생성기에서 seed만 바꾼 데이터이므로 실제 거래나 다른 "
             "분포에서의 성능을 뜻하지 않습니다.")
    parts = [intro, f"### {n}.1 설정\n\n" + md_table(
        ["항목", "값"], _holdout_settings_rows(h_std, h_sub, in_std, in_sub))]
    parts += list(notes)
    h_label = f"seed {h_range} (검증 세트)"
    sub_no = 2
    sentences: list[str] = []
    for h, ins, intensity in ((h_std, in_std, "standard"), (h_sub, in_sub, "subtle")):
        if h is None:
            continue
        block = [f"### {n}.{sub_no} {_INTENSITY_NAMES_KO[intensity]} 시나리오",
                 f"seed {h_range}(검증 세트) 지표:\n\n" + _holdout_metric_table(h)]
        if ins is not None:
            in_label = f"seed {_seed_range(ins['seeds'])} (표본 안)"
            block.append(f"{in_label}과 나란히 비교:\n\n" + _holdout_compare_table(h, ins, in_label, h_label)
                         + "\n\n'검증 세트 쪽'은 탐지율·재현율은 높을수록, 알림률·고위험률·대조군 월평균은 "
                           "낮을수록 '더 좋음'으로 적었습니다.")
        else:
            block.append(f"> 이 폴더에 표본 안 결과({_IN_SAMPLE_JSON[intensity]})가 없어 비교 표를 싣지 않았습니다.")
        block.append("시나리오별 탐지율(검증 세트):\n\n" + _subtle_recall_table(h))
        gain = _holdout_gain_table(h, ins, _seed_range(ins["seeds"]) if ins is not None else "-", h_range)
        if gain:
            block.append("결합 − 룰만 차이(AI 이상탐지가 룰 판단에 더한 몫. 괄호는 룰만 → 결합 사례·건수):\n\n" + gain)
        parts.append("\n\n".join(block))
        sub_no += 1
        sentences += _holdout_sentences(h, ins, intensity)
    pair = (h_std, in_std) if h_std is not None and in_std is not None else (h_sub, in_sub)
    headline = _holdout_headline(pair[0], pair[1], in_range, h_range)
    lines = ([headline] if headline else []) + sentences
    if lines:
        parts.append(f"### {n}.{sub_no} 표본 안과 비교(수치 그대로)\n\n"
                     "아래 문장은 결과 수치로 자동으로 만들었습니다. 검증 세트 값이 나쁘면 나쁘다고 적었습니다. "
                     f"seed {len(base['seeds'])}개({len(base['personas']) * len(base['seeds'])}사례)라 차이 일부는 "
                     "표본 변동일 수 있습니다.\n\n" + "\n".join(lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 사용자 거래내역 보고서
# ---------------------------------------------------------------------------

def _file_markdown(r: dict[str, Any], max_alerts: int = MAX_REPORT_ALERTS) -> str:
    period = r["period"]
    head = ("# SafePause 거래내역 점검 결과\n\n"
            f"> **{FILE_DISCLAIMER}.** 거래가 모두 정상이라고 가정하고, 앞부분으로 개인 기준을 "
            "학습한 뒤 뒷부분에서 알림이 얼마나 나오는지 잰 값입니다.")
    settings = md_table(["항목", "값"], [
        ["모드", f"{mode_name(r['mode'])} ({r['mode']})"],
        ["거래 수", f"{r['n_total']}건 (학습 {r['n_baseline']}건 + 평가 {r['n_eval']}건)"],
        ["학습 비율", pct(r["baseline_ratio"], 0)],
        ["학습 기간", f"{period['baseline_start']} ~ {period['baseline_end']}"],
        ["평가 기간", f"{period['eval_start']} ~ {period['eval_end']} ({r['eval_days']}일)"],
        ["모델", f"{r['model_version']} (학습 {'됨' if r['fitted'] else '안 됨: 거래가 적어 룰만 적용'})"],
        ["실행 환경", _env_text(r.get("environment"))],
    ])
    summary = md_table(
        ["알림(주의 이상)", "고위험", "알림률", "고위험률", "30일당 알림", "30일당 고위험"],
        [[r["alerts"], r["high"], pct(r["alert_rate"], 2), pct(r["high_rate"], 2),
          num(r["monthly_alerts"]), num(r["monthly_high"])]])
    signal_rows = [[signal_name(c), n] for c, n in r["by_signal"].items()]
    signal_rows.append(["룰 없이 AI 이상탐지로만 알림", r["anomaly_only"]])
    channel_rows = [[channel_name(c), v["n"], v["alerts"]] for c, v in r["by_channel"].items()]
    alert_rows = [[a["ts"].replace("T", " "), channel_name(a["channel"]), a["counterparty"] or "-",
                   won(a["amount"]), level_name(a["level"]),
                   ", ".join(signal_name(s) for s in a["signals"]) or "AI 이상탐지",
                   a["card_title"] or "-"]
                  for a in r["alert_list"][:max_alerts]]
    shown = len(alert_rows)
    alert_note = (f"알림 {r['alerts']}건 중 {shown}건을 보여 줍니다."
                  if shown < r["alerts"] else f"알림 {r['alerts']}건을 모두 보여 줍니다.")
    parts = [
        head,
        "## 설정\n\n" + settings,
        "## 요약\n\n" + summary,
        "## 시그널별 알림 수\n\n" + md_table(["시그널", "알림 수"], signal_rows)
        + "\n\n한 거래에서 시그널 여러 개가 함께 나오면 각각 셉니다.",
        "## 거래 종류별\n\n" + md_table(["종류(글자로 추정)", "평가 거래", "알림"], channel_rows),
        "## 알림 목록\n\n" + alert_note + ("\n\n" + md_table(
            ["일시", "종류", "상대", "금액", "등급", "시그널", "카드 제목"], alert_rows) if alert_rows else ""),
        "## 유의점\n\n"
        "- 이 점검은 기기 안에서만 했고, 거래내역을 밖으로 보내지 않았습니다.\n"
        "- 거래 종류(카드·이체·소액결제 등)는 적요·내용 글자로 추정했습니다. 틀릴 수 있습니다.\n"
        "- 알림은 안내일 뿐 거래를 막지 않습니다. 실제 피해 여부는 이 결과로 알 수 없습니다.",
    ]
    return "\n\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def render_markdown(results: dict[str, Any], subtle: Optional[dict[str, Any]] = None) -> str:
    """결과 dict → Markdown 보고서 글.

    합성 결과: results가 경계 변형(intensity=subtle) 결과면 그 절만, 표준 결과면 표준 절들을 쓰고,
    subtle(경계 변형 결과)을 주면 같은 보고서에 경계 변형 절을 더한다. 별도 검증 세트(split=holdout)
    결과면 검증 세트 절만 쓴다(표본 안 결과와의 비교는 write_report가 같은 폴더의 JSON으로 한다).
    """
    kind = results.get("kind")
    if kind == "file":
        return _file_markdown(results)
    if kind in ("synthetic", "comparison"):
        if split_of(results) == HOLDOUT:
            if subtle is not None:
                raise ValueError("별도 검증 세트 결과에는 subtle을 함께 줄 수 없어요.")
            if intensity_of(results) == "subtle":
                return _synthetic_markdown(None, None, holdout_subtle=results)
            return _synthetic_markdown(None, None, holdout=results)
        if intensity_of(results) == "subtle":
            return _synthetic_markdown(None, results)
        if subtle is not None and intensity_of(subtle) != "subtle":
            raise ValueError("subtle에는 경계 변형(intensity=subtle) 결과를 주세요.")
        return _synthetic_markdown(results, subtle)
    raise ValueError(f"알 수 없는 평가 결과 종류예요: {kind!r}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sp-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _load_partner(path: Path, intensity: str, split: str = IN_SAMPLE
                  ) -> tuple[Optional[dict[str, Any]], str]:
    """같은 폴더의 다른 결과 JSON(강도·표본). 없으면 (None, ""), 읽지 못하면 (None, 안내 문장)."""
    if not path.is_file():
        return None, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ok = (isinstance(data, dict) and data.get("kind") in ("synthetic", "comparison")
              and intensity_of(data) == intensity and split_of(data) == split)
    except (OSError, ValueError):
        ok, data = False, None
    if not ok:
        return None, f"> {path.name}을(를) 읽지 못해 이 보고서에 싣지 않았습니다."
    return data, ""


def write_report(results: dict[str, Any], out_dir: Path | str,
                 stem: Optional[str] = None) -> dict[str, Path]:
    """JSON과 Markdown 보고서를 쓴다. 돌려주는 값: {"json": 경로, "markdown": 경로}.

    파일 이름: 합성 데이터 결과는 eval_results.json / eval_report.md(경계 변형 결과는
    eval_results_subtle.json, 별도 검증 세트는 eval_results_holdout.json·eval_results_subtle_holdout.json),
    거래내역 결과는 file_eval_results.json / file_eval_report.md (stem으로 바꿀 수 있음).
    합성 결과의 Markdown은 하나로, 같은 폴더의 다른 결과 JSON(강도·표본)을 읽어 표준 절, 경계 변형 절,
    별도 검증 세트 절을 함께 쓴다(어느 것을 먼저 써도 같은 보고서). 다른 결과 JSON은 읽기만 한다.
    """
    kind = results.get("kind")
    stem = stem or (FILE_STEM if kind == "file" else SYNTHETIC_STEM)
    out = Path(out_dir)
    md_path = out / f"{stem}_report.md"
    if kind in ("synthetic", "comparison"):  # 형식 오류는 파일을 쓰기 전에 잡는다
        own = (intensity_of(results), split_of(results))
        data: dict[tuple[str, str], Optional[dict[str, Any]]] = {}
        notes: dict[tuple[str, str], str] = {}
        for key in _VARIANTS:
            if key == own:
                data[key], notes[key] = results, ""
            else:
                data[key], notes[key] = _load_partner(out / synthetic_json_name(stem, *key), *key)
        json_path = out / synthetic_json_name(stem, *own)
        markdown = _synthetic_markdown(
            data[("standard", IN_SAMPLE)], data[("subtle", IN_SAMPLE)], notes[("subtle", IN_SAMPLE)],
            holdout=data[("standard", HOLDOUT)], holdout_subtle=data[("subtle", HOLDOUT)],
            holdout_notes=[notes[k] for k in (("standard", HOLDOUT), ("subtle", HOLDOUT)) if notes[k]])
    else:
        markdown = render_markdown(results)
        json_path = out / f"{stem}_results.json"
    _atomic_write(json_path, json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(md_path, markdown)
    return {"json": json_path, "markdown": md_path}


__all__ = [
    "CHANNEL_NAMES_KO", "LEVEL_NAMES_KO", "MODE_NAMES_KO", "SIGNAL_NAMES_KO",
    "channel_name", "level_name", "md_table", "mode_name", "num", "pct",
    "SUBTLE_DEFINITIONS_KO", "intensity_of", "pp", "split_of", "synthetic_json_name",
    "render_markdown", "seeds_text", "signal_name", "won", "write_report",
]
