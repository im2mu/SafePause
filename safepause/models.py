"""Shared data contract for SafePause.

Every module imports its types from here. Do not change field names or types without
updating SPEC.md and all callers. All money is integer KRW (원). All datetimes are naive
local time (Asia/Seoul assumed); the app never converts time zones.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Direction(str, Enum):
    OUT = "out"  # 돈이 나감 (출금·결제·송금)
    IN = "in"    # 돈이 들어옴 (입금)


class Channel(str, Enum):
    TRANSFER = "transfer"          # 계좌 이체·송금
    CARD = "card"                  # 카드·간편결제 가맹점 결제
    MICROPAY = "micropay"          # 휴대폰(통신) 소액결제
    TELECOM_BILL = "telecom_bill"  # 통신요금 청구·납부 (회선별)
    ATM = "atm"                    # 현금 인출
    INCOME = "income"              # 급여·복지급여 등 입금
    OTHER = "other"


class RiskLevel(str, Enum):
    NONE = "none"        # 알림 없음
    CAUTION = "caution"  # 1차: 당사자 본인에게만 쉬운 말 안내
    HIGH = "high"        # 고위험: 당사자 안내 + (당사자 설정·동의 시) 신뢰 조력자 2차 알림


LEVEL_ORDER = {RiskLevel.NONE: 0, RiskLevel.CAUTION: 1, RiskLevel.HIGH: 2}


class SignalCode(str, Enum):
    """The five exploitation signals named in the submitted proposal (S19)."""
    NIGHT_REPEAT_TRANSFER = "night_repeat_transfer"    # 심야 시간대 반복 이체
    PAYEE_SURGE = "payee_surge"                        # 특정 계좌 앞 송금 급증
    MICROPAY_SURGE = "micropay_surge"                  # 통신 소액결제 급증
    NEW_MERCHANT_HIGH_VALUE = "new_merchant_high_value"  # 신규 가맹점 고액 결제 과다
    MULTI_LINE_TELECOM = "multi_line_telecom"          # 단기간 다회선 통신요금 청구


class Decision(str, Enum):
    """What the 당사자 chose on the Safe Pause card. The app never blocks: SEND is always allowed."""
    SEND = "send"                  # 그래도 보낼래요
    CANCEL = "cancel"              # 안 보낼래요
    ASK_HELPER = "ask_helper"      # 조력자에게 물어볼래요


@dataclass
class Transaction:
    id: str
    ts: datetime
    amount: int                    # KRW, always positive
    direction: Direction
    channel: Channel
    counterparty: str = ""         # 받는 사람/가맹점/통신사 표시 이름
    counterparty_id: str = ""      # 계좌번호·가맹점ID 등 식별값(마스킹 가능). 같은 상대 판별에 사용
    line_id: str = ""              # TELECOM_BILL/MICROPAY: 회선 식별값(예: 010-****-1234)
    memo: str = ""
    label: Optional[str] = None    # 합성 데이터 정답 라벨: None/"normal" 또는 SignalCode 값. 탐지에 사용 금지

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat(timespec="seconds")
        d["direction"] = self.direction.value
        d["channel"] = self.channel.value
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Transaction":
        return Transaction(
            id=str(d["id"]),
            ts=datetime.fromisoformat(str(d["ts"])),
            amount=int(d["amount"]),
            direction=Direction(d["direction"]),
            channel=Channel(d["channel"]),
            counterparty=str(d.get("counterparty", "") or ""),
            counterparty_id=str(d.get("counterparty_id", "") or ""),
            line_id=str(d.get("line_id", "") or ""),
            memo=str(d.get("memo", "") or ""),
            label=d.get("label"),
        )


@dataclass
class SignalHit:
    code: SignalCode
    severity: RiskLevel            # CAUTION or HIGH
    evidence: dict[str, Any]       # 숫자 근거 (예: {"count_7d": 4, "baseline_7d": 0.5})
    related_txn_ids: list[str] = field(default_factory=list)


@dataclass
class Reason:
    """One human-readable reason, before easy-language rendering."""
    code: str                      # SignalCode value, or "anomaly:<feature>"
    detail: dict[str, Any]         # 렌더링에 쓰는 값 (예: {"ratio": 10.2, "amount": 300000})


@dataclass
class RiskAssessment:
    txn_id: str
    level: RiskLevel
    rule_hits: list[SignalHit]
    anomaly_score: float           # 0.0~1.0, 당사자 개인 기준 대비 이례성(높을수록 이례적)
    reasons: list[Reason]
    model_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "txn_id": self.txn_id,
            "level": self.level.value,
            "anomaly_score": round(float(self.anomaly_score), 4),
            "rule_hits": [
                {"code": h.code.value, "severity": h.severity.value, "evidence": h.evidence,
                 "related_txn_ids": h.related_txn_ids} for h in self.rule_hits
            ],
            "reasons": [{"code": r.code, "detail": r.detail} for r in self.reasons],
            "model_version": self.model_version,
        }


@dataclass
class AlertCard:
    """Easy-to-read card shown to the 당사자 (Safe Pause). Rendering rules in SPEC.md §5."""
    txn_id: str
    level: RiskLevel
    title: str                     # 15자 이내
    lines: list[str]               # 1~4줄, 한 줄 30자 이내, 한 문장에 한 가지 내용
    pictograms: list[str]          # static/icons/<id>.svg 의 id
    question: str                  # 예: "이 돈을 정말 보내는 것이 맞나요?"
    choices: list[dict[str, str]]  # [{"decision": "send", "label": "그래도 보낼래요"}, ...]
    speak_text: str                # 음성 읽기(TTS)용 한 문단
    source: str = "template"       # "template" 또는 "llm"(선택 기능)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["level"] = self.level.value
        return d


@dataclass
class Helper:
    """신뢰 조력자. 당사자가 직접 지정하고, 알림 대상·범위도 당사자가 정한다 (S22, S37)."""
    id: str
    name: str
    relation: str                          # 예: "가족", "지역발달장애인지원센터 전담 인력"
    contact: str = ""                      # 표시용(마스킹). 실제 발송은 하지 않음
    identifiers: list[str] = field(default_factory=list)  # 이 조력자의 계좌번호·이름 등 (이해충돌 판별)
    min_level: RiskLevel = RiskLevel.HIGH  # 이 등급 이상만 알림 (기본: 고위험만, S22)
    signal_scope: list[str] = field(default_factory=list)  # 비어 있으면 모든 시그널
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["min_level"] = self.min_level.value
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Helper":
        return Helper(
            id=str(d["id"]), name=str(d["name"]), relation=str(d.get("relation", "")),
            contact=str(d.get("contact", "")), identifiers=[str(x) for x in d.get("identifiers", [])],
            min_level=RiskLevel(d.get("min_level", "high")),
            signal_scope=[str(x) for x in d.get("signal_scope", [])],
            active=bool(d.get("active", True)),
        )


@dataclass
class Consent:
    """당사자(또는 법정대리인)의 사전 동의와 즉시 철회권 (S18, S37)."""
    monitoring: bool = False        # 거래 분석 동의 (False면 분석하지 않음)
    helper_alerts: bool = False     # 신뢰 조력자 2차 알림 동의
    counseling_referral: bool = False  # 반복 고위험 시 상담기관 연계 동의 (S23)
    given_by: str = "self"          # "self" | "legal_representative"
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HelperNotice:
    helper_id: str
    helper_name: str
    txn_id: str
    level: RiskLevel
    message: str                    # 조력자용 요약 (당사자 결정 존중 문구 포함)
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["level"] = self.level.value
        return d


@dataclass
class NotifyPlan:
    """GuardianPolicy.decide() 결과."""
    notices: list[HelperNotice]
    excluded_conflict: list[str]    # 거래 상대방이라 이번 건 알림에서 제외된 조력자 id
    suggest_counseling: bool        # 상담기관 연계 제안 여부 (동의 있을 때만 True)
    counseling_orgs: list[str]      # 예: ["지역발달장애인지원센터", "장애인권익옹호기관"]
    note_to_person: str             # 당사자에게 보여 줄 한 줄 설명 (쉬운 말)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notices": [n.to_dict() for n in self.notices],
            "excluded_conflict": self.excluded_conflict,
            "suggest_counseling": self.suggest_counseling,
            "counseling_orgs": self.counseling_orgs,
            "note_to_person": self.note_to_person,
        }
