# SafePause — 구현 명세 (모든 빌더 에이전트 공통 계약)

SafePause = 2026 AI 라이프 솔루션 챌린지 출품 안드로이드 앱(제출물은 APK 하나).
이 문서는 앱 안에서 도는 파이썬 엔진(`safepause` 패키지)의 처음 구현 명세(v0.1)와 그 뒤 수정 기록이다. 앱 구조와 APK는 [docs/mobile.md](docs/mobile.md).
아이디어: 「지원의사결정 기반 발달장애인 경제적 착취 사전 예방 AI 모니터링 시스템」(아이디어 챌린지 수상 후보작).
**이 명세의 기능 요구는 모두 제출 제안서 원문(S 번호)에서 왔다. 제안서에 없는 기능을 "제안서 기능"이라고 문서화하지 말 것.**

- S6/S18: 당사자(또는 법정대리인) 사전 동의 기반 금융거래 데이터 실시간·상시 분석
- S19: 착취 시그널 5종 = 심야 시간대 반복 이체 / 특정 계좌 앞 송금 급증 / 통신 소액결제 급증 / 신규 가맹점 고액 결제 과다 / 단기간 다회선 통신요금 청구. 룰 기반 필터 + 경량 AI 이상탐지 모델 결합
- S20/S21: 위험 징후 시 당사자 앱에 쉬운 언어·그림(픽토그램) 카드 → 송금 전 스스로 재인지·숙고하는 **안전 정지(Safe Pause)**. 강제 차단 대신 본인이 최종 결정 (본인 확인 시 정상 거래 진행)
- S22/S23: 당사자가 사전 지정한 신뢰 조력자(가족, 지역발달장애인지원센터 전담 인력 등)에게 **고위험 이상 거래에 한해** 2차 알림. 고위험 패턴 반복 시 본인 동의 전제 상담기관(지역발달장애인지원센터·장애인권익옹호기관) 연계
- S35: 규칙 기반 필터링 + 경량 이상탐지(거래 시계열 패턴) + 쉬운 언어 변환(sLLM). 판단·알림은 단말 내부(온디바이스) 우선, 외부 전송 차단
- S37: 사전 동의·즉각 철회권(Opt-out), 조력자 알림 대상·범위 지정 권한은 당사자 본인에게
- S38: 오탐지가 금융 주권을 위축시키지 않도록 강제 차단 없는 안내 원칙. 쉬운 언어 문구
- 질의 답변서(정정본)에서 추가로 밝힌 보완: 조력자가 거래 상대방이면 해당 조력자 대신 당사자가 정한 다른 조력자에게 알리거나 본인 동의로 상담 연계 / 내려받은 실제 거래내역으로 정상 거래 오탐 확인

## 0. 공통 규칙
- Python 3.10+ (개발 환경 3.12). 의존성: numpy, scikit-learn, fastapi, uvicorn, python-multipart. 그 밖의 런타임 의존성 추가 금지(테스트: pytest, httpx).
  - [변경 r1] fastapi의 전이 의존성인 pydantic을 `pydantic>=2,<3`으로 requirements·pyproject에 명시한다(새 패키지 아님). 엔진·시험용 서버가 v2 API(AliasChoices, ConfigDict, field_validator)를 쓰는데 fastapi 0.110은 pydantic v1도 허용해, 기존 환경에서 설치하면 서버가 시작하지 못했기 때문이다.
  - [변경 r1] `pyproject.toml`의 `[tool.pytest.ini_options] pythonpath = ["."]`로 패키지를 설치하지 않은 환경에서도 `pytest -q`가 동작한다. 문서의 테스트 명령은 `python -m pytest -q`.
  - [변경 r2] `pyproject.toml`의 dependencies에 requirements.txt와 같은 주 버전 상한(numpy<3, scikit-learn<2, fastapi<1, uvicorn<1, python-multipart<1)을 둔다(`pip install .`도 확인한 범위만 설치). 테스트 의존성은 `httpx>=0.27,<0.28`: httpx 0.28은 하한 fastapi 0.110(starlette 0.36.3)의 TestClient와 맞지 않는다(리뷰 실측 89 errors). 확인: 하한 조합(fastapi 0.110.0, starlette 0.36.3, numpy 1.26.4, scikit-learn 1.4.0, uvicorn 0.29.0, httpx 0.27.2)과 개발 조합(starlette 1.7.0 + httpx 0.27.2 / 0.28.1) 모두 전체 테스트 통과.
- 타입은 `safepause/models.py`에서만 가져온다. 필드명·열거값을 바꾸지 말 것.
- **네트워크 금지**: 코드에서 외부 호스트로 나가는 호출 금지. 유일한 예외는 `explain/llm_adapter.py`의 선택 기능(기본 꺼짐)이며 `127.0.0.1`/`localhost`만 허용(다른 호스트면 ValueError). 
- 결정론: 난수는 모두 `seed` 인자로 제어(`numpy.random.default_rng(seed)`). 같은 seed → 같은 결과.
- 문자열·UI·문서는 한국어. 코드 주석은 간결하게.
- 각 모듈은 자기 테스트 파일을 `tests/`에 함께 작성한다. `pytest -q`가 3분 이내에 끝나야 한다.

## 1. 저장소 구조
```
safepause/
  __init__.py        __version__ = "0.1.0"
  __main__.py        from safepause.cli import main; main()
  models.py          [계약, 수정 금지]
  config.py          경로·설정
  store.py           JSON 저장소(앱은 /spdata/store)
  data/synth.py      합성 데이터 생성
  data/loader.py     CSV 가져오기
  detect/features.py 특징량
  detect/rules.py    5개 시그널 룰
  detect/anomaly.py  개인 기준 이상탐지(IsolationForest)
  detect/engine.py   룰+이상탐지 결합 → RiskAssessment
  explain/easy_card.py   쉬운 말 카드
  explain/llm_adapter.py 선택: 로컬 sLLM 문장 다듬기(기본 꺼짐)
  guardian/policy.py     조력자 알림·이해충돌·상담 연계
  guardian/outbox.py     알림 기록(실제 발송 없음)
  eval/metrics.py        성능 평가
  eval/report.py         평가 보고서(JSON/Markdown)
  api/                   service.py 업무 로직, router.py, bridge.py(앱 안 파이썬 엔진 진입점)
  web/                   앱 화면(index.html, css/, js/, engine/worker.mjs)
  cli.py                 개발 환경 명령행(평가 다시 계산)
  server/app.py          자동 시험용 HTTP 틀(FastAPI)
android/               안드로이드 셸·APK 빌드
tests/
sample_data/
docs/
```

## 2. config.py / store.py
- `config.data_dir() -> Path`: 앱 안 엔진은 `/spdata/store`(IndexedDB에 연결된 폴더). 개발 환경 명령행은 환경변수 `SAFEPAUSE_HOME` 또는 기본 사용자 폴더. 없으면 생성.
- `config.Settings` dataclass: `night_start_hour=23`, `night_end_hour=6`(23:00~05:59를 심야로 봄), `window_short_days=7`, `window_long_days=30`, `baseline_days=90`, `high_repeat_for_counseling=3`(30일 내 고위험 3건 이상이면 상담 연계 제안).
  - [변경 r4] `is_night(h)`: 시작 > 끝이면 자정을 넘는 구간(h ≥ 시작 또는 h < 끝), 아니면 시작 ≤ h < 끝(시작 = 끝이면 심야 없음). 두 시각과 h는 0~23 정수여야 한다(아니면 ValueError). 이유: 자정을 넘지 않는 설정(예: 0~5시)이면 늘 `h ≥ 0`이 참이라 하루 종일 심야가 됐다(리뷰).
- `store.Store(root: Path)`: JSON 파일 기반. 메서드
  - `load_consent()->Consent`, `save_consent(Consent)`
  - `load_helpers()->list[Helper]`, `save_helpers(list[Helper])`
  - `load_transactions()->list[Transaction]`, `save_transactions(list[Transaction])`
  - `append_decision(txn_id:str, decision:Decision, level:RiskLevel, at:str)`, `load_decisions()->list[dict]`
  - `append_notice(HelperNotice)`, `load_notices()->list[dict]`
  - `wipe()` : 모든 저장 데이터 삭제(당사자의 즉시 철회권).
    - [변경 r1] transactions.json부터 지운다. 잠긴 파일은 잠깐 다시 시도하고, 실패해도 나머지를 계속 지운 뒤 남은 파일 목록을 담은 `WipeIncomplete`(StoreError, 한국어 안내)를 낸다.
  - [추가 r1] `signature(name="transactions.json")`: (이름, 수정 시각 ns, 크기, 파일 번호). 서버가 밖에서 바뀐 저장 파일을 알아채는 데 쓴다.
  - [변경 r2] 쓰기·읽기의 파일 시스템 오류(OSError: 다시 시도해도 풀리지 않는 잠김, 읽기 전용, 디스크 부족)는 한국어 `StoreError`("저장 파일을 쓸 수 없어요…")로 바꾼다. 전에는 서버가 영어 'Internal Server Error'(JSON 아님)를 줬다.
  - [추가 r2] `append_decision(..., *, asked=None)`: '조력자에게 물어볼래요'로 실제 물어본 조력자 수를 기록(주었을 때만 `"asked"` 키). ④ '내가 고른 것'이 0명이면 "물어보려 했지만 조력자가 없었어요"로 보여 준다.
  - 쓰기는 임시 파일 후 교체(원자적). UTF-8.
  - [변경 r3] 프로세스 사이 잠금: 읽기·쓰기(특히 `_append`의 읽기-수정-쓰기)를 스레드 RLock에 더해 폴더 안 빈 파일
    `.sp-store.lock`의 OS 파일 잠금(표준 라이브러리 `msvcrt.locking`/`fcntl.flock`, `store.FileLock`)으로 줄 세운다. 10초 안에
    못 잡으면 한국어 `StoreError`("다른 SafePause 창이 저장 파일을 쓰고 있어요…"). 잠금 파일은 내용이 없고 wipe 대상이 아니다.
    이유(리뷰 재현): 같은 폴더에 두 프로세스가 `append_decision`을 300건씩 동시에 하자 한쪽 300건이 모두 사라졌다(두 프로세스).
    확인: 두 프로세스 80건씩 동시 기록 → 160건(잠금을 끄면 80건, 테스트가 차이를 잡음).

