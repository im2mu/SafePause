"""신뢰 조력자 알림·이해충돌·상담 연계 정책. SPEC §7, 제안서 S22/S23/S37.

원칙
- 알릴지, 누구에게, 어떤 등급·시그널까지 알릴지는 당사자가 정한다(동의·조력자 설정).
- 기본은 고위험(HIGH)만 알린다(Helper.min_level 기본값 HIGH).
- 조력자가 이번 거래의 상대방이면 그 조력자는 이번 건에서 빼고 다른 조력자에게만 알린다.
- 상담기관 연계는 당사자가 동의했을 때만 제안한다.
- 조력자 메시지는 "결정은 당사자가 한다"는 문구를 반드시 담는다.
- 당사자가 카드에서 '조력자에게 물어볼래요'를 고르면, 물어볼 조력자도 당사자가 고른다
  (helper_ids). 고르지 않았으면 당사자가 정한 '무엇을 알릴까요?' 범위 안의 조력자에게만 묻는다.
- Helper.active는 '자동으로 알리기'다. 꺼 두면 자동 알림만 받지 않고, 당사자가 직접 물을 때는
  물어볼 사람으로 고를 수 있다(예: "엄마는 자동 알림 없이 내가 물을 때만", S37).
"""
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Optional, Sequence

from safepause.config import Settings
from safepause.models import (
    LEVEL_ORDER,
    Consent,
    Helper,
    HelperNotice,
    NotifyPlan,
    RiskAssessment,
    RiskLevel,
    Transaction,
)

COUNSELING_ORGS: tuple[str, ...] = ("지역발달장애인지원센터", "장애인권익옹호기관")
DEFAULT_PERSON_NAME = ""  # 부를 이름이 없으면 '○○님' 대신 '본인'이라고 쓴다
_MIN_ACCOUNT_DIGITS = 4  # 가려진 계좌번호 비교 시 최소로 일치해야 하는 숫자 수
_MIN_KEY_DIGITS = 6      # 글 안의 숫자 조각을 계좌번호로 보려면 숫자가 이만큼 있어야 한다

NOTE_ALERTS_OFF = "조력자 알림은 꺼져 있어요."
NOTE_NO_HELPER = "알릴 조력자가 없어요."
NOTE_NOT_NOTIFIED = "이번에는 조력자에게 알리지 않았어요."
NOTE_NOT_NOTIFIED_PREVIEW = "이번에는 조력자에게 알리지 않아요."  # 고르기 전 미리 보기(현재형)
NOTE_COUNSELING = "상담을 도와줄 곳이 있어요."
NOTE_NONE_CHOSEN = "물어볼 조력자를 고르지 않았어요."
NOTE_NO_HELPER_TO_ASK = "물어볼 수 있는 조력자가 없어요."


# ---- 조력자 메시지 --------------------------------------------------------

def helper_message(person_name: str = DEFAULT_PERSON_NAME) -> str:
    """조력자에게 남길 요약. 당사자 결정 존중 문구를 포함한다(금액·상대는 넣지 않는다)."""
    p = (person_name or "").strip()
    if p:
        return (f"[SafePause] {p}님 거래에서 확인이 필요한 신호가 있어요. "
                f"결정은 {p}님이 합니다. 먼저 {p}님과 이야기해 주세요.")
    return ("[SafePause] 함께 확인이 필요한 거래가 있어요. "
            "결정은 본인이 해요. 먼저 본인과 이야기해 주세요.")


def ask_helper_message(person_name: str = DEFAULT_PERSON_NAME) -> str:
    """당사자가 '조력자에게 물어볼래요'를 골랐을 때의 메시지."""
    p = (person_name or "").strip()
    if p:
        return (f"[SafePause] {p}님이 거래를 함께 확인해 주기를 원해요. "
                f"결정은 {p}님이 합니다. 먼저 {p}님과 이야기해 주세요.")
    return ("[SafePause] 본인이 거래를 함께 확인해 주기를 원해요. "
            "결정은 본인이 해요. 먼저 본인과 이야기해 주세요.")


