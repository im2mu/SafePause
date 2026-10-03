# SafePause v0.3 화면 개편 설계서 (2026-10-02)

이 문서는 v0.3 구현 기준이다. 구현 담당(백엔드·안드로이드·화면 기반·화면별)은 이 문서를 먼저 읽고, 자기 담당 파일만 고친다.

## 0. 제품 정체성 (가장 중요)

- SafePause는 **은행 앱이 아니다.** 발달장애인의 **경제적 착취를 알아차리게 돕는 앱**이다.
- **[2026-10-02 바뀜] 돈 보내기는 `docs/v03_spec_money.md`가 기준이다.** 보내기 탭은 돈 보내기 | 알림 보내기 두 탭이다.
  SafePause는 돈을 직접 옮기지 않는다. 받는 사람·금액을 AI 확인 카드로 먼저 살펴보고, 본인이 정하면 본인이 고른 은행 앱을 연다.
  아래 목록(송금 기능 없음)은 첫 설계 기록으로 남긴다. check·decide·payees는 돈 보내기 화면(money.js)이 다시 부르고,
  연습이라는 말과 연습 화면 띠는 쓰지 않는다.
- (첫 설계, 위 문서로 바뀜) **송금·결제 기능은 없다.** 그래서 다음을 화면에서 모두 없앤다.
  - '돈 보내기 연습'(check/decide 흐름)
  - '연습 화면이에요. 실제로 돈이 나가지 않아요.' 띠
  - '돈 보내기 전에 확인하기' 버튼
  - '최근에 보낸 사람' 자동완성
  - 파이썬 API `/api/safepause/check`·`/decide`·`/api/payees`는 남겨 두되(평가·테스트용) 화면에서는 부르지 않는다.
- 핵심 흐름은 다음 순서다.
  1. 거래 불러오기(은행·카드 연결 자리, 파일, 연습용 거래)
  2. AI가 걱정되는 거래를 찾음
  3. 쉬운 말·그림 카드로 알림
  4. 본인이 조력자·상담하는 곳에 알림 보내기(문자·메일 앱)
- 톤: **토스**(한 화면 한 가지 일, 큰 글씨, 단순한 카드)에 **뱅크샐러드**(내 돈 흐름을 숫자·차트로 보여 주는 분석)를 더한다.

## 1. 요구사항 목록 (검증 기준, 빠짐없이)

| ID | 요구 | 구현 위치 |
|---|---|---|
| R1 | 토스의 단순함 + 뱅크샐러드의 데이터 분석 톤 | 홈 대시보드(차트), 내 거래 요약, 공통 디자인 토큰 |
| R2 | 왼쪽 위 '안전 정지' → `SafePause` 영문 표기 | main.js 머리글(로고 + 글자) |
| R25 | 휴대폰 홈 화면 아이콘 이름도 `SafePause` | android/res/values/strings.xml app_name |
| R3 | '무엇을 알릴까요'의 그림을 단순한 벡터 선 아이콘으로 교체 | icons.js 새 선 아이콘, labels.js SIGNAL_ICON, helpers.js |
| R4 | 소리 버튼 토글: 누르면 재생, 다시 누르면 정지(상태 관리) | speech.js, components.speakButton, 안드로이드 TTS 끝남 알림 |
| R5 | 내 거래에 [은행 거래내역 불러오기] 영역(자리표시) | txns.js |
| R23 | 은행뿐 아니라 [카드 결제내역 불러오기] 연동 영역 | txns.js, 전체 탭 '거래 연결' |
| R6 | 상용화에 필요한 기능 영역을 미구현이라도 모두 배치 | 전체 탭(준비 중 배지 + 안내 시트) |
| R7 | '열 이름 직접 알려 주기' 삭제, 올릴 수 있는 확장자를 명확히 표기 | txns.js 파일 올리기 시트 |
| R8 | 보내기 탭 = 조력자·상담하는 곳에 알림 보내기(연락처·이메일), 알림 탭과 연동 | notify.js(경로 send), alerts.js |
| R9 | 내 거래에서 거래를 누르면 바텀시트에서 바로 '알림 목록에 담기' | txns.js 거래 시트, /api/flags |
| R10 | 전체 탭 '내 데이터' 삭제·구조 단순화 | 모두 지우기는 동의 화면 맨 아래로, 내보내기는 보호자·심사용 '결과 내보내기'로 |
| R11 | 상담하는 곳을 사용자가 직접 추가·지정 | counselors.js, /api/counselors |
| R24 | 휴대폰 연락처에서 번호·메일 불러오기 | native.js pickContact, 안드로이드 연락처 고르기(권한 없음) |
| R12 | 거래 표시의 '~보내기'를 현상 명사형으로 | labels.js SIGNAL_KO |
| R13 | '연습용 정답' 표기 삭제 | components.txnRow |
| R14 | 작위적 따옴표 삭제('내 데이터'에서 → 내 데이터에서) | 모든 화면 문구 + 파이썬 사용자 문구 |
| R15 | 새 조력자 '(가려서 저장해요)' 삭제 | helpers.js |
| R16 | "SafePause는 막지 않아요…", "AI 혼자서는 정하지 않아요…" 등 불필요 문구 삭제 | 전 화면 |
| R17 | '보내지 않고 멈춘 것도 (함께) 세어요' 삭제 | consent.js |
| R18 | 설명 글은 한 문장에 한 줄씩 | ui.h()의 p 문장 나누기 + CSS |
| R19 | 접속 환경 감지: 휴대폰은 "이 휴대폰 안에서만", PC는 "이 컴퓨터 안에서만", 127.0.0.1 노출 금지 | format.deviceWord() |
| R20 | "상담하는 곳을 알려 줘요" → "상담하는 곳에 알려 줘요" | consent.js 등 |
| R21 | 금액 중복 표기 제거(50,000원 5만원 → 50,000원) | txnRow 등 목록 |
| R22 | (바뀜) 돈 보내기 = 확인 후 내 은행 앱 열기, 직접 이체 없음(`docs/v03_spec_money.md`) | send.js·money.js·bankapp.js, 안드로이드 listApps·openApp |
| R26 | 성과보고서를 APK 기준으로 수정 | 별도 단계(보고서 파이프라인) |

