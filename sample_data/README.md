# sample_data — 예시 거래 데이터

이 폴더의 거래는 **모두 가상**입니다. 실제 사람의 거래, 실제 피해 사례, 공개 통계로 보정한 값이 아닙니다.
인물 설정(소득·결제 빈도·금액)은 제안서의 착취 시그널 5종(S19)을 재현하려고 정한 가정값이고,
상대 이름·계좌·가맹점·통신사·회선도 지어낸 값입니다. 가정 전체는 `safepause/data/synth.py`의 `PERSONAS`와
시나리오 함수 설명에 적혀 있습니다.

## 1. 합성 데이터 3개 (SafePause 표준 CSV)

`safepause.data.synth.make_dataset`으로 만든 뒤 `synth.to_csv`로 저장했습니다. 생성 스크립트는 따로 두지 않았고,
아래 호출이 전부입니다. 같은 seed로 다시 만들면 같은 거래가 나옵니다(`tests/test_loader.py`에서 확인).

```python
from safepause.data import synth

synth.to_csv(synth.make_dataset("worker", seed=1, days=120, scenarios=synth.ALL_SCENARIOS),
             "sample_data/worker_scenarios.csv")
synth.to_csv(synth.make_dataset("benefit", seed=2, days=120, scenarios=synth.ALL_SCENARIOS),
             "sample_data/benefit_scenarios.csv")
synth.to_csv(synth.make_dataset("student", seed=3, days=120),   # 시나리오 없음
             "sample_data/student_normal.csv")
```

| 파일 | 인물 설정 | seed | 기간(가상) | 전체 | 정상 | 주입 시나리오 |
|---|---|---|---|---|---|---|
| `worker_scenarios.csv` | `worker` (급여 근로) | 1 | 2026-03-02 ~ 2026-06-29 (120일) | 232건 | 206건 | 5종 모두, 26건 |
| `benefit_scenarios.csv` | `benefit` (복지급여 수급) | 2 | 2026-03-02 ~ 2026-06-29 (120일) | 172건 | 143건 | 5종 모두, 29건 |
| `student_normal.csv` | `student` (용돈·소액 위주) | 3 | 2026-03-02 ~ 2026-06-29 (120일) | 204건 | 204건 | 없음 (정상 전용) |

기간 시작일은 `synth.DEFAULT_START`(2026-03-02)로 고정되어 있습니다. 시나리오는 모두 마지막 30일
(2026-05-31 ~ 2026-06-29) 안에 들어 있습니다.

주입된 시나리오 구간(`label` 열 값 기준):

| 시나리오(`label`) | worker (seed 1) | benefit (seed 2) |
|---|---|---|
| `night_repeat_transfer` 심야 반복 이체 | 06-25 ~ 06-27, 4건, 합계 115만 원 | 06-15 ~ 06-17, 4건, 합계 110만 원 |
| `payee_surge` 특정 계좌 앞 송금 급증 | 05-31 ~ 06-04, 7건, 합계 59만 원 | 06-12 ~ 06-17, 7건, 합계 37만 원 |
| `micropay_surge` 통신 소액결제 급증 | 06-10 ~ 06-15, 10건, 합계 64만 3천 원 | 06-03 ~ 06-09, 12건, 합계 64만 8천 원 |
| `new_merchant_high_value` 신규 가맹점 고액 결제 | 06-07 ~ 06-10, 3건, 합계 56만 3천 원 | 06-07 ~ 06-11, 3건, 합계 54만 원 |
| `multi_line_telecom` 단기간 다회선 통신요금 | 06-16 ~ 06-26, 새 회선 2개 | 06-15 ~ 06-24, 새 회선 3개 |

### 열 설명 (SafePause 표준 CSV)

`id,ts,amount,direction,channel,counterparty,counterparty_id,line_id,memo,label`