## 3. data/synth.py — 합성 데이터
공개 통계로 보정한 데이터가 **아니다**. 제안서 S19 시그널을 재현하기 위해 설계한 가정 기반 시나리오이며 docs/dataset_card.md에 가정을 모두 적는다.
- `Persona` dataclass: `name`, `monthly_income`, `income_day`, `daily_card_mean`, `card_count_per_week`, `known_payees: list[tuple[str,str]]`(이름,계좌), `known_merchants: list[tuple[str,str]]`, `telecom_line: str`, `telecom_bill`, `micropay_per_month`, `active_hours=(8,22)`.
- `PERSONAS: dict[str, Persona]` 최소 3종: `"worker"`(급여 근로, 월 입금), `"benefit"`(복지급여 수급), `"student"`(용돈·소액 위주). 값은 명시적 가정.
- `generate_history(persona: Persona, start: date, days: int, seed: int) -> list[Transaction]`: 정상 거래만(label="normal"). 급여 입금, 카드결제(알려진 가맹점 위주, 가끔 새 가맹점 소액), 알려진 상대 송금, 통신요금 월 1회(단일 회선), 소액결제 월 몇 건, ATM. 시간대는 주로 active_hours.
- `inject_scenario(history, code: SignalCode, at: date, seed: int) -> list[Transaction]`: 원본을 바꾸지 않고 새 리스트 반환. 주입 거래 label=code.value. 시나리오:
  - NIGHT_REPEAT_TRANSFER: 3~5일에 걸쳐 00~04시에 처음 보는 상대에게 이체 4~6건(각 10만~50만 원)
  - PAYEE_SURGE: 새 상대 1명에게 7일 내 4~7건 이체, 합계가 평소 7일 송금 합계의 5배 이상
  - MICROPAY_SURGE: 7일 내 통신 소액결제 8~15건(각 1만~10만 원)
  - NEW_MERCHANT_HIGH_VALUE: 처음 보는 가맹점 2~4곳에서 고액 결제(개인 카드결제 p95의 3배 이상)
  - MULTI_LINE_TELECOM: 30일 내 서로 다른 새 회선 2~3개의 통신요금 청구(명의도용 개통 재현)
- `make_dataset(persona_key: str, seed: int, days: int = 120, scenarios: list[SignalCode] | None = None) -> list[Transaction]`: 정상 이력 + (scenarios 각 1회, 마지막 30일 안) 주입. ts 오름차순 정렬, id 고유.
- `to_csv(txns, path)`, `from_csv(path) -> list[Transaction]`: SafePause 표준 CSV(열: id,ts,amount,direction,channel,counterparty,counterparty_id,line_id,memo,label).
  - [변경 r2] 표준 CSV의 ts는 `parse_standard_ts`로 읽는다: 시간대 표기('+09:00', 'Z')가 있으면 기기 시각으로 바꾼 뒤 시간대를 뗀다(models.py 계약: 시각은 모두 naive 로컬, 서버의 보낼 시각 처리와 같은 규칙). 'Z'는 Python 3.10에서도 읽히도록 '+00:00'으로 바꿔 읽는다. 연도가 1900~2100 밖이면 `DateRangeError`(ValueError). 이유: 시간대가 섞인 파일은 정렬에서 TypeError(500), 모두 시간대가 있는 파일은 이후 check마다 500이었고, '0001-01-01' 같은 빈 날짜 대용값은 날짜 계산 넘침(OverflowError)으로 ②·③ 화면을 멈췄다.
  - [변경 r3] `parse_standard_ts`는 먼저 `normalize_iso_ts`로 ISO 8601 모양을 Python 3.10 `fromisoformat`이 읽는 모양으로 맞춘다:
    '+0900'·'+09'→'+09:00', 'Z'→'+00:00', 소수 초는 6자리로 채우거나 자름, '20260901T100000'·'2026-09-01 10:00'→'2026-09-01T10:00:00'.
    이유: 3.11부터 fromisoformat이 넓어져, 같은 표준 CSV가 3.12에서는 읽히고 3.10에서는 행이 '형식 오류'로 빠지거나(from_csv는 실패) 했다.
  - [변경 r6] 표준 CSV의 amount는 `round_amount`로 원 단위 반올림(0.5는 절댓값이 커지는 쪽, 2.5→3)하고, 0원 이하(음수 포함)면
    `AmountError`(ValueError)다. load_csv는 그 행을 건너뛰고 warnings에 "금액이 0원 이하"로 남기고, from_csv는 줄 번호와 함께 실패한다.
    한국어 머리글 CSV(§4)도 같은 `round_amount`를 쓴다. 이유: 표준 CSV는 버림(`int`)·0원 수용·음수는 부호만 떼기, 한국어 머리글
    CSV는 Python `round`(2.5→2)여서 같은 금액이 경로마다 다르게 읽혔다. 합성 데이터 생성·평가는 CSV를 읽지 않아 바뀌지 않는다.
  - [변경 r7 · 2026-10-03, 커밋 d853475] **위 약속의 글자와 다르게 engine.py·anomaly.py·features.py의 코드를 고쳤다(계산 속도만).**
    고친 것: 학습 구간이 평가 걷기의 앞부분이면 이력을 한 번만 걷기(fit_assess·assess_modes), IsolationForest 점수를 한 번의
    score_samples로 계산, 같은 구간의 p95를 다시 쓰기. 판정 기준·임계값·모델 설정·특징량 정의·합성 정의는 그대로다.
    결과가 같다는 근거: ① tools/check_eval_unchanged.py로 seed 21~40 평가를 다시 돌려 docs/eval 원자료 1,100개 값과 차이 0,
    ② 옛 코드(5d225bf)와 새 코드의 무작위 차분 시험 3,628건(비교 칸 59,109개)에서 위험 판정·점수·근거·평가 지표·API 응답이
    비트까지 같음(실수는 float.hex로 비교, 일부러 버그를 심은 사본 두 개는 둘 다 잡힘), ③ 앱 안 엔진 다시 계산 168개 값 일치.
    다른 것은 로더·API가 받지 않는 입력(음수 금액 등)에서 내는 오류 문구·예외 종류뿐이다. 그래서 이 검증 세트의 수치는 그대로
    유효하다고 보고, 고친 사실과 근거를 여기 남긴다(위 SHA-256 문장은 이 커밋 전까지만 맞다).
- [추가 r4 · 사전 등록] 경계 변형(subtle) 시나리오. **이 항목과 §8 [추가 r4]는 subtle 평가 결과를 보기 전에 적었다. 결과를 본 뒤
  아래 정의, 룰 기준(§5 rules.py), 결합 기준(engine.py 점수 기준)을 바꾸지 않는다. 바꾸면 이 실험은 무효다.**
  - 목적: 표준 시나리오는 룰 기준을 넉넉히 넘게 만들어 '룰만'도 100% 탐지한다. 그래서 AI 이상탐지(IsolationForest)가 실제로
    더하는 것은 룰 기준에 못 미치는 변형에서만 보인다. 이 변형에서 룰만·결합·AI만 모드를 비교한다.
  - API: `inject_scenario(history, code, at, seed, intensity="standard")`, `make_dataset(..., intensity="standard")`.
    `intensity`는 `"standard"`(기본) 또는 `"subtle"`. 그 밖의 값은 ValueError. `"standard"`의 동작은 바꾸지 않는다
    (같은 인자면 바꾸기 전과 거래가 똑같다. 테스트가 바꾸기 전 출력의 SHA-256과 비교한다).
  - 라벨: standard와 같은 SignalCode 값. 따로 필드를 두지 않고, eval이 intensity별로 나눠 집계한다.
  - subtle 정의(시작일 `at` 0시 이후. 기준값은 standard와 같은 synth 기준값: `at` 이전 거래로 계산):
    - NIGHT_REPEAT_TRANSFER: 7일 안(at부터 0~6일째) 00~04시에 처음 보는 상대에게 이체 2건, 각 30만~80만 원(1만 원 단위).
      상대는 standard처럼 한 사람이다.
    - PAYEE_SURGE: 처음 보는 상대 1명에게 7일 안 이체 2건(09~20시, standard와 같음). 2건 합계 = 평소 7일 송금 합계 ×
      U(2.0, 2.9). 평소 합계가 0이면 합계는 20만~29만 원(1만 원 단위). '평소 7일 송금 합계'는 standard와 같은 값이다:
      at 이전 이체 합계 ÷ max(1, (at − 이력 첫날)/7). 합계는 1,000원 단위로 맞추고 [2.0배, 2.9배] 밖으로 나가지 않게 자른다
      (그 구간에 1,000원 단위 값이 없으면 원 단위). 첫 건 비율은 U(0.3, 0.7)이고, 두 건 모두 1,000원 이상이다.
    - MICROPAY_SURGE: 7일 안 본인 회선의 휴대폰 소액결제 4건, 각 5만~10만 원(1,000원 단위), 09~22시.
    - NEW_MERCHANT_HIGH_VALUE: 처음 보는 가맹점 1곳에서 카드결제 1건(10~20시). 금액 = max(개인 카드 p95 × U(2.0, 2.9), 10만 원).
      p95는 standard와 같은 값(at 이전 카드결제 금액의 95백분위)이다. p95 × 배율은 100원 단위로 맞추고 [2.0배, 2.9배] 안에 둔다.
      카드 이력이 없으면(p95 = 0) 10만 원.
    - MULTI_LINE_TELECOM: 처음 보는 회선 1개의 통신요금 청구 1건. at 당일 09~18시, 금액은 standard와 같은 3만 5천~9만 8,990원.
  - 배치(make_dataset): standard처럼 각 1회, 마지막 30일 안에 넣는다. 차지하는 일수는 `SUBTLE_SPAN_DAYS`(심야 7, 송금 급증 7,
    소액결제 7, 가맹점 1, 회선 1)이다. 위치·하위 seed를 정하는 방식은 standard와 같다. 같은 seed면 정상 거래는 standard·subtle·
    대조군에서 모두 같다.
  - 룰 기준과의 관계(결과를 보기 전에 rules.py를 읽고 정리). '못 미친다'는 모든 룰의 CAUTION 기준 아래라는 뜻이 아니다.
    - 심야 반복 이체: 7일 심야 이체 2건이다. 심야 룰의 CAUTION 기준(2건)에는 닿고 HIGH 기준(3건)에는 못 미친다. 같은 상대에게
      30만 원 이상을 두 번 보내므로 특정 계좌 송금 급증 룰의 금액 경로가 함께 발동할 수 있다(2건째에 룰의 배율이 5 이상이면 HIGH).
    - 특정 계좌 송금 급증: 건수 2는 건수 기준(3건)에 못 미치고, synth 기준 배율 < 3은 금액 경로 배율 기준(3배)에 못 미친다.
      합계가 30만 원 미만이면 금액 경로의 하한에도 못 미친다. 단, 룰의 '평소 합계'는 평가 시각 기준 [90일 전, 7일 전] 구간으로
      계산해 synth 기준값과 다를 수 있다.
    - 통신 소액결제 급증: 4건은 CAUTION 기준(5건 이상)에 못 미친다. 같은 7일 안에 정상 소액결제가 있으면 5건 이상이 될 수 있다.
    - 신규 가맹점 고액 결제: 1건이라 HIGH 기준(7일 2건)에 못 미친다. p95 × 3 < 10만 원인 사람은 금액이 10만 원이 되어 룰의
      CAUTION 기준(금액 ≥ max(p95 × 3, 10만 원))에 닿는다.
    - 단기간 다회선 통신요금: 새 회선 1개다. 본인 회선이 최근 30일 안에 청구됐으면 서로 다른 회선이 2개가 되어 CAUTION 기준에
      닿고, HIGH 기준(새 회선 2개)에는 못 미친다.