## 2. 정보 구조와 경로

아래 탭 5개는 다음과 같다.

| 탭 | 경로 | 제목 | 역할 |
|---|---|---|---|
| 홈 | `#/home` | (머리글 SafePause) | 상태·이번 달 돈 흐름 분석(차트)·걱정되는 거래 요약·바로가기 |
| 내 거래 | `#/txns` | 내 거래 | 거래 불러오기(은행·카드 연결 자리, 파일, 연습용)·목록·거래 바텀시트(담기·알리기) |
| 보내기 | `#/send` | 보내기 | 위 탭 돈 보내기(기본, `docs/v03_spec_money.md`) \| 알림 보내기(`?mode=notify`, `?txn=`·`?to=`가 있어도): 무엇을(거래) → 누구에게(조력자·상담하는 곳) → 어떻게(문자·메일) → 글 확인 → 앱 열기 |
| 알림 | `#/alerts` | 알림 | 걱정되는 거래(쉬운 말 카드) · 담은 거래 · 보낸 알림 |
| 전체 | `#/more` | 전체 | 설정·연결·보호자·심사용·도움말(준비 중 포함) |

하위 경로는 다음과 같다.

- `#/more/consent`: 동의, 누가 동의했나요, **모두 지우기(맨 아래)**
- `#/more/helpers`: 조력자
- `#/more/counselors`: 상담하는 곳 (새로 만듦)
- `#/more/settings`: 앱 설정
  - 글자 크기(실제 동작: 보통·크게·아주 크게)
  - 화면 밝기 모드(실제 동작: 자동·밝게·어둡게)
  - 휴대폰 알림 받기(준비 중), 앱 잠금(준비 중)
- `#/more/eval`: AI 성능 확인(보호자·심사용, 그대로)
- `#/more/export`: 결과 내보내기(보호자·심사용: 현장 검증용 요약 파일, 분석 결과 표 파일)
- `#/more/about`: AI와 데이터 설명(문구 정리)
- `#/onboarding`: 첫 실행 3단계

경로 파라미터는 `#/send?txn=<id>`, `#/send?to=counselors`처럼 붙인다. main.js는 `?` 뒤를 `ctx.params`(URLSearchParams)로 넘긴다.

옛 경로는 다음으로 옮긴다: `more/data` → `more/consent`, `more/notices` → `alerts?tab=sent`.

## 3. 백엔드 API 계약 (서비스·안드로이드 router·FastAPI 세 곳 같게, 파리티 테스트)

모든 오류 문구는 쉬운 한국어로 쓴다. 따옴표로 낱말을 감싸지 않는다.

### 3.1 조력자 연락처 원본 저장

- `Helper`에 `phone: str = ""`, `email: str = ""`를 더한다.
  - 원본은 이 기기에만 저장한다. 문자·메일 앱을 열려면 원본이 필요하다.
- 옛 `contact`는 읽을 때만 바꾼다: `@`가 있으면 email, 없으면 phone. 이미 가려진 값이면 그대로 둔다.
- `HelperIn`
  - `phone`(0~20자, 숫자·+·-·공백·괄호만)과 `email`(0~80자, 간단한 형식 검사)을 받는다.
  - `contact`는 옛 클라이언트용으로 받고 위 규칙으로 나눈다.
- `GET /api/helpers` 응답 항목: `id, name, relation, phone, email, phone_masked, email_masked, identifiers, min_level, signal_scope, active`
  - `contact`는 가린 표시용으로 남긴다.
- 내보내기 파일(검증 요약·분석 결과 표)과 알림 기록에는 번호·메일 원본을 넣지 않는다.

### 3.2 상담하는 곳

- 모델 `Counselor {id, name, kind, phone, email, memo, active}`
  - kind는 `disability_center | rights_agency | police | finance | other` 중 하나다.
- 저장 파일은 `counselors.json`이다. 모두 지우기에서 같이 지운다.
- `GET /api/counselors` → `{"items": [...], "presets": [...]}`
- `PUT /api/counselors` (목록 전체 저장, 조력자와 같은 방식) → `{"items": [...]}`
- 이름 1~30자, 메모 0~100자, 최대 20곳. 검증은 HelperIn과 같은 스타일로 한다.
- presets(`safepause/api/constants.py`, 확인된 번호만)