# ---- 이해충돌(조력자 = 거래 상대방) 판별 ------------------------------------

def _norm_text(value: str) -> str:
    """공백 제거 + 대소문자 무시."""
    return re.sub(r"\s+", "", value or "").casefold()


# 글 안의 계좌번호처럼 보이는 조각(숫자·가림표와 그 사이의 공백·하이픈·점)
_ACCOUNT_CHUNK_RE = re.compile(r"[0-9*][0-9*\s\-.]{4,}[0-9*]")
_ACCOUNT_SEP_RE = re.compile(r"[\s\-.]")


def _account_keys(value: str) -> list[str]:
    """글에서 계좌번호처럼 보이는 조각을 찾아 숫자(와 가림표 *)만 남긴 값 목록.

    '농협 302-1234-5678-91', '302-1234-5678-91 (농협)'처럼 은행 이름이 붙어 있어도 찾는다.
    숫자가 _MIN_KEY_DIGITS개 이상인 조각만 계좌로 본다. 공백으로 이어진 조각은 통째로 한 번,
    공백으로 나눈 부분마다 한 번씩 본다(계좌와 전화번호를 한 칸에 적은 경우).
    """
    keys: list[str] = []
    for chunk in _ACCOUNT_CHUNK_RE.findall(value or ""):
        for part in [chunk, *chunk.split()]:
            compact = _ACCOUNT_SEP_RE.sub("", part)
            if sum(ch.isdigit() for ch in compact) >= _MIN_KEY_DIGITS and compact not in keys:
                keys.append(compact)
    return keys


def _accounts_match(a: str, b: str) -> bool:
    """숫자만 비교. 가림표(*)가 있으면 같은 자리의 보이는 숫자가 모두 같아야 한다."""
    if "*" not in a and "*" not in b:
        return a == b
    if len(a) != len(b):
        return False
    same_digits = 0
    for x, y in zip(a, b):
        if x == "*" or y == "*":
            continue
        if x != y:
            return False
        same_digits += 1
    return same_digits >= _MIN_ACCOUNT_DIGITS


def is_conflict(helper: Helper, txn: Transaction) -> bool:
    """조력자가 이번 거래의 상대방인지.

    identifiers 중 하나가 상대 이름·식별값과 같으면(공백·대소문자 무시) True. 계좌번호는 글 안에서
    계좌처럼 보이는 조각을 찾아 숫자만 비교한다(은행 이름이 앞뒤에 붙어 있어도 같음).
    """
    targets = [v for v in (txn.counterparty, txn.counterparty_id) if v and v.strip()]
    target_texts = {_norm_text(v) for v in targets}
    target_accounts = [k for v in targets for k in _account_keys(v)]
    for ident in helper.identifiers:
        if not ident or not ident.strip():
            continue
        if _norm_text(ident) in target_texts:
            return True
        if any(_accounts_match(k, t) for k in _account_keys(ident) for t in target_accounts):
            return True
    return False


# ---- 알림 대상 판별 -------------------------------------------------------

def _scope_values(scope: Iterable[object]) -> set[str]:
    return {s.value if isinstance(s, Enum) else str(s) for s in scope}


def in_signal_scope(helper: Helper, assessment: RiskAssessment) -> bool:
    """당사자가 정한 '무엇을 알릴까요?'(signal_scope)에 이번 판단이 드는지. 비어 있으면 모두."""
    if not helper.signal_scope:
        return True
    hit_codes = {h.code.value for h in assessment.rule_hits}
    return bool(_scope_values(helper.signal_scope) & hit_codes)


def is_eligible(helper: Helper, assessment: RiskAssessment) -> bool:
    """자동 알림 대상인지: '자동으로 알리기'(active)를 켰고 당사자가 정한 등급·시그널 범위에 드는지.

    이해충돌은 따로 본다.
    """
    level = RiskLevel(assessment.level)
    if not helper.active or level == RiskLevel.NONE:
        return False
    # 문자열("high")로 들어와도 동작하도록 열거형으로 맞춘다
    if LEVEL_ORDER[level] < LEVEL_ORDER[RiskLevel(helper.min_level)]:
        return False
    return in_signal_scope(helper, assessment)


