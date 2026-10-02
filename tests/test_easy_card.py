"""explain/easy_card.py 테스트."""
from __future__ import annotations

import itertools
from datetime import datetime, time

import pytest

from safepause.explain.easy_card import (
    ANOMALY_FEATURE_GROUPS,
    COMMON_QUESTION,
    FORBIDDEN_WORDS,
    PAST_QUESTION,
    PICTOGRAMS,
    build_card,
    format_time_kr,
    format_won,
    practice_result,
    readability_issues,
    render_card,
    to_whom,
)
from safepause.models import (
    AlertCard,
    Channel,
    Decision,
    Direction,
    Reason,
    RiskAssessment,
    RiskLevel,
    SignalCode,
    SignalHit,
    Transaction,
)


def make_txn(amount: int = 300_000, hour: int = 2, minute: int = 0, counterparty: str = "홍길동",
             channel: Channel = Channel.TRANSFER, txn_id: str = "t1") -> Transaction:
    return Transaction(id=txn_id, ts=datetime(2026, 9, 1, hour, minute), amount=amount,
                       direction=Direction.OUT, channel=channel, counterparty=counterparty,
                       counterparty_id="110-123-456789")


def make_assessment(hits: list[SignalHit], level: RiskLevel | None = None,
                    reasons: list[Reason] | None = None, txn_id: str = "t1") -> RiskAssessment:
    if level is None:
        level = RiskLevel.HIGH if any(h.severity == RiskLevel.HIGH for h in hits) else RiskLevel.CAUTION
    if reasons is None:
        reasons = [Reason(code=h.code.value, detail=dict(h.evidence)) for h in hits]
    return RiskAssessment(txn_id=txn_id, level=level, rule_hits=hits, anomaly_score=0.5,
                          reasons=reasons)


# ---- 금액·시각 포맷 -------------------------------------------------------

@pytest.mark.parametrize("amount, expected", [
    (0, "0원"),
    (800, "800원"),
    (1_000, "1천 원"),
    (5_000, "5천 원"),
    (9_500, "1만 원"),
    (10_000, "1만 원"),
    (125_400, "12만 5천 원"),
    (300_000, "30만 원"),
    (1_500_000, "150만 원"),
    (99_999_499, "9,999만 9천 원"),
    (99_999_500, "1억 원"),
    (120_000_000, "1억 2,000만 원"),
    (1_000_000_000_000, "1조 원"),
    (1_234_500_000_000, "1조 2,345억 원"),
])
def test_format_won(amount: int, expected: str) -> None:
    assert format_won(amount) == expected


def test_format_won_rejects_negative() -> None:
    with pytest.raises(ValueError):
        format_won(-1)


@pytest.mark.parametrize("hour, minute, expected", [
    (0, 30, "밤 12시 30분"),
    (2, 0, "새벽 2시"),
    (5, 59, "새벽 5시 59분"),
    (7, 5, "아침 7시 5분"),
    (10, 0, "오전 10시"),
    (12, 0, "낮 12시"),
    (15, 20, "오후 3시 20분"),
    (19, 0, "저녁 7시"),
    (23, 0, "밤 11시"),
])
def test_format_time_kr(hour: int, minute: int, expected: str) -> None:
    assert format_time_kr(datetime(2026, 9, 1, hour, minute)) == expected


def test_format_time_kr_accepts_time_and_hides_minutes() -> None:
    assert format_time_kr(time(2, 40), with_minutes=False) == "새벽 2시"
    assert format_time_kr(time(2, 40)) == "새벽 2시 40분"


# ---- 카드 기본 -----------------------------------------------------------

def test_none_level_returns_none() -> None:
    assessment = RiskAssessment(txn_id="t1", level=RiskLevel.NONE, rule_hits=[],
                                anomaly_score=0.1, reasons=[])
    assert render_card(assessment, make_txn()) is None