| kind | 이름 | 전화 | 출처 |
|---|---|---|---|
| rights_agency | 장애인권익옹호기관 (장애인학대 신고) | 1644-8295 | 중앙장애인권익옹호기관 naapd.or.kr/abuse/report: 전국 공통, 전화·문자·카카오톡 |
| finance | 금융감독원 불법금융 신고 | 1332 | 금융감독원 fss.or.kr 서민금융1332 |
| police | 경찰 (금융사기 신고) | 112 | 국번 없이 |
| disability_center | 지역발달장애인지원센터 | (빈칸: 지역마다 달라 사용자가 적음) | — |

- 상담 안내(동의 시 30일 고위험 3건): 기존 기관 이름 목록 대신, 사용 중인 상담하는 곳 이름을 쓴다. 없으면 기존 기본 2곳 이름을 쓴다.

### 3.3 담은 거래 (알림 목록에 담기)

- 저장 파일 `flags.json`, 형식 `[{txn_id, created_at}]`
  - 모두 지우기에서 같이 지운다.
  - 거래를 통째로 바꿀 때(연습용 거래·파일 올리기) 비운다.
- `GET /api/flags` → `{"items": [{"txn_id", "created_at", "item": <거래 항목(_item 형식)>}]}` (최근 담은 것부터)
  - 거래 살펴보기 동의가 필요하다(transactions와 같음).
  - 사라진 거래는 뺀다.
- `POST /api/flags {"txn_id"}` → `{"ok": true, "count": n}`
  - 없는 거래는 404 "그 거래를 찾지 못했어요."
  - 이미 담겨 있으면 그대로 둔다.
- `POST /api/flags/remove {"txn_id"}` → `{"ok": true, "count": n}`
- `GET /api/transactions` 항목에 `"flagged": bool`을 더한다.

### 3.4 보낸 알림 기록

- `POST /api/notices/record` 요청 본문
  - `channel`: `sms|email|call|copy`
  - `recipients`: `[{kind: "helper"|"counselor", id, name}]`, 1~10개
  - `txn_ids`: 0~20개
  - `message`: 1~1000자
  - 응답은 기록 1건 `{id, kind: "manual", channel, recipients: [{kind, name}], txn_ids, message, created_at}`이다.
  - 번호·메일 원본은 저장하지 않는다.
- `GET /api/notices` → `{"items": [...자동 기록(kind "auto") + 직접 보낸 기록(kind "manual"), 최근 것부터], "delivery_note": ...}`
  - 자동 기록의 기존 형식은 유지하고 `kind: "auto"`만 더한다.
  - delivery_note는 "이 기기에 적어 둔 기록이에요. 실제로 보냈는지는 문자·메일 앱에서 확인해 주세요."
- 직접 보낸 기록은 `notices.json`에 같이 저장한다. 모두 지우기에서 지운다.

### 3.5 돈 흐름 분석 (뱅크샐러드 톤)

- `GET /api/insights`. 거래 살펴보기 동의가 필요하다.
- 기준 달은 **저장된 마지막 거래가 있는 달**이다(합성 데이터는 과거라서).
- 응답 형식

```json
{
  "as_of": "2026-06-29",
  "months": [{"month": "2026-03", "out_total": 0, "in_total": 0, "out_count": 0, "flagged": {"caution": 0, "high": 0}}],
  "this_month": {"month": "2026-06", "out_total": 0, "in_total": 0, "out_count": 0, "flagged": {"caution": 0, "high": 0}},
  "prev_month": null,
  "channels": [{"channel": "transfer", "out_total": 0, "out_count": 0, "share": 0.0}],
  "time_bands": [{"band": "dawn", "hours": "0-6", "flagged": 0, "out_count": 0}],
  "top_payees": [{"name": "김*호", "out_total": 0, "out_count": 0, "flagged": 0}],
  "flagged_total": {"caution": 0, "high": 0}
}
```

- 각 항목의 뜻
  - `months`: 최근 6달까지(시간 순)
  - `channels`: 나간 돈만, 금액 큰 순. share는 0~1, 소수 셋째 자리
  - `time_bands`: `dawn 0-6, morning 6-12, day 12-18, evening 18-24`
  - `top_payees`: 계좌 이체·카드 결제의 나간 돈 기준 상위 3
- 거래가 없으면 months와 channels는 빈 목록이다.

### 3.6 기타

