# AI 모델 코드 안내 (공고 선택 사항: AI 모델 코드·설명)

SafePause의 판단은 **룰(착취 시그널 5종) + 개인 기준 이상탐지 AI(IsolationForest)**의 결합입니다.
모델 카드(성능·한계): [model_card.md](model_card.md) · 데이터: [dataset_card.md](dataset_card.md), [dataset_summary.md](dataset_summary.md)

## 1. 코드 지도

| 파일 | 하는 일 |
|---|---|
| `safepause/detect/features.py` | 거래 이력에서 특징 11종 계산(`FEATURE_NAMES`): 금액(log), 평소 상위 5% 대비 금액, 시각(sin·cos), 심야, 처음 보는 상대, 같은 상대 7일 건수·합계 비율, 같은 방법 7일 건수 비율, 처음 보는 회선, 나가는 돈. 상대·회선 식별값은 정책과 같은 규칙으로 정규화(공백·하이픈·점 무시) |
| `safepause/detect/rules.py` | 룰 5종: 심야 반복 이체, 특정 계좌 송금 급증, 통신 소액결제 급증, 신규 가맹점 고액 결제, 단기간 다회선 통신요금. 개인 이력(평소 금액·건수)과 고정 기준으로 '확인해요(주의)'·'꼭 확인해요(고위험)' |
| `safepause/detect/anomaly.py` | `PersonalAnomalyModel`: 본인 과거 정상 거래(30건 이상)로 IsolationForest(트리 200개) 학습. 점수 = 학습 거래 이례도 분포 대비 백분위(0~1, 1이면 학습한 어떤 평소 거래보다도 이례적). 설명용으로 평균과 가장 다른 특징(표준화 편차) 계산 |
| `safepause/detect/engine.py` | `combine_level()`: 룰과 점수 결합(아래 2절), `RiskEngine.assess_many()`: 시간순 증분 평가(평가 시점 이후 정보 사용 안 함) |
| `safepause/explain/easy_card.py` | 판단 → 쉬운 말·그림 카드(제목 15자·줄 30자·4줄·금지어 검사 `readability_issues`) |
| `safepause/guardian/policy.py` | 조력자 알림 정책: 기본 고위험만, 조력자별 등급·범위, 돈 받는 조력자 제외, 반복 고위험 시 상담 안내(동의 시) |
| `safepause/eval/metrics.py` | 합성 데이터 평가(시나리오 탐지율, 거래별 재현율, 정상 거래 알림률, 대조군 월 알림) |
| `safepause/api/service.py` | 화면이 쓰는 업무 로직(PC 서버·안드로이드 앱 공통) |

## 2. 결합 규칙 (engine.py `combine_level`)

```python
FUSED_ESCALATE_SCORE = 0.90   # 룰 '주의'를 '고위험'으로 올리는 점수
ANOMALY_ALONE_SCORE = 0.98    # 룰 없이 AI만으로 '주의'를 내는 점수(나가는 돈만)

if 룰 최고 등급 == 고위험:                 → 고위험
elif 룰 최고 등급 == 주의:
    점수 >= 0.90 이고 짧은 이력 때문에 낮춘 근거가 아니면 → 고위험, 아니면 → 주의
elif 나가는 돈 and 점수 >= 0.98:            → 주의 (AI 혼자서는 고위험을 내지 않음: 기본 설정의 조력자 알림은 룰 근거 필요)
else:                                        → 괜찮아요
```

## 3. 재현

```bash
python -m safepause eval --seeds 20 --seed-start 21                      # 표준, 별도 검증 세트
python -m safepause eval --seeds 20 --seed-start 21 --intensity subtle   # 경계 변형
python -m pytest -q                                                       # 자동 테스트
python tools/make_samples.py && python tools/make_dataset_summary.py      # 샘플 결과물·데이터 요약
```

- 같은 seed면 같은 합성 데이터·같은 모델(IsolationForest `random_state` 고정)이라 결과가 같습니다.
- v0.2·v0.3의 모든 수정 뒤에도(마지막 확인: v0.3 최종 2026-10-06, 1,100개 값 차이 0) 위 두 명령의 결과가 제출 성과보고서의 원자료
  (`docs/eval/eval_results_holdout.json`, `eval_results_subtle_holdout.json`)와 같습니다.
  확인 명령: `python tools/check_eval_unchanged.py`(모든 지표를 한 값씩 비교, 같으면 종료 코드 0).
- 안드로이드 앱 안 파이썬(Pyodide, numpy 2.4.6·scikit-learn 1.8.0)에서도 같은 값이 나옵니다([mobile.md](mobile.md) 2절).

## 4. 한계 (요약)

- 합성 데이터 기준이며 실제 피해 데이터로 검증하지 않았습니다.
- 룰 '주의' 시나리오 거래의 97%가 점수 0.90 이상이라, 고위험 상향은 '룰 주의를 모두 올리는' 비AI 규칙과 성적이 비슷합니다
  (판별 기여 미미). AI의 고유 기여는 룰이 못 본 나가는 돈에 '주의'를 먼저 띄우는 경로입니다(model_card 5.4).
- 개선 과제: 룰과 겹치지 않는 특징의 판별 모델, 실거래 오탐 측정, 당사자 참여 쉬운 말 감수.
