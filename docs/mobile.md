# 안드로이드 앱 (SafePause v0.3)

## 1. 한눈에

| 항목 | 내용 |
|---|---|
| 파일 | `SafePause-0.3.0.apk` (약 30MB, 쓰는 동안 인터넷 연결 불필요) |
| 홈 화면 이름 | `SafePause` (`res/values/strings.xml`의 app_name, 아이콘은 그림만) |
| 버전 | versionCode 3 / versionName 0.3.0 |
| 지원 | Android 8.0(API 26) 이상, targetSdk 35(Android 15). 화면 프로그램 Android System WebView(Android 8·9는 Chrome) **97 이상**, 권장 112 이상(Pyodide 권장). 97 미만이면 앱이 빈 화면 대신 업데이트 안내를 보인다(`js/legacy.js`·`js/compat.js`), 97~110이면 배치 일부가 어긋날 수 있어 한 번 권한다 |
| 권한 | **없음** (INTERNET·READ_CONTACTS·CALL_PHONE 모두 요청하지 않음). 연락처는 시스템 선택 창이 고른 한 건만 받고, 전화는 다이얼 화면만 연다 |
| 화면 | PC판과 같은 파일(`safepause/web`) — 토스 계열 모바일 우선 화면 |
| AI 엔진 | 앱 안 파이썬(Pyodide 314.0.7, Python 3.14) + NumPy·SciPy·scikit-learn. **PC판과 같은 파이썬 코드**(`safepause` 패키지) |
| 저장 | 앱 전용 저장소(IndexedDB). 기기 백업·기기 이전에서 뺌(`allowBackup=false`, data_extraction_rules) |

## 2. 구조

```
[WebView 화면: safepause/web]  ──메시지──▶  [웹 워커: engine/worker.mjs]
  홈·내 거래·보내기·알림·전체                  Pyodide(웹어셈블리 파이썬)
  api.js(전달 방식만 다름)                      safepause.api.bridge → router → service(PC와 같은 코드)
        │                                        저장: /spdata(IDBFS, 앱 전용 IndexedDB)
        ▼
[MainActivity.java]  https://app.safepause.local/* 요청만 APK assets에서 꺼내 줌. 그 밖의 주소는 403.
  JS 다리 SafePauseNative: 기기 TTS(인터넷이 필요한 음성은 쓰지 않음), 파일 저장(시스템 저장 창),
    v0.3: openExternal(sms:·smsto:·mailto:·tel:만, 문자·메일 앱/다이얼 화면 열기), pickContact(phone|email, 시스템 연락처 선택 창),
    capabilities()(문자·메일·다이얼·연락처 앱이 있는지, TTS 준비, apps), 읽기가 끝나면 window.__safepauseSpeechDone(소리 버튼 토글),
    setThemeMode(auto|light|dark)(앱 설정의 화면 모드에 맞춰 위아래 시스템 막대 색을 바꿈, ui.applyPrefs가 부름)
    돈 보내기(docs/v03_spec_money.md): listApps()(홈 화면 앱 목록 {package, label}, 자기 앱 빼고 이름순), openApp(pkg)(그 목록의 앱만 연다).
    SafePause는 돈을 옮기지 않는다. 확인 카드 뒤 본인이 고른 은행 앱을 열 뿐이고, 은행 이름·패키지는 앱에 넣지 않는다
  Manifest <queries>: TTS_SERVICE, SENDTO(sms·smsto·mailto), DIAL(tel), PICK(phone_v2·email_v2), MAIN·LAUNCHER(내 은행 앱 고르기).
    QUERY_ALL_PACKAGES는 쓰지 않는다
  파일 고르기: 시스템 문서 선택 창(ACTION_OPEN_DOCUMENT, CSV·TXT·XLSX)
  launchMode singleTop: 연락처·파일·저장 창이 열린 채 홈 화면 아이콘으로 돌아와도 그 창이 그대로 남는다
  렌더러가 죽으면(메모리 부족·WebView 업데이트) 앱을 닫지 않고 화면을 다시 연다(60초 안에 4번째면 멈추고 안내)
```

