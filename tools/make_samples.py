"""공고 선택 사항 '샘플 결과물'을 실제 코드로 만든다(합성 데이터, 결정론적).

    python tools/make_samples.py            # → samples/ 폴더

만드는 것(모두 합성 데이터 기준, 진짜 사람의 거래 아님)
- samples/01_sample_transactions.csv   가상 근로자(seed 1, 걱정되는 거래 5종 섞음) 120일 거래(표준 CSV)
- samples/02_analysis_results.csv      거래마다 판단 결과(괜찮아요·확인해요·꼭 확인해요, 걸린 약속, AI 점수)
- samples/03_alert_cards.json          '알림' 화면의 기록 카드(쉬운 말 문장 원본)
- samples/04_safe_pause_checks.json    보내기 연습 4가지(평범한 송금·새벽 송금·새 가게 큰 결제·휴대폰 결제)의 안전 정지 카드
- samples/05_validation_summary.json   현장 검증용 요약(이름·계좌·금액·날짜 없음)
- samples/06_eval_quick.json           성능 확인(인물 3 × seed 3, 규칙+AI·규칙만·AI만)
- samples/README.md                    각 파일 설명
같은 코드·같은 입력이면 늘 같은 결과가 나온다(만든 시각 필드만 고정값으로 둔다).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safepause.api.schemas import ConsentIn, EvalIn, HelperIn, PendingIn, SampleIn  # noqa: E402
from safepause.api.service import Service  # noqa: E402
from safepause.data import synth  # noqa: E402

NOW = datetime(2026, 10, 1, 9, 0, 0)   # 결정론: 만든 시각을 고정
PRACTICE = [
    ("평범한 송금(엄마에게 5만 원, 오후 3시)", {"to": "엄마", "amount": 50000, "channel": "transfer", "time": "15:00"}),
    ("새벽에 처음 보는 사람에게 30만 원", {"to": "김*호", "amount": 300000, "channel": "transfer", "time": "02:00"}),
    ("처음 가는 가게에서 80만 원 결제", {"to": "새로 연 전자상가", "amount": 800000, "channel": "card", "time": "15:00"}),
    ("휴대폰 소액결제 3만 원", {"to": "게임 아이템", "amount": 30000, "channel": "micropay", "time": "21:00"}),
]


def dump(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(out: Path = ROOT / "samples") -> int:
    out.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="sp-samples-"))
    try:
        svc = Service(home, now=lambda: NOW)
        svc.put_consent(ConsentIn(monitoring=True, helper_alerts=True, counseling_referral=True))
        svc.put_helpers([HelperIn(name="엄마", relation="가족", identifiers=["엄마"]),
                         HelperIn(name="센터 선생님", relation="지역발달장애인지원센터 전담 인력")])
        info = svc.data_sample(SampleIn(persona="worker", seed=1, scenarios=True))
        synth.to_csv(svc.store.load_transactions(), out / "01_sample_transactions.csv")
        (out / "02_analysis_results.csv").write_text(svc.export_results_csv()["text"], encoding="utf-8")
        dump(out / "03_alert_cards.json", svc.cards(limit=500))
        checks = []
        for label, req in PRACTICE:
            r = svc.check(PendingIn(**req))
            checks.append({"상황": label, "요청": req, "판단": r["assessment"]["level"], "카드": r["card"],
                           "조력자_미리보기": r["notify_plan_preview"]["note_to_person"]})
        dump(out / "04_safe_pause_checks.json", checks)
        dump(out / "05_validation_summary.json", svc.export_validation()["summary"])
        quick = svc.eval_run(EvalIn(seeds=3, modes=["fused", "rules", "anomaly"]))
        quick["elapsed_sec"] = None   # 기기마다 달라 결정론을 깨므로 비움
        dump(out / "06_eval_quick.json", quick)
        (out / "README.md").write_text(README.format(count=info["count"]), encoding="utf-8")
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print(f"완료: {out}")
    return 0


README = """# 샘플 결과물 (공고 선택 사항: 학습 데이터셋 요약 또는 샘플 결과물)

모두 **합성(가상) 데이터**로 만든 실제 프로그램 결과입니다. 진짜 사람의 거래가 아닙니다.
다시 만들기: `python tools/make_samples.py` (같은 코드면 같은 결과, 만든 시각은 2026-10-01 09:00으로 고정)

| 파일 | 내용 |
|---|---|
| 01_sample_transactions.csv | 가상 근로자(seed 1) 120일 거래 {count}건. 걱정되는 거래 5종을 마지막 30일에 섞음(label 열이 정답) |
| 02_analysis_results.csv | 거래마다 판단(괜찮아요·확인해요·꼭 확인해요), 걸린 약속(규칙), AI 점수(0~1) |
| 03_alert_cards.json | '알림' 화면의 기록 카드(쉬운 말 제목·문장·그림 이름) |
| 04_safe_pause_checks.json | 보내기 연습 4가지의 안전 정지 카드와 조력자 안내 미리보기 |
| 05_validation_summary.json | 현장 검증용 요약: 이름·계좌·금액·날짜 없이 거래 수·알림 수만 |
| 06_eval_quick.json | 성능 확인(인물 3 × seed 3 = 9사례, 규칙+AI·규칙만·AI만) |
| 07_dataset_stats.json | 학습·평가 데이터셋 통계(인물 3 × seed 1~40, `python tools/make_dataset_summary.py`) |

- 제출 성과보고서의 성능 수치는 별도 검증 세트(seed 21~40)이며 원자료는 `docs/eval/eval_results_holdout.json`,
  `docs/eval/eval_results_subtle_holdout.json`입니다(이 폴더의 06은 빠른 확인용이라 값이 다릅니다).
- 데이터 설명: `docs/dataset_card.md`, 통계 요약: `docs/dataset_summary.md`
"""

if __name__ == "__main__":
    sys.exit(main())
