# 안드로이드 앱 (SafePause v0.3)

## 1. 한눈에

| 항목 | 내용 |
|---|---|
| 파일 | `SafePause-0.3.0.apk` (약 30MB, 쓰는 동안 인터넷 연결 불필요) |
| 홈 화면 이름 | `SafePause` (`res/values/strings.xml`의 app_name, 아이콘은 그림만) |
| 버전 | versionCode 3 / versionName 0.3.0 |
| 지원 | Android 8.0(API 26) 이상, targetSdk 35(Android 15) |
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
    capabilities()(문자·메일·다이얼·연락처 앱이 있는지, TTS 준비), 읽기가 끝나면 window.__safepauseSpeechDone(소리 버튼 토글)
  Manifest <queries>: TTS_SERVICE, SENDTO(sms·smsto·mailto), DIAL(tel), PICK(phone_v2·email_v2)
  파일 고르기: 시스템 문서 선택 창(ACTION_OPEN_DOCUMENT, CSV)
```

- 2단계 준비: 앱을 켜면 파이썬과 가벼운 기능(동의·조력자·기록)을 먼저 준비하고, AI 분석 패키지는 뒤에서 싣습니다.
  에뮬레이터(Android 15, x86_64) 첫 실행: AI 분석까지 준비 약 11초, 거래 232건 첫 학습 약 4초, 이후 요청은 수십 ms.
- 같은 요청에 PC판과 같은 응답을 주는지는 `tests/test_api_service.py::test_router_matches_fastapi`가 검사합니다.
- 앱 안 AI 엔진이 제출 보고서 수치를 그대로 재현하는지: 브라우저 Pyodide에서 검증 세트(seed 21~40) 전체 평가를 돌려
  `docs/eval/eval_results_holdout.json`·`eval_results_subtle_holdout.json`의 528개 값과 비교해 **차이 0**을 확인했습니다
  (numpy 2.4.6·scikit-learn 1.8.0, PC는 numpy 2.5.3·scikit-learn 1.9.1).

## 3. 확인한 것

### v0.3 (2026-10-02, 빌드·데스크톱 Chrome)

| 확인 | 결과 |
|---|---|
| 빌드 | `build_apk.py --debug`: aapt2·javac·d8·zipalign·서명·검증 통과 |
| aapt2 dump badging | label `SafePause`, versionCode 3 / 0.3.0, 요청 권한 0개, queries 7개 |
| 앱 안 엔진(묶음 www를 Chrome에서 엔진 모드로) | full 단계 약 8초. 상담하는 곳·담기·보낸 알림 기록·돈 흐름 분석 API가 router로 정상 응답, 잘못된 요청은 한국어 422, 기록 글의 번호 원본은 가려 저장 |

에뮬레이터·실기기 확인이 아직 남은 것: 홈 화면 이름 표시, 문자 앱(sms_body)·메일 앱(제목·본문) 채우기, 연락처 선택 창 결과, TTS 끝남 알림으로 소리 버튼이 돌아오는지.

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