def test_night_template_matches_spec_example() -> None:
    hit = SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, RiskLevel.HIGH, {"count_7d": 4},
                    ["a", "b", "c", "t1"])
    card = render_card(make_assessment([hit]), make_txn())
    assert card is not None
    assert card.title == "밤에 돈을 자주 보냈어요"
    # 근거 건수(4)는 보내려는 이번 거래를 포함한다 → '이번이 4번째'
    assert card.lines == ["요즘 밤늦게 돈을 여러 번 보냈어요.", "7일 동안 이번이 4번째예요.", "누가 시켰나요?"]
    assert card.pictograms == ["moon", "money", "question"]
    assert card.level == RiskLevel.HIGH
    assert card.source == "template"
    # 이미 끝난 거래의 기록 카드: 과거형, '이번 주' 대신 '7일 동안', 묻지 않음
    past = render_card(make_assessment([hit]), make_txn(), past=True)
    assert past is not None
    # [변경 r3] 기록 카드는 '요즘'(지금 기준) 대신 '그때'
    assert past.lines == ["그때 밤늦게 돈을 여러 번 보냈어요.", "7일 동안 4번 보냈어요.", "누가 시켰나요?"]
    assert past.question == PAST_QUESTION and past.choices == []
    assert past.speak_text.endswith(PAST_QUESTION)


def test_common_question_choices_and_speak_text() -> None:
    hit = SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, RiskLevel.HIGH, {"count_7d": 4})
    card = render_card(make_assessment([hit]), make_txn(channel=Channel.TRANSFER))
    assert card is not None
    assert card.question == COMMON_QUESTION == "이 돈을 정말 보내는 것이 맞나요?"
    assert card.choices == [
        {"decision": "send", "label": "그래도 보낼래요"},
        {"decision": "cancel", "label": "안 보낼래요"},
        {"decision": "ask_helper", "label": "조력자에게 물어볼래요"},
    ]
    assert card.speak_text.startswith(card.title)
    for piece in [*card.lines, card.question]:
        assert piece in card.speak_text
    assert card.speak_text.endswith(card.question)


@pytest.mark.parametrize("channel, question, go, stop", [
    (Channel.CARD, "이 돈을 정말 내는 것이 맞나요?", "그래도 낼래요", "안 낼래요"),
    (Channel.MICROPAY, "이 돈을 정말 내는 것이 맞나요?", "그래도 낼래요", "안 낼래요"),
    (Channel.TELECOM_BILL, "이 요금을 정말 내는 것이 맞나요?", "그래도 낼래요", "안 낼래요"),
    (Channel.ATM, "이 돈을 정말 찾는 것이 맞나요?", "그래도 찾을래요", "안 찾을래요"),
])
def test_question_and_choices_follow_channel(channel: Channel, question: str, go: str, stop: str) -> None:
    """결제·요금·현금 찾기에는 '보내다'를 쓰지 않는다(쉬운 정보: 정확한 말)."""
    hit = SignalHit(SignalCode.MICROPAY_SURGE, RiskLevel.CAUTION, {"count_7d": 6})
    card = render_card(make_assessment([hit]), make_txn(channel=channel))
    assert card is not None
    assert card.question == question
    assert [c["label"] for c in card.choices] == [go, stop, "조력자에게 물어볼래요"]
    assert "보내" not in card.question + "".join(c["label"] for c in card.choices)


def test_count_falls_back_to_related_ids() -> None:
    hit = SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, RiskLevel.HIGH, {}, ["a", "b", "t1"])
    card = render_card(make_assessment([hit]), make_txn())
    assert card is not None
    assert "7일 동안 이번이 3번째예요." in card.lines


def test_payee_template_uses_short_name_and_sum() -> None:
    hit = SignalHit(SignalCode.PAYEE_SURGE, RiskLevel.HIGH, {"count_7d": 5, "sum_7d": 1_500_000})
    card = render_card(make_assessment([hit]), make_txn(counterparty="홍길동"))
    assert card is not None
    assert card.lines[0] == "홍길동에게 돈을 자주 보냈어요."
    assert "이번 돈까지 모두 150만 원이에요." in card.lines
    # 긴 이름·숫자 섞인 이름은 일반 표현으로
    card2 = render_card(make_assessment([hit]), make_txn(counterparty="아주아주긴이름의상대방"))
    assert card2 is not None and card2.lines[0] == "이 사람에게 돈을 자주 보냈어요."
    card3 = render_card(make_assessment([hit]), make_txn(counterparty="계좌110123"))
    assert card3 is not None and card3.lines[0] == "이 사람에게 돈을 자주 보냈어요."


