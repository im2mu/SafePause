# SafePause v0.3 추가 설계: 돈 보내기 (송금 전 확인 → 내 은행 앱) — 2026-10-02 사용자 결정

사용자 결정: "확인 후 내 은행 앱 열기(권장)" 방식으로 송금 기능을 넣는다. 오픈뱅킹 직접 송금 화면은 '준비 중'으로 배치한다.
v03_spec.md 0절의 "송금 기능 없음"은 이 문서로 고친다. SafePause가 직접 돈을 옮기지는 않는다.

## 원칙

- SafePause는 돈을 직접 옮기지 않는다.
  - 받는 사람·금액을 미리 확인하고(AI 확인 카드), 본인이 정하면 **본인이 고른 은행 앱**을 연다.
  - 실제 이체는 은행 앱의 인증·한도 절차를 거친다.
- 이렇게 하는 이유
  - 오픈뱅킹 직접 이체는 전자금융업 등록·이용기관 승인·보안점검이 필요해 시제품에서 할 수 없다.
  - 착취 피해자용 앱의 송금 버튼은 송금 강요의 통로가 될 수 있다.
  - 권한 0개를 유지한다.
- 은행 이름·로고를 앱에 넣지 않는다. 은행 앱은 휴대폰에 설치된 앱 목록에서 본인이 한 번 고른다(앱 이름만 표시).
- 필수 문장: "SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요."
- 금지 문구는 그대로다(연습 화면, 실제로 돈이 나가지 않아요, 막지 않아요 등).

## 정보 구조

- 보내기 탭(`#/send`) 위에 탭 2개를 둔다: **돈 보내기 | 알림 보내기** (`?mode=money|notify`).
  - 기본은 돈 보내기다.
  - `?txn=`·`?to=`가 있으면 알림 보내기를 연다.
- 홈 바로가기에 '돈 보내기 전 확인'을 더한다.

## 돈 보내기 흐름

v0.2 send.js를 되살려 다듬는다. 옛 코드는 `git show 7d57ea9:safepause/web/js/views/send.js`로 본다.

1. **입력**: 받는 사람(최근 보낸 사람 칩: `/api/payees`), 금액(한국어 단위·정확한 원 표시·0과 한도 안내), 방법(계좌 이체·가게에서 결제·휴대폰 결제), 보낼 시각(지금·오후 3시·밤 11시·새벽 2시), 계좌번호(선택).
2. **[보내기 전에 확인하기]** → `POST /api/safepause/check`
   - 카드가 없으면(걱정 없음) "걱정되는 점이 없어요." 결과로 바로 간다.
3. **안전 정지 카드**(v0.2와 같은 규칙)
   - 등급, 그림, 제목, 줄, 질문, 소리 토글
   - 선택지는 서버가 준 순서·문구 그대로: 그래도 보낼래요 / 안 보낼래요 / 조력자에게 물어볼래요
   - 닫을 수 없다. Esc·뒤로 가기는 '안 보낼래요'로 초점만 옮긴다.
   - 넓으면 본문·선택지를 나누고, 좁으면 한 번에 스크롤한다.
4. **결정** → `POST /api/safepause/decide`
   - 그래도 보낼래요: 결과 시트 "내 은행 앱에서 보내 주세요." + **[내 은행 앱 열기]**(고른 앱 이름 표시)와 [다른 은행 앱 고르기]
   - 안 보낼래요: "보내지 않았어요." 결과
   - 조력자에게 물어볼래요: v0.2의 물어볼 사람 고르기 단계 → 결정 기록. 결과에 [알림 보내기로 문자·메일 보내기](→ `#/send?mode=notify&txn=<확인한 거래 id>`)
5. 결과 문구에서 '연습'이라는 말을 쓰지 않는다. 확인한 거래는 내 거래 끝에 적힌다. 표시 이름은 '보내기 전 확인'이다(txnRow의 practice 배지 문구).

- **계좌 연결해서 바로 보내기 (준비 중)** 카드: comingSoonSheet로 단계(계좌 연결 → 받는 사람·금액 → AI 확인 카드 → 이체 인증 → 완료)를 보이고 "정식 버전에서 열려요."를 붙인다.

## 내 은행 앱 고르기

- 앱이면 `SafePauseNative.listApps()` → `[{package, label}]`(실행 가능한 앱, 이름순)을 받는다.
  - 검색 칸이 있는 시트를 연다.
  - 이름에 은행·뱅크·bank·페이·pay·증권·카드가 들어간 앱을 위로 올린다. 일반 규칙이고 특정 회사 이름은 넣지 않는다.
  - 고르면 localStorage `safepause.bankApp = {package, label}`(try/catch)에 저장한다.
