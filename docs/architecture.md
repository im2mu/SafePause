# SafePause 구조

SafePause는 당사자 한 사람이 자기 휴대폰에서 쓰는 안드로이드 앱입니다. 앱은 화면(`safepause/web`)과
파이썬 엔진(Pyodide 위의 `safepause` 패키지)을 앱 안에서 돌립니다([mobile.md](mobile.md) 2장). 화면의 요청은 HTTP 없이
앱 안 엔진(`api/bridge.py` → `api/router.py` → `api/service.py`)이 받고, 모든 판단·저장은 기기 안에서 끝납니다(제안서 S35).

## 1. 모듈

| 계층 | 모듈 | 하는 일 |
|---|---|---|
| 계약 | `safepause/models.py` | 공통 데이터형: `Transaction`, `SignalHit`, `RiskAssessment`, `AlertCard`, `Helper`, `Consent`, `HelperNotice`, `NotifyPlan` |
| 설정 | `safepause/config.py` | 판단 설정(심야 23~6시, 짧은 창 7일, 긴 창 30일, 평소 기준 90일, 상담 연계 30일 3건) |
| 저장 | `safepause/store.py` | JSON 파일 저장소(동의·조력자·거래·결정·알림). 앱에서는 `/spdata/store`(앱 전용 IndexedDB에 연결된 폴더). 임시 파일에 쓴 뒤 교체(원자적). 읽기·쓰기는 스레드 잠금 + 파일 잠금(`.sp-store.lock`, 빈 파일)으로 줄 세움. `wipe()`는 거래 기록부터 지우고 실패한 파일을 모아 알림. `signature()`는 파일 변경 표식 |
| 데이터 | `data/synth.py` | 합성 데이터(가상 인물 3종 + 시나리오 5종, 표준·경계 변형 `intensity`). [dataset_card.md](dataset_card.md) |
| | `data/loader.py` | 거래내역 가져오기: CSV·TXT(표준 CSV / 한국어 머리글 자동 짝짓기 / `mapping` 지정), 엑셀 첫 시트(`xlsx.py`·`xls.py`), 확장자만 .xls인 웹 표(`htmltable.py`) |
| 판단 | `detect/features.py` | 평가 시점 이전 거래만으로 만든 개인 기준 이력(`History`)과 특징량 11개 |
| | `detect/rules.py` | 제안서 S19 시그널 5종 룰 |
| | `detect/anomaly.py` | 개인 기준 IsolationForest. [model_card.md](model_card.md) |
| | `detect/engine.py` | 룰 + 이상 점수 결합 → 위험 등급(없음·확인해요·꼭 확인해요) |
| 설명 | `explain/easy_card.py` | 쉬운 말 카드(제목·줄·그림·질문·선택지·음성 문장), 가독성 검사, 연습 결과 문장 |
| | `explain/llm_adapter.py` | 로컬 sLLM으로 카드 문장 다듬기. 파이썬 API로만 제공하고 화면·명령행에는 연결하지 않음(기본 꺼짐, loopback 주소만 허용) |
| 조력자 | `guardian/policy.py` | 누구에게 알릴지(등급·시그널 범위·동의), 이해충돌(조력자 = 거래 상대방) 제외, 상담 연계 제안 |
| | `guardian/outbox.py` | 알림을 저장소에 기록만 함(발송 없음) |
| 평가 | `eval/metrics.py`, `eval/report.py` | 합성 데이터 평가(표준 `eval_results.json`, 경계 변형 `eval_results_subtle.json`, 별도 검증 세트 seed 21~40 `eval_results_holdout.json`·`eval_results_subtle_holdout.json`), 내 거래 알림 비율, 보고서(JSON·Markdown) |
| 앱 엔진 | `api/service.py`, `api/router.py`, `api/bridge.py` | 업무 로직, 경로(메서드·주소)별 나누기, 안드로이드 엔진 진입점(웹 워커 `web/engine/worker.mjs`가 부름) |
| 화면 | `web/` | 바닐라 HTML·CSS·JS 화면 |
| 개발·시험 | `cli.py`, `server/app.py` | 명령행(평가 다시 계산 `eval` 등), 자동 시험이 같은 API를 HTTP로 검사할 때 쓰는 FastAPI 틀 |

## 2. 판단 흐름