## 4. data/loader.py — 실제 거래내역 가져오기
- `load_csv(path_or_text, mapping: dict | None = None) -> tuple[list[Transaction], dict]`: 두 번째 값은 리포트(`{"rows": n, "skipped": k, "mapping": {...}, "warnings": [...], "delimiter": ","}` 등). 읽은 거래가 하나도 없으면 `LoaderError`.
- 표준 CSV(§3)면 그대로 읽음. 아니면 헤더 자동 매핑(머리글은 공백·괄호 속 글자를 빼고 비교: '출금(원)'→'출금'):
  일시(`거래일시`,`일시`,`날짜`,`이용일시`,`승인일시`, 또는 `거래일자`·`이용일자`·`승인일자`+`거래시간`·`이용시간`·`승인시간`),
  금액(`출금액`·`출금금액`·`출금`·`지급`·`지급액`·`찾으신금액`/`입금액`·`입금금액`·`입금`·`맡기신금액` 쌍, 또는 `금액`·`거래금액`+`구분`,
  또는 카드 이용내역 `이용금액`·`승인금액`), 상대(`받는분`,`보낸분`,`받는사람`,`보낸사람`,`수취인`,`상대방`,`거래처`,`가맹점명`,`가맹점`,
  `내용`,`거래내용`,`기재내용`; '보낸분/받는분'처럼 '/'가 든 머리글은 나눠 비교), 메모(`메모`,`비고`,`적요`).
  적요(모바일이체·체크카드 같은 거래 종류 글자)는 상대로 쓰지 않는다(mapping으로 지정하면 씀).
- 인코딩: 앞 2바이트가 FF FE / FE FF면 UTF-16, 아니면 utf-8-sig → cp949 순. 구분자: 쉼표·탭·세미콜론·세로줄(|)을 하나씩 써서
  머리글을 찾고, 찾은 구분자 가운데 머리글 칸이 가장 많은 것을 쓴다.
- 금액: 쉼표, 통화 표기(₩, 전각 ￦, CP949 파일의 '\', KRW, 원), 모든 유니코드 공백(NBSP 등)을 지운다. 괄호 '(5,000)', 끝 '-'('5,000-'),
  U+2212 빼기 기호, '△'는 음수. 원 단위 반올림은 §3 `round_amount`와 같다.
- channel 추정: 적요/내용에 `소액결제`,`휴대폰결제` → MICROPAY; 통신사 이름(`SKT`,`SK텔레콤`,`KT`,`LG U+`,`LGU+`,`LG유플러스`, 알뜰폰 브랜드,
  'OO통신'·'OO텔레콤' 회사 이름)이나 `통신요금`·`휴대폰요금`·`인터넷요금`·`통신비` → TELECOM_BILL('KT&G'·'케이티앤지', '통신판매',
  '정보통신'·'전자통신' 회사, 통행요금·택배요금·렌탈요금은 아님); `ATM`,`현금`('현금영수증' 제외) → ATM; 입금 → INCOME; 가맹점명 열이 있거나
  '체크카드' 등 → CARD; 그 외 출금 → TRANSFER. 추정 규칙은 리포트 `warnings`에 "추정" 사실을 남긴다.
- 특정 은행 양식을 지원한다고 주장하지 말 것(테스트한 적 없음). 헤더를 모르면 `mapping` 인자로 지정하라는 오류 메시지를 한국어로.
- [변경 r2] 표준·한국어 머리글 두 경로 모두 연도가 1900~2100 밖인 행은 건너뛰고 `skipped`·`warnings`에 "날짜가 1900~2100년 밖"으로 남긴다.
- [변경 r3] 최신순(내림차순) 파일: 이웃한 행의 시각이 내려가는 쌍이 올라가는 쌍보다 많으면(같으면 첫 행이 마지막 행보다 늦으면)
  행 목록을 뒤집은 뒤 안정 정렬해, 같은 시각 거래도 오래된 것(파일 아래 줄)이 먼저 오게 한다. warnings에 "최근 거래가 위에 있는 파일이라…
  다시 정렬했어요"를 남긴다. 이유: 날짜만 있는 파일은 모두 낮 12시라, 최신순 파일에서 같은 날 거래가 거꾸로 평가됐다(리뷰 재현: 같은 날
  1만→2만→50만 원 송금에서 50만 원 건이 '처음 보낸 돈', 첫 1만 원 건이 뒤 거래까지 더한 '3번·53만 원'이 됨).
- [변경 r3 → r6에서 대체] 회선 열이 없는 통신요금의 회선 키를 통신사 이름으로 만들던 규칙은 아래 r6 규칙으로 바뀌었다.
- [변경 r6] CSV 로더 리뷰(data_review.md) 반영. 확인: tests/test_loader.py의 r6 절(수정 전 코드에서 112개 실패, 수정 뒤 통과),
  리뷰 판정표(make_and_run.py)·e2e 재실행. 합성 데이터 평가(eval)는 CSV를 읽지 않아 결과 JSON이 그대로다.
  - 회선: 통신요금·소액결제의 회선은 회선 열(`회선`,`전화번호` 등)이나 글 속 휴대폰 번호로만 정하고, 번호를 모르면 비운다
    (warnings: "통신요금 N건은 회선(전화번호) 정보가 없어 '휴대폰 요금이 여러 개' 판단에서 뺐어요"). 번호는 가운데를 가리고
    (010-****-1234), '+82 10-…'·'82-10-…'·'+82(0)10…'은 0으로 바꾼 뒤 가린다. 이유: 이름으로 만든 회선은 같은 통신사의 두 회선도,
    한 사람의 휴대폰·인터넷·태블릿도 가르지 못해 '여러 회선' 판단이 틀렸다(리뷰 재현: 통행요금·택배요금·렌탈요금이 이름별 회선이 되어
    고위험 2건·주의 1건 → 0건). detect/는 바꾸지 않았다(회선이 빈 통신요금은 multi_line_telecom 룰·new_line 특징에서 빠진다).
  - 상대 열이 없으면 상대를 비우고 warnings에 "받는 사람 열을 찾지 못해 '한 사람에게 많이 보내기'는 판단하기 어려워요"를 남긴다.
    이유: 적요를 상대로 쓰면 모든 이체가 '모바일이체' 한 상대로 합쳐졌다(리뷰 재현: '보낸분/받는분' 파일 고위험 0건 vs 내용 열 3건 → 둘 다 3건).
  - 날짜·시각은 칸 전체가 맞아야 읽는다(요일 '(화)', 소수 초, '+09:00'·'Z' 시간대는 허용하며 시간대는 기기 시각으로 바꾼다).
    오전/오후와 영어 AM/PM(앞·뒤, 'A.M.' 포함)을 24시간제로 바꾸고, '오전 13시'처럼 모순이면 못 읽음. 이유: 앞부분만 맞아도 받아서
    'PM'을 버렸고(낮 송금 → 심야 알림 4건·고위험 1건), '2026.09.01 ~ 2026.09.30 합계' 같은 행이 가짜 출금이 되었다.
  - 숫자만 있는 시각 열은 엑셀이 앞 0을 지운 값으로 보고 0을 채운다: 열에 5~6자리가 하나라도 있으면 HHMMSS(91030 → 09:10:30),
    아니면 HHMM(905 → 09:05). 한 칸 일시의 '20260901 91030'도 읽는다. 시각 칸이 있는데 못 읽으면 낮 12시로 두고 warnings에
    "시각을 읽지 못한 N건"(비어 있으면 "시각이 없는 거래 N건")을 남긴다. 이유: 91030이 12:00이 되어 심야 고위험 2건이 사라졌다.
  - 합계·소계: '합계'·'소계'가 든 행, 일시·시각 칸에 '~'가 든 행은 건너뛰고 warnings에 "합계·소계 줄 N개는 거래가 아니라서 뺐어요".
  - 취소: '취소'가 든 행, 출금·입금 칸이 음수인 행, 방향을 정해 둔 파일(default_direction·카드 이용내역)의 음수 금액은 방향을 뒤집지
    않고 건너뛴다(warnings "취소로 보이는 N줄… 원래 거래는 그대로 두었어요"). 단 그 열의 0 아닌 금액이 모두 음수면 음수로 적는
    파일로 보고 부호만 뗀다. 금액 한 열+구분 열 파일의 음수도 부호만 뗀다(구분 열이 방향을 정함).
  - 카드 이용내역: 금액 열이 `이용금액`·`승인금액`이고 구분 열·default_direction이 없으면 모두 쓴 돈(출금)으로 본다(warnings에 추정 표시).
  - mapping `date_format`: strptime 형식(예: "%m/%d/%Y", "%y.%m.%d %H:%M"). 칸 전체가 맞아야 하고, 형식에 시각이 없으면 시각 열을 쓴다.
    열 이름 없이 설정(`date_format`·`default_direction`)만 준 mapping은 열을 자동으로 찾는다. 잘못된 형식은 한국어 LoaderError.
  - 엑셀: `.xlsx`는 첫 시트(`data/xlsx.py`), `.xls`(엑셀 97~2003 BIFF8)도 첫 시트를 읽는다(`data/xls.py`). 확장자만 .xls인 HTML 표
    (은행·카드사 웹 내려받기)는 날짜·금액 머리글이 있는 첫 표를 읽는다(`data/htmltable.py`). 모두 표준 라이브러리라 앱 엔진에서도 같다.
    암호가 걸린 엑셀·엑셀 95 이전·한글/워드 문서는 쉬운 말로 안내한다.
  - 파일 종류: 앞 바이트로 PDF·PNG·JPEG·GIF를, 글 앞부분으로 표가 없는 HTML·XML을 알아보고 "엑셀에서 'CSV UTF-8(쉼표로
    분리)'로 저장해 올려 주세요" 같은 안내를 한다(이전에는 '인코딩' 오안내). 빈 줄·쉼표만 있는 파일은 "파일이 비어 있어요".
  - 머리글을 못 찾으면 무엇이 없는지(날짜 열·금액 열·둘 다) 알려 준다.
  - 읽은 거래가 없으면 LoaderError: "읽을 수 있는 거래가 없어요. N줄을 모두 건너뛰었어요. 건너뛴 이유: …"(많은 순서로 최대 3가지,
    날짜가 가장 많으면 date_format 예시). 머리글만 있으면 "머리글 아래에 거래 줄이 없어요". 서버는 이 문구를 400 detail로 그대로 보여 준다.

