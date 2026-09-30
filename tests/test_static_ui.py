"""화면(safepause/web) 정적 검사: 쉬운 말 규칙·꼭 남길 문장·접근성·보안·오프라인(v0.2 새 화면).

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
CSS = (WEB / "css" / "app.css").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
ALL_JS = {p.relative_to(WEB).as_posix(): p.read_text(encoding="utf-8")
          for p in sorted(WEB.rglob("*")) if p.suffix in (".js", ".mjs")}
JOINED = "\n".join(ALL_JS.values())

# 당사자가 보는 화면(보호자·심사용 화면 eval·about은 전문 용어 예외)
PERSON_VIEWS = ["home.js", "txns.js", "send.js", "alerts.js", "consent.js", "helpers.js", "notices.js",
                "onboarding.js", "more.js", "data.js"]


def _string_literals(js: str) -> list[str]:
    """JS 문자열 리터럴(따옴표·백틱) 안의 글만 뽑는다(주석·코드 이름 제외)."""
    no_comments = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    no_comments = re.sub(r"(?m)^\s*//.*$", "", no_comments)
    return re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', no_comments)


def _visible_text(js: str) -> str:
    return "\n".join(a or b for a, b in _string_literals(js))


def test_font_size_not_reduced() -> None:
    # SPEC 접근성: 기본 글자 20px 이상(html 125%, 1rem = 20px). 모든 글자 크기는 1rem 이상.
    assert "html { font-size: 125%;" in CSS
    sizes = [float(x) for x in re.findall(r"font-size:\s*([0-9.]+)rem", CSS)]
    assert sizes and min(sizes) >= 1.0
    assert not re.search(r"font-size:\s*[0-9.]+px", CSS)


def test_touch_targets_at_least_48px() -> None:
    # 버튼 최소 높이(1rem = 20px 기준): 2.4rem = 48px 이상
    for sel in (".btn", ".icon-btn", ".chip", ".row"):
        block = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", CSS)
        assert block, sel
    heights = [float(x) for x in re.findall(r"min-height:\s*([0-9.]+)rem", CSS)]
    assert min(heights) >= 2.4 or all(h >= 2.4 for h in heights if h >= 2)


def test_no_external_resources_and_csp() -> None:
    for name, text in {**ALL_JS, "index.html": INDEX, "app.css": CSS}.items():
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), name
        assert "@import" not in text and "fonts.googleapis" not in text, name
    assert "Content-Security-Policy" in INDEX and "default-src 'self'" in INDEX
    assert "script-src 'self' 'wasm-unsafe-eval'" in INDEX       # 앱 안 파이썬(웹어셈블리)만 추가 허용
    assert "<script>" not in INDEX and "onclick=" not in INDEX   # 인라인 스크립트 없음


def test_no_html_injection_apis() -> None:
    # 서버·엔진이 준 글(받는 사람 이름 등)은 textContent로만 넣는다(XSS 차단)
    for name, text in ALL_JS.items():
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert bad not in text, (name, bad)
        assert 'setAttribute("style"' not in text, name   # CSP가 막는 인라인 style 속성 대신 CSSOM


def test_spellcheck_and_autocorrect_off() -> None:
    # 받는 사람·계좌번호·금액·조력자 입력이 브라우저의 온라인 맞춤법 검사로 나가지 않게(S35)
    assert '<body spellcheck="false">' in INDEX
    for view in ("send.js", "helpers.js"):
        text = (VIEWS / view).read_text(encoding="utf-8")
        assert 'spellcheck: "false"' in text and 'autocorrect: "off"' in text and 'autocapitalize: "off"' in text


@pytest.mark.parametrize("phrase", [
    "연습 화면이에요. 실제로 돈이 나가지 않아요.",
    "SafePause는 막지 않아요.",
    "걱정되면 한 번 더 물어볼 뿐이에요. 결정은 내가 해요.",
    "은행 파일 모양은 따로 확인하지 못했어요.",
    "이 조력자에게 자동으로 알리기",
    "끄면 자동으로는 알리지 않아요. 카드에서 '조력자에게 물어볼래요'로 고를 때만 알려요.",
    "꼭 확인할 일이 30일 동안 3번 이상 생길 때",
    "이 스위치를 꺼도 직접 물어볼 수 있어요.",
    "'동의'에서 '상담하는 곳 알려 주기'를 켰을 때만이에요.",
    "언제든지 끌 수 있어요. 끄면 바로 멈춰요.",
    "알림은 기록만 해요.",
    "합성 데이터 기준, 실제 피해 데이터 검증 아님",
    "정말 모두 지울까요?",
])
def test_required_phrases_kept(phrase: str) -> None:
    assert phrase in JOINED, phrase


@pytest.mark.parametrize("view", PERSON_VIEWS)
def test_person_views_use_easy_words(view: str) -> None:
    text = _visible_text((VIEWS / view).read_text(encoding="utf-8"))
    for word in [*FORBIDDEN_WORDS, "이상거래", "패턴", "탐지", "알고리즘", "모니터링", "이례", "임계", "통계",
                 "고위험", "푸시", "당사자님"]:
        assert word not in text, (view, word)
    assert not re.search(r"(?<![가-힣])주의(?![가-힣])", text), view   # '주의' 단독(전문 용어) 금지


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


def test_safe_pause_card_rules() -> None:
    send = (VIEWS / "send.js").read_text(encoding="utf-8")
    # 초점은 제목, 등급을 대화상자 이름에(리뷰 M4), 닫을 수 없는 카드(Esc·뒤로 가기는 '안 보낼래요'로 초점만)
    assert 'initialFocus: "#card-title"' in send
    assert 'aria-labelledby", "card-level card-title"' in send
    assert "dismissible: false" in send
    assert "[data-decision=\"cancel\"]" in send
    # 선택지는 서버가 준 순서·문구 그대로
    assert "card.choices.map" in send
    # 카드 없으면 바로 '보냈어요'(막지 않음), 동의가 없어도 막지 않고 결과를 보여 줌
    assert 'await decide("send", null, null)' in send and "showUnchecked(req)" in send
    # 금액은 한국어 단위를 읽는다(리뷰 H2)
    assert "parseKoreanAmount" in send


def test_stale_response_guard() -> None:
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert "session.epoch !== epoch" in main and "throw STALE" in main
    assert "ctx.session.bumpEpoch()" in (VIEWS / "consent.js").read_text(encoding="utf-8")
    assert "ctx.session.bumpEpoch()" in (VIEWS / "data.js").read_text(encoding="utf-8")


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
