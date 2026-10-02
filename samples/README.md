# 샘플 결과물 (공고 선택 사항: 학습 데이터셋 요약 또는 샘플 결과물)

모두 **합성(가상) 데이터**로 만든 실제 프로그램 결과입니다. 진짜 사람의 거래가 아닙니다.
다시 만들기: `python tools/make_samples.py` (같은 코드면 같은 결과, 만든 시각은 2026-10-01 09:00으로 고정)

| 파일 | 내용 |
|---|---|
| 01_sample_transactions.csv | 가상 근로자(seed 1) 120일 거래 232건. 걱정되는 거래 5종을 마지막 30일에 섞음(label 열이 정답) |
| 02_analysis_results.csv | 거래마다 판단(괜찮아요·확인해요·꼭 확인해요), 걸린 약속(규칙), AI 점수(0~1) |
| 03_alert_cards.json | '알림' 화면의 기록 카드(쉬운 말 제목·문장·그림 이름) |
| 04_safe_pause_checks.json | 돈 보내기 전 확인 4가지의 안전 정지 카드와 조력자 안내 미리보기 |
| 05_validation_summary.json | 현장 검증용 요약: 이름·계좌·금액·날짜 없이 거래 수·알림 수만 |
| 06_eval_quick.json | 성능 확인(인물 3 × seed 3 = 9사례, 규칙+AI·규칙만·AI만) |
| 07_dataset_stats.json | 학습·평가 데이터셋 통계(인물 3 × seed 1~40, `python tools/make_dataset_summary.py`) |

- 제출 성과보고서의 성능 수치는 별도 검증 세트(seed 21~40)이며 원자료는 `docs/eval/eval_results_holdout.json`,
  `docs/eval/eval_results_subtle_holdout.json`입니다(이 폴더의 06은 빠른 확인용이라 값이 다릅니다).
- 데이터 설명: `docs/dataset_card.md`, 통계 요약: `docs/dataset_summary.md`