def names_phrase(names: list[str]) -> str:
    if len(names) <= 2:
        return ", ".join(names)
    return f"{names[0]} 외 {len(names) - 1}명"


def _topic(phrase: str) -> str:
    """은/는 조사를 붙인다. 끝 글자가 한글이 아니면 '은(는)'."""
    last = phrase[-1:] or " "
    if not 0xAC00 <= ord(last) <= 0xD7A3:
        return phrase + "은(는)"
    return phrase + ("은" if (ord(last) - 0xAC00) % 28 else "는")


def _conflict_reason(conflicted: list[Helper]) -> str:
    """'엄마는 돈을 받는 사람이에요.' — 이번 거래의 상대방이라 뺀 까닭."""
    return f"{_topic(names_phrase([h.name for h in conflicted]))} 돈을 받는 사람이에요."


def _make_notice(helper: Helper, txn_id: str, level: RiskLevel, message: str,
                 created_at: str) -> HelperNotice:
    return HelperNotice(helper_id=helper.id, helper_name=helper.name, txn_id=txn_id,
                        level=level, message=message, created_at=created_at)


def _timestamp(now: Optional[datetime]) -> str:
    return (now or datetime.now()).isoformat(timespec="seconds")


def _empty_plan(note: str = "") -> NotifyPlan:
    return NotifyPlan(notices=[], excluded_conflict=[], suggest_counseling=False,
                      counseling_orgs=[], note_to_person=note)


# ---- 공개 함수 ------------------------------------------------------------

def decide(assessment: RiskAssessment, txn: Transaction, helpers: list[Helper], consent: Consent,
           recent_high_count_30d: int, settings: Optional[Settings] = None, *,
           person_name: str = DEFAULT_PERSON_NAME, now: Optional[datetime] = None,
           preview: bool = False) -> NotifyPlan:
    """이번 판단에 대해 누구에게 알릴지, 상담 연계를 제안할지 정한다.

    recent_high_count_30d: 최근 30일 고위험 건수(이번 건 포함 여부는 호출자가 일관되게 정한다).
    preview: 당사자가 고르기 전 카드에 보여 줄 계획이면 True. 안내 문장을 현재형으로 쓴다
    (아직 아무것도 하지 않았으므로 '알리지 않았어요' 대신 '알리지 않아요').
    """
    settings = settings or Settings()
    if assessment.level == RiskLevel.NONE:
        return _empty_plan()

    repeat_high = (consent.counseling_referral
                   and recent_high_count_30d >= settings.high_repeat_for_counseling)

    if not consent.helper_alerts:
        plan = _empty_plan(NOTE_ALERTS_OFF)
        if repeat_high:
            plan.suggest_counseling = True
            plan.counseling_orgs = list(COUNSELING_ORGS)
        return plan

    eligible = [h for h in helpers if is_eligible(h, assessment)]
    conflicted = [h for h in eligible if is_conflict(h, txn)]
    to_notify = [h for h in eligible if h not in conflicted]

    all_conflicted = bool(eligible) and not to_notify
    suggest = repeat_high or (all_conflicted and consent.counseling_referral)

    created_at = _timestamp(now)
    message = helper_message(person_name)
    notices = [_make_notice(h, assessment.txn_id or txn.id, assessment.level, message, created_at)
               for h in to_notify]

    if to_notify:
        names = names_phrase([h.name for h in to_notify])
        note = (f"{_conflict_reason(conflicted)} 그래서 {names}에게만 알려 드릴게요." if conflicted
                else f"{names}에게 알려 드릴게요.")
    elif all_conflicted:
        verb = "않아요" if preview else "않았어요"
        note = (f"{_conflict_reason(conflicted)} 그래서 이번에는 "
                f"{names_phrase([h.name for h in conflicted])}에게 알리지 {verb}.")
    elif suggest:
        note = NOTE_COUNSELING
    elif not any(h.active for h in helpers):
        note = NOTE_NO_HELPER
    else:
        note = NOTE_NOT_NOTIFIED_PREVIEW if preview else NOTE_NOT_NOTIFIED

    return NotifyPlan(
        notices=notices,
        excluded_conflict=[h.id for h in conflicted],
        suggest_counseling=suggest,
        counseling_orgs=list(COUNSELING_ORGS) if suggest else [],
        note_to_person=note,
    )


