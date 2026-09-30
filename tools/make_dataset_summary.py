"""공고 선택 사항 '학습 데이터셋 요약': 평가에 쓴 합성 데이터의 통계를 실제로 세어 표로 만든다.

    python tools/make_dataset_summary.py      # → docs/dataset_summary.md, samples/07_dataset_stats.json

범위: 인물 3종 × seed 1~40(1~20 룰 보완용, 21~40 별도 검증 세트) × 표준·경계 변형, 사례당 120일.
평가와 같은 함수(eval.metrics.synthetic_case)로 만든다: 앞 90일 = 학습 구간, 뒤 30일 = 평가 구간.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safepause.config import Settings  # noqa: E402
from safepause.data import synth  # noqa: E402
from safepause.eval.metrics import synthetic_case  # noqa: E402
from safepause.models import Direction  # noqa: E402

SEEDS = range(1, 41)
CHANNEL_KO = {"transfer": "계좌 이체", "card": "카드 결제", "micropay": "휴대폰 소액결제", "telecom_bill": "통신요금",
              "atm": "현금 인출", "income": "입금"}
SIGNAL_KO = {"night_repeat_transfer": "심야 반복 이체", "payee_surge": "특정 계좌 송금 급증",
             "micropay_surge": "통신 소액결제 급증", "new_merchant_high_value": "신규 가맹점 고액 결제",
             "multi_line_telecom": "단기간 다회선 통신요금"}


def pct(n: float, d: float) -> str:
    return f"{n / d * 100:.1f}%" if d else "-"


def won(v: float) -> str:
    return f"{round(v):,}원"


def main() -> int:
    night = Settings()
    stats: dict = {"range": {"personas": list(synth.PERSONAS), "seeds": [SEEDS.start, SEEDS.stop - 1], "days": 120,
                             "train_days": 90, "eval_days": 30}, "personas": {}, "scenarios": {}}
    lines = ["# 학습·평가 데이터셋 요약 (합성 데이터)", "",
             "`python tools/make_dataset_summary.py`로 실제로 세어 만든 표입니다(평가와 같은 생성 함수).",
             "진짜 사람의 거래가 아니며, 인물 설정은 공개 통계로 보정하지 않은 가정입니다(자세한 가정은 `docs/dataset_card.md`).", "",
             f"- 범위: 인물 3종 × seed {SEEDS.start}~{SEEDS.stop - 1}(1~20 룰 보완용, 21~40 별도 검증 세트) = {3 * len(SEEDS)}사례, 사례당 120일",
             "- 사례마다 앞 90일(정상 거래만)은 개인 기준 AI의 학습 구간, 뒤 30일은 평가 구간입니다.",
             "- 대조군: 같은 seed에서 걱정되는 거래를 섞지 않은 사례(정상 거래는 같음)", ""]

    lines += ["## 1. 인물별 거래 규모 (표준 강도, 학습 구간 90일 기준)", "",
              "| 인물 | 사례 수 | 학습 구간 거래(평균) | 평가 구간 정상 거래(평균) | 나가는 돈 비율 | 심야(23~6시) 비율 | 서로 다른 상대(평균) |",
              "|---|---|---|---|---|---|---|"]
    channel_rows = []
    amount_rows = []
    for persona in synth.PERSONAS:
        n_train, n_eval_norm, outs, nights, uniq, total = [], [], 0, 0, [], 0
        ch = Counter()
        amounts = defaultdict(list)
        for seed in SEEDS:
            case = synthetic_case(persona, seed)
            base = case.baseline_normal
            n_train.append(len(base))
            n_eval_norm.append(sum(1 for t in case.evaluated if t.label in (None, synth.NORMAL_LABEL)))
            uniq.append(len({(t.channel, t.counterparty) for t in base}))
            for t in base:
                total += 1
                outs += t.direction == Direction.OUT
                nights += night.is_night(t.ts.hour)
                ch[t.channel.value] += 1
                amounts[t.channel.value].append(t.amount)
        p = synth.PERSONAS[persona]
        lines.append(f"| {p.name} | {len(SEEDS)} | {statistics.mean(n_train):.1f}건 | {statistics.mean(n_eval_norm):.1f}건 | "
                     f"{pct(outs, total)} | {pct(nights, total)} | {statistics.mean(uniq):.1f}곳 |")
        channel_rows.append((p.name, {k: pct(v, total) for k, v in ch.items()}))
        amount_rows.append((p.name, {k: (statistics.median(v), sorted(v)[int(len(v) * 0.9) - 1]) for k, v in amounts.items()}))
        stats["personas"][persona] = {
            "name": p.name, "train_txns_mean": round(statistics.mean(n_train), 1),
            "eval_normal_txns_mean": round(statistics.mean(n_eval_norm), 1),
            "out_share": round(outs / total, 4), "night_share": round(nights / total, 4),
            "channel_share": {k: round(v / total, 4) for k, v in ch.items()},
            "amount_median": {k: statistics.median(v) for k, v in amounts.items()},
        }

    chans = ["card", "transfer", "atm", "telecom_bill", "micropay", "income"]
    lines += ["", "## 2. 거래 방법 구성 (학습 구간)", "",
              "| 인물 | " + " | ".join(CHANNEL_KO[c] for c in chans) + " |", "|---|" + "---|" * len(chans)]
    for name, shares in channel_rows:
        lines.append(f"| {name} | " + " | ".join(shares.get(c, "0.0%") for c in chans) + " |")
    lines += ["", "## 3. 금액 (학습 구간, 중앙값 / 상위 10% 경계)", "",
              "| 인물 | " + " | ".join(CHANNEL_KO[c] for c in chans) + " |", "|---|" + "---|" * len(chans)]
    for name, am in amount_rows:
        lines.append(f"| {name} | " + " | ".join(f"{won(am[c][0])} / {won(am[c][1])}" if c in am else "-" for c in chans) + " |")

    lines += ["", "## 4. 섞은 걱정 거래(시나리오) — 평가 구간", "",
              "| 시나리오 | 강도 | 사례 수 | 사례당 거래(평균) | 한 건 금액 중앙값 | 새벽 0~4시 비율 |", "|---|---|---|---|---|---|"]
    for intensity in ("standard", "subtle"):
        per: dict[str, list] = defaultdict(list)
        amts: dict[str, list] = defaultdict(list)
        nights_s: dict[str, int] = Counter()
        for persona in synth.PERSONAS:
            for seed in SEEDS:
                case = synthetic_case(persona, seed, intensity=intensity)
                groups = Counter(t.label for t in case.evaluated if t.label not in (None, synth.NORMAL_LABEL))
                for code, n in groups.items():
                    per[code].append(n)
                for t in case.evaluated:
                    if t.label not in (None, synth.NORMAL_LABEL):
                        amts[t.label].append(t.amount)
                        nights_s[t.label] += 0 <= t.ts.hour < 4
        for code in SIGNAL_KO:
            n_txn = sum(per[code])
            lines.append(f"| {SIGNAL_KO[code]} | {'표준' if intensity == 'standard' else '경계 변형'} | {len(per[code])} | "
                         f"{statistics.mean(per[code]):.2f}건 | {won(statistics.median(amts[code]))} | {pct(nights_s[code], n_txn)} |")
            stats["scenarios"].setdefault(code, {})[intensity] = {
                "cases": len(per[code]), "txns_mean": round(statistics.mean(per[code]), 2),
                "amount_median": statistics.median(amts[code]), "night_0_4_share": round(nights_s[code] / n_txn, 4) if n_txn else None}
    lines += ["", "- 표준: 룰의 '꼭 확인해요' 기준을 넘게 설계한 시나리오라 룰만으로도 모두 찾습니다(실제 탐지율을 뜻하지 않음).",
              "- 경계 변형: 룰 기준 근처로 줄인 변형(결과 확인 전에 정의, SPEC.md [추가 r4]).",
              "- 라벨(정답)은 평가와 합성 샘플의 학습 구간 경계를 정하는 데만 쓰고, 거래별 판단에는 쓰지 않습니다.", ""]
    (ROOT / "docs" / "dataset_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "samples").mkdir(exist_ok=True)
    (ROOT / "samples" / "07_dataset_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("완료: docs/dataset_summary.md, samples/07_dataset_stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