def test_new_merchant_topic_particle() -> None:
    hit = SignalHit(SignalCode.NEW_MERCHANT_HIGH_VALUE, RiskLevel.CAUTION, {})
    card = render_card(make_assessment([hit]), make_txn(counterparty="행복마트", channel=Channel.CARD))
    assert card is not None and card.lines[0] == "행복마트는 처음 가는 가게예요."
    card = render_card(make_assessment([hit]), make_txn(counterparty="우리식당", channel=Channel.CARD))
    assert card is not None and card.lines[0] == "우리식당은 처음 가는 가게예요."
    card = render_card(make_assessment([hit]), make_txn(counterparty="GS", channel=Channel.CARD))
    assert card is not None and card.lines[0] == "처음 가는 가게예요."
    assert "이번 결제는 30만 원이에요." in card.lines


def test_primary_hit_is_highest_severity_and_extra_line() -> None:
    caution = SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, RiskLevel.CAUTION, {"count_7d": 2})
    high = SignalHit(SignalCode.MICROPAY_SURGE, RiskLevel.HIGH, {"count_7d": 9})
    card = render_card(make_assessment([caution, high]), make_txn(channel=Channel.MICROPAY))
    assert card is not None
    assert card.title == "휴대폰 결제가 많아요"
    assert "걱정되는 점이 1가지 더 있어요." in card.lines
    assert card.lines[-1] == "누가 결제해 달라고 했나요?"  # 질문은 마지막 줄


@pytest.mark.parametrize("feature", sorted(ANOMALY_FEATURE_GROUPS) + ["unknown_feature"])
def test_anomaly_only_cards(feature: str) -> None:
    reasons = [Reason(code=f"anomaly:{feature}", detail={"z": 4.2})]
    assessment = make_assessment([], level=RiskLevel.CAUTION, reasons=reasons)
    card = render_card(assessment, make_txn())
    assert card is not None
    assert card.level == RiskLevel.CAUTION
    assert readability_issues(card) == []


def test_unknown_feature_and_no_reason_use_generic_card() -> None:
    generic = render_card(make_assessment([], RiskLevel.CAUTION, []), make_txn())
    unknown = render_card(make_assessment([], RiskLevel.CAUTION,
                                          [Reason("anomaly:mystery", {})]), make_txn())
    assert generic is not None and unknown is not None
    assert generic.title == unknown.title == "한 번 더 확인해요"


def test_anomaly_amount_and_time_use_txn_values() -> None:
    amount_card = render_card(make_assessment([], RiskLevel.CAUTION, [Reason("anomaly:amount_vs_p95", {})]),
                              make_txn(amount=450_000))
    assert amount_card is not None and amount_card.lines[0] == "이번 돈은 45만 원이에요."
    time_card = render_card(make_assessment([], RiskLevel.CAUTION, [Reason("anomaly:hour_sin", {})]),
                            make_txn(hour=2, minute=10))
    assert time_card is not None and time_card.lines[0] == "새벽 2시 10분에 돈이 나가요."
    assert time_card.pictograms[0] == "moon"


def test_render_is_deterministic() -> None:
    hit = SignalHit(SignalCode.PAYEE_SURGE, RiskLevel.HIGH, {"count_7d": 5, "sum_7d": 900_000})
    a = render_card(make_assessment([hit]), make_txn())
    b = render_card(make_assessment([hit]), make_txn())
    assert a == b


# ---- 모든 템플릿 조합의 가독성 -------------------------------------------