- 버전은 0.3.0이다(`safepause/__init__.py`, `pyproject.toml`, build_apk 기본값 3 / "0.3.0").
- 파이썬 사용자 문구에서 작위적 따옴표를 뺀다(R14).
  - 대상: constants.py, explain/easy_card.py, guardian/*.py, api/service.py의 한국어 문구
  - 예: `'동의' 화면에서` → `동의 화면에서`
- 상담 동의 이름을 "상담하는 곳에 알려 주기"로 바꾼다. 관련 문구는 "상담하는 곳에 알려 줘요."
- 탐지 로직·평가 수치는 바꾸지 않는다. `python tools/check_eval_unchanged.py`가 차이 0이어야 한다.

### 3.7 2026-10-03 수정(적대적 검증 145건, `docs/v03_fixplan.md`)으로 더하고 바꾼 것

결정과 까닭은 fixplan 1절이 원본이다. 여기에는 구현된 계약만 적는다(서비스·router·FastAPI 같음, `tests/test_v03_fixplan.py` 파리티 시험).

- **새 저장 파일 `reviews.json`** `[{txn_id, status: "ok", created_at}]`(내가 한 거예요). `store.STORE_FILES`·모두 지우기·packaging `PRIVATE_FILE_NAMES`·`.gitignore`에 들어 있다. 거래를 통째로 바꾸면 비우고, 이어 붙이기에서는 그대로 둔다.
- **새 API**
  - `POST /api/reviews {txn_id}` → `{ok, count}`. 거래 살펴보기 동의가 필요하고, 없는 거래는 404 "그 거래를 찾지 못했어요."
  - `POST /api/reviews/remove {txn_id}` → `{ok, count}`(동의 없이 됨)
  - `POST /api/notices/remove {id}` → `{ok, count}`. 직접 보낸 기록(kind manual)만 지운다. 자동 기록이나 없는 id는 404 "그 알림 기록을 찾지 못했어요."
  - `POST /api/transactions/remove-checked {txn_id}` → `{ok, count(남은 거래 수)}`. 보내기 전 확인 기록(`live-…`)만 지우고 관련 담음·확인 표시도 정리한다. 그 밖의 id는 400 "보내기 전 확인 기록만 지울 수 있어요.", 없으면 404
  - `GET /api/export/summary` → `{filename: "safepause-summary-YYYYMMDD.txt", mime: "text/plain", text, note}`. 조력자·기관용 한 장 요약이고 이름·계좌는 넣지 않는다.
- **바뀐 API**
  - `POST /api/notify/suggest {txn_ids, pending?}`: `pending`(check 응답의 pending 모양)이면 저장하지 않은 확인 거래도 이해충돌·등급을 본다. 이해충돌은 나간 돈의 받는 사람만 본다. 알릴 조력자가 모두 돈 받은 사람이고 상담하는 곳 동의가 있으면 상담하는 곳을 추천한다. 응답에 `counseling_reason: "repeat"|"conflict"|""`를 더했다.
  - `POST /api/data/upload`: 본문 `mode: "replace"(기본)|"append"`(PC는 multipart 칸, 앱 엔진은 본문). append는 같은 거래(시각·금액·방향·방법·상대 정규화)를 한 번만 둔다. 응답에 `mode, added, duplicates, levels, ai_only`. 틀린 mode는 422 "입력한 값을 확인해 주세요: 올리는 방법"
  - `.xlsx`: 표준 라이브러리(zipfile·xml.etree)만으로 첫 시트를 읽는다(`safepause/data/xlsx.py`). 압축 해제 합계 30MB, 파일 5,000개, 10만 줄, 256칸 상한, DTD 거부. 앱 엔진(Pyodide)에서도 같다.
  - `.xls`(2026-10-03): 엑셀 97~2003(BIFF8)은 첫 워크시트를 읽고(`safepause/data/xls.py`), 확장자만 .xls인 HTML 표는 날짜·금액 머리글이 있는 첫 표를 읽는다(`safepause/data/htmltable.py`). 암호가 걸린 엑셀(.xls·암호로 감싼 .xlsx)·엑셀 95 이전·한글/워드 문서는 안내만 한다. 표 전체 300만 칸 상한(.xlsx에도).
  - `GET /api/insights`: 보내기 전 확인 기록(live)을 모든 수치에서 빼고 `checked_excluded`로 그 수를 알린다. `compare: {month, days, prev_days, prev_same_period_out, prev_same_period_count}`(지난달 같은 날짜 범위, 지난달을 다 모르면 null)를 더했다.
  - `GET /api/transactions?level&limit&offset&q&since&until`: 이름 검색과 기간. 최상위에 `open_summary`(내가 확인한 것을 뺀 등급별 수)·`reviewed_count`. `GET /api/cards`에 `open`·`reviewed`
  - 거래·카드·담은 거래 항목: `reviewed: bool`, `notified_at`(직접 보낸 기록 가운데 그 거래가 든 가장 최근 시각 또는 null), `ai: {fitted, percentile(0~100 또는 null), top_feature(쉬운 말 한 줄 또는 null), only_ai, raised}`. check 응답에도 `ai`
  - `POST /api/data/sample`: 기본값이 가상 근로자·번호 10이다(AI만 먼저 찾은 거래가 1건 있는 조합). 응답에 `levels`·`ai_only`
  - `POST /api/notices/record`의 `recipients`에 저장된 조력자·상담하는 곳 `id`를 함께 적는다(다시 보내기용, 모르는 받는 사람은 빈 글)
  - 자동 기록(kind auto)은 조력자 이름의 번호를 가리고, 글에서 결정 문장을 뺀다. 화면은 이것을 적어 둔 기록(아직 안 보냄)으로 나눠 보인다.
  - 조력자 PUT: 옛 가린 연락처만 있는 조력자는 phone·email을 비워 보내도 보존한다. 지우려면 그 항목에 `clear_contact: true`
- **보내기 전 확인 기록의 시각**: 저장된 실제 거래의 마지막 시각이 45일 안이면 지금, 더 오래됐으면(합성 데이터) 마지막 실제 거래 날짜에 고른 시각을 붙인다. 그 시각이 마지막 실제 거래보다 이르면 다음 날이다(확인 기록이 실제 거래 사이에 끼지 않게). 여러 번 확인해도 날짜가 더 밀리지 않는다. 이때만 `ts_note`를 준다.
- **문구**: `delivery_note`는 "알림은 기록만 해요. 문자나 메일은 알림 보내기에서 보낼 수 있어요."(장소 말 없음). 미리 보기는 "…에게 알릴 수 있어요.", 결정 뒤는 "…에게 알릴 수 있게 적어 두었어요.", 물어볼래요는 "…에게 물어봐요."이다. 보냈다고 약속하는 글은 쓰지 않는다. 보낸 알림 탭의 `GET /api/notices` delivery_note는 3.4의 고정 문구 그대로다.
- **앱 엔진**: 위 새 API 가운데 reviews·reviews/remove·notices/remove·transactions/remove-checked는 AI 패키지 없이 처리돼 worker.mjs BASIC에 넣었다(AI 준비 전·AI 부분 실패 때도 됨). suggest·upload·sample·export/summary는 AI 준비 뒤에 처리한다.

## 4. 안드로이드 계약 (`android/`)

- `res/values/strings.xml` app_name을 `SafePause`로 바꾼다. 런처 이름이 바뀐다.
- 새 권한은 **0개**다. 연락처 고르기는 시스템 선택 창이 고른 한 건만 넘겨주므로 READ_CONTACTS가 필요 없다. 전화는 걸지 않고 다이얼 화면만 연다.
- `NativeBridge` 추가

| JS 이름 | 동작 |
|---|---|
| `openExternal(uri)` | `sms:`·`smsto:`·`mailto:`·`tel:`만 허용한다. sms·smsto는 ACTION_SENDTO(+ `sms_body`, uri의 `?body=`에서 꺼냄), mailto는 ACTION_SENDTO(+ EXTRA_SUBJECT·EXTRA_TEXT), tel은 ACTION_DIAL을 쓴다. UI 스레드에서 실행하고, 시작하면 true, 앱이 없으면 false |
| `pickContact(kind)` | kind는 `phone`·`email`이다. ACTION_PICK(Phone.CONTENT_URI / Email.CONTENT_URI) 결과에서 이름·번호(메일)를 읽어 `window.__safepauseContactPicked({kind, name, value})`를 부른다. 취소 시 `{kind, cancelled: true}`를 넘긴다. 문자열은 JSONObject로 안전하게 만든다 |
| `speak(text)` (기존) | 발화 id를 붙인다. UtteranceProgressListener의 onDone·onError·onStop에서 `window.__safepauseSpeechDone()`을 UI 스레드로 부른다 |
| `capabilities()` | `{"external":true,"contacts":true,"tts":<준비 여부>}` JSON 문자열(돈 보내기 뒤 `"apps":true`도 있음) |
| `listApps()`·`openApp(pkg)` | 내 은행 앱 고르기·열기(`docs/v03_spec_money.md` 안드로이드 절). Manifest queries에 MAIN·LAUNCHER, 권한 0개 그대로 |

- WebView에서 `sms:`·`mailto:`·`tel:` 링크를 누르면 openExternal로 넘긴다. 그 밖의 외부 주소는 지금처럼 막는다.
- Manifest `<queries>`에 SENDTO(sms, mailto)·DIAL(tel)·PICK(연락처) intent를 더한다.
- 빌드 확인: `build_apk.py --debug`로 javac·d8·서명이 통과해야 한다.

## 5. 화면 공통 기반 (화면 기반 담당)

- `index.html`: `css/views/{home,txns,notify,more}.css` 링크를 더한다(빈 파일은 담당이 채움). CSP는 바꾸지 않는다.
- `main.js`
  - 경로표(2절), `ctx.params`, 옛 경로 옮기기
  - 머리글: 뿌리 화면(홈)에 SafePause 로고(아이콘 + 영문 글자)
  - 글자 크기·밝기 모드 설정을 시작할 때 적용한다(localStorage, try/catch)
  - 아래 탭 이름: 홈·내 거래·보내기·알림·전체
- `native.js`(새로 만듦)
  - `capabilities()`
  - `openExternal(uri)`: 앱이면 브리지, PC면 mailto·tel은 location, sms는 false
  - `pickContact(kind)` → `Promise<{name, value}|null>`: 앱이면 브리지, 브라우저에 `navigator.contacts`가 있으면 그것, 없으면 null
  - `canPickContact()`, `copyText(text)`
- `format.js`
  - `deviceWord()`: 앱(엔진 모드)이나 휴대폰 브라우저면 "이 휴대폰", 아니면 "이 컴퓨터"
  - `moneyText(n)` = "50,000원"(쉼표 원 단위 하나만)
- `ui.js`
  - `h("p", {text})`는 문장 끝(요. 다. 니다. ? !) 뒤에서 나눠 `span.sent`(display:block)로 한 줄씩 넣는다. `data-nosplit`이면 나누지 않는다.
  - `comingSoonSheet({icon, title, lines, steps?})`: 준비 중 기능 안내 시트. 배지 "준비 중"과 고정 문장 "정식 버전에서 열려요."를 쓴다.
- `components.js`
  - `speakButton` 토글: aria-pressed, 글자 '소리로 듣기' ↔ '멈추기', 아이콘을 바꾼다. 하나가 재생되면 다른 버튼은 원래대로 돌아간다. 끝나면 원래대로 돌아간다.
  - `txnRow`
    - 금액 한 번만 표기(`-50,000원`, 들어온 돈은 `+`)
    - 표시는 등급 + 명사형 신호
    - '연습용 정답' 없음
    - 담은 거래면 '담음' 배지
  - `soonBadge()`
- `speech.js`: 상태 관리(`speak(text, {onEnd})`, `stop()`, `isSpeaking()`). 네이티브 끝남 콜백과 Web Speech onend를 쓴다.
- `labels.js`
  - SIGNAL_KO(명사형)

| 코드 | 이름표 |
|---|---|
| night_repeat_transfer | 밤 시간 잦은 이체 |
| payee_surge | 한 사람에게 송금 집중 |
| micropay_surge | 휴대폰 소액결제 급증 |
| new_merchant_high_value | 처음 가는 곳 큰 금액 결제 |
| multi_line_telecom | 휴대폰 요금 여러 회선 |

  - SIGNAL_KO_NEUTRAL: `new_merchant_high_value: "큰 금액 결제"`
  - SIGNAL_ICON을 새 선 아이콘으로 바꾼다. 송금 연습용 내보내기(EXAMPLES, PRACTICE_NOTE, DONE_KO, DECISION…)는 화면에서 안 쓰면 지운다.
- `icons.js` UI 선 아이콘 추가(24 viewBox, stroke currentColor, 굵기 2, 둥근 끝)
  - 신호용: `sig-night`, `sig-person`, `sig-phone-pay`, `sig-store`, `sig-sim`
  - 기능용: `bank`, `card`, `contacts`, `mail`, `chat`, `call`, `bookmark`, `bookmark-fill`, `chart`, `building`, `text-size`, `moon-sun`, `lock`, `bell`, `help`, `doc`, `link`, `shield`, `headset`, `info`, `copy`, `edit`
- `css/app.css`
  - 토큰을 정리한다: 차트 색 5개(밝게·어둡게 모두 대비 3:1 이상), 카드 그림자, 섹션 제목
  - 추가 규칙: `.sent{display:block}`, `.soon` 배지, 탭(segmented), 바텀시트 손잡이, 차트 기본(`.chart`, `.bar`, `.legend`)
  - 글자 크기 설정: `html[data-font="l"]{font-size:140%}`, `html[data-font="xl"]{font-size:160%}`
  - 밝기 모드: `:root[data-theme]` 활용
  - **모든 글자 1rem 이상, px 글자 크기 금지, 터치 2.4rem 이상, 인라인 style 속성 금지(CSSOM `el.style.cssText`만), innerHTML 금지, 외부 URL 금지**

## 6. 화면별 명세 (화면 담당)

### 6.1 홈 (home.js, css/views/home.css, js/charts.js)

- 상태 카드: 거래 살펴보기 켜짐·꺼짐, "꼭 확인할 거래가 N건 있어요" → 알림 탭
- 이번 달(기준 달) 요약
  - 나간 돈 합계
  - 지난달보다 늘었는지·줄었는지(▲▼ 금액, 쉬운 말: "지난달보다 3만 원 더 썼어요")
  - 거래 수, 걱정되는 거래 수
- 차트(SVG 직접 그림, 외부 라이브러리 없음)
  - 월별 나간 돈 막대 6개. 걱정 거래가 있는 달은 점 표시
  - 어디에 썼나요: 결제 방법별 가로 비율 막대 + 범례 목록(금액·%)
  - 언제 걱정되는 거래가 있었나요: 시간대 4칸 막대
  - 많이 보낸 곳 TOP 3
- 바로가기: 거래 불러오기, 알림 보내기, 조력자, 상담하는 곳
- 모든 차트에 글로 된 요약(aria-label 또는 숨긴 표)을 둔다. 쉬운 말을 쓰고 '통계·패턴' 같은 금지어를 쓰지 않는다.
- 동의가 꺼져 있거나 거래가 없으면 빈 상태 안내 + 버튼을 보인다.

### 6.2 내 거래 (txns.js, css/views/txns.css)

- 요약 카드: 저장된 거래 N건, 기간
- '거래 불러오기' 4칸
  - 은행 거래내역 불러오기(준비 중) → 시트
    - 단계: 1 은행 고르기 → 2 본인 확인 → 3 가져올 기간(3·6·12개월). 모두 비활성
    - '연결하기(준비 중)' 비활성 버튼
    - 실제 은행 이름·로고는 쓰지 않는다. 일반 아이콘과 "은행 1", "은행 2" 같은 자리표시도 쓰지 않는다. 대신 "마이데이터로 내 계좌를 연결해요" 설명과 단계만 보인다.
  - 카드 결제내역 불러오기(준비 중) → 같은 형식의 시트(카드사 고르기)
  - 파일 올리기(동작)
  - 연습용 거래 불러오기(동작)
- 파일 올리기 시트
  - '열 이름 직접 알려 주기' 삭제
  - "지금 올릴 수 있는 파일" 칩: `.csv` `.txt` `.xls` `.xlsx`(엑셀은 2026-10-03까지 차례로 열림)
  - "준비 중" 비활성 칩: `.pdf` `.jpg` `.png`
  - 파일 고르기 accept에 .txt를 더한다.
  - 필수 문장 "은행 파일 모양은 따로 확인하지 못했어요."는 유지한다.
- 걸러 보기 칩: 전체 / 걱정되는 것 / 꼭 확인할 것 / 담은 거래
- 거래 바텀시트(누르면 열림)
  - 상대·시각·방법·금액(한 번만), 등급·이유(명사형 + 쉬운 말 한 줄)
  - [알림 목록에 담기]·[담기 취소] 토글(POST /api/flags, /remove). 담으면 토스트 "알림 탭에 담았어요."
  - [조력자·상담하는 곳에 알리기] → `#/send?txn=<id>`
  - [닫기]
- 거래를 바꾸기 전 확인 시트, 연습용 거래 시트는 기존 동작을 유지한다(문구만 정리).

### 6.3 보내기 탭의 알림 보내기 (views/notify.js, 경로 `send?mode=notify`, css/views/notify.css)

[2026-10-02 바뀜] 보내기 탭은 views/send.js가 위 탭 두 개(돈 보내기 | 알림 보내기)를 그린다. 돈 보내기는 `docs/v03_spec_money.md`, 알림 보내기는 아래와 같다.
알림 보내기는 거래를 고르면 `POST /api/notify/suggest`로 받는 사람을 추천받고, 돈을 받은 조력자는 체크를 풀고 경고한다(money 문서).

1. **무엇을 알릴까요?**
   - 고른 거래 카드(params.txn이면 미리 고름) + [거래 고르기] 시트(꼭 확인·걱정·담은 거래 체크)
   - "거래 없이 직접 적기"도 된다.
2. **누구에게 알릴까요?**
   - 조력자 목록 + 상담하는 곳 목록을 체크한다. 번호·메일이 있는지 아이콘으로 보인다.
   - 비어 있으면 [조력자 정하기]·[상담하는 곳 정하기] 버튼을 보인다.
   - params.to=counselors면 상담하는 곳을 펼쳐 둔다.
3. **어떻게 보낼까요?**
   - 문자 / 메일 / 전화(상담하는 곳 1곳일 때)
   - 고른 사람에게 그 연락처가 없으면 비활성 + 이유를 보인다.
4. **보낼 글**
   - 자동으로 채운 쉬운 글(수정 가능 textarea), 예: "[SafePause] 걱정되는 거래가 있어 알려요. 6월 27일 새벽 4시 41분, 김*호, 계좌 이체 360,000원. 밤 시간 잦은 이체. 확인해 주세요."
5. **[문자 앱 열기] / [메일 앱 열기] / [전화 걸기 화면 열기]**
   - native.openExternal을 부른다.
   - 성공하면 POST /api/notices/record → 토스트 → 알림 탭 '보낸 알림'
   - 실패하면 "이 휴대폰에서 문자 앱을 열지 못했어요." + [글 복사하기]를 보인다.
- 필수 문장: "보내기 버튼은 문자·메일 앱에서 직접 눌러요."
- PC에서는 문자 비활성 + "문자는 휴대폰 앱에서 보낼 수 있어요." 메일은 mailto로 연다.
- spellcheck·autocorrect·autocapitalize를 끈다(textarea 포함).

### 6.4 알림 (alerts.js, css/views/notify.css 공유)

- 탭(segmented, params.tab): 걱정되는 거래 / 담은 거래 / 보낸 알림
- **걱정되는 거래**: /api/cards의 쉬운 말 카드
  - 그림, 제목, 줄, 소리 토글
  - 카드마다 [알리기](→ #/send?txn=) · [담기]
- **담은 거래**: /api/flags 목록. 항목마다 [알리기]·[빼기]
- **보낸 알림**: /api/notices
  - 자동 기록과 직접 보낸 기록을 함께 보인다.
  - 받는 사람 이름, 방법(문자·메일·전화·복사), 시각, 글을 보인다. delivery_note도 보인다.
- 상담 안내 띠: 동의에서 상담하는 곳에 알려 주기가 켜져 있고 기준을 넘으면 "상담하는 곳에 알려 볼까요?" → `#/send?to=counselors`
- notices.js는 지우고 이 탭으로 합친다.

### 6.5 전체·설정류 (more.js, consent.js, helpers.js, counselors.js, settings.js, export.js, onboarding.js, about.js, eval.js, css/views/more.css)

- **전체**(more.js) 구역
  - 나를 지키는 설정: 동의, 조력자, 상담하는 곳
  - 거래 연결: 은행 계좌 연결(준비 중), 카드 연결(준비 중) → 내 거래와 같은 시트(공통 함수는 txns 담당이 `views/connect.js`로 내보냄)
  - 앱 설정: 글자 크기·화면 모드(동작), 휴대폰 알림 받기(준비 중), 앱 잠금(준비 중)
  - 보호자·심사용: AI 성능 확인, 결과 내보내기, 보호자 앱 연결(준비 중)
  - 도움말·정보: 사용법 안내(준비 중), 고객센터(준비 중), 이용약관(준비 중), 개인정보 처리방침(준비 중), AI와 데이터 설명, 버전 정보(앱 0.3.0·엔진 상태, 동작)
- **동의**
  - 세 스위치: 거래 살펴보기 / 조력자에게 알리기 / 상담하는 곳에 알려 주기
  - 설명 문장 정리(R17·R20, 따옴표 없음)
  - 누가 동의했나요
  - 맨 아래 **모두 지우기**: 기존 data.js의 확인·bumpEpoch 동작을 옮기고, 필수 문장 "정말 모두 지우기?"는 "정말 모두 지울까요?"를 유지한다.
- **조력자**
  - 필드: 이름, 관계, 휴대폰 번호 [연락처에서 불러오기], 이메일 [연락처에서 불러오기], 이 사람의 계좌번호·이름
  - 언제 알릴까요, 무엇을 알릴까요(새 선 아이콘 + 명사형), 이 조력자에게 자동으로 알리기
  - '(가려서 저장해요)' 삭제
  - 목록은 가린 번호·메일을 보인다.
  - 연락처 고르기를 쓸 수 없는 PC면 버튼을 숨긴다.
- **상담하는 곳**: presets 추천(한 번에 더하기) + 직접 추가·수정(이름, 종류, 전화, 이메일, 메모, 연락처에서 불러오기, 사용)
- **설정**: 글자 크기 3단(바로 적용·저장), 화면 모드 3단, 준비 중 항목
- **내보내기**: 기존 data.js의 내보내기 두 줄
- **첫 실행**
  - 1단계 약속 문구를 바꾼다: "AI가 걱정되는 거래를 찾아요." / "조력자와 상담하는 곳에 알릴 수 있어요." / "{deviceWord} 안에서만 살펴봐요." (막지 않아요 문구 삭제)
  - 2단계 동의 이름을 바꾼다.
  - 3단계는 그대로다.
- **about·eval**: R14·R16·R19 문구 정리. 수치·표는 그대로 둔다.

## 7. 문구 규칙 (모든 담당)

- 따옴표('…', "…")로 낱말·화면 이름을 감싸지 않는다(R14).
- 한 문장은 한 줄이다. 문장마다 마침표를 찍고, ui.h의 문장 나누기를 쓴다(R18).
- 다음 문구를 쓰지 않는다.
  - 막지 않아요, 결정은 내가 해요, AI 혼자서는 정하지 않아요, 연습 화면, 실제로 돈이 나가지 않아요, 보내지 않고 멈춘 것, 연습용 정답, (가려서 저장해요), 127.0.0.1
- 당사자 화면 금지어(tests/test_static_ui.py)
  - FORBIDDEN_WORDS + 이상거래·패턴·탐지·알고리즘·모니터링·이례·임계·통계·고위험·푸시·당사자님·단독 '주의'
  - '휴대폰 알림'이라고 쓰고 '푸시'라고 쓰지 않는다.
- 금액은 목록·표에서 `moneyText`("50,000원") 하나만 쓴다. 쉬운 말 카드 문장(파이썬)은 그대로 둔다.
- 장소는 `deviceWord()`로 이 휴대폰·이 컴퓨터를 쓴다.
- 실제 은행·카드사 이름·로고는 쓰지 않는다(제휴로 오해받지 않게).
- 준비 중 기능은 반드시 '준비 중' 배지와 "정식 버전에서 열려요."를 붙인다. 동작하는 척하지 않는다.

## 8. 테스트

- 파이썬: 새 API마다 서비스 테스트 + router==FastAPI 파리티 + 검증 오류 한국어 + 모두 지우기 포함을 확인한다.
- `tests/test_static_ui.py` 갱신
  - PERSON_VIEWS에 home, txns, notify, alerts, consent, helpers, counselors, onboarding, more, settings, export를 넣는다.
  - 필수 문장 목록을 바꾼다(아래).
  - CSS 검사는 app.css + views/*.css 모두 본다.
  - 따옴표 금지·127.0.0.1 금지·SIGNAL_KO에 '보내기'로 끝나는 이름 금지 검사를 더한다.
  - 알림 카드 규칙을 더한다.
- 필수 문장
  - 은행 파일 모양은 따로 확인하지 못했어요. / 이 조력자에게 자동으로 알리기 / 꼭 확인할 일이 30일 동안 3번 이상 생길 때
  - 언제든지 끌 수 있어요. 끄면 바로 멈춰요. / 합성 데이터 기준, 실제 피해 데이터 검증 아님 / 정말 모두 지울까요?
  - 보내기 버튼은 문자·메일 앱에서 직접 눌러요. / 정식 버전에서 열려요. / 상담하는 곳에 알려 줘요.
- 전체 pytest 통과와 `tools/check_eval_unchanged.py` 차이 0이 필요하다.