## 5. detect/
### features.py
- `class History`: 과거 거래(평가 대상 이전 것만)로부터 개인 기준 통계 계산. `History(txns: list[Transaction], settings)`; `.known_payees`, `.known_merchants`, `.known_lines`, `.card_amount_p95`, `.transfer_7d_mean` 등.
- `txn_features(txn, history_before: list[Transaction], settings) -> dict[str, float]`: 이례성 모델 입력. 최소: `log_amount`, `amount_vs_p95`(금액/개인 p95), `hour_sin`,`hour_cos`, `is_night`, `new_counterparty`(0/1), `cp_count_7d`, `cp_sum_7d_ratio`(해당 상대 7일 합(대상 포함) / 같은 거래 방법·방향의 평소 7일 합계, 분모 하한 1만 원. 이체면 평소 7일 송금 합), `channel_count_7d_ratio`, `new_line`(0/1). 누수 금지: history_before는 txn.ts 이전 거래만.
  - [변경 r4] 같은 상대·회선 판별(`counterparty_key`, `line_key`)은 조력자 정책(§7 이해충돌)과 같은 규칙으로 한다: 식별값의 공백·하이픈·점은 무시하고, 계좌처럼 보이는 조각(숫자 6개 이상)은 숫자와 가림표(*)만 남긴다('900-0101-100001' = '9000101100001' = '농협 900.0101.100001'). 가림표가 있으면 길이가 같고 둘 다 보이는 자리의 숫자가 모두 같으며 그런 자리가 4개 이상일 때 같은 상대로 보고, History가 먼저 본 상대·회선 키로 묶는다(`resolve_counterparty`, `resolve_line`). 계좌가 아닌 식별값은 공백·하이픈·점을 빼고 대소문자를 무시한다('M-1001' = 'm1001'). 근거의 `usual_line`은 처음 본 표기 그대로 남긴다.
    이유(리뷰 재현): 공백만 지워서, 13번 보낸 엄마 계좌를 숫자만 적으면 '처음 보내는 사람'이 되어 송금 급증 CAUTION + 이상 점수 0.970 → 고위험, 카드는 "엄마에게 처음 보내는 돈이에요."(거짓)였고, 정책은 엄마를 이번 거래 상대로 보고 알림에서 빼 다른 조력자에게만 고위험 알림이 갔다. 영향: 위 재현은 위험 없음(점수 0.902, 저장 표기와 같음). 20-seed eval(docs/eval) 수치는 그대로다.
  - [변경 r4] `amount_p95`는 docstring·모델 카드의 '평소' 정의대로 평소 기준 구간(`baseline_bounds`)이 7일 미만이면 0(기준 없음)이다. 전에는 표본 5건만 있으면 구간이 짧아도 계산해, 1.5일 동안 6만 원 6건 뒤 처음 가는 가게 15만 원이 기준 18만 원에 못 미쳐 룰에 걸리지 않았다(이제 10만 원 하한). 20-seed eval 수치는 그대로다.
  - [변경 r4] 금액: `History.append`·`compute_features`는 음수 금액이면 ValueError. 0원 거래는 이력(transactions·start)에는 남기지만 개인 기준 통계와 룰 건수(심야 반복·같은 상대·소액결제·새 가게·회선)에 넣지 않고, 0원 대상은 어느 룰에도 걸리지 않는다. 이유: 0원 심야 이체 3건이 심야 반복 HIGH가 됐다(리뷰 재현). 합성 데이터에는 0원 이하 거래가 없어 eval 수치는 그대로다.
  - [변경 r1] 같은 시각 거래 규칙을 walk()·assess_many와 맞춘다: history_before 목록에 대상이 있으면 대상보다 이른 시각 거래 + 같은 시각이면서 목록에서 대상보다 앞의 거래만 쓴다. 대상이 목록에 없으면 목록 전체를 과거 이력으로 보고 txn.ts 이하를 쓴다(walk의 context와 같은 규칙). 날짜만 있는 CSV는 모든 거래가 12:00이라 같은 시각이 흔하다.
- `FEATURE_NAMES: list[str]` 고정 순서.
### rules.py
- `evaluate_rules(txn, history_before, settings) -> list[SignalHit]` (평가 대상 거래 시점 기준, 대상 거래 포함 최근 창에서 판단):
  - NIGHT_REPEAT_TRANSFER: 대상이 심야 출금 이체이고, 최근 7일 심야 이체(대상 포함) ≥3 → HIGH; =2 → CAUTION.
  - PAYEE_SURGE: 대상이 이체이고 상대가 첫 거래 30일 이내(또는 처음)이며, 그 상대 7일 이체 건수 ≥3 또는 7일 합계 ≥ 평소 7일 송금 합계×3 (평소 합계가 0이면 합계 ≥ 30만 원) → 건수≥4 또는 배율≥5면 HIGH, 아니면 CAUTION.
    - [변경 r1] 금액(배율) 경로에도 절대 하한을 둔다: 7일 합계 ≥ 30만 원이어야 발동한다. 배율만으로 HIGH가 되려면 7일 건수 ≥ 2이고 합계 ≥ 30만 원이어야 한다(건수 ≥ 4 HIGH는 그대로).
      이유: 평소 송금이 적은 사람은 처음 보는 상대에게 2만~5만 원을 한 번 보내도 배율 5 이상이 되어 HIGH·조력자 알림이 나갔다(리뷰 실측: 시나리오 없는 대조군 60사례 rules 모드에서 소액 1건 HIGH 4건). S38(오탐이 금융 주권을 위축시키지 않게)에 반한다.
      영향(20-seed eval 재실행, docs/eval): 시나리오 탐지율은 모든 방식에서 그대로(결합·룰 100%/100%). 대조군 월평균 알림 결합 0.30→0.18건, 고위험 0.17→0.03건, 룰만 0.18→0.03건. 대신 송금 급증 시나리오의 첫 알림이 늦어졌다(결합 첫 알림 순번 평균 1.65→2.45번째, 첫 알림 전 금액 평균 8만 2,500원→16만 3,000원).
    - [변경 r2] (1) 건수 경로의 HIGH에도 7일 합계 30만 원 하한을 둔다: HIGH = 합계 ≥ 30만 원 이고 (건수 ≥ 4 또는 (배율 ≥ 5 이고 건수 ≥ 2)). (2) 상대의 첫 거래가 이력 첫 거래 뒤 30일(window_long_days) 안이면 이력이 그 전을 담지 않아 '새 상대인지 알 수 없음'(`evidence.newness_unknown=True`)으로 보고, 건수 경로를 쓰지 않고 금액 경로(7일 합계 ≥ 30만 원, 평소 합계가 있으면 3배 이상)로만 CAUTION까지 낸다. 카드는 이때 '처음·새로'라고 말하지 않는다.
      이유(리뷰 재현): 첫 거래 30일 이내 판정을 저장된 이력의 시작부터 계산해, 어떤 파일이든 처음 30일 동안은 모든 송금 상대가 '새 상대'가 되고 건수 경로에는 금액 하한이 없었다. 엄마에게 2일마다 1만 원씩 보낸 120일 이력에서 HIGH 13건(모두 파일 시작 뒤 6~30일째), 같은 패턴의 1개월치 은행형 CSV에서 32건 중 23건이 HIGH, 엄마에게 1만 원을 다시 보내려 하면 HIGH와 조력자 알림이 계획됐다. r1의 MULTI_LINE_TELECOM 문제와 원인이 같다. S38·r1 취지에 따라 고친다.
      영향: 위 재현은 HIGH 13→0건, 23→0건(check도 위험 없음). 20-seed eval(docs/eval)은 시나리오 탐지율·오탐·대조군·첫 알림 지표가 모두 그대로이고, 룰만 방식의 거래 단위 고위험 적중만 931→918건(재현율 56.4→55.6%)으로 줄었다. 대가: 1개월치 파일 안에서 시작된 착취 송금은 이 룰로는 '꼭 확인해요'가 되지 않는다(심야 반복 이체 등 다른 룰은 그대로).
  - MICROPAY_SURGE: 대상이 MICROPAY이고 7일 건수 ≥ max(5, 개인 평소 7일 평균×3) → 건수≥8이면 HIGH 아니면 CAUTION.
  - NEW_MERCHANT_HIGH_VALUE: 대상이 CARD이고 처음 보는 가맹점이며 금액 ≥ max(개인 카드 p95×3, 10만 원) → 최근 7일 같은 조건 거래(대상 포함) ≥2면 HIGH, 1이면 CAUTION.
  - MULTI_LINE_TELECOM: 대상이 TELECOM_BILL이고 처음 보는 회선이며 최근 30일 서로 다른 회선 청구 수 ≥2 (평소 회선 1개 기준) → 새 회선 ≥2개면 HIGH, 1개면 CAUTION.
    - [변경 r1] '평소 회선' = 이력에서 가장 먼저 청구된 회선. 새 회선을 셀 때 이 회선은 뺀다. 이력이 30일보다 짧으면(예: 1개월치 CSV) 본인 회선도 '첫 청구가 최근 30일 안'이 되어 새 회선 하나만으로 HIGH가 되던 문제를 막는다. evidence에 `usual_line`을 남긴다.
  - [변경 r3] '처음인지 알 수 없음'(`evidence.newness_unknown=True`)을 PAYEE_SURGE(r2)와 같은 규칙으로 NEW_MERCHANT_HIGH_VALUE·
    MULTI_LINE_TELECOM에도 적용한다. 기준: 처음 본 때(대상이면 평가 시각)가 이력 첫 거래 뒤 window_long_days(30일) 안이거나 이력이 비었으면 알 수 없음.
    - NEW_MERCHANT_HIGH_VALUE: 대상이 알 수 없음이면 최대 CAUTION. 7일 '같은 조건' 건수에서도 알 수 없는 과거 거래는 뺀다.
    - MULTI_LINE_TELECOM: 첫 청구가 이력 첫 30일 안인 회선은 '새 회선'으로 세지 않는다(`unknown_lines_30d`로 따로 남김). 대상 회선이
      그런 경우면 newness_unknown이고 늘 CAUTION. r1의 '평소 회선 = 가장 먼저 청구된 회선' 규칙은 그대로.
    - PAYEE_SURGE: 처음 보는 상대(first 없음)도 평가 시각이 이력 첫 30일 안이면 알 수 없음으로 본다(카드가 '처음'이라고 하지 않게. 건수는 1이라 등급은 그대로).
    - engine.combine_level: CAUTION 근거가 모두 newness_unknown이면 이상 점수 ≥ 0.90이어도 HIGH로 올리지 않는다(룰이 낮춘 판단을 모델이 되돌리지 않게).
    - 카드: 새 가게·새 회선인지 알 수 없으면 '처음·새'라고 말하지 않는다("연세치과에서 결제해요." / "한 달 동안 요금이 3개 나왔어요.").
    이유(리뷰 재현): 파일 첫 30일에는 모든 가맹점이 '처음 보는 곳'이고, 평소 회선 하나만 빼서 2·3번째 정상 회선도 '새 회선'이 되었다.
    정상 1개월치 은행형 CSV(첫 주 치과 15만·안경점 12만, SKT 휴대폰·KT 인터넷·LG U+ 태블릿 요금)에서 HIGH 2건·CAUTION 2건이 나왔고,
    이 가짜 HIGH가 S23 반복 고위험 건수에 들어가 다음 고위험 한 번에 상담 안내가 나왔다(2+1=3). S38·r2 취지에 따라 고친다.
    영향: 위 재현 HIGH 2→0건(CAUTION 4건, 모두 newness_unknown), 적요 달 표기 재현 HIGH 1→0건, 서버의 반복 고위험 건수는 이번 건만.
    20-seed eval(docs/eval)은 다시 돌린 eval_results.json이 이전과 바이트 단위로 같다(평가 구간이 이력 90일 뒤라 영향 없음).
    평가 구간 밖(서버 ②처럼 이력 전체를 판단할 때, 60사례): 대조군 정상 거래 HIGH 12→9건(CAUTION 10→13건), 시나리오 데이터의
    정상 거래 HIGH 47→44건, 주입 거래 판정은 그대로(HIGH 1,307건, CAUTION 69건). 대가: 1개월치 파일 안에서 시작된 새 가게 고액 결제·
    명의도용 회선은 이 룰들로는 '꼭 확인해요'가 되지 않는다(심야 반복 이체·소액결제 급증 룰은 그대로).
  - 각 hit.evidence에 판단 숫자, related_txn_ids에 관련 거래 id.