EVIDENCE_VARIANTS = [
    ({}, []),
    ({}, ["x1"]),
    ({"count_7d": 4, "sum_7d": 1_500_000, "distinct_lines_30d": 3}, ["x1", "x2", "x3", "x4"]),
    ({"count_7d": 999, "sum_7d": 9_999_999_999_999_999 // 1000}, []),
    ({"count": 2.0, "total": 12_345}, ["x1", "x2"]),
    ({"new_lines": ["010-****-1111", "010-****-2222"]}, []),
]
AMOUNTS = [1, 999, 12_345, 300_000, 99_999_999, 9_999_999_999_999_999 // 1000]
NAMES = ["", "홍길동", "아주아주긴이름의상대방", "행복마트", "ABC", "김*수", "패턴상사", "이 름"]
CHANNELS = [Channel.TRANSFER, Channel.CARD, Channel.MICROPAY, Channel.TELECOM_BILL]
# 이상탐지 카드는 시각·채널을 쓰므로 모든 조합, 시그널 카드는 이름·금액·채널 조합
TXN_VARIANTS = [
    make_txn(amount=a, hour=h, minute=m, counterparty=name, channel=ch)
    for a, h, m, name, ch in itertools.product(AMOUNTS, [0, 2, 12, 15, 23], [0, 59], NAMES, CHANNELS)
]
SIGNAL_TXN_VARIANTS = [
    make_txn(amount=a, hour=h, minute=59, counterparty=name, channel=ch)
    for a, h, name, ch in itertools.product(AMOUNTS, [2, 15], NAMES, CHANNELS)
]


def _all_template_cards() -> list[AlertCard]:
    cards: list[AlertCard] = []
    # 1) 시그널 하나씩
    for code, severity, (evidence, related), txn in itertools.product(
            SignalCode, [RiskLevel.CAUTION, RiskLevel.HIGH], EVIDENCE_VARIANTS, SIGNAL_TXN_VARIANTS):
        hit = SignalHit(code, severity, dict(evidence), list(related))
        card = render_card(make_assessment([hit]), txn)
        assert card is not None
        cards.append(card)
    # 2) 시그널 여러 개(두 개 조합 + 다섯 개 모두)
    evidence, related = EVIDENCE_VARIANTS[2]
    combos = list(itertools.combinations(SignalCode, 2)) + [tuple(SignalCode)]
    for combo in combos:
        for sev in (RiskLevel.CAUTION, RiskLevel.HIGH):
            hits = [SignalHit(c, sev, dict(evidence), list(related)) for c in combo]
            for txn in SIGNAL_TXN_VARIANTS[::5]:
                card = render_card(make_assessment(hits), txn)
                assert card is not None
                cards.append(card)
    # 3) 이상탐지 사유 단독
    for feature, txn in itertools.product(list(ANOMALY_FEATURE_GROUPS) + ["other"], TXN_VARIANTS):
        assessment = make_assessment([], RiskLevel.CAUTION, [Reason(f"anomaly:{feature}", {})])
        card = render_card(assessment, txn)
        assert card is not None
        cards.append(card)
    # 4) 사유 없음
    for txn in TXN_VARIANTS[::11]:
        card = render_card(make_assessment([], RiskLevel.CAUTION, []), txn)
        assert card is not None
        cards.append(card)
    return cards


def test_payee_single_first_transfer_never_says_often() -> None:
    """근거 건수가 1건(보내려는 이번 돈뿐)이면 '자주·여러 번'이라고 말하지 않는다."""
    hit = SignalHit(SignalCode.PAYEE_SURGE, RiskLevel.CAUTION,
                    {"count_7d": 1, "sum_7d": 300_000, "first_seen_days_ago": None})
    card = render_card(make_assessment([hit]), make_txn(counterparty="김*호"))
    assert card is not None
    text = " ".join([card.title, *card.lines])
    assert "자주" not in text and "여러 번" not in text and "번째" not in text
    assert card.title == "처음 보내는 사람이에요"
    assert card.lines[0] == "김*호에게 처음 보내는 돈이에요."
    assert "이번 돈은 30만 원이에요." in card.lines


def test_payee_second_transfer_is_not_often() -> None:
    """앞서 1번 보낸 뒤 2번째(보내기 전): 아직 '자주'가 아니다."""
    hit = SignalHit(SignalCode.PAYEE_SURGE, RiskLevel.CAUTION,
                    {"count_7d": 2, "sum_7d": 600_000, "first_seen_days_ago": 1.0})
    card = render_card(make_assessment([hit]), make_txn(counterparty="김*호"))
    assert card is not None
    assert "자주" not in " ".join([card.title, *card.lines])
    assert "7일 동안 이번이 2번째예요." in card.lines
    assert "이번 돈까지 모두 60만 원이에요." in card.lines


def test_night_two_pending_is_not_many_times() -> None:
    hit = SignalHit(SignalCode.NIGHT_REPEAT_TRANSFER, RiskLevel.CAUTION, {"count_7d": 2})
    card = render_card(make_assessment([hit]), make_txn())
    assert card is not None
    text = " ".join([card.title, *card.lines])
    assert "자주" not in text and "여러 번" not in text
    assert "7일 동안 이번이 2번째예요." in card.lines


def test_place_names_use_e_not_ege() -> None:
    """사람이 아닌 받는 곳(모임 회비 등)에는 '에게' 대신 '에'를 붙인다."""
    assert to_whom("활동 모임 회비") == "활동 모임 회비에"
    assert to_whom("엄마") == "엄마에게" and to_whom("김*호") == "김*호에게"
    assert to_whom("계좌110123") == "이 사람에게"
    hit = SignalHit(SignalCode.PAYEE_SURGE, RiskLevel.HIGH, {"count_7d": 5, "sum_7d": 500_000})
    card = render_card(make_assessment([hit]), make_txn(counterparty="활동 모임 회비"))
    assert card is not None and card.lines[0] == "활동 모임 회비에 돈을 자주 보냈어요."
    assert card.title == "한 곳에 많이 보냈어요"


def test_practice_result_uses_channel_words() -> None:
    card_txn = make_txn(amount=800_000, counterparty="새로 연 전자상가", channel=Channel.CARD)
    title, lines = practice_result(Decision.CANCEL, card_txn)
    assert title == "결제하지 않았어요"
    assert lines == ["새로 연 전자상가에서 80만 원을 결제하지 않았어요."]
    assert "에게" not in lines[0] and "보내" not in lines[0]
    title, lines = practice_result(Decision.SEND, make_txn(counterparty="엄마", amount=50_000))
    assert (title, lines) == ("보냈어요 (연습)", ["엄마에게 5만 원을 보냈어요."])
    title, lines = practice_result(Decision.ASK_HELPER, make_txn(channel=Channel.MICROPAY))
    assert lines == ["휴대폰으로 30만 원을 결제하기 전에 조력자에게 물어봐요.", "아직 결제하지 않았어요."]


def test_every_template_combination_is_readable() -> None:
    cards = _all_template_cards()
    assert len(cards) > 1000
    for card in cards:
        assert readability_issues(card) == [], (card.title, card.lines, readability_issues(card))
        assert 1 <= len(card.lines) <= 4
        assert card.pictograms and set(card.pictograms) <= PICTOGRAMS
        assert len(card.choices) == 3


# ---- 가독성 검사기 자체 --------------------------------------------------

def _card(title: str = "제목", lines: list[str] | None = None) -> AlertCard:
    return build_card("t1", RiskLevel.CAUTION, title, lines or ["짧은 문장이에요."], ["warning"])


def test_readability_flags_each_rule() -> None:
    assert readability_issues(_card()) == []
    assert any("15자 초과" in s for s in readability_issues(_card(title="가" * 16)))
    assert any("30자 초과" in s for s in readability_issues(_card(lines=["가" * 31])))
    assert any("4줄 초과" in s for s in readability_issues(_card(lines=["한 줄이에요."] * 5)))
    assert any("문장 여러 개" in s for s in readability_issues(_card(lines=["보냈어요. 또 보냈어요."])))
    assert any("긴 숫자" in s for s in readability_issues(_card(lines=["300,000원을 보냈어요."])))
    assert any("시각" in s for s in readability_issues(_card(lines=["02:30에 보냈어요."])))


def test_empty_lines_flagged() -> None:
    card = AlertCard("t1", RiskLevel.CAUTION, "제목", [], ["warning"], COMMON_QUESTION, [], "제목")
    assert any("줄 없음" in s for s in readability_issues(card))


@pytest.mark.parametrize("word", FORBIDDEN_WORDS)
def test_readability_flags_forbidden_words(word: str) -> None:
    issues = readability_issues(_card(lines=[f"{word}이 있어요."]))
    assert any(word in s for s in issues)


def test_forbidden_word_with_spaces_is_flagged() -> None:
    assert readability_issues(_card(lines=["이상 거래가 있어요."]))


def test_build_card_rejects_unknown_pictogram() -> None:
    with pytest.raises(ValueError):
        build_card("t1", RiskLevel.CAUTION, "제목", ["문장이에요."], ["rocket"])


_SLOW_DOWN_TEXT = "천천히 한 번 더 생각해요."


def test_every_past_card_is_readable_and_asks_nothing() -> None:
    """④ 기록 카드(past=True)도 쉬운 정보 원칙을 지키고, 지금 보낼지 묻지 않는다."""
    n = 0
    for code, severity, (evidence, related), txn in itertools.product(
            SignalCode, [RiskLevel.CAUTION, RiskLevel.HIGH], EVIDENCE_VARIANTS, SIGNAL_TXN_VARIANTS[::3]):
        card = render_card(make_assessment([SignalHit(code, severity, dict(evidence), list(related))]),
                           txn, past=True)
        assert card is not None
        assert readability_issues(card) == [], (card.title, card.lines, readability_issues(card))
        assert card.question == PAST_QUESTION and card.choices == []
        assert all("이번이" not in line and "이번 주" not in line for line in card.lines)
        n += 1
    for feature, txn in itertools.product(list(ANOMALY_FEATURE_GROUPS) + ["other"], TXN_VARIANTS[::7]):
        card = render_card(make_assessment([], RiskLevel.CAUTION, [Reason(f"anomaly:{feature}", {})]),
                           txn, past=True)
        assert card is not None and readability_issues(card) == []
        assert _SLOW_DOWN_TEXT not in card.lines   # 끝난 거래에 '한 번 더 생각해요'는 맞지 않음
        n += 1
    assert n > 300


def test_synthetic_cards_do_not_claim_often_without_history() -> None:
    """합성 데이터 전체 카드에서: '자주·여러 번'은 이미 2건 이상 이뤄졌을 때만 쓴다."""
    from safepause.detect.engine import RiskEngine
    from safepause.eval.metrics import synthetic_case

    checked = 0
    for persona in ("worker", "benefit", "student"):
        for seed in (1, 2, 3):
            case = synthetic_case(persona, seed)
            engine = RiskEngine(seed=seed).fit(case.baseline_normal)
            assessed = engine.assess_many(case.evaluated, history=case.baseline)
            for txn, a in zip(case.evaluated, assessed):
                if not a.rule_hits:
                    continue
                hit = min(a.rule_hits, key=lambda h: (h.severity != RiskLevel.HIGH,
                                                      list(SignalCode).index(h.code)))
                n = hit.evidence.get("count_7d")
                for past in (False, True):
                    card = render_card(a, txn, past=past)
                    assert card is not None and readability_issues(card) == []
                    text = " ".join([card.title, *card.lines])
                    claims_often = ("자주" in text or "여러 번" in text)
                    if isinstance(n, int) and claims_often and hit.code in (
                            SignalCode.NIGHT_REPEAT_TRANSFER, SignalCode.PAYEE_SURGE):
                        done = n if past else n - 1
                        assert done >= 2, (txn.id, past, n, card.lines)
                    checked += 1
    assert checked > 50


# ---- 리뷰 수정 확인(round 2) ------------------------------------------------

_JONG_SSANG_SIOT = 20   # 받침 ㅆ(했·었·았·였·됐·왔 …)


def _is_past_or_question(line: str) -> bool:
    """줄이 과거형('…ㅆ어요.')이나 질문('…?')으로 끝나는지."""
    text = line.strip()
    if text.endswith("?"):
        return True
    if not text.endswith("어요.") or len(text) < 4:
        return False
    ch = text[-4]
    return 0xAC00 <= ord(ch) <= 0xD7A3 and (ord(ch) - 0xAC00) % 28 == _JONG_SSANG_SIOT


def test_past_tense_checker_itself() -> None:
    for ok in ("보냈어요.", "그때 결제는 14만 4천 원이었어요.", "얼마 안 됐어요.", "누가 시켰나요?",
               "평소에 쓰는 돈보다 많았어요.", "처음 간 가게였어요."):
        assert _is_past_or_question(ok), ok
    for bad in ("큰 돈이에요.", "평소에 쓰는 돈보다 많아요.", "잘 안 써요.", "보내는 돈이에요."):
        assert not _is_past_or_question(bad), bad


def _past_cards() -> list:
    """여러 시그널·근거·거래 방법 조합의 기록 카드(past=True)."""
    cards = []
    for code, severity, (evidence, related), txn in itertools.product(
            SignalCode, [RiskLevel.CAUTION, RiskLevel.HIGH], EVIDENCE_VARIANTS + [
                ({"card_p95": 0, "count_7d": 1}, []), ({"card_p95": 50_000}, []),
                ({"first_seen_days_ago": None, "count_7d": 1, "sum_7d": 300_000}, []),
                ({"first_seen_days_ago": 3.0, "newness_unknown": True, "count_7d": 1, "sum_7d": 300_000}, []),
                ({"newness_unknown": True, "card_p95": 40_000, "distinct_lines_30d": 3}, [])],
            SIGNAL_TXN_VARIANTS[::3]):
        cards.append(render_card(make_assessment([SignalHit(code, severity, dict(evidence), list(related))]),
                                 txn, past=True))
    combos = list(itertools.combinations(SignalCode, 2))
    for combo in combos:
        hits = [SignalHit(c, RiskLevel.HIGH, {"count_7d": 3, "sum_7d": 500_000}, []) for c in combo]
        cards.append(render_card(make_assessment(hits), make_txn(), past=True))
    for feature, txn in itertools.product(list(ANOMALY_FEATURE_GROUPS) + ["other"], TXN_VARIANTS[::7]):
        for detail in ({}, {"feature": "cp_count_7d", "value": 3.0}):
            reason = Reason(f"anomaly:{feature}", dict(detail))
            cards.append(render_card(make_assessment([], RiskLevel.CAUTION, [reason]), txn, past=True))
    return cards


def test_every_past_card_line_is_past_tense_or_question() -> None:
    """[변경 r2] ④ 기록 카드는 이미 끝난 일이라 한 카드 안에서 시제가 섞이지 않게 한다(SPEC §6)."""
    cards = _past_cards()
    assert len(cards) > 500
    for card in cards:
        assert card is not None
        for line in card.lines:
            assert _is_past_or_question(line), (card.title, line)


def test_every_past_card_title_is_past_tense_without_now_words() -> None:
    """[변경 r3] 제목도 과거형이고, 지금 기준 말('요즘')을 쓰지 않는다(소리로 듣기도 같은 글)."""
    titles = set()
    for card in _past_cards():
        assert card is not None
        assert _is_past_or_question(card.title + "."), card.title
        for text in (card.title, *card.lines, card.speak_text):
            assert "요즘" not in text, (card.title, text)
        assert not readability_issues(card), (card.title, readability_issues(card))
        titles.add(card.title)
    assert len(titles) >= 15


def test_cards_do_not_claim_new_when_history_is_short() -> None:
    """[변경 r3] 새 가게·새 회선인지 알 수 없으면(newness_unknown) '처음·새'라고 말하지 않는다."""
    for code, channel in ((SignalCode.NEW_MERCHANT_HIGH_VALUE, Channel.CARD),
                          (SignalCode.MULTI_LINE_TELECOM, Channel.TELECOM_BILL)):
        hit = SignalHit(code, RiskLevel.CAUTION,
                        {"newness_unknown": True, "card_p95": 0, "distinct_lines_30d": 3})
        for past in (False, True):
            card = render_card(make_assessment([hit], RiskLevel.CAUTION),
                               make_txn(amount=150_000, counterparty="연세치과", channel=channel), past=past)
            assert card is not None and not readability_issues(card)
            text = " ".join([card.title, *card.lines])
            assert "처음" not in text and "새 " not in text and "새로" not in text, text
    hit = SignalHit(SignalCode.NEW_MERCHANT_HIGH_VALUE, RiskLevel.CAUTION, {"newness_unknown": True, "card_p95": 0})
    card = render_card(make_assessment([hit], RiskLevel.CAUTION),
                       make_txn(amount=150_000, counterparty="연세치과", channel=Channel.CARD))
    assert card is not None
    assert card.lines[:3] == ["연세치과에서 결제해요.", "이번 결제는 15만 원이에요.", "큰 돈이에요."]


def test_new_merchant_past_card_example() -> None:
    hit = SignalHit(SignalCode.NEW_MERCHANT_HIGH_VALUE, RiskLevel.HIGH, {"card_p95": 40_000})
    card = render_card(make_assessment([hit]), make_txn(amount=144_000, counterparty="새 가게",
                                                        channel=Channel.CARD), past=True)
    assert card is not None
    assert card.lines[1:3] == ["그때 결제는 14만 4천 원이었어요.", "평소보다 훨씬 큰 돈이었어요."]


def test_payee_card_does_not_claim_new_when_history_is_short() -> None:
    """이력이 짧아 새 상대인지 모르면(newness_unknown) '처음·새로'라고 말하지 않는다."""
    hit = SignalHit(SignalCode.PAYEE_SURGE, RiskLevel.CAUTION,
                    {"count_7d": 1, "sum_7d": 300_000, "first_seen_days_ago": 5.0, "newness_unknown": True})
    card = render_card(make_assessment([hit]), make_txn(counterparty="엄마"))
    assert card is not None
    text = " ".join([card.title, *card.lines])
    assert "처음" not in text and "새로" not in text and "얼마 안 됐" not in text
    assert card.lines[0] == "엄마에게 보내는 돈이에요."


def test_practice_result_when_nobody_was_asked() -> None:
    title, lines = practice_result(Decision.ASK_HELPER, make_txn(counterparty="김*호"), asked_count=0)
    assert title == "물어볼 조력자가 없어요"
    assert lines == ["김*호에게 30만 원을 아직 보내지 않았어요.", "조력자 화면에서 조력자를 정할 수 있어요."]
    title, _ = practice_result(Decision.ASK_HELPER, make_txn(counterparty="김*호"), asked_count=2)
    assert title == "조력자에게 물어봐요"


# ---- 리뷰 7: 심야 그림은 근거의 심야 여부나 넘겨받은 설정으로 ----
def _time_card(reason: Reason, hour: int, **kwargs):
    return render_card(make_assessment([], RiskLevel.CAUTION, [reason]), make_txn(hour=hour), **kwargs)


def test_time_card_icon_follows_reason_night_flag() -> None:
    # 근거(엔진 설정 기준 심야 여부)가 시각보다 우선
    day_but_night = _time_card(Reason("anomaly:hour_sin", {"feature": "hour_sin", "is_night": True}), 14)
    night_but_day = _time_card(Reason("anomaly:hour_cos", {"feature": "hour_cos", "is_night": False}), 2)
    assert day_but_night is not None and day_but_night.pictograms[0] == "moon"
    assert night_but_day is not None and night_but_day.pictograms[0] == "warning"
    is_night_feature = _time_card(Reason("anomaly:is_night", {"feature": "is_night", "value": 1.0}), 21)
    assert is_night_feature is not None and is_night_feature.pictograms[0] == "moon"


def test_time_card_icon_uses_passed_settings() -> None:
    from safepause.config import Settings

    reason = Reason("anomaly:hour_sin", {})          # 심야 여부가 없는 근거
    assert _time_card(reason, 23).pictograms[0] == "moon"                        # 기본 23~6시
    early = Settings(night_start_hour=0, night_end_hour=5)                        # 자정을 넘지 않는 설정
    assert _time_card(reason, 23, settings=early).pictograms[0] == "warning"
    assert _time_card(reason, 3, settings=early).pictograms[0] == "moon"
    late = Settings(night_start_hour=21, night_end_hour=6)
    card = _time_card(reason, 22, settings=late, past=True)
    assert card.pictograms[0] == "moon" and readability_issues(card) == []


def test_engine_time_reason_drives_card_icon() -> None:
    """엔진이 붙인 시각 이유에는 엔진 설정 기준 심야 여부가 담겨 카드 그림과 맞는다."""
    from datetime import timedelta

    from safepause.config import Settings
    from safepause.detect.engine import RiskEngine
    from safepause.data.synth import make_dataset

    from safepause.detect.features import FEATURE_NAMES, History, compute_features

    settings = Settings(night_start_hour=20, night_end_hour=6)   # 21시도 심야로 보는 설정
    txns = make_dataset("worker", 2, 120)
    eng = RiskEngine(settings, seed=0).fit(txns[: int(len(txns) * 0.75)])
    p = Transaction(id="live-1", ts=(txns[-1].ts + timedelta(days=1)).replace(hour=21, minute=0),
                    amount=20_000, direction=Direction.OUT, channel=Channel.CARD,
                    counterparty="동네편의점", counterparty_id="M-1001")
    feats = compute_features(p, History(txns, settings, as_of=p.ts), p.ts)
    reasons = eng.model.explain_features(feats, top_k=len(FEATURE_NAMES))
    times = [r for r in reasons if r.detail["feature"] in ("hour_sin", "hour_cos", "is_night")]
    assert times                                      # 밤 9시는 이 사람의 평소 시간과 다르다
    assert all(r.detail["is_night"] is True for r in times)
    a = RiskAssessment(txn_id=p.id, level=RiskLevel.CAUTION, rule_hits=[], anomaly_score=0.99,
                       reasons=[times[0]])
    card = render_card(a, p)                          # 설정을 넘기지 않아도 근거로 정한다
    assert card is not None and card.pictograms[0] == "moon"
    assert card.title == "평소와 다른 시간이에요" and readability_issues(card) == []
