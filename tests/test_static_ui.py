"""화면 파일(정적) 점검: 개인정보·쉬운 말·글자 크기 규칙이 코드에 남아 있는지."""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "safepause" / "server" / "static"
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")


def test_speech_uses_only_local_voices() -> None:
    """온라인 음성은 읽을 글(받는 사람·금액)을 밖으로 보내므로 쓰지 않는다(S35)."""
    assert "localService === true" in APP_JS
    assert "u.voice = koVoice" in APP_JS
    assert "voiceschanged" in APP_JS
    assert 'u.lang = "ko-KR"' not in APP_JS          # 목소리 없이 언어만 주면 브라우저가 온라인 음성을 고를 수 있음
    assert 'id="speech-note"' in INDEX


def test_no_hard_words_on_person_screens() -> None:
    # 등급 배지·조력자 설정·기록 안내(당사자가 보는 곳). ⑥ 성능 확인 표의 심사용 표기는 예외.
    level_block = APP_JS.split("const LEVEL = {")[1].split("};")[0]
    helper_form = APP_JS.split("function helperForm")[1].split("function renderHelpers")[0]
    for text in ("고위험", "주의"):
        assert text not in level_block and text not in helper_form, text
    for text in ("푸시", "당사자님"):
        assert text not in APP_JS and text not in INDEX, text


def test_no_claim_of_checked_bank_formats() -> None:
    assert "모든 금융기관의 파일 모양을 확인한 것은 아니에요" not in INDEX
    assert "은행 파일 모양은 따로 확인하지 못했어요" in INDEX


def test_font_size_not_reduced_on_small_screens() -> None:
    assert "118.75%" not in CSS
    sizes = [float(x) for x in re.findall(r"font-size:\s*([0-9.]+)rem", CSS)]
    assert sizes and min(sizes) >= 1.0                # 1rem = 20px(html 125%)
    assert "[hidden] { display: none !important; }" in CSS


def test_upload_size_checked_in_browser_and_wipe_clears_screen() -> None:
    assert "file.size > MAX_UPLOAD_BYTES" in APP_JS
    clear = APP_JS.split("function clearShownData")[1].split("async function doWipe")[0]
    # [변경 r2] 카드 모달·입력칸에 남은 받는 사람·금액·계좌번호·조력자 이름도 지운다
    for sel in ("#pay-result", "#upload-report", "#eval-mine-result", "#cards-list", "#notices-list",
                "#decisions-list", "#card-title", "#card-question", "#card-pictos", "#card-helper-note",
                "#helpers-list", "#pay-amount-easy", "#upload-mapping"):
        assert sel in clear, sel
    assert '$("#pay-form").reset()' in clear              # 받는 사람·금액·계좌번호 입력칸
    assert '$("#card-helper-note").hidden = true' in clear
    assert "state.pending = null" in APP_JS and "state.lastCheck = null" in APP_JS


def test_ask_helper_step_and_consent_notes() -> None:
    assert "openAskStep" in APP_JS and "helper_ids" in APP_JS
    assert 'id="card-ask"' in INDEX
    assert "30일 동안 3번 이상" in INDEX                # 상담 연결 조건(Settings.high_repeat_for_counseling)
    assert "이 스위치를 꺼도 직접 물어볼 수 있어요" in INDEX   # 조력자 알림을 꺼도 직접 물으면 알림
    assert ">지금 시각<" in INDEX


def _block(html: str, element_id: str) -> str:
    start = html.index(f'id="{element_id}"')
    return html[start:html.index("</div>", start)]


def test_consent_texts_are_short_sentences() -> None:
    """[변경 r2] 동의 설명은 쉬운 정보 원칙: 한 줄(문장·목록 항목)에 한 내용, 30자 안팎."""
    for element_id in ("c-monitoring-desc", "c-helper-desc", "c-counsel-desc"):
        block = _block(INDEX, element_id)
        items = re.findall(r"<(?:p|li)>([^<]+)</(?:p|li)>", block)
        assert len(items) >= (2 if element_id == "c-monitoring-desc" else 4), element_id
        for text in items:
            sentences = [x for x in re.split(r"(?<=[.?!])\s+", text.strip()) if x]
            assert len(sentences) == 1, text
            assert len(text) <= 32, text
            assert ":" not in text, text
    # ⑤ 안내는 ① 스위치 이름으로 부른다
    assert "상담 연결에 동의했을 때" not in INDEX
    assert "'상담하는 곳 알려 주기'를 켰을 때" in INDEX


def test_ask_step_is_truthful_and_card_is_escapable() -> None:
    ask = APP_JS.split("function openAskStep")[1].split("function closeAskStep")[0]
    # 고를 사람이 없으면 요청을 보내지 않고 까닭을 보여 준다(거짓 '물어봐요' 결과 방지)
    nobody = ask.split("if (!cands.some((c) => !c.conflict))")[1].split("return;")[0]
    assert "chooseDecision" not in nobody and "askNobodyLines" in nobody
    # 자동 알림 대상은 체크를 풀 수 없게 두고 까닭을 적는다('고른 사람에게만'이라고 하지 않음)
    assert "c.auto" in ask and "⑤에서 정한 대로" in ask
    assert "고른 사람에게만" not in APP_JS
    assert "speakButton(" in ask                          # 물어볼 사람 고르기도 소리로 듣기
    # 카드 음성은 조력자 안내도 읽는다
    speak = APP_JS.split("function cardSpeakText")[1].split("function closeCard")[0]
    assert "#card-helper-note" in speak
    # 결정 요청이 실패해도 모달에 갇히지 않는다
    choose = APP_JS.split("async function chooseDecision")[1].split("function closeCardAfterError")[0]
    assert "isConsentError(err)" in choose and "showUncheckedResult(" in choose
    assert "#card-close" in choose and 'id="card-close"' in INDEX
    # 고른 기록: 물어본 조력자가 없었으면 그렇게 적는다
    assert "x.asked === 0" in APP_JS and "물어보려 했지만 조력자가 없었어요" in APP_JS