- 2단계 준비: 앱을 켜면 파이썬과 가벼운 기능(동의·조력자·기록)을 먼저 준비하고, AI 분석 패키지는 뒤에서 싣습니다.
  에뮬레이터(Android 15, x86_64) 첫 실행: AI 분석까지 준비 약 11초, 거래 232건 첫 학습 약 4초, 이후 요청은 수십 ms.
- 같은 요청에 PC판과 같은 응답을 주는지는 `tests/test_api_service.py::test_router_matches_fastapi`가 검사합니다.
- 앱 안 AI 엔진이 제출 보고서 수치를 그대로 재현하는지는 앱 화면에서 직접 확인할 수 있습니다: **전체 → AI 성능 확인 → 보고서 수치 다시 계산**.
  검증 세트와 같은 설정(인물 3명 × seed 21~40, 세 방식)으로 표준 시나리오와 경계 변형을 차례로 계산하고,
  화면에 넣은 보고서 기준값(`data/eval_reference.json`) 168개와 반올림 없이 견줍니다(`docs/v03_frontend_api.md` 17절).
  2026-10-03 통합 점검에서 이 화면을 앱 묶음으로 끝까지 돌려 168개가 모두 같았고, 화면이 받은 응답을
  `docs/eval/eval_results_holdout.json`·`eval_results_subtle_holdout.json`의 값 1,100개(세트마다 550개, 계산 환경 정보 제외)와 견줘도
  **차이 0**이었습니다(앱 Pyodide: numpy 2.4.6·scikit-learn 1.8.0, PC: numpy 2.5.3·scikit-learn 1.9.1). 걸린 시간은 3장 첫 표.

## 3. 확인한 것

### v0.3 성능 확인 다시 계산 (2026-10-03, 통합 점검)

빌드: `assemble_www.py`(지금 저장소의 화면·`safepause` 패키지 + Pyodide 314.0.7) → `build_apk.py --debug`.
누른 버튼: 전체 → AI 성능 확인 → 보고서 수치 다시 계산(seed 20개 × 인물 3명 × 세 방식, 표준 → 경계 변형).

| 확인 | 결과 |
|---|---|
| aapt2 dump badging | label `SafePause`, versionCode 3 / 0.3.0, 요청 권한 0개 |
| 앱 묶음(www)을 헤드리스 Chrome에서 엔진 모드로(휴대폰 흉내 360×780, PC: AMD Ryzen 5 7500F 6코어, Windows 11) | 엔진 full까지 6.7초. full 뒤 누름: 표준 23.9초, 경계 변형 19.5초, 화면 표시 모두 43.4초. 결론 줄 `다시 계산한 값이 보고서 수치와 모두 같아요.`, 같아요 표시 32개·달라요 0개. 응답 값: 기준값 168개 차이 0, holdout 원자료 1,100개 차이 0, JS 오류 0 |
| 디버그 빌드 `polish-debug.apk`를 에뮬레이터에서(Android 15 google_apis x86_64, WebView 124, `-gpu guest`, 가상 4코어·4GB, 같은 PC) | 설치 성공, 요청 권한 없음(`dumpsys package`), versionName 0.3.0. 막 부팅한 에뮬레이터에서 앱을 켠 뒤 엔진 full 단계를 확인하기까지 21.9초. full 뒤 누름: 표준 48.2초, 경계 변형 40.6초, 화면 표시 모두 88.8초. 결론 줄 `다시 계산한 값이 보고서 수치와 모두 같아요.`, 같아요 32개·달라요 0개. 응답 값: 기준값 168개 차이 0, holdout 원자료 1,100개 차이 0. 계산 환경 python 3.14.2·numpy 2.4.6·scikit-learn 1.8.0. 계산 뒤에도 앱 프로세스 그대로 |
휴대폰 실기(ARM)에서는 재지 않았습니다. 에뮬레이터는 PC 위에서 도는 x86_64 가상 기기라 휴대폰 시간을 대신하지 않습니다.
화면 안내 문장은 잰 값만 쓰고, 휴대폰은 아직 재 보지 않았다고 적습니다.
앱 엔진은 요청을 한 줄로 처리해서, 계산하는 동안 다른 화면으로 가도 이미 보낸 계산은 끝까지 돌고 그동안 다른 요청이 기다립니다(화면은 결과를 버리고 두 번째 세트를 보내지 않음).

### v0.3 (2026-10-02, 빌드·데스크톱 Chrome)