```
거래 목록(합성 또는 CSV) ──► store.save_transactions
                                  │
                                  ▼
     엔진 스냅샷: 앞쪽 거래로 IsolationForest 학습(api/service.py train_count)
       - 실제 거래내역: 앞 75%(올림, 최소 30건)
       - 걱정되는 거래를 섞은 합성 데이터: 마지막 30일 이전 거래(평가와 같은 날짜 경계)
                                  │
                                  ▼
        engine.assess_many: 시간순으로 각 거래를 "그 이전 거래만"으로 평가
          ├─ rules.evaluate_rules_on  → SignalHit(시그널, 등급, 근거 숫자, 관련 거래)
          └─ anomaly.score_matrix     → 이상 점수 0~1 (개인 학습 분포 대비 백분위)
                                  │ combine_level
                                  ▼
                      RiskAssessment(없음 / 확인해요 / 꼭 확인해요)
```

돈 보내기 전 확인은 아직 보내지 않은 거래를 이력 끝에 붙여 평가합니다(`engine.assess_pending`). SafePause는 돈을 보내지 않고, 확인 뒤 본인이 고른 은행 앱을 엽니다.

```
화면 "보내기 → 돈 보내기" ─► POST /api/safepause/check ─► assess_pending ─► render_card(보내기 전 카드)
                                                        └─► policy.decide(미리 보기), ask_helper_candidates
화면 카드에서 고르기 ─► POST /api/safepause/decide  (check가 준 거래 id를 다시 보냄. id는 check마다 새로 주고
                                                     내용과 묶어 기억: 같은 id·다른 내용이면 새 id로 따로 기록)
    ① "그래도 보낼래요": 저장된 현재 거래 목록에 더해 저장(차단 없음)
    ② 결정 기록(decisions.json, 같은 id·같은 결정은 한 번만)
    ③ 자동 알림: policy.decide (동의·등급·범위·이해충돌) ─► outbox 기록
       "조력자에게 물어볼래요": 당사자가 체크한 helper_ids(자동 알림 대상은 체크를 풀 수 없음) ─► outbox 기록
       (이 거래로 이미 적은 조력자는 다시 적지 않음)
```

저장이 중간에 실패하면(파일 잠김·읽기 전용·저장 공간 부족) 한국어 안내(`StoreError`, 500 JSON)를 돌려줍니다.
거래를 먼저 쓰므로 결정·알림만 남는 반쪽 기록이 생기지 않고, 같은 요청을 다시 보내도 두 번 적히지 않습니다.

반복 고위험(S23) 건수는 저장된 거래(거래 시각 기준 30일)와 결정 기록(기록한 실제 시각 기준 30일)을 함께 셉니다.
그래서 '안 보낼래요'·'물어볼래요'로 멈춘 고위험 시도도 셉니다(같은 거래는 한 번만).

결합 규칙(`detect/engine.py`, SPEC §5):

- 룰 고위험 1개 이상 → 꼭 확인해요(고위험)
- 룰 확인해요 + 이상 점수 ≥ 0.90 → 꼭 확인해요
- 룰 확인해요 → 확인해요
- 룰 없음 + 출금 + 이상 점수 ≥ 0.98 → 확인해요 (AI 단독으로는 고위험을 내지 않음, S38)

## 3. 누수 방지와 시간 규칙

- 모든 특징량·룰은 평가 시점 이하의 거래만 봅니다. 목록으로 이력을 받을 때 같은 시각 거래는
  `walk()`와 같은 규칙을 씁니다: 대상이 목록 안에 있으면 목록에서 대상보다 앞의 것만, 대상이 목록에 없으면
  목록 전체를 과거로 봅니다(`features.as_history`).
- 평소 기준 구간은 최근 7일을 뺀 과거 90일입니다. 지금 일어나는 급증이 '평소' 값을 끌어올리지 않게 하기 위함입니다.
- 정답 라벨(`label`)은 평가와, 화면에서 합성 샘플의 AI 학습 구간 경계(`api/service.py` `train_count`)를 정하는 데만 씁니다.
  거래별 판단(룰·점수)에는 쓰지 않습니다.

## 4. 엔진 상태와 저장

- `Service.snapshot()`(`api/service.py`)은 학습한 엔진과 전체 평가 결과를 메모리에 둡니다. `transactions.json`의 표식
  (수정 시각·크기·파일 번호)이 바뀌면 버리고 다시 만듭니다. 그래서 지운 거래가 메모리에서 되살아나지 않습니다.
- 저장 파일을 바꾸거나 분석 결과를 쓰는 요청(동의 바꾸기·조력자 저장·샘플/CSV 거래 저장·거래 목록·check·decide·카드·지우기)과
  "내 거래로 확인"(전체 → AI 성능 확인)의 동의 확인·스냅샷은 엔진 잠금(`Service.lock`) 하나로 줄 세웁니다. 동의 확인도 잠금 안에서 하므로, 동의 철회와 분석 요청이
  겹치면 철회가 먼저 적용됩니다.