### anomaly.py — 경량 AI 이상탐지
- `class PersonalAnomalyModel`: scikit-learn `IsolationForest(n_estimators=200, contamination="auto", random_state=seed)`를 **당사자 본인의 과거 정상 기준 기간** 특징량으로 학습.
  - `fit(train_txns: list[Transaction], settings, seed=0) -> self`: 각 거래를 그 이전 이력으로 특징화해 학습(최소 30건 미만이면 `fitted=False`, score는 0.0 반환).
  - `score(txn, history_before) -> float`: 0~1. 학습 데이터 점수 분포 대비 백분위(`학습 거래 중 대상보다 덜 이례적인 거래의 비율` = `1 - 학습 거래 중 대상만큼 또는 더 이례적인 비율`)로 정규화. 높을수록 이례적(1.0이면 학습한 어떤 거래보다도 이례적).
  - `explain(txn, history_before, top_k=2) -> list[Reason]`: 특징별 학습 분포 대비 표준화 편차가 큰 순으로 `Reason(code="anomaly:<feature>", detail={...})`.
    - [변경 r4] 학습 때 값이 한 가지뿐이던(분산 0) 연속 특징은 z를 구할 수 없고 모델 점수에도 쓰이지 않으므로 이유로 내지 않는다(z=0). 0/1 사실 특징(`new_counterparty`, `new_line`, `is_night`, `is_out`)은 분산 0이어도 값이 다르면 남긴다(±99). 학습 거래 시각이 모두 같으면(날짜만 있는 CSV, 모두 12:00) 시각 특징(`hour_sin`, `hour_cos`, `is_night`)은 이유로 내지 않는다(`time_known()`). 시각 특징 이유의 detail에는 모델 설정 기준 심야 여부 `is_night`(bool)를 담는다(카드 그림용). 이유(리뷰 재현): 날짜만 있는 CSV에서 모델 단독 카드 28장 모두 '평소와 다른 시간이에요'(z=±99)였는데, 점수는 시각을 바꿔도 같았다(237/240). 등급·점수는 그대로라 eval 수치도 그대로다.
    - [변경 r4] scikit-learn은 `fit()`이 처음 불러온다(지연 불러오기). `import safepause.detect.engine`은 sklearn·scipy를 싣지 않고, 룰만 쓰거나 학습 전(30건 미만)이면 sklearn 없이 돈다(모바일 2단계 로딩). 실측(개발 컴퓨터, 3회): engine import 1.2초·새 모듈 1,216개 → 0.1초·130개. pickle·`version` 문자열은 그대로다.
  - `version` 문자열(예: "iforest-v1-<n_train>").
### engine.py
- `class RiskEngine(settings=None, seed=0)`:
  - `fit(baseline_txns)`: 이상탐지 모델 학습.
  - `assess(txn, history_before) -> RiskAssessment` 결합 규칙:
    - 룰 HIGH 1개 이상 → HIGH
    - 룰 CAUTION + anomaly ≥ 0.90 → HIGH
    - 룰 CAUTION → CAUTION
    - 룰 없음 + anomaly ≥ 0.98 + 출금 → CAUTION (모델 단독으로는 HIGH로 올리지 않음: 오탐으로 조력자 알림이 가는 것을 막기 위함, S38)
    - 그 외 NONE
    - reasons = 룰 근거 + (anomaly≥0.90이면) 이상탐지 설명
  - `assess_many(txns) -> list[RiskAssessment]`: 시간순으로 각 거래를 그 이전 이력으로 평가.
  - `assess_pending(pending: Transaction, history: list[Transaction]) -> RiskAssessment`: 안전 정지용. 보내기 전 거래를 이력 끝에 붙여 평가(실시간 판단 경로).
  - 모드 인자 `mode: "fused"|"rules"|"anomaly"` (평가 비교용).

## 6. explain/
### easy_card.py
- `render_card(assessment: RiskAssessment, txn: Transaction) -> AlertCard | None` (NONE이면 None).
  - [변경 r4] `render_card(..., settings=None)`: AI 단독 '평소와 다른 시간' 카드의 심야 그림(moon)은 모듈 전역 `Settings()`가 아니라 근거의 심야 여부(이상탐지 시각 이유의 `detail.is_night`, `is_night` 특징 값)로 정하고, 근거에 없으면 넘겨받은 settings(없으면 기본값)로 정한다. 이유: 심야 시각을 바꾼 설정에서도 그림은 늘 23~6시 기준이었다(리뷰).