| 확인 | 결과 |
|---|---|
| 빌드 | `build_apk.py --debug`: aapt2·javac·d8·zipalign·서명·검증 통과 |
| aapt2 dump badging | label `SafePause`, versionCode 3 / 0.3.0, 요청 권한 0개, queries 7개 |
| 앱 안 엔진(묶음 www를 Chrome에서 엔진 모드로) | full 단계 약 8초. 상담하는 곳·담기·보낸 알림 기록·돈 흐름 분석 API가 router로 정상 응답, 잘못된 요청은 한국어 422, 기록 글의 번호 원본은 가려 저장 |
| 돈 보내기(엔진 모드, 가짜 앱 다리) | AI 준비 전: 동의·조력자는 basic 단계에서 답하고, 받는 사람 추천은 full 뒤에 답함(BASIC 아님). full 뒤 payees·check·decide(보낼래요·안 보낼래요·물어볼래요)·suggest(추천·돈 받은 조력자·404·422·403) 정상, 결과 글에 연습 없음 |
| aapt2(돈 보내기 뒤) | 요청 권한 0개, label `SafePause`, queries 8개(MAIN·LAUNCHER 더함), QUERY_ALL_PACKAGES 없음 |

### v0.3 돈 보내기 (2026-10-02, 에뮬레이터: Android 15 google_apis x86_64)

| 확인 | 결과 |
|---|---|
| 설치 | `SafePause-0.3.0-debug.apk` 설치, `dumpsys package`에 요청 권한 없음, versionName 0.3.0 |
| 앱 목록(listApps) | 홈 화면 앱 18개를 이름순으로 돌려줌(약 0.25초), SafePause 자신은 빠짐. capabilities에 `apps: true` |
| 앱 열기(openApp) | 목록의 앱(달력)을 열면 true, 그 앱이 앞으로 옴. 자기 앱·홈 화면에 없는 앱·없는 패키지·잘못된 글은 false |
| 돌아오기 | SafePause로 돌아오면 화면이 그대로(결과 시트·주소·페이지 상태 유지, 다시 불러오지 않음) |
| 화면 흐름 | 예시(김*호 새벽 2시) → 확인 카드(처음 초점 제목, 뒤로 가기로 닫히지 않고 안 보낼래요로 초점) → 그래도 보낼래요 → 내 은행 앱 고르기(검색) → 내 은행 앱 열기 |
| 지우기 | 동의 화면 모두 지우기 뒤 고른 은행 앱도 사라짐(앱 설정: 아직 고르지 않았어요) |

에뮬레이터에는 은행 앱이 없어 다른 앱(달력)으로 열기를 확인했다. 실제 은행 앱이 열리는지, 은행 앱의 인증 화면에서 돌아올 때의 동작은 실기기에서 확인해야 한다.

실기기 확인이 아직 남은 것: 실제 은행 앱 열기와 돌아오기, ARM 기기의 준비 시간. (문자 앱 글 채우기·연락처 선택 창 결과·TTS 끝남 알림은 아래 2026-10-03 표에서 에뮬레이터로 확인)

### v0.3 수정 (2026-10-03, 에뮬레이터: Android 15 google_apis x86_64, `-gpu guest`)

적대적 검증의 안드로이드 결함 9건(AND-01~09)을 고친 뒤 확인했다. 빌드는 `assemble_www.py` → `build_apk.py --debug`.

