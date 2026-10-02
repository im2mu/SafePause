"""화면(safepause/web) 정적 검사: 쉬운 말 규칙·꼭 남길 문장·문구 규칙·접근성·보안·오프라인(v0.3 화면).

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
PERSON_VIEWS = ["home.js", "txns.js", "notify.js", "alerts.js", "consent.js", "helpers.js", "counselors.js",
                "onboarding.js", "more.js", "settings.js", "export.js"]
# 당사자 화면이 같이 쓰는 공용 모듈(글이 당사자에게 보인다)
PERSON_COMMON = ["js/main.js", "js/ui.js", "js/components.js", "js/labels.js", "js/format.js", "js/native.js",
                 "js/speech.js", "js/views/connect.js"]
EASY_FORBIDDEN = [*FORBIDDEN_WORDS, "이상거래", "패턴", "탐지", "알고리즘", "모니터링", "이례", "임계", "통계",
                  "고위험", "푸시", "당사자님"]
# 설계서 7절: 화면에 쓰지 않는 문구(송금 연습 흔적·불필요한 안내·접속 주소)
BANNED_PHRASES = ["막지 않아요", "결정은 내가 해요", "AI 혼자서는", "연습 화면", "실제로 돈이 나가지 않아요",
                  "보내지 않고 멈춘 것", "연습용 정답", "(가려서 저장해요)", "127.0.0.1", "안전 정지"]
VIEW_ROUTES = {"home": "home.js", "txns": "txns.js", "send": "notify.js", "alerts": "alerts.js", "more": "more.js",
               "more/consent": "consent.js", "more/helpers": "helpers.js", "more/counselors": "counselors.js",
               "more/settings": "settings.js", "more/eval": "eval.js", "more/export": "export.js",
               "more/about": "about.js", "onboarding": "onboarding.js"}


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
    # 화면별 CSS 4개는 index.html에 연결돼 있다
    for name in ("home", "txns", "notify", "more"):
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
    for view in ("notify.js", "helpers.js", "counselors.js"):
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


def test_no_money_transfer_screens() -> None:
    # 0절: 송금·결제 기능 없음. 송금 연습 화면과 그 API를 화면에서 부르지 않는다
    for gone in ("send.js", "data.js", "notices.js"):
        assert not (VIEWS / gone).exists(), gone
    for path in ("/api/safepause/check", "/api/safepause/decide", "/api/payees"):
        assert path not in JOINED, path


def test_alert_and_notify_rules() -> None:
    # 소리 버튼 토글(R4): 누르면 재생 ↔ 멈추기, 한 번에 하나, 끝나면 원래대로(앱 끝남 알림 연결)
    comp = (JS / "components.js").read_text(encoding="utf-8")
    assert 'aria-pressed' in comp and "speech.stop()" in comp and "onEnd: () => paint(false)" in comp
    speech = (JS / "speech.js").read_text(encoding="utf-8")
    assert "window.__safepauseSpeechDone" in speech and "export function isSpeaking" in speech
    # 알림 탭: 쉬운 말 카드마다 알리기(→ 알림 보내기)
    alerts = _read_view("alerts.js")
    assert "send?txn=" in alerts
    assert "alertCard" in alerts or "speakButton" in alerts
    # 알림 보내기(R8): 문자·메일 앱을 열고, 연 뒤에 기록한다. 번호·메일 원본은 기록에 넣지 않는다(서버)
    notify = _read_view("notify.js")
    assert "openExternal" in notify and "/api/notices/record" in notify
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
    for key in ("/api/flags", "/api/insights", "/api/decisions"):
        assert key not in basic, key


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