- 쉬운 정보 원칙: 짧은 문장, 한 문장 한 내용, 어려운 말 금지(금지어 목록: 이상거래, 패턴, 탐지, 알고리즘, 모니터링, 이례, 임계, 통계). 숫자는 "30만 원"처럼 만 원 단위, 시각은 "새벽 2시".
- 시그널별 템플릿(예): NIGHT_REPEAT_TRANSFER → title "밤에 돈을 자주 보냈어요", lines ["요즘 밤늦게 돈을 여러 번 보냈어요.", "이번 주에만 4번이에요.", "누가 시켰나요?"]; pictograms ["moon","money","question"].
- 모든 카드 공통: question "이 돈을 정말 보내는 것이 맞나요?", choices 3개(send "그래도 보낼래요", cancel "안 보낼래요", ask_helper "조력자에게 물어볼래요"), speak_text = title + lines + question.
  - [변경 r1] 질문·선택지는 거래 방법에 맞춘다(쉬운 정보: 정확한 말). 이체: 위 문장 그대로. 카드·소액결제·기타: "이 돈을 정말 내는 것이 맞나요?" / "그래도 낼래요" / "안 낼래요". 통신요금: "이 요금을 정말 내는 것이 맞나요?". 현금 인출: "이 돈을 정말 찾는 것이 맞나요?" / "그래도 찾을래요" / "안 찾을래요". ask_helper는 늘 "조력자에게 물어볼래요". 모임 회비·가게처럼 사람이 아닌 받는 곳에는 '에게' 대신 '에'를 붙인다.
  - [변경 r1] 룰 근거의 건수·합계는 대상 거래를 포함한다. 보내기 전 카드(`render_card(..., past=False)`, 기본)는 "7일 동안 이번이 N번째예요.", "이번 돈까지 모두 X원이에요."처럼 말하고, 이미 이뤄진 건수(N-1)가 2 미만이면 '자주·여러 번'을 쓰지 않는다(처음이면 "처음 보내는 돈이에요."). 이유: "자주 보냈어요 / 이번 주에만 1번이에요"처럼 거짓·모순 문장이 나왔다.
  - [추가 r1] 기록 카드 `render_card(..., past=True)`(④ 알림 카드): 이미 끝난 거래이므로 과거형, '이번 주' 대신 '7일 동안', question = "그때 걱정했던 거래예요.", choices = [] (speak_text도 같은 규칙).
  - [추가 r1] `practice_result(decision, txn) -> (제목, 줄)`: 보내기 연습 결과 문장(이체 "○○에게 보냈어요", 카드 "○○에서 결제했어요", 소액결제 "휴대폰으로 결제했어요" 등).
  - [변경 r2] `practice_result(decision, txn, asked_count=None)`: ask_helper인데 실제 물어본 조력자가 0명이면 "물어볼 조력자가 없어요" / "○○에게 30만 원을 아직 보내지 않았어요." / "⑤ 조력자에서 조력자를 정할 수 있어요."(전에는 알림 0건인데도 '조력자에게 물어봐요'라고 했다).
  - [변경 r2] 기록 카드(past=True)의 모든 줄은 과거형(…했어요/였어요/었어요)이나 질문으로 끝난다: '큰 돈이었어요', '평소에 쓰는 돈보다 많았어요', '그 돈은 ○원이었어요', '걱정되는 점이 N가지 더 있었어요' 등. 한 카드 안에서 시제가 섞이지 않게 한다(테스트로 전수 검사).
  - [변경 r3] 기록 카드는 제목도 과거형이다('휴대폰 결제가 많았어요', '평소보다 큰 돈이었어요', '평소와 다른 시간이었어요',
    '새로 보내던 사람이었어요', '휴대폰 요금이 여러 개였어요', '다시 볼 거래였어요' 등). 지금 기준 말 '요즘'은 '그때'로 바꾼다
    ('그때 밤늦게 돈을 여러 번 보냈어요.'). 테스트는 제목·줄·speak_text 모두 과거형(또는 질문)이고 '요즘'이 없는지 전수 검사한다.
    이유: 제목에 과거형이 없었고(리뷰 실측: 인물 3명×seed 3개의 ④ 카드 215장 중 73장이 '휴대폰 결제가 많아요'), 6월 카드도 '요즘…'이라고 말했다.
- `readability_issues(card) -> list[str]`: 규칙 위반 목록(줄 길이>30, 금지어, 줄 수>4, 제목>15). 테스트에서 모든 템플릿 카드가 빈 목록이어야 한다.
### llm_adapter.py (선택)
- [변경 r2] 파이썬 API로만 제공하고 화면·명령행에는 연결하지 않는다. 문서는 '선택 기능(기본 꺼짐)'이 아니라 'API만 제공'으로 쓴다(켤 방법이 있는 것처럼 읽히지 않게).
- `LocalLLMRewriter(endpoint="http://127.0.0.1:11434", model="", enabled=False)`; `rewrite(card) -> AlertCard`: enabled이고 서버 응답 시 lines만 다듬고, `readability_issues`가 생기거나 숫자가 달라지면 원본 반환. endpoint 호스트가 loopback이 아니면 ValueError. 네트워크 실패 시 원본 반환. `source="llm"`은 실제 다듬었을 때만.
  - [변경 r4] 숫자 보존 검사(`same_numbers`)는 줄마다 비교하고, 토큰은 숫자와 뒤의 단위어 전체('3번째', '2시간', '3개월')다. '시'는 앞의 때 말까지 한 토큰('새벽2시' ≠ '오후2시'). 이유(리뷰 재현): 숫자와 바로 뒤 한 글자만 봐서 "7일 동안 이번이 3번째예요."(보내기 전) → "7일 동안 3번 보냈어요."처럼 뜻이 바뀐 문장과, 숫자를 다른 줄로 옮긴 문장이 통과했다. 남은 한계: 숫자·단위가 같은 채 '모두/이번' 같은 말만 바뀌는 경우("이번 돈까지 모두 30만 원" → "이번 돈은 30만 원")는 이 검사로 막지 못한다.

## 7. guardian/
### policy.py
- `decide(assessment, txn, helpers: list[Helper], consent: Consent, recent_high_count_30d: int, settings) -> NotifyPlan`:
  - consent.helper_alerts False → notices 없음.
  - 대상 조력자: active, `LEVEL_ORDER[assessment.level] >= LEVEL_ORDER[helper.min_level]`, signal_scope 비었거나 hit 코드와 겹침. **기본 min_level=HIGH → 고위험만** (S22).
  - 이해충돌: txn.counterparty 또는 counterparty_id가 helper.identifiers 중 하나와 같으면(공백 제거·대소문자 무시, 계좌는 숫자만 비교) 그 조력자는 이번 건에서 제외(excluded_conflict), 다른 대상 조력자에게만 알림.
    - [변경 r2] '계좌는 숫자만 비교'를 자유 형식 글에도 적용한다: 값 전체가 아니라 글 안에서 계좌처럼 보이는 조각(숫자·가림표와 그 사이의 공백·하이픈·점)을 찾아, 숫자가 6개 이상이면 계좌 키로 비교한다(가림표 비교 규칙은 그대로). '농협 302-1234-5678-91', '302-1234-5678-91 (농협)', '농협302-…' 모두 같다(양방향). 이유: 전에는 값 전체가 숫자·하이픈일 때만 계좌로 봐, 은행 이름을 붙여 적은 조력자가 거래 상대방이어도 고위험 알림을 받았다(리뷰 재현 5형식 중 4형식).
  - 이해충돌로 알릴 조력자가 하나도 없고 consent.counseling_referral이면 suggest_counseling=True.
  - recent_high_count_30d ≥ settings.high_repeat_for_counseling 이고 consent.counseling_referral → suggest_counseling=True (S23).
  - counseling_orgs = ["지역발달장애인지원센터", "장애인권익옹호기관"] (suggest일 때).
  - HelperNotice.message: "[SafePause] ○○님 거래에서 확인이 필요한 신호가 있어요. 결정은 ○○님이 합니다. 먼저 ○○님과 이야기해 주세요." 형식(당사자 결정 존중).
    - [변경 r1] 부를 이름(person_name)이 없으면 '당사자님' 대신 "[SafePause] 함께 확인이 필요한 거래가 있어요. 결정은 본인이 해요. 먼저 본인과 이야기해 주세요."를 쓴다(⑤ 기록에 그대로 보여 당사자가 읽기 때문).
  - [변경 r1] `ask_helper_plan(..., helper_ids=None)`: '조력자에게 물어볼래요'는 당사자가 카드에서 고른 조력자(helper_ids)에게만 묻는다. helper_ids가 없으면 당사자가 정한 '무엇을 알릴까요?'(signal_scope) 범위 안의 활성 조력자에게 묻는다(직접 요청이므로 자동 알림 등급 min_level은 보지 않음). 거래 상대방인 조력자는 골라도 뺀다. 이유: 전에는 범위와 무관하게 활성 조력자 전원에게 기록해 S37(알림 대상·범위 지정 권한)과 부딪쳤다.
  - [추가 r1] `ask_helper_candidates(assessment, txn, helpers)`: 고르기 전에 카드에 보여 줄 후보(id, name, relation, in_scope, conflict, default).
  - [변경 r3] `Helper.active`는 '자동으로 알리기'다. 끄면 자동 알림(decide)에서만 빠지고, `ask_helper_candidates`·`ask_helper_plan`은
    active와 관계없이 등록한 조력자 모두를 후보로 본다(후보에 `active`를 더함). ⑤의 체크 이름은 "이 조력자에게 자동으로 알리기"와
    설명("끄면 … '조력자에게 물어볼래요'로 고를 때만 알려요"). 후보가 0명이면 "물어볼 수 있는 조력자가 없어요". 이유: 체크를 끄면 물어보기
    후보에서도 사라져 화면이 '등록한 조력자가 없어요'라고 틀리게 말했고, "엄마는 자동 알림 없이 내가 물을 때만"처럼 정할 수 없었다(S37).
  - note_to_person: 쉬운 말 한 줄(예: "엄마에게 알려 드릴게요." / "이번에는 ○○님께 알리지 않았어요.").
    - [변경 r2] 이해충돌로 뺀 조력자가 있으면 까닭을 먼저 쓴다: "엄마는 돈을 받는 사람이에요. 그래서 아빠에게만 알려 드릴게요." `decide(..., preview=True)`(check의 미리 보기)는 아직 한 일이 없으므로 현재형("…알리지 않아요.")을 쓴다.
### outbox.py
- `Outbox(store)`: `send(notice)`는 store.append_notice만 한다. **실제 문자·메일·푸시 발송 없음**(프로토타입). 문서와 UI에 "알림은 기록만 됩니다" 명시.

## 8. eval/
### metrics.py
- `evaluate(persona_keys, seeds, mode, days=120, baseline_days=90) -> dict`: 각 (persona, seed)마다 make_dataset(모든 시나리오 주입) → 처음 baseline_days의 정상 거래로 fit → 이후 모든 거래 assess.
  - 시나리오 탐지율(scenario recall): 시나리오별로, 주입 거래 중 1건 이상이 CAUTION 이상이면 탐지. HIGH 기준 탐지율도 따로.
  - 오탐률: 평가 구간 정상 거래 중 CAUTION 이상 비율, 정상 거래 월평균 알림 수, **정상 거래가 HIGH(조력자 알림 대상)가 된 비율**.
  - 정상 전용 대조군: 같은 seed로 시나리오 없이 생성한 데이터의 월평균 알림 수.
  - 결과 dict는 모드·설정·seed 목록·지표·혼동 요약 포함.