| 확인 | 결과 |
|---|---|
| aapt2 | 요청 권한 0개, label `SafePause`, launchMode singleTop, 테마 아이콘(monochrome)은 일시정지 두 막대가 뚫린 팔각형 |
| JVM 시험 `android/check_shell.py` | 44개 사례 ALL OK(읽기 끝남 id 비교, 문자·메일 주소 길이 한도, 앱 목록 이름순) |
| TTS 끝남(AND-01) | 짧은 글 읽기가 약 1.3초 뒤 끝남 알림을 보내고 8초 뒤 읽는 중이 아님. 알림 탭 카드의 소리로 듣기가 다 읽은 뒤 저절로 소리로 듣기로 돌아옴 |
| 렌더러 종료(AND-02) | 렌더러 프로세스를 죽여도 앱 프로세스는 남고 화면을 다시 열며 토스트로 알림 |
| 저장 창 중 앱 종료(AND-03) | 앱이 다시 만들어진 뒤 저장 결과를 토스트로 알리고, 내용이 없으면 빈 파일을 지움 |
| 다크 모드 바꾸기(AND-04) | 켠 채로 기기 다크 모드를 바꾸면 위아래 막대 색이 바뀜. 앱 설정에서 어둡게를 고르면 기기 설정이 밝아도 막대가 어두운 색(23,23,28), 자동이면 다시 흰색 |
| 연락처 창 중 아이콘으로 돌아오기(AND-05) | 홈 → 런처 아이콘으로 돌아와도 연락처 선택 창이 그대로 맨 위, 고른 결과가 화면에 한 번 옴 |
| 긴 글(AND-06) | 한글 1,000자 글로 문자 앱 작성 화면이 열리고 글이 채워짐(보내지 않음) |
| 연락처 불러오기 두 번 누르기(AND-08) | 두 번째는 연락처 창이 이미 열려 있어요 안내만, 창은 하나, 고른 번호·이름이 칸에 들어감 |
| 엑셀 올리기 | 시스템 문서 선택 창에서 `.xlsx`를 고를 수 있음(EXTRA_MIME_TYPES에 xlsx 형식 추가). 이어 붙이기로 올리면 5건 읽음·새 거래 5건 |
| 서명 비밀번호(AND-09) | keytool·apksigner에 환경 변수로 넘김(명령줄에 보이지 않음) |
| 앱 안 엔진(묶음 www를 Chrome 엔진 모드로) | full 단계 약 8초. 내가 한 거예요·확인 기록 지우기·보낸 알림 지우기·받는 사람 추천(pending)·이어 붙여 올리기·조력자·기관용 요약 정상. `.xlsx` 올리기는 zipfile·xml.etree로 5건 읽음(합계 줄 뺌), 같은 파일을 다시 이어 붙이면 새 거래 0건·겹친 5건 |
| AI 부분만 실패(numpy·scipy·scikit-learn wheel을 뺀 묶음) | 단계 error(fatal false). 동의·내가 한 거예요·보낸 알림 지우기·확인 기록 지우기·모두 지우기는 파이썬이 답하고, 돈 흐름 분석만 503 |

### v0.2 (에뮬레이터: Android 15 google_apis x86_64, WebView 124)

| 확인 | 결과 |
|---|---|
| 설치·실행 | 설치 성공, 시작 화면(첫 실행 안내) 표시, 상태 표시줄·내비게이션 바와 겹치지 않음 |
| 권한 | `dumpsys package`에 요청 권한 없음 |
| 인터넷 차단 | 에뮬레이터는 인터넷 가능(ping 성공)한 상태에서 앱 안 `fetch`로 외부 주소 3곳 접속 → 모두 차단 |
| 전체 API | 동의·조력자·연습용 거래·거래 목록·자동완성·안전 정지 확인/결정·기록 카드·알림 기록·성능 확인·내 거래로 확인·내보내기 2종·지우기 |
| 안전 정지 카드 | 꼭 확인해요 카드 표시, 안드로이드 뒤로 가기로 닫히지 않고 '안 낼래요'로 초점, 조력자에게 물어보기 → 결과 화면 |
| 파일 올리기 | 시스템 파일 선택 창에서 CSV 선택 → 46건 읽음 |
| 파일 저장 | '현장 검증용 요약' → 시스템 저장 창 → Downloads에 JSON 저장·내용 확인(이름·계좌·금액·날짜 없음) |
| 다시 켜기 | 저장한 동의·거래가 남아 있음(IDBFS) |
| 음성 | 기기 한국어 음성 준비됨(ttsStatus=ready), 읽기 호출 성공(소리 자체는 듣지 않음) |

확인하지 않은 것: 실제 휴대폰(ARM) 기기, Android 8~14 실기기, 저사양 기기의 준비 시간, 화면 낭독(TalkBack) 실사용.
화면 프로그램 버전: 최소 97은 앱이 쓰는 웹 기능·Pyodide 요구 기능을 정적으로 대조한 값이다. 97~111에서 Pyodide를 실제로 돌려 보지는 않았고(공식 권장 112), 96 이하에서 엔진 워커가 페이지 CSP를 물려받는지도 확인하지 못해 보수적으로 막는다. Play 스토어로 업데이트되는 Android 8·9 휴대폰의 WebView는 최대 138, Android 10 이상은 최신이라 대부분 해당하지 않는다. 순정 에뮬레이터 이미지(android-26 default WebView 58, android-30 default 83)처럼 업데이트가 안 되는 기기에서만 안내가 뜬다.