- 열기: `SafePauseNative.openApp(package)` → true/false. 실패하면 "은행 앱을 열지 못했어요. 다시 골라 주세요."
- PC(브라우저)면 버튼을 비활성으로 하고 "은행 앱은 휴대폰 앱에서 열 수 있어요."를 보인다. 휴대폰·태블릿 브라우저는 "은행 앱은 SafePause 앱을 설치하면 열 수 있어요."(휴대폰을 든 사람에게 '휴대폰 앱에서'라고 하지 않게).
- 설정 화면(`#/more/settings`)에 '내 은행 앱'(고르기·바꾸기·지우기)을 둔다.
- 모두 지우기 때 `safepause.bankApp`도 지운다(동의 화면 wipe에서 같이).

## 안드로이드

- NativeBridge에 `listApps()`를 둔다.
  - Intent(MAIN, LAUNCHER) queryIntentActivities로 패키지·라벨을 모은다. 자기 앱은 뺀다. JSON 배열 문자열을 돌려준다.
- NativeBridge에 `openApp(pkg)`를 둔다.
  - getLaunchIntentForPackage + FLAG_ACTIVITY_NEW_TASK를 쓰고, 성공 여부를 boolean으로 돌려준다.
  - 목록에 없는 패키지는 false다.
- Manifest `<queries>`에 `<intent><action MAIN/><category LAUNCHER/></intent>`를 더한다. QUERY_ALL_PACKAGES는 쓰지 않는다. 권한은 0개를 유지한다.
- `capabilities()`에 `"apps": true`를 더한다.

## 테스트

- test_static_ui
  - 필수 문장 "SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요."
  - 카드 규칙: initialFocus #card-title, dismissible false, card.choices.map, aria-labelledby card-level card-title, parseKoreanAmount
  - 은행 이름 하드코딩 금지 검사(예: 국민·신한·우리·하나·농협·카카오뱅크·토스 등 문자열이 JS에 없어야 함)
- 엔진 모드에서 check·decide·payees가 정상 응답하는지 확인한다(BASIC 목록 아님 → full 대기).

## 받는 사람 추천과 돈 받은 조력자 경고 (알림 보내기)

조력자 설정(알릴 등급·범위·자동으로 알리기)과 이해충돌(돈 받는 조력자 제외)이 v0.3에서도 쓰이게 한다. 이미 테스트된 safepause/guardian/policy.py의 is_conflict·is_eligible을 그대로 쓴다.

- `POST /api/notify/suggest {"txn_ids": [...]}` (0~20개, 거래 살펴보기 동의 필요)
  - 응답:
    `{"helpers": [{"id", "name", "suggested": bool, "conflict": bool, "reason": "..."}], "counselors": [{"id", "name", "suggested": bool}], "counseling_due": bool}`
  - helper.suggested는 다음을 모두 만족할 때 참이다.
    - 동의 helper_alerts가 켜져 있다.
    - helper.active다.
    - 고른 거래 가운데 하나 이상에 is_eligible(등급·범위)이다.
    - 고른 거래 어느 것과도 is_conflict가 아니다.
  - conflict가 참이면 reason은 "이 거래에서 돈을 받은 사람이에요."다. 거래가 없으면 suggested는 active 기준이다.
  - counseling_due는 동의 counseling_referral이 켜져 있고, 30일 안에 꼭 확인할 일이 3번 이상일 때 참이다. 기존 상담 안내와 같은 기준이다.
  - counselor.suggested는 counseling_due 그리고 active일 때 참이다.
  - 서비스·router·FastAPI 세 곳 같게 하고, 파리티 테스트를 붙인다.
- 화면(알림 보내기)
  - 거래를 고르면 suggest를 불러 추천받은 사람을 미리 체크하고 '추천' 배지를 단다.
  - conflict인 조력자는 체크를 풀고 경고를 보인다: "이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요."
  - 그래도 본인이 체크하면 보낼 수 있다(본인 결정). 단, 확인 시트를 한 번 더 보인다.

## 파이썬 문구

- check/decide 응답 가운데 사용자에게 보이는 글에서 '연습' 표현을 뺀다. PRACTICE_NOTE는 평가 호환을 위해 상수로 남기되, 화면은 쓰지 않는다.
- 결과 글은 다음처럼 쓴다: "내 은행 앱에서 보내 주세요." / "보내지 않았어요." / "조력자에게 물어봐요."
- 탐지 로직·평가 수치는 바꾸지 않는다(check_eval_unchanged 차이 0).