- `evaluate_file(txns, baseline_ratio=0.75) -> dict`: 사용자의 실제 거래내역(정상으로 가정)에 대해 알림 비율(오탐 근사) 계산 — 질의 답변서 권고 사항.
- [추가 r4 · 사전 등록] 경계 변형(subtle) 평가. §3 [추가 r4]와 함께 결과를 보기 전에 적었고, 결과를 본 뒤 바꾸지 않는다.
  - `evaluate(..., intensity="standard")`, `compare_modes(..., intensity="standard")`, `synthetic_case(..., intensity="standard")`.
    `"subtle"`이면 `make_dataset(..., intensity="subtle")`로 만든 데이터를 standard와 같은 절차로 평가한다: 처음 90일 정상 거래로
    학습, 뒤 30일의 모든 거래를 시간순 평가, 같은 seed의 정상 전용 대조군(시나리오 없음, standard와 같은 데이터). 결과 dict에
    `"intensity"`를 담는다(standard도). 지표 정의는 standard와 같다(시나리오 탐지 = 주입 거래 중 1건 이상이 주의 이상/고위험).
  - 등록한 실행: `python -m safepause eval --seeds 20 --intensity subtle --out docs/eval` = seed 1~20 × 인물 3종(worker·benefit·student)
    = 60사례, 모드 fused·rules·anomaly, days 120, baseline_days 90. standard도 같은 설정(`--intensity` 없이)으로 다시 돌린다.
  - 주 지표: 시나리오별·전체의 주의 이상 탐지율과 고위험 탐지율, 평가 구간 정상 거래의 알림률·고위험률(대조군 월평균도 함께).
  - AI 기여 = 결합(fused) − 룰만(rules)의 탐지율 차이(%p). 결합 규칙(§5)상 거래마다 fused 등급 ≥ rules 등급이라 이 차이는 0 이상이다.
    차이가 있으면 이상 점수가 룰 CAUTION을 HIGH로 올렸거나(점수 ≥ 0.90, newness_unknown 제외) 룰 없이 CAUTION을 냈다(출금, 점수 ≥ 0.98)는
    뜻이다. 같은 차이를 정상 거래 알림률·고위험률에도 적는다(AI가 더한 오탐). AI만(anomaly) 모드도 따로 적는다.
  - 기준값은 그대로 둔다: FUSED_ESCALATE_SCORE 0.90, ANOMALY_ALONE_SCORE 0.98, anomaly 모드 CAUTION 0.90·HIGH 0.98, §5 룰 기준 전부.
  - 해석 문장은 결과 수치로 자동으로 만든다. 차이가 0이면 0이라고 쓰고, 좋게 포장하는 말을 넣지 않는다.
- [추가 r5 · 별도 검증 세트] **이 항목은 seed 21~40 평가 결과를 보기 전에 적었다. 결과를 본 뒤 룰 기준(§5 rules.py),
  결합 기준·임계값(engine.py), 모델·특징량(anomaly.py·features.py), 합성 정의(synth.py의 standard·subtle), models.py를 한 글자도
  바꾸지 않는다. 바꾸면 이 검증은 무효다.**
  - 까닭: r1~r3의 룰 보완은 seed 1~20 평가(docs/eval, 특히 시나리오 없는 대조군 60사례의 알림)와 개별 재현(worker seed 2,
    1개월치 은행형 CSV 등)을 보며 했다. 그래서 docs/eval 1~6절(seed 1~20)의 수치는 룰을 맞추는 데 쓴 표본 안(in-sample) 값이다.
    룰을 맞추는 데 쓰지 않은 seed에서도 같은 수준인지 따로 잰다.
  - 검증 세트: seed 21~40(20개) × 인물 3종(worker·benefit·student) = 60사례. 고른 까닭: 룰 보완·경계 변형 설계에 쓰지 않은 seed다.
    SPEC의 영향 기록과 docs/eval은 모두 seed 1~20이고, 앱 ⑥ 평가는 seed 1부터 최대 20까지, 이 항목을 적을 때 테스트의 합성 데이터(synth)는
    seed 0~11만 썼다(tests/test_engine.py의 seed=21은 synth가 아닌 테스트 전용 생성기). r5 테스트도 seed 21~40의 탐지 수치로 무엇을
    맞추지 않는다. 개수를 seed 1~20과 같게 해 나란히 비교한다. 결과를 본 뒤
    seed 범위를 바꾸거나 더하지 않는다. 이 항목을 적는 지금 rules.py·engine.py·anomaly.py·features.py·synth.py의 SHA-256은
    r4 사전 등록 기록(2026-09-30 22:27)과 같다(그 뒤로 룰 쪽 파일은 바뀌지 않았다).
  - 평가: 표준·경계 변형(subtle) 두 강도 모두 seed 1~20과 같은 절차·설정(days 120, baseline_days 90, 처음 90일 정상 거래로 학습,
    모드 fused·rules·anomaly, 같은 seed의 정상 전용 대조군)과 같은 지표 정의로 잰다. 등록한 실행:
    `python -m safepause eval --seeds 20 --seed-start 21 --out docs/eval`, 같은 명령에 `--intensity subtle`.
  - 싣는 지표(두 강도 각각, 모드별): 시나리오 단위 주의 이상·고위험 탐지율, 거래 단위 고위험 재현율, 정상 거래 알림률·고위험률,
    정상 전용 대조군 1인당 월평균 알림(주의 이상)·고위험. seed 1~20(표본 안) 값과 나란히 적고 차이(검증 세트 − 표본 안)를 적는다.
  - 결과가 나빠도(예: 대조군 오탐이 검증 세트에서 더 높아도) 수치 그대로 적고, 룰을 고치지 않는다. 문서(README·model_card)는
    어느 값이 표본 안(seed 1~20, 룰 보완에 사용)이고 어느 값이 검증 세트(seed 21~40)인지 나눠 적는다.
  - API: `default_seeds(n, start=1)` → [start, …, start+n−1] (기존 호출 `default_seeds(n)`은 그대로 [1, …, n]).
### report.py
- `write_report(results: dict, out_dir: Path)`: `eval_results.json` + `eval_report.md`(표). 문구에 "합성 데이터 기준, 실제 피해 데이터 검증 아님"을 명시.
  - [추가 r4] 합성 결과 JSON은 intensity로 이름을 나눈다: standard `eval_results.json`, subtle `eval_results_subtle.json`.
    Markdown은 하나(`eval_report.md`)에 standard 절들과 subtle 절(모드별 시나리오별 주의 이상·고위험 탐지율 표, 정상 거래 알림률 표,
    결합−룰만 차이 표와 문장)을 함께 쓴다. 어느 쪽을 먼저 써도 같은 폴더의 다른 쪽 JSON을 읽어 두 절을 다시 만든다.
    두 결과의 설정(인물·seed·기간·모드)이 다르면 subtle 절에 그 사실을 적는다.
  - [추가 r5] 별도 검증 세트 결과(결과 dict의 `"split": "holdout"`, 명령행 `--seed-start`가 1이 아닐 때)는 JSON 이름을 나눈다:
    standard `eval_results_holdout.json`, subtle `eval_results_subtle_holdout.json`. `eval_report.md`에는 기존 절(1~6절, seed 1~20
    결과 JSON에서 다시 만듦. 수치는 그대로) 뒤에 "7. 별도 검증 세트(seed 21~40)" 절을 더한다: 두 강도 각각 모드별 위 r5 지표 표,
    seed 1~20 값과 나란히 놓은 비교 표(차이 포함), 시나리오별 탐지율, 수치로 자동으로 만든 비교 문장(높으면 높다고 씀).
    검증 세트 seed가 표본 안 seed와 겹치거나 설정이 다르면 그 사실을 적는다. 네 JSON 중 어느 것을 먼저 써도 같은 보고서가 된다.

## 9. cli.py
`python -m safepause <명령>`(개발 환경에서 엔진을 시험·평가할 때 쓰는 명령행):
- `eval [--seeds 20] [--out docs/eval]`: 3개 모드 비교 평가 + 보고서.
  - [변경 r2] 기본 `--out`은 `eval_out`. 제출 보고서 폴더 `docs/eval`에 다른 설정(seed 수·인물·방식 등, 출력 경로 표기는 비교하지 않음)의 결과를 쓰려 하면 거절하고 `--overwrite`로만 허용한다. 이유: 빠른 확인(`--seeds 3`)이 README 수치의 근거인 20-seed 보고서를 경고 없이 덮어썼다.
  - [추가 r4] `--intensity standard|subtle`(기본 standard). subtle이면 `eval_results_subtle.json`을 쓰고, 재현 명령에 `--intensity subtle`을
    붙이며, docs/eval 덮어쓰기 보호도 `eval_results_subtle.json`의 명령과 비교한다. standard의 재현 명령·파일 이름은 그대로다.
  - [추가 r5] `--seed-start N`(기본 1): seeds = range(N, N + --seeds). 1이 아니면 별도 검증 세트로 보고 결과 JSON을
    `eval_results_holdout.json`(standard) / `eval_results_subtle_holdout.json`(subtle)에 쓰고, 재현 명령에 `--seed-start N`을 붙이며,
    docs/eval 덮어쓰기 보호도 그 파일의 명령과 비교한다. 기본값(1)의 재현 명령·파일 이름·결과는 그대로다.