## 4. 빌드 (Gradle 없이 안드로이드 SDK 명령만)

필요한 것(공식 배포본): JDK 17+(작성 시 Microsoft OpenJDK 21), Android build-tools 35, platforms/android-35,
Pyodide 314.0.7 파일(아래). 모두 한 번만 내려받으면 됩니다.

```bash
# 1) Pyodide 파일을 android/pyodide-dist 에 둔다(목록은 android/assemble_www.py 머리말)
# 2) 화면·엔진 묶음 만들기(wheel sha256을 pyodide-lock.json과 대조)
python android/assemble_www.py --pyodide android/pyodide-dist --out android/www-build
# 3) APK 빌드·서명(서명 키가 없으면 android/signing/release.jks를 새로 만듦)
python android/build_apk.py --sdk <SDK 폴더> --jdk <JDK 폴더> --www android/www-build --out dist/SafePause-0.3.0.apk
```

- 서명 키(`android/signing/`)는 저장소·배포 zip에 넣지 않습니다(.gitignore). **같은 키로 서명해야 설치된 앱을 지우지 않고
  업데이트**할 수 있으니 키 파일과 `keystore.properties`를 안전한 곳에 보관하세요.
- `--debug`로 빌드하면 WebView 원격 디버깅과 화면 로그(logcat)가 켜집니다. 배포판은 끕니다(로그에 받는 사람·금액이 섞일 수 있어서).

## 5. 설치 (심사위원·사용자)

1. APK 파일을 휴대폰에 옮깁니다(구글 드라이브 링크, USB 등).
2. 파일을 누르고, "출처를 알 수 없는 앱 설치" 허용을 물으면 그 앱(파일 관리자·브라우저)에만 허용합니다.
3. Play 프로텍트가 "알 수 없는 개발자" 경고를 보여 주면 [세부정보] → [무시하고 설치]를 누릅니다(개인 서명 앱이라 뜨는 경고).
4. 처음 켜면 AI 엔진 준비에 10초쯤 걸립니다(위쪽 파란 막대). 동의·조력자 화면은 그 전에 쓸 수 있습니다.

## 6. 인터넷 연결이 필요해지는 경우 (본 사업 단계)

이번 시제품(Pre-R&D)은 CSV 파일과 연습용 거래로 검증하므로 인터넷이 필요 없고, 그래서 INTERNET 권한을 넣지 않았습니다.
실시간 분석(제안서의 마이데이터 연계)으로 넓히면 다음을 더합니다.

- 데이터 연결 어댑터: `safepause/data/sources.py`의 `MyDataSource`(지금은 NotImplementedError)를 구현합니다.
  서비스 계층은 `TransactionSource.load()`만 부르므로 화면·탐지 코드는 바꾸지 않습니다.
- 허가·계약: 본인신용정보관리업(마이데이터) 허가 또는 허가 사업자 제휴, 금융사 API 이용 계약, 전송요구 동의 화면.
- 앱: `AndroidManifest.xml`에 `<uses-permission android:name="android.permission.INTERNET"/>`를 더하고,
  `res/xml/network_security_config.xml`에 **허용할 API 주소만** 적습니다(cleartext 금지, 그 밖 주소 차단).
  `MainActivity.shouldInterceptRequest`의 앱 밖 주소 403 규칙은 WebView 화면에 그대로 두고, 네트워크 요청은
  네이티브(자바) 쪽 어댑터만 하게 합니다.
- 원칙 유지: 인터넷은 **본인 거래를 기기로 받아오는 통로**로만 쓰고, 분석·판단·조력자 알림 기록은 기기 안에서 합니다.
- 현장 검증 결과 모으기는 서버 전송 대신 '현장 검증용 요약(JSON)' 내보내기를 씁니다(개인 식별 정보 없음, 본인이 직접 전달).