- `ts`: 거래 일시(ISO 형식, 초 단위, 시간대 변환 없음)
- `amount`: 금액(원, 양의 정수) / `direction`: `out`(나감) 또는 `in`(들어옴)
- `channel`: `transfer` 이체, `card` 카드결제, `micropay` 휴대폰 소액결제, `telecom_bill` 통신요금,
  `atm` 현금 인출, `income` 입금
- `counterparty` / `counterparty_id`: 상대 이름 / 계좌·가맹점ID 같은 식별값
- `line_id`: 통신요금·소액결제의 회선(가운데 가림, 예: `010-****-1234`)
- `label`: 정답 라벨. `normal` 또는 시나리오 코드. **평가용이며 탐지에는 쓰지 않습니다.**

파일은 엑셀에서 한글이 깨지지 않도록 UTF-8(BOM 포함)으로 저장했습니다.

### 정상 이력에 넣은 잡음

오탐(정상 거래를 위험으로 잘못 보는 일)을 의미 있게 재기 위해, 정상 이력에도 드물게 다음을 넣었습니다.
빈도는 인물마다 다른 가정값입니다(`Persona` 필드 참고).

- 처음 가는 가게에서 소액 카드결제(3만 원 이하), 가끔 조금 큰 결제(5만~15만 원)
- 밤 23시~01시 카드결제(인물의 첫 번째 단골 가게)
- 알려진 상대에게 밤 23시~00시 송금
- 처음 보는 상대에게 1회 소액 송금(1만~5만 원)

## 2. `bank_export_example.csv` — 은행 내보내기 모양 예시

헤더: `거래일시,적요,출금액,입금액,내용,잔액`

- 한국어 머리글 CSV를 불러오는 기능(`safepause/data/loader.py`)을 시험하려고 만든 **가상 거래 46건**입니다
  (2026-07-01 ~ 2026-08-15). 특정 은행의 실제 양식을 옮긴 것이 아니며, SafePause가 어느 은행 양식을
  지원한다는 뜻도 아닙니다.
- 최신 거래가 위에 오도록 적었습니다. 불러오면 시간순으로 다시 정렬됩니다.
- 금액은 `"12,300"`처럼 쉼표를 넣어 적었고, 없는 쪽 금액은 `0`입니다. 잔액은 앞뒤 거래와 맞춰 계산했습니다.
- `적요`에는 거래 방식(체크카드, 모바일이체, 자동이체, ATM출금, 휴대폰결제, 급여)을, `내용`에는 상대를 적었습니다.
- 들어 있는 거래: 급여 입금 2건, 체크카드 결제, 엄마·동생·집주인 이체, 관리비 자동이체, ATM 출금,
  통신요금 자동이체 1건(`가나통신 010-****-1234`), 휴대폰결제 1건.
- **위험 예시**: 마지막 사흘(08-13 ~ 08-15) 새벽 1~3시에 처음 보는 상대 `김*호`에게 20만·30만·25만 원을
  보낸 이체 3건을 넣었습니다(심야 반복 이체 시그널 체험용).

불러오기:

```python
from safepause.data.loader import load_csv

txns, report = load_csv("sample_data/bank_export_example.csv")
print(report["mapping"])   # 어떤 열을 어떻게 읽었는지
print(report["warnings"])  # 추정한 내용(거래 종류, 상대 판별 방법 등)
```

이 파일은 머리글 자동 매핑으로 다음처럼 읽힙니다: 일시=`거래일시`, 출금/입금=`출금액`/`입금액`,
상대=`내용`(비어 있으면 `적요`), 메모=`적요`. 거래 종류는 글자를 보고 추정하며(카드 29건, 이체 11건, 입금 2건, 현금 인출 2건,
통신요금 1건, 소액결제 1건), 추정했다는 사실이 `report["warnings"]`에 남습니다. `잔액` 열은 쓰지 않습니다.

다른 머리글을 쓰는 파일은 `mapping`으로 열 이름을 알려 주면 됩니다(형식은 `loader.py` 맨 위 설명 참고).