## 10. server/ — FastAPI(자동 시험용 HTTP 틀)
지금(v0.3) 업무 로직은 `safepause/api/service.py`에 있고, 앱(APK)은 이 서버 없이 같은 서비스를 앱 안 파이썬(Pyodide) 브리지
(`safepause/api/bridge.py`)로 부른다. 이 서버는 같은 API를 HTTP로 감싼 틀이며, 자동 시험이 같은 요청에 같은 응답을 주는지 검사할 때
쓴다(`tests/test_api_service.py`의 `test_router_matches_fastapi`). 아래는 v0.1 명세와 수정 기록이다.
엔드포인트(JSON):
- `GET /api/health` → {"status":"ok","version":...,"offline":true}
- `GET/PUT /api/consent`
- `GET/PUT /api/helpers` (리스트 전체 교체)
- `POST /api/data/sample` body {"persona":"worker","seed":1,"scenarios":true} → 거래 저장 후 요약
- `POST /api/data/upload` (multipart CSV) → loader 리포트
- `GET /api/transactions` → 거래 + 평가(level, reasons) 목록 (consent.monitoring False면 403과 한국어 안내)
- `POST /api/safepause/check` body: 보내려는 거래(to/amount/channel/ts 선택) → {"assessment", "card", "notify_plan_preview"}; 저장하지 않음
- `POST /api/safepause/decide` body {"pending":..., "decision":"send|cancel|ask_helper"} → decision 기록, send면 거래 이력에 추가(차단 없음), HIGH이고 동의 있으면 outbox로 조력자 알림 기록, ask_helper면 해당 조력자 알림 기록
  - [변경 r1] body에 선택 `helper_ids`(물어볼 조력자). 응답에 `result_title`, `result_lines`(거래 방법에 맞는 결과 문장), `ts_note`. send는 메모리 사본이 아니라 디스크의 현재 거래 목록에 더해 저장한다.
  - [변경 r1] check 응답에 `ask_helper_preview.candidates`(고르기 전에 누가 알게 되는지)와 `ts_note`('지금 시각'을 골랐는데 날짜가 저장된 거래의 마지막 날로 옮겨지면 그 이유).
  - [변경 r1] check·decide·transactions·cards·eval/file은 동의 확인을 서버 잠금 안에서 한다(동의 철회와 겹치면 철회가 먼저).
  - [변경 r2] decide는 ① 거래 이력(보낼래요) → ② 결정 기록 → ③ 조력자 알림 순서로 쓴다. body의 `pending.id`가 check가 준 연습 거래 id(`live-숫자`)면 그대로 쓰고, 같은 id·같은 결정은 다시 기록하지 않으며 이 거래로 이미 적은 조력자 알림도 다시 적지 않는다(재시도해도 중복 없음). 같은 id를 '안 보낼래요'로 바꾸면 이력에서 뺀다. 이유: 전에는 결정·알림을 먼저 적고 거래 저장이 실패하면 반쪽 기록이 남았고, 다시 시도하면 새 id로 결정·알림이 한 번 더 기록됐다.
  - [변경 r2] 반복 고위험 건수(S23)는 저장된 거래의 고위험(거래 시각 기준 30일)에 결정 기록의 고위험(기록한 실제 시각 at 기준 30일, 이력에 든 거래는 빼고 같은 id는 한 번)을 더한다. '안 보낼래요'·'물어볼래요'로 멈춘 고위험 시도도 센다. 이유: 밤마다 송금을 요구받고 당사자가 매번 멈추는 경우 상담 안내가 끝내 나오지 않았다(리뷰 재현: 6번 연속 cancel HIGH인데 모두 False). 연습 거래 시각은 저장된 거래의 날짜로 옮겨지므로 결정 기록은 실제 시각으로 따로 센다.
  - [변경 r2] ask_helper에서 물어본 조력자가 0명이면 응답 `result_title`·`result_lines`·`message`가 '물어볼 조력자가 없어요'를 말하고 `asked_count`=0을 준다. check 응답의 `ask_helper_preview.candidates`에 `auto`(자동 알림 대상: 체크를 풀 수 없음)를, `ask_helper_preview.counseling_orgs`(물어볼 수 있는 조력자가 없고 상담 동의가 있을 때)를 더한다. 자동 알림 대상이 따로 알림을 받으면 안내 둘째 문장은 그 사람 이름만 쓴다("엄마에게 물어볼게요. 아빠에게도 알려 드릴게요.").
  - [변경 r3] 연습 거래 id는 check마다 새로 준다(`_State.issue_live_id`: 저장된 거래·결정 기록·이미 준 id의 최댓값 + 1). 준 id는 거래 지문
    (받는 사람·계좌·회선·금액·방법·시각)과 묶어 기억한다(최근 1,000개, 지우기·동의 끄기 때 지문은 버리고 번호 최댓값만 남김).
    decide는 body의 id가 (1) check가 준 id면 지문이 같을 때, (2) 저장된 거래의 id면 그 거래와 내용이 같을 때, (3) 어디에도 없는 id(서버를
    다시 켠 뒤)면 그대로 쓴다. 결정 기록에만 있거나 지문이 다르면 새 id를 준다(다른 거래를 바꾸거나 지우지 않고 결정·알림도 따로 기록).
    같은 내용 재시도는 r2처럼 중복 없음. 화면은 decide 응답의 id를 이어 쓴다. 이유(리뷰 재현): 결정 전 check 두 번(탭 두 개)이 같은
    live-00001을 받아, B가 보낸 거래를 A의 '안 보낼래요'가 이력에서 지웠고, A의 고위험 거래를 B의 1만 원 거래가 바꿔 놓아 S23 건수와
    두 번째 조력자 알림이 빠졌다.
- `GET /api/cards` 최근 카드들, `GET /api/notices` 조력자 알림 기록, `GET /api/decisions`
  - [변경 r1] /api/cards는 기록 카드(`render_card(past=True)`)를 준다.
- [추가 r1] `PUT /api/helpers`: 연락처는 가려서 저장한다(전화 010-****-5678, 메일 앞 1~2글자만, 그 밖 7자리 이상 숫자는 끝 4자리만). 발송 기능이 없어 전체 값을 둘 까닭이 없다(최소 수집).
  - [변경 r2] 번호는 숫자만 뽑아 판단한다: 숫자·공백·하이픈·점·괄호·+·대시류가 이어진 구간에 숫자가 7개 이상이면, +82는 0으로 바꿔 국내 번호로 보고 '010-****-5678' 모양으로(그 밖은 끝 4자리만) 가린다. '(010)1234-5678', '+82 10 1234 5678', '010 - 1234 - 5678', '010–1234–5678'이 그대로 저장되던 문제.
  - [변경 r3] 가린 모양(010-****-5678, ***5678) 밖에 숫자가 아직 7개 이상 남으면, 숫자와 글자(한글 음절·영문)·가림표·@가 아닌 모든 문자를
    구분 기호로 보고 다시 가린다('010ㆍ1234ㆍ5678', '010·1234·5678', '010ㅡ1234ㅡ5678', '010/1234/5678', '010_1234_5678', '010~1234~5678',
    '010,1234,5678' → 010-****-5678). 그래도 남으면(글자 사이에 끼운 번호) 끝 4자리만 남긴다. 여러 번호('010-…, 010-…')는 따로 가린다.
- [추가 r1] `POST /api/data/upload`: 5MB까지.
  - [변경 r2] 동의 확인과 저장을 모두 서버 잠금 안에서 한다: 요청 시작 때(본문을 읽기 전) 동의를 확인하고 세대 번호를 적어 두며, 파일을 읽은 뒤 저장 직전에 세대 번호와 동의를 다시 본다. 지우기(`/api/wipe`)·거래 살펴보기 끄기는 세대 번호를 올리므로, 그사이 지우기·동의 끄기가 먼저 끝났으면 저장하지 않고 409("지우기(또는 동의 끄기)가 먼저 처리돼서 이번 거래는 저장하지 않았어요…"). `POST /api/data/sample`도 같은 세대 번호 확인을 한다. 이유: 파일을 읽는 사이 지우기·동의 철회를 하면 '모두 지웠어요'를 본 뒤에 실제 거래가 다시 저장됐다(S37 위반, 리뷰 재현).
- `POST /api/eval/run` {"seeds":5} → 평가 결과 (빠른 버전)
- `POST /api/wipe` → 모든 데이터 삭제
- 서버 시작 시 모델은 저장된 거래의 앞 75%(최소 30건)로 학습, 데이터 변경 시 재학습.
  - [변경 r1] '데이터 변경'에는 서버 밖의 변경도 포함한다: 메모리 스냅샷은 transactions.json의 `Store.signature()`가 바뀌면 버리고 다시 만든다. 동의(거래 살펴보기)를 끄거나 다시 켤 때도 버린다.
  - [변경 r2] 걱정되는 거래를 섞은 합성 데이터(시나리오 라벨이 있는 거래가 하나라도 있음)는 앞 75% 대신 '마지막 SCENARIO_WINDOW_DAYS(30)일 이전' 거래로 학습한다(`server/app.py train_count`, eval.metrics.synthetic_case와 같은 날짜 경계. 마지막 날은 라벨 있는 거래의 마지막 날짜). 라벨은 경계를 정하는 데만 쓴다. 이유: 시나리오가 마지막 30일에 몰려 앞 75% 경계가 시나리오 기간 안으로 들어가, 60사례 중 57사례에서 섞은 거래(합계 423건)를 평소로 배웠고 ②·③·④ 데모가 ⑥ 평가 방식과 달랐다. 실제 거래내역은 앞 75% 그대로(eval/file과 같음). 확인: 60사례 모두 학습 구간에 섞은 거래 0건, 47사례는 평가 기준 기간과 건수까지 같고 나머지는 마지막 날에 거래가 없어 1~4일 앞에서 자른다.
화면: v0.1의 정적 UI(server/static, 탭 ①~⑦)는 v0.3에서 앱 화면(`safepause/web`)으로 바뀌었다. 지금 화면 명세는 [docs/v03_spec.md](docs/v03_spec.md).

## 11. 패키징·실행
- 안드로이드 APK 빌드는 [docs/mobile.md](docs/mobile.md) 4장.
- `pyproject.toml`(setuptools), 콘솔 스크립트 `safepause = safepause.cli:main`, 패키지 데이터(앱 화면 파일) 포함.
- `requirements.txt` (런타임 고정 범위).
- 개발 환경 시험: `python -m pytest -q`. 평가 수치 다시 계산은 §8의 `python -m safepause eval` 명령, 제출 수치와 같은지 확인은
  `python tools/check_eval_unchanged.py`(seed 21~40 평가를 다시 돌려 docs/eval 원자료와 비교).
- `.github/workflows/test.yml`(pytest).
  - [변경 r2] job의 `defaults.run.shell: bash`: Windows 러너 기본 셸(pwsh)은 여러 줄 run에서 마지막 명령의 종료 코드만 봐, demo·eval이 실패해도 단계가 통과했다.

## 12. 문서
- `README.md`: 심사위원용 안내(APK 설치·체험), 기능↔제안서 대응표, 개인정보·오프라인 원칙, 한계.
- `docs/architecture.md`, `docs/mobile.md`(안드로이드 앱·APK 빌드), `docs/model_card.md`(IsolationForest 설명·한계), `docs/dataset_card.md`(합성 데이터 가정 전부), `docs/eval/eval_report.md`(실측).
- **문서의 모든 성능 수치는 실제 `python -m safepause eval` 결과 파일에서 가져온다. 추정·예상 수치 금지.**
- [변경 r3] model_card·eval_report의 'AI 단독으로 조력자 알림을 만들지 않음'은 기본 설정(꼭 확인할 때만) 기준임을 적는다. 당사자가 조력자 설정에서
  '확인할 때도'·'모든 것'을 고르면 AI만 걱정한 '확인해요' 거래도 알린다(리뷰 재현: worker seed2, 김*호 30만 원 새벽 2시, rule_hits 없음·
  anomaly 0.98 → caution → 알림 1건).
