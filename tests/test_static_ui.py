"""화면(safepause/web) 정적 검사: 쉬운 말 규칙·꼭 남길 문장·문구 규칙·접근성·보안·오프라인(v0.3 화면).

v0.3 돈 보내기(docs/v03_spec_money.md): SafePause는 돈을 옮기지 않고, AI 확인 카드 뒤 본인이 고른 은행 앱을 연다.
그래서 직접 이체 화면(계좌 비밀번호·인증 번호 입력)이 없고, 실제 은행·카드사 이름을 화면에 넣지 않는지도 본다.

화면 코드는 PC 서버와 안드로이드 앱이 같이 쓴다. 브라우저 동작은 docs/mobile.md의 수동 점검 목록과
에뮬레이터 점검으로 확인하고, 여기서는 파일만 본다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from safepause.explain.easy_card import FORBIDDEN_WORDS, PICTOGRAMS

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "safepause" / "web"
JS = WEB / "js"
VIEWS = JS / "views"
VIEW_CSS = sorted((WEB / "css" / "views").glob("*.css"))
CSS_FILES = {"app.css": (WEB / "css" / "app.css").read_text(encoding="utf-8"),
             **{f"views/{p.name}": p.read_text(encoding="utf-8") for p in VIEW_CSS}}
CSS = "\n".join(CSS_FILES.values())   # 공용 + 화면별 CSS 모두
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
ALL_JS = {p.relative_to(WEB).as_posix(): p.read_text(encoding="utf-8")
          for p in sorted(WEB.rglob("*")) if p.suffix in (".js", ".mjs")}
JOINED = "\n".join(ALL_JS.values())

# 당사자가 보는 화면(보호자·심사용 화면 eval·about은 전문 용어 예외)
PERSON_VIEWS = ["home.js", "txns.js", "send.js", "money.js", "bankapp.js", "notify.js", "alerts.js", "consent.js",
                "helpers.js", "counselors.js",
                "onboarding.js", "more.js", "settings.js", "export.js"]
# 당사자 화면이 같이 쓰는 공용 모듈(글이 당사자에게 보인다)
PERSON_COMMON = ["js/main.js", "js/ui.js", "js/components.js", "js/labels.js", "js/format.js", "js/native.js",
                 "js/speech.js", "js/views/connect.js"]
EASY_FORBIDDEN = [*FORBIDDEN_WORDS, "이상거래", "패턴", "탐지", "알고리즘", "모니터링", "이례", "임계", "통계",
                  "고위험", "푸시", "당사자님"]
# 설계서 7절·수정 계획 1-G: 화면에 쓰지 않는 문구(송금 연습 흔적·불필요한 안내·접속 주소·심사용 표기·장소 하드코딩)
BANNED_PHRASES = ["막지 않아요", "결정은 내가 해요", "결정은 본인이 해요", "AI 혼자서는", "연습 화면",
                  "실제로 돈이 나가지 않아요", "보내지 않고 멈춘 것", "연습용 정답", "(가려서 저장해요)", "127.0.0.1",
                  "안전 정지", "심사·시연용", "이 기기"]
VIEW_ROUTES = {"home": "home.js", "txns": "txns.js", "send": "send.js", "alerts": "alerts.js", "more": "more.js",
               "more/consent": "consent.js", "more/helpers": "helpers.js", "more/counselors": "counselors.js",
               "more/settings": "settings.js", "more/eval": "eval.js", "more/export": "export.js",
               "more/about": "about.js", "more/guide": "guide.js", "onboarding": "onboarding.js"}


def _string_literals(js: str) -> list[tuple[str, str]]:
    """JS 문자열 리터럴(큰따옴표·백틱) 안의 글만 뽑는다(주석·코드 이름 제외)."""
    no_comments = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    no_comments = re.sub(r"(?m)^\s*//.*$", "", no_comments)
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', no_comments)


def _visible_text(js: str) -> str:
    return "\n".join(a or b for a, b in _string_literals(js))


def _read_view(view: str) -> str:
    path = VIEWS / view
    assert path.is_file(), f"화면 파일이 없어요: {view}"
    return path.read_text(encoding="utf-8")


# 글자 크기에 px를 쓰는 단 하나의 예외: 아래 탭 이름은 기본 1rem(20px) 밑으로는 내려가지 않고, 큰 글씨 설정·기기 글자
# 크기에서도 다섯 칸이 한 줄에 들어가게 20px에서 멈춘다(v0.2 2차 검증, 휴대폰 아래 탭의 일반적인 동작)
FONT_SIZE_EXCEPTIONS = {(".bottom-nav .nav-item", "min(1rem, 20px)")}


def _font_size_decls(css: str) -> list[tuple[str, str]]:
    """(선택자, font-size 값) 목록. 주석은 빼고, @media 안 규칙은 안쪽 선택자만 남긴다."""
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"font-size:\s*([^;}]+)", text):
        brace = text.rfind("{", 0, m.start())
        head = text[text.rfind("}", 0, brace) + 1:brace]
        out.append((head.split("{")[-1].strip(), m.group(1).strip()))
    return out


def test_font_size_not_reduced() -> None:
    # SPEC 접근성: 기본 글자 20px 이상(html 125%, 1rem = 20px). 모든 글자 크기는 1rem 이상(공용·화면별 CSS 모두).
    # 허용: 1rem 이상의 rem, 1rem 이상인 토큰(var), max(1rem, …)(px 없이), html의 % 기준 크기. px·em·pt·vw만 쓴 크기는 금지
    assert "html { font-size: 125%;" in CSS
    tokens = dict(re.findall(r"(--[\w-]+):\s*([0-9.]+rem)", CSS))
    seen_rem = False
    for name, text in CSS_FILES.items():
        for sel, value in _font_size_decls(text):
            if (sel, value) in FONT_SIZE_EXCEPTIONS:
                continue
            if sel.startswith("html"):
                assert re.fullmatch(r"[0-9.]+%", value), (name, sel, value)
                continue
            if m := re.fullmatch(r"([0-9.]+)rem", value):
                assert float(m.group(1)) >= 1.0, (name, sel, value)
                seen_rem = True
            elif m := re.fullmatch(r"var\((--[\w-]+)\)", value):
                assert m.group(1) in tokens and float(tokens[m.group(1)][:-3]) >= 1.0, (name, sel, value)
            elif value.startswith("max(1rem,") and "px" not in value:
                pass
            elif value != "inherit":
                raise AssertionError(f"{name}: {sel} {{ font-size: {value} }}는 1rem 이상 rem으로 써 주세요")
    assert seen_rem


def test_font_setting_and_theme_modes() -> None:
    # 앱 설정: 글자 크기 보통·크게·아주 크게, 화면 모드 자동·밝게·어둡게
    assert 'html[data-font="l"] { font-size: 140%; }' in CSS
    assert 'html[data-font="xl"] { font-size: 160%; }' in CSS
    assert ':root[data-theme="dark"]' in CSS and ':root:not([data-theme="light"])' in CSS
    ui = (JS / "ui.js").read_text(encoding="utf-8")
    assert "export function setPref" in ui and "export function applyPrefs" in ui and "localStorage" in ui
    assert "applyPrefs()" in (JS / "main.js").read_text(encoding="utf-8")


def test_chart_tokens_both_modes() -> None:
    # 차트 색 5개는 밝게·어둡게 모두 정의한다(대비 3:1 이상은 dataviz 검사기로 확인한 값)
    light = re.search(r":root \{(.*?)\n\}", CSS, re.S).group(1)
    dark = re.search(r':root\[data-theme="dark"\] \{(.*?)\n\}', CSS, re.S).group(1)
    for i in range(1, 6):
        assert f"--chart-{i}:" in light and f"--chart-{i}:" in dark, i


def test_touch_targets_at_least_48px() -> None:
    # 버튼 최소 높이(1rem = 20px 기준): 2.4rem = 48px 이상
    for sel in (".btn", ".icon-btn", ".chip", ".row", ".seg-tab"):
        block = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", CSS)
        assert block, sel
    for name, text in CSS_FILES.items():
        heights = [float(x) for x in re.findall(r"min-height:\s*([0-9.]+)rem", text)]
        assert all(h >= 2.4 for h in heights if h >= 2), name


def test_no_external_resources_and_csp() -> None:
    for name, text in {**ALL_JS, "index.html": INDEX, **CSS_FILES}.items():
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), name
        assert "@import" not in text and "fonts.googleapis" not in text, name
    assert "Content-Security-Policy" in INDEX and "default-src 'self'" in INDEX
    assert "script-src 'self' 'wasm-unsafe-eval'" in INDEX       # 앱 안 파이썬(웹어셈블리)만 추가 허용
    assert "<script>" not in INDEX and "onclick=" not in INDEX   # 인라인 스크립트 없음
    assert " style=" not in INDEX                                # 인라인 style 속성 없음


def test_view_css_files_linked() -> None:
    # 화면별 CSS 5개는 index.html에 연결돼 있다
    for name in ("home", "txns", "notify", "money", "more"):
        assert (WEB / "css" / "views" / f"{name}.css").is_file(), name
        assert f'<link rel="stylesheet" href="css/views/{name}.css">' in INDEX, name


def test_no_html_injection_apis() -> None:
    # 서버·엔진이 준 글(받는 사람 이름 등)은 textContent로만 넣는다(XSS 차단)
    for name, text in ALL_JS.items():
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert bad not in text, (name, bad)
        assert 'setAttribute("style"' not in text, name   # CSP가 막는 인라인 style 속성 대신 CSSOM


def test_spellcheck_and_autocorrect_off() -> None:
    # 받는 사람·연락처·보낼 글이 브라우저의 온라인 맞춤법 검사로 나가지 않게(S35)
    assert '<body spellcheck="false">' in INDEX
    for view in ("notify.js", "helpers.js", "counselors.js", "money.js", "bankapp.js"):
        text = _read_view(view)
        assert 'spellcheck: "false"' in text and 'autocorrect: "off"' in text and 'autocapitalize: "off"' in text, view


@pytest.mark.parametrize("phrase", [
    "은행 파일 모양은 따로 확인하지 못했어요.",
    "이 조력자에게 자동으로 알리기",
    "꼭 확인할 일이 30일 동안 3번 이상 생길 때",
    "언제든지 끌 수 있어요. 끄면 바로 멈춰요.",
    "합성 데이터 기준, 실제 피해 데이터 검증 아님",
    "정말 모두 지울까요?",
    "보내기 버튼은 문자·메일 앱에서 직접 눌러요.",
    "정식 버전에서 열려요.",
    "상담하는 곳에 알려 줘요.",
    "SafePause는 돈을 보내지 않아요. 보내기는 내 은행 앱에서 해요.",
    "은행 앱은 휴대폰 앱에서 열 수 있어요.",
    "은행 앱을 열지 못했어요. 다시 골라 주세요.",
    "이 거래에서 돈을 받은 사람이에요. 다른 사람에게 알리는 게 좋아요.",
])
def test_required_phrases_kept(phrase: str) -> None:
    assert phrase in JOINED, phrase


@pytest.mark.parametrize("view", PERSON_VIEWS)
def test_person_views_use_easy_words(view: str) -> None:
    text = _visible_text(_read_view(view))
    for word in EASY_FORBIDDEN:
        assert word not in text, (view, word)
    assert not re.search(r"(?<![가-힣])주의(?![가-힣])", text), view   # '주의' 단독(전문 용어) 금지


@pytest.mark.parametrize("name", PERSON_COMMON)
def test_common_modules_use_easy_words(name: str) -> None:
    text = _visible_text(ALL_JS[name])
    for word in EASY_FORBIDDEN:
        assert word not in text, (name, word)
    assert not re.search(r"(?<![가-힣])주의(?![가-힣])", text), name


@pytest.mark.parametrize("name", sorted(ALL_JS))
def test_banned_phrases_and_quotes(name: str) -> None:
    # 설계서 7절: 따옴표로 낱말·화면 이름을 감싸지 않는다(R14), 금지 문구(R16·R17·R19·R13·R15·R2)
    if name.startswith("pyodide/"):
        return
    literals = _string_literals(ALL_JS[name])
    text = "\n".join(a or b for a, b in literals)
    for phrase in BANNED_PHRASES:
        assert phrase not in text, (name, phrase)
    for dq, bt in literals:
        # 백틱 글의 ${...} 안은 코드다(그 안의 "나감" 같은 문자열은 따옴표로 감싼 글이 아님)
        lit = dq or re.sub(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", bt)
        assert not re.search(r"'[^'\n]*[가-힣][^'\n]*'", lit), (name, lit)          # '동의'에서
        assert not re.search(r"[‘’“”「」『』]", lit), (name, lit)
        if bt:
            assert not re.search(r'"[^"\n]*[가-힣][^"\n]*"', lit), (name, lit)     # `"동의"에서`
        else:
            assert not re.search(r'\\"[^"\\]*[가-힣][^"\\]*\\"', lit), (name, lit)


def test_no_korean_in_single_quoted_js_strings() -> None:
    # 화면 글은 큰따옴표·백틱 문자열로만 쓴다(위 따옴표·금지 문구 검사가 작은따옴표 문자열을 빠뜨리지 않게). 주석은 빼고 본다
    for name, js in ALL_JS.items():
        if name.startswith("pyodide/"):
            continue
        text = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        for line in text.splitlines():
            code = re.sub(r"(^|\s)//.*$", "", line)
            assert not re.search(r"'[^'\n]*[가-힣][^'\n]*'", code), (name, line.strip())


def test_index_html_phrases() -> None:
    # 머리 제목·홈 화면에 더할 때 이름은 SafePause(R2·R25), 접속 주소는 보이지 않는다(R19)
    for phrase in ("127.0.0.1", "localhost", "안전 정지"):
        assert phrase not in INDEX, phrase
    assert '<meta name="application-name" content="SafePause">' in INDEX


def test_signal_names_are_nouns() -> None:
    # R12: 신호 이름은 지시어(~보내기)가 아니라 일어난 일(명사형)
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    block = re.search(r"export const SIGNAL_KO = \{(.*?)\};", labels, re.S).group(1)
    names = re.findall(r':\s*"([^"]+)"', block)
    assert len(names) == 5
    for n in names:
        assert not n.endswith("보내기") and not n.endswith("요"), n
    neutral = re.search(r"export const SIGNAL_KO_NEUTRAL = \{(.*?)\};", labels, re.S).group(1)
    assert '"큰 금액 결제"' in neutral
    icons = (JS / "icons.js").read_text(encoding="utf-8")
    for code_icon in re.findall(r':\s*"(sig-[a-z-]+)"', labels):
        assert f'"{code_icon}":' in icons, code_icon


def test_level_names_are_easy_words() -> None:
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    for text in ('text: "괜찮아요"', 'text: "확인해요"', 'text: "꼭 확인해요"'):
        assert text in labels


def test_pictograms_match_easy_card() -> None:
    icons = (JS / "icons.js").read_text(encoding="utf-8")
    picto = json.loads(re.search(r"export const PICTO = (\{.*?\});", icons, re.S).group(1))
    assert set(picto) == set(PICTOGRAMS)
    for name in PICTOGRAMS:
        assert (WEB / "icons" / f"{name}.svg").is_file()
    ui = json.loads(re.search(r"export const UI = (\{.*?\});", icons, re.S).group(1))
    for name in ("sig-night", "sig-person", "sig-phone-pay", "sig-store", "sig-sim", "bank", "card", "contacts",
                 "mail", "chat", "call", "bookmark", "bookmark-fill", "chart", "building", "text-size", "moon-sun",
                 "lock", "bell", "help", "doc", "link", "shield", "headset", "info", "copy", "edit"):
        assert name in ui, name


def test_routes_and_moved_paths() -> None:
    # 설계서 2절: 경로표, 보내기 탭 = 알림 보내기, 옛 경로 옮기기, ? 뒤 값은 ctx.params
    main = (JS / "main.js").read_text(encoding="utf-8")
    for route, view in VIEW_ROUTES.items():
        assert f'"{route}": () => import("./views/{view}")' in main or f'{route}: () => import("./views/{view}")' in main, route
        assert (VIEWS / view).is_file(), view
    assert '"more/data": "more/consent"' in main and '"more/notices": "alerts?tab=sent"' in main
    assert "params: new URLSearchParams(query)" in main
    for label in ('label: "홈"', 'label: "내 거래"', 'label: "보내기"', 'label: "알림"', 'label: "전체"'):
        assert label in main
    assert 'text: "SafePause"' in main            # 머리글 로고(R2)
    assert "<title>SafePause</title>" in INDEX


def test_no_direct_transfer() -> None:
    # 돈 보내기 원칙: SafePause는 돈을 직접 옮기지 않는다. 확인(check·decide)은 돈 보내기 화면만 부르고,
    # 이체 API·계좌 비밀번호·인증 번호 입력칸·은행 앱 깊은 연결(intent: 주소에 금액 넣기)이 화면에 없다
    for gone in ("data.js", "notices.js"):
        assert not (VIEWS / gone).exists(), gone
    for path in ("/api/safepause/check", "/api/safepause/decide", "/api/payees"):
        users = [n for n, t in ALL_JS.items() if path in t]
        assert users == ["js/views/money.js"], (path, users)
    for name, text in ALL_JS.items():
        if name.startswith("pyodide/"):
            continue
        for bad in ('type: "password"', "type=\"password\"", '"one-time-code"', '"cc-number"', '"cc-csc"',
                    "/api/transfer", "openbanking", "intent:"):
            assert bad not in text, (name, bad)
    money_views = "\n".join(_visible_text(_read_view(v)) for v in ("send.js", "money.js", "bankapp.js", "notify.js"))
    for word in ("비밀번호", "OTP", "보안카드", "인증번호", "공동인증서", "카드 번호", "유효기간", "CVC"):
        assert word not in money_views, word
    # 계좌 연결해서 바로 보내기는 준비 중 안내(comingSoonSheet)만
    money = _read_view("money.js")
    assert "comingSoonSheet" in money and "계좌 연결해서 바로 보내기" in money and "soon: true" in money


# 실제 은행·카드사·간편결제 이름(제휴로 오해받지 않게 화면 글에 넣지 않는다). 앱 이름은 휴대폰 앱 목록에서 본인이 고른다
BANK_NAMES = ["국민은행", "KB국민", "국민카드", "신한", "우리은행", "우리카드", "하나은행", "하나카드", "농협", "기업은행",
              "IBK", "산업은행", "카카오뱅크", "카카오페이", "토스뱅크", "토스페이", "케이뱅크", "새마을금고", "우체국",
              "신협", "수협", "SC제일", "씨티은행", "대구은행", "iM뱅크", "부산은행", "경남은행", "광주은행", "전북은행",
              "제주은행", "삼성카드", "현대카드", "롯데카드", "BC카드", "비씨카드", "네이버페이", "삼성페이", "페이코", "PAYCO"]
BANK_PACKAGES = ["kbstar", "shinhan", "wooribank", "kakaobank", "viva.republica", "kbanknow", "hanabank", "nonghyup",
                 "nh.smart", "ibk.", "kfcc", "epost"]


def test_no_bank_names_in_screens() -> None:
    for name, js in ALL_JS.items():
        if name.startswith("pyodide/"):
            continue
        text = _visible_text(js)
        for bank in BANK_NAMES:
            assert bank not in text, (name, bank)
        assert not re.search(r"토스(?!트)", text), name   # 토스트(알림 글)는 괜찮다
        low = text.lower()
        for pkg in BANK_PACKAGES:
            assert pkg not in low, (name, pkg)


def test_money_screen_rules() -> None:
    # 보내기 탭: 돈 보내기 | 알림 보내기(?mode=money|notify, 기본 돈 보내기, txn·to가 있으면 알림 보내기)
    send = _read_view("send.js")
    assert 'import money from "./money.js"' in send and 'import notify from "./notify.js"' in send
    assert 'label: "돈 보내기"' in send and 'label: "알림 보내기"' in send
    assert 'params.get("mode")' in send and 'params.get("txn") || params.get("to")' in send
    assert "ctx.replaceParams(" in send and "ctx.session.unsaved" in send   # 기록을 늘리지 않고 탭 전환, 고친 글은 묻기
    # 안전 정지 카드 규칙(v0.2와 같음): 처음 초점은 제목, 닫을 수 없음, 선택지는 서버 순서·문구, 대화상자 이름은 등급 + 제목
    money = _read_view("money.js")
    assert 'initialFocus: "#card-title"' in money
    assert "dismissible: false" in money
    assert "card.choices.map((c)" in money and "text: c.label" in money
    assert 'setAttribute("aria-labelledby", "card-level card-title")' in money
    assert 'foot.querySelector(\'[data-decision="cancel"]\')' in money   # Esc·뒤로 가기는 안 보낼래요로 초점만
    assert "function fitLayout" in money and "room * 0.4" in money          # 본문이 0px로 접히지 않게
    assert "parseKoreanAmount" in money and "0보다 큰 금액을 적어 주세요." in money and "100억 원까지" in money
    assert money.index("errorSlot,") < money.index("speakButton(speakText")    # 오류·닫기는 소리로 듣기·선택지 앞
    assert "speakButton" in money and "showUnchecked" in money and "동의 켜러 가기" in money
    assert "예시로 해 보기" in money and "EXAMPLES" in money
    assert "PRACTICE_NOTE" not in JOINED and "practicePill" not in JOINED
    # 결과: 그래도 보낼래요 → 내 은행 앱, 물어볼래요 → 알림 보내기(확인한 거래)
    assert "내 은행 앱에서 보내 주세요." in money and "보내지 않았어요." in money
    assert "bankAppActions()" in money and 'mode: "notify"' in money and '"알림 보내기로 문자·메일 보내기"' in money
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    assert "export const DECISION_ICON" in labels and "export const EXAMPLES" in labels
    # 확인한 거래 표시 이름(내 거래 줄)
    comp = (JS / "components.js").read_text(encoding="utf-8")
    assert 'CHECKED_TEXT = "보내기 전 확인"' in comp and "item.practice ? CHECKED_TEXT" in comp
    # 홈 바로가기
    assert "#/send?mode=money" in _read_view("home.js")


def test_bank_app_rules() -> None:
    # 내 은행 앱: 앱 브리지가 있을 때만(부를 때 확인), 앱 목록은 일반 낱말로만 위로 올림, 고른 앱은 이 기기에(try/catch)
    native = (JS / "native.js").read_text(encoding="utf-8")
    for fn in ("export function canListApps", "export function listApps", "export function openApp"):
        assert fn in native, fn
    assert "const bridge = () => window.SafePauseNative || null;" in native
    assert "PACKAGE_RE.test(p)" in native                          # 패키지 이름 모양만 브리지에 넘긴다
    bank = _read_view("bankapp.js")
    assert 'BANK_APP_KEY = "safepause.bankApp"' in bank
    assert "/은행|뱅크|bank|페이|pay|증권|카드/i" in bank
    assert bank.count("try {") >= 3 and "localStorage" in bank
    assert 'type: "search"' in bank and "openApp(app.package)" in bank
    assert "clearBankApp()" in _read_view("consent.js")            # 모두 지우기 때 함께 지움
    assert "bankAppSettings()" in _read_view("settings.js")        # 설정: 고르기·바꾸기·지우기


def test_alert_and_notify_rules() -> None:
    # 소리 버튼 토글(R4): 누르면 재생 ↔ 멈추기, 한 번에 하나, 끝나면 원래대로(앱 끝남 알림 연결)
    comp = (JS / "components.js").read_text(encoding="utf-8")
    assert 'aria-pressed' in comp and "speech.stop()" in comp and "paint(false); } })" in comp
    # 버튼이 화면에서 떨어지거나 숨겨지면(탭 바꾸기·패널 다시 그리기·시트 닫기) 읽기를 멈춘다(D1·FE-09)
    assert "new MutationObserver" in comp and "!speaking.isConnected" in comp and 'closest("[hidden]")' in comp
    speech = (JS / "speech.js").read_text(encoding="utf-8")
    assert "window.__safepauseSpeechDone" in speech and "export function isSpeaking" in speech
    # 알림 탭: 쉬운 말 카드마다 알리기(→ 알림 보내기)
    alerts = _read_view("alerts.js")
    assert "send?txn=" in alerts
    assert "alertCard" in alerts or "speakButton" in alerts
    # 알림 보내기(R8): 문자·메일 앱을 열고, 연 뒤에 기록한다. 번호·메일 원본은 기록에 넣지 않는다(서버)
    notify = _read_view("notify.js")
    assert "openExternal" in notify and "/api/notices/record" in notify
    # 받는 사람 추천: 고른 거래로 추천을 받고, 돈을 받은 조력자는 체크를 풀고 경고, 그래도 고르면 보내기 전에 묻는다
    assert '"/api/notify/suggest"' in notify and "txn_ids:" in notify
    assert "CONFLICT_WARN" in notify and "confirmSheet({" in notify and 'text: "추천"' in notify
    native = (JS / "native.js").read_text(encoding="utf-8")
    assert "export function openExternal" in native and "export function pickContact" in native
    assert "window.__safepauseContactPicked" in native
    assert "/^(sms|smsto|mailto|tel):/i" in native             # 다른 주소는 열지 않는다


def test_one_sentence_per_line() -> None:
    # R18: 설명 글(p)은 문장마다 한 줄(span.sent)
    ui = (JS / "ui.js").read_text(encoding="utf-8")
    assert 'sp.className = "sent"' in ui and 'hasAttribute("data-nosplit")' in ui
    assert ".sent { display: block; }" in CSS


def test_device_word_and_money_text() -> None:
    # R19·R21: 장소는 이 휴대폰·이 컴퓨터, 금액은 한 번만
    fmt = (JS / "format.js").read_text(encoding="utf-8")
    assert '"이 휴대폰"' in fmt and '"이 컴퓨터"' in fmt and "export function moneyText" in fmt
    comp = (JS / "components.js").read_text(encoding="utf-8")
    row = comp[comp.index("export function txnRow"):comp.index("export function dateHead")]
    assert "formatWon" not in row and "txnAmount(t)" in row


def test_stale_response_guard() -> None:
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert "session.epoch !== epoch" in main and "throw STALE" in main
    consent = _read_view("consent.js")
    assert consent.count("ctx.session.bumpEpoch()") >= 2    # 거래 살펴보기 끄기 + 모두 지우기(맨 아래)
    assert "/api/wipe" in consent


def test_engine_basic_routes() -> None:
    # 앱 엔진: AI 없이 처리하는 가벼운 요청에 상담하는 곳·알림 기록을 넣는다(분석이 필요한 담기·돈 흐름은 빼고)
    worker = (WEB / "engine" / "worker.mjs").read_text(encoding="utf-8")
    basic = re.search(r"const BASIC = new Set\(\[(.*?)\]\);", worker, re.S).group(1)
    for key in ("GET /api/counselors", "PUT /api/counselors", "POST /api/notices/record", "POST /api/wipe"):
        assert f'"{key}"' in basic, key
    for key in ("/api/flags", "/api/insights", "/api/decisions", "/api/safepause/", "/api/payees", "/api/notify/suggest"):
        assert key not in basic, key   # 돈 보내기 확인·받는 사람 추천은 AI 준비가 끝난 뒤(full)


def test_reduced_motion_and_dark_mode() -> None:
    assert "prefers-reduced-motion: reduce" in CSS
    assert "prefers-color-scheme: dark" in CSS


def test_eval_reference_matches_submitted_numbers() -> None:
    ref = json.loads((WEB / "data" / "eval_reference.json").read_text(encoding="utf-8"))
    for key, fn in (("standard", "eval_results_holdout.json"), ("subtle", "eval_results_subtle_holdout.json")):
        doc = json.loads((ROOT / "docs" / "eval" / fn).read_text(encoding="utf-8"))
        for mode, v in doc["modes"].items():
            got = ref["sets"][key]["modes"][mode]
            assert got["scenario_high"] == v["overall"]["recall_high"]
            assert got["txn_high_recall"] == v["confusion"]["high"]["recall"]
            assert got["normal_high_rate"] == v["normal"]["high_rate"]
            assert got["control_monthly_alerts"] == v["control"]["monthly_alerts"]


# ---- v0.3 수정 계획(docs/v03_fixplan.md 2절 화면 공용 계약) ---------------------------------------
def _ui_icons() -> tuple[dict, dict]:
    icons = (JS / "icons.js").read_text(encoding="utf-8")
    ui = json.loads(re.search(r"export const UI = (\{.*?\});", icons, re.S).group(1))
    picto = json.loads(re.search(r"export const PICTO = (\{.*?\});", icons, re.S).group(1))
    return ui, picto


def test_line_icon_system() -> None:
    # D4: 화면 아이콘은 한 체계(24 viewBox, 굵기 2)다. 픽토그램 이름(check·warning·stop·person …)도 선 버전이 있고,
    # ui.icon()은 64 그림으로 넘어가지 않는다. 큰 픽토그램(picto)은 돈 보내기 확인 카드 본문에만 쓴다.
    ui, picto = _ui_icons()
    for name in picto:
        assert name in ui, f"선 아이콘이 없는 그림 이름: {name}"
    ui_js = (JS / "ui.js").read_text(encoding="utf-8")
    icon_fn = ui_js[ui_js.index("export function icon("):ui_js.index("export function picto(")]
    assert "PICTO" not in icon_fn and '"0 0 64 64"' not in icon_fn
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    level = re.search(r"export const LEVEL = \{(.*?)\};", labels, re.S).group(1)
    for name in re.findall(r'icon: "([a-z-]+)"', level):
        assert name in ui, name
    comp = (JS / "components.js").read_text(encoding="utf-8")
    assert "picto(" not in comp                      # 알림 카드 머리 그림도 신호 선 아이콘
    card = comp[comp.index("export function alertCard"):comp.index("function topText")]
    assert "txnSignals(" in card and "icon(headIcon)" in card
    users = sorted(n for n, t in ALL_JS.items() if re.search(r"\bpicto\(", t) and not n.startswith("pyodide/"))
    assert users == ["js/ui.js", "js/views/money.js"], users


def test_favicon_matches_logo() -> None:
    # D9: 브라우저 탭 아이콘은 머리글 로고(팔각형 + 두 막대)와 같은 그림
    assert '<link rel="icon" href="icons/logo.svg" type="image/svg+xml">' in INDEX
    svg = (WEB / "icons" / "logo.svg").read_text(encoding="utf-8")
    assert "M16 15v6M20 15v6" in svg and 'rx="10.8"' in svg and "<rect" in svg


def test_flag_and_review_terms() -> None:
    # 수정 계획 1-G·2절: 담기 용어 하나(버튼 알림 목록에 담기·담기 취소, 토스트 알림 탭에 담았어요., 목록 담은 거래, 배지 담음)
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    flag = re.search(r"export const FLAG_TEXT = \{(.*?)\};", labels, re.S).group(1)
    for pair in ('button: "알림 목록에 담기"', 'undo: "담기 취소"', 'toast: "알림 탭에 담았어요."', 'list: "담은 거래"',
                 'badge: "담음"'):
        assert pair in flag, pair
    review = re.search(r"export const REVIEW_TEXT = \{(.*?)\};", labels, re.S).group(1)
    for pair in ('button: "내가 한 거예요"', 'undo: "확인 취소"', 'badge: "내가 확인함"', 'toast: "내가 한 거래로 표시했어요."',
                 'note: "걱정되는 거래 수에서 뺐어요."'):
        assert pair in review, pair
    comp = (JS / "components.js").read_text(encoding="utf-8")
    assert "FLAG_TEXT.button" in comp and "FLAG_TEXT.toast" in comp and "REVIEW_TEXT.button" in comp


def test_flag_terms_same_on_every_screen() -> None:
    # RF-10·C3: 화면마다 다른 담기 문구를 쓰지 않는다(알림 카드도 flagButton 또는 FLAG_TEXT)
    for name, js in ALL_JS.items():
        if name.startswith("pyodide/"):
            continue
        text = _visible_text(js)
        for old in ("담은 거래에 넣었어요", "알림 목록에서 뺐어요"):
            assert old not in text, (name, old)
    alerts = _read_view("alerts.js")
    assert "flagButton(" in alerts or "FLAG_TEXT" in alerts
    assert 'text.textContent = on ? "담음" : "담기"' not in alerts


def test_shared_contract_exports() -> None:
    # 수정 계획 2절: 화면 담당은 이 이름만 쓴다
    comp = (JS / "components.js").read_text(encoding="utf-8")
    for fn in ("aiExplain(item", "reviewBadge(item)", "notifiedBadge(item)", "flagBadge(item)", "reviewButton(ctx, item",
               "noVoiceNote(", "speakButton(getText"):
        assert f"export function {fn}" in comp, fn
    explain = comp[comp.index("export function aiExplain"):comp.index("export function errorNotice")]
    assert "AI_TEXT.rules" in explain and "AI_TEXT.ai" in explain and "AI_TEXT.aiLearning" in explain and "item.ai" in explain
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    assert 'aiLearning: "거래가 30건보다 적어 AI는 아직 배우는 중이에요."' in labels
    fmt = (JS / "format.js").read_text(encoding="utf-8")
    assert "export function amountPreview" in fmt and "export function bandLabel" in fmt and "export function keepUnits" in fmt
    for band, label in (("dawn", "새벽"), ("morning", "오전"), ("day", "낮"), ("evening", "저녁·밤")):
        assert f'{band}: {{ label: "{label}"' in fmt, band
    preview = fmt[fmt.index("export function amountPreview"):fmt.index("export const BANDS")]
    assert "moneyText(" in preview and "formatWon" not in preview   # 정확한 원 단위 하나(반올림 금액을 = 로 붙이지 않음)


def test_amount_preview_not_rounded() -> None:
    # RF-4·C10: 돈 보내기 금액 칸 아래 줄은 amountPreview(정확한 원 단위)만 쓰고, 반올림한 만 원 표기를 = 로 붙이지 않는다
    money = _read_view("money.js")
    assert "= ${formatWon(" not in money
    assert "amountPreview(" in money


def test_examples_keep_units_together() -> None:
    # C13·D8: 예시 칩의 금액·시각 안 빈칸은 줄을 바꾸지 않는 빈칸
    labels = (JS / "labels.js").read_text(encoding="utf-8")
    block = re.search(r"export const EXAMPLES = \[(.*?)\];", labels, re.S).group(1)
    for label in re.findall(r'label: "([^"]+)"', block):
        assert not re.search(r"\d[만천억]? 원", label) and not re.search(r"(오후|새벽|밤|오전) \d", label), label


def test_speech_waits_for_voice() -> None:
    # D10: 음성 준비가 늦어도 화면이 맞게 바뀐다(html[data-voice] + CSS), 안내의 장소 말은 deviceWord(C7)
    speech = (JS / "speech.js").read_text(encoding="utf-8")
    assert "export function voiceStatus" in speech and "dataset.voice" in speech and "deviceWord()" in speech
    assert 'html:not([data-voice="ready"]) .speak-btn' in CSS and 'html:not([data-voice="none"]) .voice-note' in CSS


def test_focus_is_kept_on_busy_and_sheet_close() -> None:
    # FE-04·FN-07: 하는 중 버튼은 disabled가 아니라 aria-disabled(초점 유지), 시트를 닫으면 연 버튼 → 위 시트 → 본문으로 초점
    ui = (JS / "ui.js").read_text(encoding="utf-8")
    busy = ui[ui.index("export async function busy"):ui.index("export function skeleton")]
    assert "disabled = true" not in busy and 'setAttribute("aria-disabled", "true")' in busy
    assert "function restoreFocus" in ui and "restoreFocus(returnFocus)" in ui
    assert "!sheet.contains(document.activeElement)" in ui      # Tab이 시트 밖으로 나가지 않게
    comp = (JS / "components.js").read_text(encoding="utf-8")
    assert "btn.disabled = true" not in comp
    assert '.btn[aria-disabled="true"]' in CSS


def test_toast_and_engine_bar_one_sentence_per_line() -> None:
    # C4: 토스트·엔진 띠도 문장마다 한 줄(p의 text → span.sent)
    ui = (JS / "ui.js").read_text(encoding="utf-8")
    toast = ui[ui.index("export function toast"):ui.index("// ---- 시트")]
    assert 'h("p", { text: message })' in toast
    main = (JS / "main.js").read_text(encoding="utf-8")
    bar = main[main.index("function engineSlot"):main.index("// ---- 시작")]
    assert 'h("p", { text: lines.join(" ") })' in bar and 'h("span", { text: err' not in bar
    assert ".engine-bar svg {" in CSS                            # FE-12: 경고 아이콘 크기


def test_contact_pick_single_window() -> None:
    # IA-5·AND-08: 연락처 창이 열려 있는 동안 다시 부르면 새 창을 열지 않고(앞 창 결과를 지킴) 안내와 함께 null
    native = (JS / "native.js").read_text(encoding="utf-8")
    pick = native[native.index("export function pickContact"):native.index("// ---- 내 은행 앱")]
    assert "if (pending) {" in pick and "toast(PICK_TEXT.busy)" in pick
    assert "pending.resolve(null); pending = null;" not in native   # 앞 창의 결과를 버리지 않는다
    assert "연락처를 불러오지 못했어요." in native


def test_engine_basic_after_ai_failure_and_fifo() -> None:
    # FE-03: AI 부분만 못 켜도 기본 요청(동의 끄기·모두 지우기)은 처리. FE-05: 우선 요청끼리는 온 순서대로
    worker = (WEB / "engine" / "worker.mjs").read_text(encoding="utf-8")
    assert "queue.unshift(" not in worker and "queue.splice(i, 0, msg)" in worker
    assert 'stage("error", "AI 분석 부분을 켜지 못했어요", String(e && e.message || e), false)' in worker
    client = (JS / "engine-client.js").read_text(encoding="utf-8")
    assert 'status.stage === "error" && status.fatal' in client


def test_common_layout_rules_for_large_text() -> None:
    # L3·L4·L9·L10·L11·L14·L8: 큰 글씨·좁은 화면·가로 화면 공용 규칙
    assert ".bottom-nav .nav-item { min-height: 0;" in CSS                       # L3 아래 탭 이름이 잘리지 않게
    assert ".notice svg { width: min(1.375rem, 6vw)" in CSS                       # L4 안내 상자 아이콘 상한
    assert ".notice > svg + * { flex: 1 1 9em;" in CSS                           # L4 아주 큰 글씨: 아이콘을 글 위 줄로
    assert ".table-wrap td.num::before { white-space: normal;" in CSS            # L9 숫자는 끊지 않고 칸 이름만 줄바꿈
    assert ".switch::before {" in CSS and "max(100%, 48px)" in CSS               # L11 스위치 누르는 자리 48px
    assert "@media (max-height: 480px) and (max-width: 899px)" in CSS            # L14 가로 화면
    assert "text-wrap: pretty" in CSS and "text-wrap: balance" in CSS            # L8 한두 글자 줄


def test_integration_contracts_2026_10_03() -> None:
    # 통합 점검: 백엔드·안드로이드가 만든 계약을 화면 공용 파일이 실제로 쓰는지
    api = (JS / "api.js").read_text(encoding="utf-8")
    assert 'form.append("mode", file.mode)' in api and "payload.mode = file.mode" in api   # 이어 붙여 올리기(AUG-03): PC·앱 모두
    assert 'export const UPLOAD_MODES = ["replace", "append"]' in api                    # txns.js가 고르기 창을 보이는 조건
    worker = (WEB / "engine" / "worker.mjs").read_text(encoding="utf-8")
    basic = re.search(r"const BASIC = new Set\(\[(.*?)\]\);", worker, re.S).group(1)
    for key in ("POST /api/reviews", "POST /api/reviews/remove", "POST /api/notices/remove",
                "POST /api/transactions/remove-checked"):
        assert f'"{key}"' in basic, key    # AI 패키지 없이 처리(test_v03_fixplan 가벼운 경로 시험)
    ui = (JS / "ui.js").read_text(encoding="utf-8")
    assert 'typeof native.setThemeMode === "function"' in ui                             # AND-04: 앱 설정 화면 모드 → 시스템 막대
    consent = _read_view("consent.js")
    assert '"내가 확인한 거래"' in consent and '"돈 보내기 확인 기록"' in consent          # IA-7: reviews.json·decisions.json도 지움
    java = (ROOT / "android" / "src" / "kr" / "safepause" / "mobile" / "MainActivity.java").read_text(encoding="utf-8")
    assert '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"' in java  # 앱 파일 고르기 창에서 .xlsx 선택
