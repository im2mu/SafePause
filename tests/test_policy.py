"""guardian/policy.py 테스트."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from safepause.config import Settings
from safepause.guardian.policy import (
    COUNSELING_ORGS,
    NOTE_ALERTS_OFF,
    NOTE_NO_HELPER,
    NOTE_NOT_NOTIFIED,
    NOTE_NONE_CHOSEN,
    ask_helper_candidates,
    ask_helper_plan,
    decide,
    ask_helper_message,
    helper_message,
    is_conflict,
)
from safepause.models import (
    Channel,
    Consent,
    Direction,
    Helper,
    RiskAssessment,
    RiskLevel,
    SignalCode,
    SignalHit,
    Transaction,
)

NOW = datetime(2026, 9, 30, 21, 5, 0)
SETTINGS = Settings()


def txn(counterparty: str = "처음보는사람", counterparty_id: str = "333-44-555555") -> Transaction:
    return Transaction(id="t9", ts=datetime(2026, 9, 30, 2, 0), amount=300_000,
                       direction=Direction.OUT, channel=Channel.TRANSFER,
                       counterparty=counterparty, counterparty_id=counterparty_id)


def assessment(level: RiskLevel = RiskLevel.HIGH,
               codes: tuple[SignalCode, ...] = (SignalCode.NIGHT_REPEAT_TRANSFER,)) -> RiskAssessment:
    hits = [SignalHit(c, level if level != RiskLevel.NONE else RiskLevel.CAUTION, {}) for c in codes]
    return RiskAssessment(txn_id="t9", level=level, rule_hits=hits if level != RiskLevel.NONE else [],
                          anomaly_score=0.5, reasons=[])


MOM = Helper(id="h1", name="엄마", relation="가족", identifiers=["110-123-456789", "김 엄마"])
CENTER = Helper(id="h2", name="센터 선생님", relation="지역발달장애인지원센터 전담 인력",
                identifiers=["222-333-444444"])
ALL_ON = Consent(monitoring=True, helper_alerts=True, counseling_referral=True)
ALERTS_ONLY = Consent(monitoring=True, helper_alerts=True, counseling_referral=False)


def run(a: RiskAssessment, t: Transaction, helpers: list[Helper], consent: Consent,
        high_30d: int = 0, settings: Settings = SETTINGS):
    return decide(a, t, helpers, consent, high_30d, settings, person_name="민수", now=NOW)


# ---- 동의 ----------------------------------------------------------------

def test_no_helper_alert_consent_means_no_notices() -> None:
    plan = run(assessment(), txn(), [MOM, CENTER], Consent(monitoring=True, helper_alerts=False))
    assert plan.notices == []
    assert plan.excluded_conflict == []
    assert plan.suggest_counseling is False and plan.counseling_orgs == []
    assert plan.note_to_person == NOTE_ALERTS_OFF


def test_none_level_gives_empty_plan() -> None:
    plan = run(assessment(RiskLevel.NONE), txn(), [MOM], ALL_ON, high_30d=10)
    assert plan.notices == [] and plan.suggest_counseling is False and plan.note_to_person == ""


# ---- 등급 범위 -----------------------------------------------------------

def test_default_min_level_is_high_only() -> None:
    assert MOM.min_level == RiskLevel.HIGH
    caution = run(assessment(RiskLevel.CAUTION), txn(), [MOM], ALERTS_ONLY)
    assert caution.notices == []
    assert caution.note_to_person == NOTE_NOT_NOTIFIED
    high = run(assessment(RiskLevel.HIGH), txn(), [MOM], ALERTS_ONLY)
    assert [n.helper_id for n in high.notices] == ["h1"]
    assert high.note_to_person == "엄마에게 알릴 수 있게 적어 두었어요."
    # 고르기 전 미리 보기: 보낸다는 약속 없이 알릴 수 있다고만(v0.3 수정 계획 A)
    preview = decide(assessment(RiskLevel.HIGH), txn(), [MOM], ALERTS_ONLY, 0, SETTINGS, now=NOW, preview=True)
    assert preview.note_to_person == "엄마에게 알릴 수 있어요."


def test_min_level_caution_helper_gets_caution_alerts() -> None:
    sister = Helper(id="h3", name="언니", relation="가족", min_level=RiskLevel.CAUTION)
    plan = run(assessment(RiskLevel.CAUTION), txn(), [MOM, sister], ALERTS_ONLY)
    assert [n.helper_id for n in plan.notices] == ["h3"]
    assert plan.notices[0].level == RiskLevel.CAUTION


def test_string_min_level_is_accepted() -> None:
    helper = Helper(id="h9", name="언니", relation="가족", min_level="caution")  # type: ignore[arg-type]
    plan = run(assessment(RiskLevel.CAUTION), txn(), [helper], ALERTS_ONLY)
    assert [n.helper_id for n in plan.notices] == ["h9"]


def test_inactive_helper_is_skipped() -> None:
    off = Helper(id="h4", name="삼촌", relation="가족", active=False)
    plan = run(assessment(), txn(), [off], ALERTS_ONLY)
    assert plan.notices == []
    assert plan.note_to_person == NOTE_NO_HELPER


def test_no_helpers_registered() -> None:
    plan = run(assessment(), txn(), [], ALERTS_ONLY)
    assert plan.notices == [] and plan.note_to_person == NOTE_NO_HELPER


# ---- 시그널 범위 ---------------------------------------------------------

def test_signal_scope_limits_alerts() -> None:
    micropay_only = Helper(id="h5", name="형", relation="가족",
                           signal_scope=[SignalCode.MICROPAY_SURGE.value])
    night = run(assessment(codes=(SignalCode.NIGHT_REPEAT_TRANSFER,)), txn(), [micropay_only, CENTER],
                ALERTS_ONLY)
    assert [n.helper_id for n in night.notices] == ["h2"]  # 빈 범위 = 모든 시그널
    both = run(assessment(codes=(SignalCode.NIGHT_REPEAT_TRANSFER, SignalCode.MICROPAY_SURGE)), txn(),
               [micropay_only], ALERTS_ONLY)
    assert [n.helper_id for n in both.notices] == ["h5"]


def test_signal_scope_accepts_enum_values() -> None:
    helper = Helper(id="h6", name="누나", relation="가족", signal_scope=[SignalCode.PAYEE_SURGE])  # type: ignore[list-item]
    plan = run(assessment(codes=(SignalCode.PAYEE_SURGE,)), txn(), [helper], ALERTS_ONLY)
    assert [n.helper_id for n in plan.notices] == ["h6"]


def test_scoped_helper_not_notified_for_anomaly_only() -> None:
    scoped = Helper(id="h7", name="형", relation="가족", min_level=RiskLevel.CAUTION,
                    signal_scope=[SignalCode.MICROPAY_SURGE.value])
    anomaly_only = RiskAssessment(txn_id="t9", level=RiskLevel.CAUTION, rule_hits=[],
                                  anomaly_score=0.99, reasons=[])
    assert run(anomaly_only, txn(), [scoped], ALERTS_ONLY).notices == []


# ---- 이해충돌 ------------------------------------------------------------

@pytest.mark.parametrize("counterparty, counterparty_id", [
    ("아무개", "110123456789"),        # 계좌: 숫자만 비교
    ("아무개", "110 123 456789"),
    ("아무개", "110-***-456789"),      # 가려진 계좌번호
    ("김엄마", ""),                    # 이름: 공백 무시
    ("  김  엄마 ", "999"),
])
def test_conflict_detected(counterparty: str, counterparty_id: str) -> None:
    assert is_conflict(MOM, txn(counterparty, counterparty_id))


@pytest.mark.parametrize("counterparty, counterparty_id", [
    ("아무개", "110123456780"),
    ("아무개", "110-***-456780"),
    ("김엄마님", ""),
    ("", ""),
    ("아무개", "***-***-******"),
])
def test_conflict_not_detected(counterparty: str, counterparty_id: str) -> None:
    assert not is_conflict(MOM, txn(counterparty, counterparty_id))


@pytest.mark.parametrize("identifier, counterparty_id", [
    # [변경 r2] 은행 이름이 앞뒤에 붙은 자유 형식도 계좌 숫자만 비교한다(양방향)
    ("302-1234-5678-91", "302-1234-5678-91"),
    ("농협 302-1234-5678-91", "302-1234-5678-91"),
    ("302-1234-5678-91 (농협)", "302-1234-5678-91"),
    ("농협302-1234-5678-91", "3021234567891"),
    ("302-1234-5678-91", "농협 302-1234-5678-91"),
    ("농협 302 1234 5678 91", "(농협)302-1234-5678-91"),
    ("농협 302-****-5678-91", "302-1234-5678-91"),          # 가린 계좌번호
    ("302-1234-5678-91 / 010-1234-5678", "302-1234-5678-91"),  # 한 칸에 계좌와 전화번호
])
def test_conflict_account_with_bank_name(identifier: str, counterparty_id: str) -> None:
    helper = Helper(id="h9", name="삼촌", relation="가족", identifiers=[identifier])
    assert is_conflict(helper, txn("김*수", counterparty_id))


@pytest.mark.parametrize("identifier, counterparty_id", [
    ("농협 302-1234-5678-91", "302-1234-5678-92"),   # 한 자리 다름
    ("농협 12-34", "1234"),                          # 숫자가 적으면 계좌로 보지 않음(이름 비교만)
    ("2026년 9월", "20269"),
])
def test_conflict_account_not_matched(identifier: str, counterparty_id: str) -> None:
    helper = Helper(id="h9", name="삼촌", relation="가족", identifiers=[identifier])
    assert not is_conflict(helper, txn("김*수", counterparty_id))


def test_conflict_bank_name_end_to_end_excludes_helper() -> None:
    """리뷰 재현: 은행 이름을 붙여 적은 조력자가 받는 사람이면 고위험 알림에서 빠진다."""
    uncle = Helper(id="h1", name="삼촌", relation="가족", identifiers=["농협 302-1234-5678-91"])
    plan = run(assessment(), txn("삼촌", "3021234567891"), [uncle], ALL_ON)
    assert plan.notices == [] and plan.excluded_conflict == ["h1"]
    assert plan.suggest_counseling is True


def test_conflict_ignores_case() -> None:
    helper = Helper(id="h8", name="Mom", relation="가족", identifiers=["Mom Kim"])
    assert is_conflict(helper, txn("MOMKIM", ""))
    assert is_conflict(helper, txn("아무개", "mom kim"))


def test_conflicted_helper_excluded_others_notified() -> None:
    plan = run(assessment(), txn("김엄마", "110-123-456789"), [MOM, CENTER], ALERTS_ONLY)
    assert plan.excluded_conflict == ["h1"]
    assert [n.helper_id for n in plan.notices] == ["h2"]
    assert plan.note_to_person == "엄마는 돈을 받는 사람이에요. 그래서 센터 선생님에게만 알릴 수 있게 적어 두었어요."
    assert plan.suggest_counseling is False


def test_all_conflicted_suggests_counseling_only_with_consent() -> None:
    t = txn("김엄마", "110123456789")
    with_consent = run(assessment(), t, [MOM], ALL_ON)
    assert with_consent.notices == []
    assert with_consent.excluded_conflict == ["h1"]
    assert with_consent.suggest_counseling is True
    assert with_consent.counseling_orgs == list(COUNSELING_ORGS) == ["지역발달장애인지원센터", "장애인권익옹호기관"]
    assert with_consent.note_to_person == "엄마는 돈을 받는 사람이에요. 그래서 이번에는 엄마에게 알리지 않았어요."
    # 고르기 전 미리 보기는 현재형(아직 아무것도 하지 않음)
    preview = decide(assessment(), t, [MOM], ALL_ON, 0, SETTINGS, now=NOW, preview=True)
    assert preview.note_to_person == "엄마는 돈을 받는 사람이에요. 그래서 이번에는 엄마에게 알리지 않아요."

    without = run(assessment(), t, [MOM], ALERTS_ONLY)
    assert without.notices == [] and without.excluded_conflict == ["h1"]
    assert without.suggest_counseling is False and without.counseling_orgs == []


def test_conflict_only_counted_for_eligible_helpers() -> None:
    # 고위험만 받는 조력자가 상대방이어도 주의(CAUTION) 건에서는 원래 알림 대상이 아니다
    plan = run(assessment(RiskLevel.CAUTION), txn("김엄마", ""), [MOM], ALL_ON)
    assert plan.excluded_conflict == [] and plan.suggest_counseling is False


# ---- 반복 고위험 → 상담 연계 ----------------------------------------------

def test_repeated_high_suggests_counseling_with_consent() -> None:
    plan = run(assessment(), txn(), [MOM], ALL_ON, high_30d=3)
    assert plan.suggest_counseling is True
    assert plan.counseling_orgs == list(COUNSELING_ORGS)
    assert [n.helper_id for n in plan.notices] == ["h1"]  # 조력자 알림과 함께


def test_repeat_below_threshold_or_without_consent() -> None:
    assert run(assessment(), txn(), [MOM], ALL_ON, high_30d=2).suggest_counseling is False
    assert run(assessment(), txn(), [MOM], ALERTS_ONLY, high_30d=5).suggest_counseling is False


def test_repeat_counseling_even_when_helper_alerts_off() -> None:
    consent = Consent(monitoring=True, helper_alerts=False, counseling_referral=True)
    plan = run(assessment(), txn(), [MOM], consent, high_30d=3)
    assert plan.notices == [] and plan.suggest_counseling is True


def test_repeat_threshold_comes_from_settings() -> None:
    settings = Settings(high_repeat_for_counseling=2)
    assert run(assessment(), txn(), [MOM], ALL_ON, high_30d=2, settings=settings).suggest_counseling is True


def test_settings_default_used_when_omitted() -> None:
    plan = decide(assessment(), txn(), [MOM], ALL_ON, 3)
    assert plan.suggest_counseling is True


# ---- 메시지 ---------------------------------------------------------------

def test_message_respects_persons_decision() -> None:
    """적어 둔 기록 글은 먼저 본인과 이야기해 달라고 쓴다. 당사자 화면에 보이므로 결정 문장은 넣지 않는다(RF-11)."""
    plan = run(assessment(), txn(), [MOM, CENTER], ALERTS_ONLY)
    assert len(plan.notices) == 2
    for notice in plan.notices:
        assert notice.message == ("[SafePause] 민수님 거래에서 확인이 필요한 신호가 있어요. "
                                  "먼저 민수님과 이야기해 주세요.")
        assert "결정은" not in notice.message
        assert notice.txn_id == "t9" and notice.level == RiskLevel.HIGH
        assert notice.created_at == "2026-09-30T21:05:00"
    assert [n.helper_name for n in plan.notices] == ["엄마", "센터 선생님"]
    assert plan.note_to_person == "엄마, 센터 선생님에게 알릴 수 있게 적어 두었어요."


def test_message_does_not_leak_amount_or_counterparty() -> None:
    plan = run(assessment(), txn("처음보는사람", "333-44-555555"), [MOM], ALERTS_ONLY)
    msg = plan.notices[0].message
    assert "30만" not in msg and "처음보는사람" not in msg and "555555" not in msg


def test_default_person_name() -> None:
    # 부를 이름이 없으면 '당사자님' 같은 어려운 말 대신 '본인'으로 쓴다(⑤ 기록에 그대로 보임)
    msg = helper_message()
    assert msg == "[SafePause] 함께 확인이 필요한 거래가 있어요. 먼저 본인과 이야기해 주세요."
    assert "당사자" not in msg and "결정은" not in msg
    assert "먼저 민수님과 이야기해 주세요." in helper_message("민수")
    for text in (msg, helper_message("민수"), ask_helper_message(), ask_helper_message("민수")):
        assert "결정은" not in text and "알려 드릴" not in text


def test_many_helpers_note_is_short() -> None:
    helpers = [Helper(id=f"h{i}", name=f"조력자{i}", relation="가족") for i in range(4)]
    plan = run(assessment(), txn(), helpers, ALERTS_ONLY)
    assert plan.note_to_person == "조력자0 외 3명에게 알릴 수 있게 적어 두었어요."


def test_plan_is_json_serializable() -> None:
    plan = run(assessment(), txn("김엄마", ""), [MOM, CENTER], ALL_ON, high_30d=4)
    json.dumps(plan.to_dict(), ensure_ascii=False)


# ---- 당사자가 직접 묻기 ---------------------------------------------------

def test_ask_helper_plan_ignores_level_but_respects_conflict() -> None:
    caution = assessment(RiskLevel.CAUTION)
    plan = ask_helper_plan(caution, txn("김엄마", ""), [MOM, CENTER], ALERTS_ONLY,
                           person_name="민수", now=NOW)
    assert [n.helper_id for n in plan.notices] == ["h2"]
    assert plan.excluded_conflict == ["h1"]
    assert plan.notices[0].message == ("[SafePause] 민수님이 거래를 함께 확인해 주기를 원해요. "
                                       "먼저 민수님과 이야기해 주세요.")
    assert plan.note_to_person == "엄마는 돈을 받는 사람이에요. 그래서 센터 선생님에게만 물어봐요."


def test_ask_helper_plan_all_conflicted() -> None:
    plan = ask_helper_plan(assessment(), txn("김엄마", ""), [MOM], ALL_ON, now=NOW)
    assert plan.notices == [] and plan.suggest_counseling is True
    assert plan.note_to_person == "엄마는 돈을 받는 사람이에요. 그래서 이번에는 물어보지 않았어요."
    no_consent = ask_helper_plan(assessment(), txn("김엄마", ""), [MOM], ALERTS_ONLY, now=NOW)
    assert no_consent.suggest_counseling is False


DAD_BILLS_ONLY = Helper(id="h3", name="아빠", relation="가족",
                        signal_scope=[SignalCode.MULTI_LINE_TELECOM.value])


def test_ask_helper_default_respects_signal_scope() -> None:
    """직접 물을 때도 당사자가 정한 '무엇을 알릴까요?' 범위 밖의 조력자에게는 묻지 않는다(S37)."""
    night = assessment(RiskLevel.HIGH, (SignalCode.NIGHT_REPEAT_TRANSFER,))
    plan = ask_helper_plan(night, txn(), [CENTER, DAD_BILLS_ONLY], ALERTS_ONLY, now=NOW)
    assert [n.helper_id for n in plan.notices] == ["h2"]
    bills = assessment(RiskLevel.CAUTION, (SignalCode.MULTI_LINE_TELECOM,))
    plan2 = ask_helper_plan(bills, txn(), [CENTER, DAD_BILLS_ONLY], ALERTS_ONLY, now=NOW)
    assert [n.helper_id for n in plan2.notices] == ["h2", "h3"]


def test_ask_helper_uses_chosen_ids_only() -> None:
    night = assessment(RiskLevel.HIGH, (SignalCode.NIGHT_REPEAT_TRANSFER,))
    # 당사자가 범위 밖 조력자를 직접 고르면 그 사람에게만 묻는다
    plan = ask_helper_plan(night, txn(), [CENTER, DAD_BILLS_ONLY], ALERTS_ONLY,
                           helper_ids=["h3"], now=NOW)
    assert [n.helper_id for n in plan.notices] == ["h3"]
    assert plan.note_to_person == "아빠에게 물어봐요."
    # 아무도 고르지 않으면 알리지 않는다
    none = ask_helper_plan(night, txn(), [CENTER, DAD_BILLS_ONLY], ALERTS_ONLY, helper_ids=[], now=NOW)
    assert none.notices == [] and none.note_to_person == NOTE_NONE_CHOSEN
    # 거래 상대방인 조력자는 골라도 뺀다
    conflict = ask_helper_plan(night, txn("김엄마", ""), [MOM, CENTER], ALL_ON,
                               helper_ids=["h1"], now=NOW)
    assert conflict.notices == [] and conflict.excluded_conflict == ["h1"]
    assert conflict.suggest_counseling is True


def test_ask_helper_candidates_preview() -> None:
    night = assessment(RiskLevel.HIGH, (SignalCode.NIGHT_REPEAT_TRANSFER,))
    inactive = Helper(id="h4", name="이웃", relation="이웃", active=False)
    got = ask_helper_candidates(night, txn("김엄마", ""), [MOM, CENTER, DAD_BILLS_ONLY, inactive])
    by_id = {c["id"]: c for c in got}
    # [변경 r3] '자동으로 알리기'(active)를 끈 조력자도 직접 물을 때는 후보다(자동 알림에서만 빠짐)
    assert set(by_id) == {"h1", "h2", "h3", "h4"}
    assert by_id["h4"]["active"] is False and by_id["h4"]["default"] is True
    assert by_id["h1"]["conflict"] is True and by_id["h1"]["default"] is False
    assert by_id["h2"]["default"] is True and by_id["h2"]["active"] is True
    assert by_id["h3"]["in_scope"] is False and by_id["h3"]["default"] is False


def test_helper_without_auto_alerts_can_still_be_asked() -> None:
    """[변경 r3] '엄마는 자동 알림 없이 내가 물을 때만'(S37): 자동 알림에서는 빼고 물어보기는 된다."""
    mom_ask_only = Helper(id="h1", name="엄마", relation="가족", active=False)
    night = assessment(RiskLevel.HIGH, (SignalCode.NIGHT_REPEAT_TRANSFER,))
    auto = decide(night, txn(), [mom_ask_only], ALL_ON, 0, now=NOW)
    assert auto.notices == []
    asked = ask_helper_plan(night, txn(), [mom_ask_only], ALL_ON, helper_ids=["h1"], now=NOW)
    assert [n.helper_id for n in asked.notices] == ["h1"]
    assert asked.note_to_person == "엄마에게 물어봐요."
    by_scope = ask_helper_plan(night, txn(), [mom_ask_only], ALL_ON, now=NOW)   # 고르지 않으면 범위 안 모두
    assert [n.helper_id for n in by_scope.notices] == ["h1"]
    nobody = ask_helper_plan(night, txn(), [], ALL_ON, now=NOW)
    assert nobody.notices == [] and nobody.note_to_person == "물어볼 수 있는 조력자가 없어요."


# ---- 조사(C11: 은(는) 같은 묶음 표기 없이) ------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("엄마", "엄마는"), ("센터 선생님", "센터 선생님은"), ("조력자0 외 3명", "조력자0 외 3명은"),
    ("010-1234-5678", "010-1234-5678은"), ("010-1234-5672", "010-1234-5672는"), ("이모(2)", "이모(2)는"),
    ("Tom", "Tom은"), ("Mike", "Mike는"), ("엄마 :)", "엄마 :)는"), ("!!", "!!는"),
])
def test_topic_particle_has_no_paren_form(name: str, expected: str) -> None:
    from safepause.guardian.policy import _topic
    assert _topic(name) == expected
    assert "(는)" not in _topic(name) and "(은)" not in _topic(name)