- 잠금 밖에서 하는 것: 올린 파일 읽기(`load_csv`, 저장 직전에 세대 번호·동의를 다시 확인), "내 거래로 확인"의 계산, 합성 평가
  (`POST /api/eval/run`), 읽기 전용 요청(`GET /api/consent`·`/api/helpers`·`/api/notices`·`/api/decisions`·`/api/data/summary`).
  저장소 읽기·쓰기 자체는 `store.py`의 잠금으로 줄 세웁니다.
- 동의를 끄거나 다시 켜면 메모리 결과를 버립니다.

## 5. API (JSON)

화면과 엔진은 아래 경로로 JSON을 주고받습니다. 앱에서는 화면의 `api.js`가 요청을 웹 워커로 보내고, 앱 안 엔진
(`api/bridge.py` → `api/router.py`)이 HTTP 없이 처리합니다. `server/app.py`(FastAPI)는 자동 시험이 같은 경로를 HTTP로
검사할 때 쓰는 틀이고, 두 쪽이 같은 요청에 같은 응답을 주는지는 `tests/test_api_service.py::test_router_matches_fastapi`가 봅니다.

| 메서드·경로 | 설명 |
|---|---|
| `GET /api/health` | `{"status":"ok","version":…,"offline":true}` |
| `GET/PUT /api/consent` | 동의 세 가지(거래 살펴보기·조력자 알림·상담 연결)를 따로 켜고 끔 |
| `GET/PUT /api/helpers` | 조력자 목록 전체 교체(최대 10명). 연락처는 가려서 저장 |
| `GET /api/data/summary` | 저장된 거래 요약 |
| `POST /api/data/sample` | 합성 데이터 불러오기(앱의 연습용 거래) |
| `POST /api/data/upload` | 거래 파일 올리기(CSV·TXT·엑셀, 5MB, 동의 필요) |
| `GET /api/transactions` | 거래 + 판단(동의 없으면 403) |
| `POST /api/safepause/check` | 보내기 전 판단 + 카드 + 조력자 알림 미리 보기(저장 안 함) |
| `POST /api/safepause/decide` | 결정 기록, 알림 기록, "보낼래요"면 이력에 더함 |
| `GET /api/cards` | 지난 걱정 거래의 기록 카드(과거형, 묻지 않음) |
| `GET /api/notices`, `GET /api/decisions` | 알림 기록, 결정 기록 |
| `POST /api/eval/run`, `POST /api/eval/file` | 합성 데이터 평가(`seed_start`·`seeds`·`intensity`로 고름, 인물 3명 × seed 21~40이면 응답 `report_set`이 참 = 제출 보고서 검증 세트와 같은 설정), 내 거래 알림 비율 |
| `POST /api/wipe` | 모두 지우기 |

v0.3에서 더한 API(상담하는 곳 `/api/counselors`, 담은 거래 `/api/flags`, 내가 한 거예요 `/api/reviews`, 돈 흐름 분석 `/api/insights`·`/api/payees`,
알림 기록 `/api/notices/record`·`/remove`, 받는 사람 추천 `/api/notify/suggest`, 결과 내보내기 `/api/export/*` 등)는 `api/router.py`와
[v03_spec.md](v03_spec.md) 3.7절에 있습니다.

보안: 앱은 INTERNET 권한이 없고, 화면(WebView)은 `https://app.safepause.local/*` 요청만 APK 안 파일에서 꺼내 주며 그 밖의 주소는 403입니다.
화면 CSP와 엔진 워커의 동적 코드 실행 막기는 [mobile.md](mobile.md) 4장에 있습니다.

## 6. 화면

바닐라 HTML·CSS·JS(빌드 도구·외부 라이브러리 없음). 기본 글자 20px(좁은 화면 포함), 버튼 최소 48px(실제 56px 이상),
고대비, 키보드 조작(탭 화살표 이동, 모달 초점 가두기), 픽토그램 SVG 11종. 음성 읽기는 기기 음성 엔진(TTS)을 쓰고
인터넷이 필요한 음성은 쓰지 않습니다. 기기에 한국어 음성이 없으면 버튼을 숨기고 까닭을 알려 줍니다.
입력칸은 맞춤법 검사를 끕니다(`spellcheck="false"`, S35). 좁은 화면·400% 확대(320px)에서도 가로로 넘치지 않게 칸 너비를 `min(…, 100%)`로 둡니다.

## 7. APK 빌드

- `android/`: 안드로이드 APK(앱 묶음 조립 `assemble_www.py`, 빌드·서명 `build_apk.py`). [mobile.md](mobile.md) 4장
- APK 파일은 저장소에 넣지 않고 공모전 제출물로 따로 냅니다.