# ---- 리뷰 수정 확인(round 3) ------------------------------------------------

def _tag(html: str, element_id: str) -> str:
    start = html.rindex("<", 0, html.index(f'id="{element_id}"'))
    return html[start:html.index(">", start)]


def test_sensitive_inputs_turn_off_spellcheck() -> None:
    """[변경 r3] 온라인 맞춤법 검사가 받는 사람·계좌번호·조력자 글을 브라우저 회사 서버로 보내지 않게(S35)."""
    assert '<body spellcheck="false">' in INDEX
    for element_id in ("pay-to", "pay-to-id", "pay-amount", "upload-mapping"):
        assert 'spellcheck="false"' in _tag(INDEX, element_id), element_id
    form = APP_JS.split("function helperForm")[1].split("function renderHelpers")[0]
    assert 'spellcheck: "false"' in form
    for field in ('"data-f": "name"', '"data-f": "identifiers"', '"data-f": "relation"', '"data-f": "contact"'):
        line = next(ln for ln in form.splitlines() if field in ln)
        assert "...noCheck" in line, field


def test_grid_columns_shrink_on_narrow_screens() -> None:
    """[변경 r3] minmax(20em, 1fr)처럼 em만 쓰면 320px(400% 확대)에서 가로로 넘친다. min(…, 100%)로 감싼다."""
    assert re.findall(r"minmax\(min\(", CSS)
    assert not re.findall(r"minmax\(\s*[0-9.]+em", CSS)


def test_result_speech_reads_everything_shown() -> None:
    """[변경 r3] 결과 화면의 '소리로 듣기'는 상담 안내·기록 안내도 읽고, 카드 음성은 등급 배지도 읽는다."""
    result = APP_JS.split("function showPayResult")[1].split("// ---- ④ 알림 카드")[0]
    assert "spokenParts.push(COUNSELING_TITLE" in result and "spokenParts.push(recorded)" in result
    unchecked = APP_JS.split("function showUncheckedResult")[1].split("// 카드 모달")[0]
    assert "speakButton(" in unchecked
    speak = APP_JS.split("function cardSpeakText")[1].split("function closeCard")[0]
    assert "LEVEL[r.card.level]" in speak and "state.cardHelperText" in speak
    assert 'notes.join(" ")' in APP_JS


def test_speech_note_shown_when_browser_has_no_speech_api() -> None:
    assert "SPEECH_NOTE_NO_API" in APP_JS and "이 브라우저에서는 '소리로 듣기'를 쓸 수 없어요." in APP_JS
    pick = APP_JS.split("function pickVoice")[1].split("function speak(")[0]
    assert "if (!canSpeak) return;" not in pick          # 음성 기능이 없어도 안내는 보여 준다


def test_ask_step_texts_match_level_and_auto_rules() -> None:
    ask = APP_JS.split("function openAskStep")[1].split("function closeAskStep")[0]
    assert 'r.card.level === "high" ? "꼭 확인할 일이라" : "확인할 일이라"' in ask
    assert "⑤에서 정한 대로 꼭 알려요" not in APP_JS
    preview = APP_JS.split("function askPreviewText")[1].split("function fillWith")[0]
    assert "다른 사람을 더할 수 있어요" in preview
    assert "등록한 조력자가 없어요" not in APP_JS and "물어볼 수 있는 조력자가 없어요" in APP_JS


def test_helper_active_switch_is_auto_alert_only() -> None:
    """[변경 r3] ⑤의 체크는 '자동으로 알리기'. 꺼도 직접 물어볼 때는 고를 수 있다고 알린다."""
    form = APP_JS.split("function helperForm")[1].split("function renderHelpers")[0]
    assert "이 조력자에게 자동으로 알리기" in form and "'조력자에게 물어볼래요'로 고를 때만 알려요" in form
    assert '"이 조력자에게 알리기"' not in APP_JS


def test_turning_off_monitoring_clears_payee_names() -> None:
    """[변경 r3] '거래 살펴보기'를 끄면 받는 사람 자동완성 등 분석 결과를 화면에서 바로 지운다(S37)."""
    toggle = APP_JS.split("async function toggleConsent")[1].split("async function changeGivenBy")[0]
    assert 'key === "monitoring" && !next' in toggle and "clearAnalysisViews()" in toggle
    clear = APP_JS.split("function clearAnalysisViews")[1].split("async function changeGivenBy")[0]
    assert "#payee-list" in clear and "#txn-list" in clear and "#cards-list" in clear
    practice = APP_JS.split("async function loadPractice")[1].split("function parseAmount")[0]
    assert "isConsentError(e)" in practice and '$("#payee-list").replaceChildren()' in practice


def test_learned_count_says_span_and_rows() -> None:
    """AI 학습 안내는 학습 구간 거래 수와 실제 학습 행 수(평소 기준이 없는 맨 앞 거래를 뺌)를 구분한다."""
    assert "건으로 평소 모습을 배웠어요.`" not in APP_JS.split("function learnedText")[0]
    learned = APP_JS.split("function learnedText")[1].split("function learnedRows")[0]
    assert "rows < span" in learned and "비교할 평소가 없어서 뺐어요" in learned
    assert "learnedText(data.model.train_count, data.model.train_rows)" in APP_JS
    assert "learnedRows(r.n_baseline, r.n_train_rows)" in APP_JS