def ask_helper_candidates(assessment: RiskAssessment, txn: Transaction,
                          helpers: list[Helper]) -> list[dict[str, Any]]:
    """'조력자에게 물어볼래요'에서 고를 수 있는 조력자 목록(화면이 고르기 전에 보여 준다).

    등록한 조력자 모두가 후보다. '자동으로 알리기'(active)를 꺼 둔 조력자도 직접 물을 때는 고를 수 있다.
    - default: 당사자가 정한 범위(signal_scope) 안이고 거래 상대방이 아니면 True(미리 골라 둠)
    - conflict: 이번 거래의 상대방이라 이번에는 물어볼 수 없음
    - active: 자동 알림을 받는 조력자인지(화면 안내용)
    """
    out: list[dict[str, Any]] = []
    for h in helpers:
        conflict = is_conflict(h, txn)
        scope = in_signal_scope(h, assessment)
        out.append({"id": h.id, "name": h.name, "relation": h.relation, "active": h.active,
                    "in_scope": scope, "conflict": conflict, "default": scope and not conflict})
    return out


def ask_helper_plan(assessment: RiskAssessment, txn: Transaction, helpers: list[Helper],
                    consent: Consent, *, helper_ids: Optional[Sequence[str]] = None,
                    person_name: str = DEFAULT_PERSON_NAME,
                    now: Optional[datetime] = None) -> NotifyPlan:
    """당사자가 직접 '조력자에게 물어볼래요'를 골랐을 때의 알림 계획.

    helper_ids: 당사자가 카드에서 고른 조력자 id. None이면 당사자가 정한 '무엇을 알릴까요?'
    범위(signal_scope) 안의 조력자에게 묻는다. 직접 요청이므로 자동 알림 설정(min_level·active)은
    보지 않는다('자동으로 알리기'를 꺼 둔 조력자에게도 물을 수 있음). 거래 상대방인 조력자는 골라도
    빼고, 고른 조력자가 모두 빠지면 동의 시 상담 연계를 제안한다.
    """
    if helper_ids is not None:
        wanted = {str(x) for x in helper_ids}
        chosen = [h for h in helpers if h.id in wanted]
    else:
        chosen = [h for h in helpers if in_signal_scope(h, assessment)]
    conflicted = [h for h in chosen if is_conflict(h, txn)]
    to_notify = [h for h in chosen if h not in conflicted]
    all_conflicted = bool(chosen) and not to_notify
    suggest = all_conflicted and consent.counseling_referral

    created_at = _timestamp(now)
    message = ask_helper_message(person_name)
    notices = [_make_notice(h, assessment.txn_id or txn.id, assessment.level, message, created_at)
               for h in to_notify]

    if to_notify:
        names = names_phrase([h.name for h in to_notify])
        note = (f"{_conflict_reason(conflicted)} 그래서 {names}에게만 물어볼게요." if conflicted
                else f"{names}에게 물어볼게요.")
    elif all_conflicted:
        note = f"{_conflict_reason(conflicted)} 그래서 이번에는 물어보지 않았어요."
    elif helpers:
        note = NOTE_NONE_CHOSEN
    else:
        note = NOTE_NO_HELPER_TO_ASK

    return NotifyPlan(
        notices=notices,
        excluded_conflict=[h.id for h in conflicted],
        suggest_counseling=suggest,
        counseling_orgs=list(COUNSELING_ORGS) if suggest else [],
        note_to_person=note,
    )


__all__ = [
    "COUNSELING_ORGS", "ask_helper_candidates", "ask_helper_message", "ask_helper_plan", "decide",
    "helper_message", "in_signal_scope", "is_conflict", "is_eligible", "names_phrase",
]
