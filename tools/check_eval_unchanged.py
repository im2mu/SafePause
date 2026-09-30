"""제출 성과보고서 수치가 그대로인지 확인한다: 별도 검증 세트(seed 21~40) 평가를 다시 돌려 docs/eval 원자료와 비교.

    python tools/check_eval_unchanged.py       # 같으면 0, 다르면 1(다른 값 목록 출력). 약 1~2분

비교 범위: modes 아래 모든 지표(시나리오 탐지율·거래별 혼동행렬·정상 거래·대조군·인물별·모델 버전).
environment(설치된 numpy·scikit-learn 버전)와 command 문자열은 비교하지 않는다.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safepause.data import synth  # noqa: E402
from safepause.eval.metrics import compare_modes  # noqa: E402

REFERENCE = {"standard": ROOT / "docs" / "eval" / "eval_results_holdout.json",
             "subtle": ROOT / "docs" / "eval" / "eval_results_subtle_holdout.json"}


def diff(a: object, b: object, path: str, out: list[str]) -> int:
    n = 0
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in ("environment", "command"):
                continue
            if k not in a or k not in b:
                out.append(f"{path}.{k}: 한쪽에만 있음")
                continue
            n += diff(a[k], b[k], f"{path}.{k}", out)
        return n
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return sum(diff(x, y, f"{path}[{i}]", out) for i, (x, y) in enumerate(zip(a, b)))
    n = 1
    same = (math.isclose(a, b, rel_tol=0, abs_tol=1e-9) if isinstance(a, float) and isinstance(b, float) else a == b)
    if not same:
        out.append(f"{path}: 원자료 {a!r} / 지금 {b!r}")
    return n


def main() -> int:
    problems: list[str] = []
    compared = 0
    for intensity, ref_path in REFERENCE.items():
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        now = compare_modes(list(synth.PERSONAS), list(range(21, 41)), intensity=intensity)
        now = json.loads(json.dumps(now["modes"], ensure_ascii=False, default=str))
        compared += diff(ref["modes"], now, intensity, problems)
    print(f"비교한 값 {compared}개, 다른 값 {len(problems)}개")
    for p in problems[:50]:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
