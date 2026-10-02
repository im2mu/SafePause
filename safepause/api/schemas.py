"""요청 형식(pydantic)과 한국어 입력 오류 문구. PC(FastAPI)와 앱(Pyodide)이 같은 규칙으로 검사한다."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    field_validator,
    model_validator,
)

from safepause.api.constants import (
    MAX_EVAL_SEEDS,
    MAX_HELPERS,
    MAX_NOTICE_MESSAGE,
    MAX_NOTICE_RECIPIENTS,
    MAX_NOTICE_TXNS,
    MAX_TXN_ID_CHARS,
    MAX_YEAR,
    MIN_YEAR,
    PERSONA_KEYS,
    SCENARIO_WINDOW_DAYS,
)
from safepause.models import EMAIL_RE, PHONE_RE, Decision, SignalCode, split_legacy_contact

# 화면에서 입력할 수 있는 거래 방법(입금은 제외: 안전 정지는 돈이 나갈 때만)
PendingChannel = Literal["transfer", "card", "micropay", "telecom_bill", "atm", "other"]
EvalMode = Literal["fused", "rules", "anomaly"]
CounselorKind = Literal["disability_center", "rights_agency", "police", "finance", "other"]   # = constants.COUNSELOR_KINDS
NoticeChannel = Literal["sms", "email", "call", "copy"]                                       # = constants.NOTICE_CHANNELS

# 입력 오류 안내용 항목 이름
FIELD_KO: dict[str, str] = {
    "to": "받는 사람", "counterparty": "받는 사람", "amount": "금액", "channel": "보내는 방법",
    "ts": "시각", "time": "시각", "to_id": "계좌번호", "counterparty_id": "계좌번호",
    "line_id": "회선", "pending": "보낼 거래", "decision": "고른 것",
    "name": "이름", "relation": "관계", "contact": "연락처", "identifiers": "계좌번호·이름",
    "min_level": "알림 등급", "signal_scope": "알릴 범위", "active": "자동으로 알리기", "id": "번호",
    "monitoring": "거래 살펴보기", "helper_alerts": "조력자에게 알리기",
    "counseling_referral": "상담하는 곳에 알려 주기", "given_by": "동의한 사람",
    "persona": "인물", "seed": "번호(seed)", "scenarios": "걱정되는 거래 섞기", "days": "기간",
    "seeds": "반복 횟수", "personas": "인물", "modes": "방식", "helper_ids": "물어볼 조력자",
    "level": "보기", "limit": "개수", "offset": "시작 위치",
    "phone": "전화번호", "email": "이메일", "phone_masked": "전화번호", "email_masked": "이메일",
    "kind": "종류", "memo": "메모", "txn_id": "거래", "txn_ids": "거래", "recipients": "받는 사람",
    "message": "보낼 글",
}


def validation_detail(errors: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """pydantic 오류 목록 → ('입력한 값을 확인해 주세요: 금액, 받는 사람', [{loc, type}])."""
    names: list[str] = []
    out: list[dict[str, Any]] = []
    for err in errors:
        loc = [str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path")]
        label = next((FIELD_KO[x] for x in reversed(loc) if x in FIELD_KO), None)
        if err.get("type") == "extra_forbidden" and loc:   # 받지 않는 칸: 영어 경로 대신 쉬운 말 + 칸 이름
            label = f"받지 않는 항목({loc[-1]})"
        names.append(label or (".".join(loc) or "요청"))
        out.append({"loc": loc, "type": str(err.get("type", ""))})
    return "입력한 값을 확인해 주세요: " + ", ".join(dict.fromkeys(names)), out


class ConsentIn(BaseModel):
    """동의 부분 변경. 보낸 항목만 바꾼다(세 가지 동의를 따로 켜고 끔)."""

    model_config = ConfigDict(extra="forbid")
    monitoring: Optional[StrictBool] = None
    helper_alerts: Optional[StrictBool] = None
    counseling_referral: Optional[StrictBool] = None
    given_by: Optional[Literal["self", "legal_representative"]] = None


def _check_phone(value: str) -> str:
    value = value.strip()
    if value and (not PHONE_RE.fullmatch(value) or not any(ch.isdigit() for ch in value)):
        raise ValueError("전화번호는 숫자로 적어 주세요.")
    return value


def _check_email(value: str) -> str:
    value = value.strip()
    if value and not EMAIL_RE.fullmatch(value):
        raise ValueError("이메일 모양이 아니에요.")
    return value


class HelperIn(BaseModel):
    """조력자 한 명. phone·email 원본은 이 기기에만 저장한다(문자·메일 앱을 열 때 씀).

    contact는 옛 클라이언트(phone·email 칸을 보내지 않음)용이다. 그때만 contact를 나눠 넣는다(@가 있으면 메일).
    phone·email 칸을 보내는 새 클라이언트의 contact(GET이 준 가린 표시)는 쓰지 않는다. 번호·메일을 지웠는데
    옛 표시가 남지 않게 하기 위함이다. GET이 주는 phone_masked·email_masked도 그대로 돌려보내도 되며 무시한다.
    """

    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(None, max_length=40, pattern=r"^[A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=30)
    relation: str = Field("", max_length=40)
    phone: str = Field("", max_length=20)
    email: str = Field("", max_length=80)
    contact: str = Field("", max_length=60)
    phone_masked: Optional[str] = Field(None, max_length=100)   # 보여 주기용(무시)
    email_masked: Optional[str] = Field(None, max_length=100)   # 보여 주기용(무시)
    identifiers: list[str] = Field(default_factory=list, max_length=20)
    min_level: Literal["caution", "high"] = "high"   # 기본: 고위험만(S22)
    signal_scope: list[SignalCode] = Field(default_factory=list)
    active: StrictBool = True

    @model_validator(mode="before")
    @classmethod
    def _legacy_contact(cls, data: Any) -> Any:
        """옛 클라이언트가 contact만 보낸 경우: 번호·메일로 나눈다(나눈 값도 아래 형식 검사를 받는다)."""
        if not isinstance(data, dict) or "contact" not in data:
            return data
        if "phone" in data or "email" in data:   # 새 클라이언트: contact는 보여 주기용이라 버린다
            return {**data, "contact": ""}
        contact = data.get("contact")
        if not isinstance(contact, str) or not contact.strip():
            return data                          # 글이 아닌 값은 그대로 두어 422
        p, e, keep = split_legacy_contact(contact)
        return {**data, "phone": p, "email": e, "contact": keep}

    @field_validator("name", "relation", "contact")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return _check_phone(value)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _check_email(value)

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value:
            raise ValueError("이름을 적어 주세요.")
        return value

    @field_validator("identifiers")
    @classmethod
    def _clean_identifiers(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        for v in values:
            v = v.strip()
            if len(v) > 60:
                raise ValueError("계좌번호·이름은 60자까지 적을 수 있어요.")
            if v and v not in out:
                out.append(v)
        return out


HelperList = TypeAdapter(list[HelperIn])


class CounselorIn(BaseModel):
    """상담하는 곳 하나(v0.3). 검증 방식은 HelperIn과 같다."""

    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(None, max_length=40, pattern=r"^[A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=30)
    kind: CounselorKind = "other"
    phone: str = Field("", max_length=20)
    email: str = Field("", max_length=80)
    memo: str = Field("", max_length=100)
    active: StrictBool = True

    @field_validator("name", "memo")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value:
            raise ValueError("이름을 적어 주세요.")
        return value

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return _check_phone(value)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return _check_email(value)


CounselorList = TypeAdapter(list[CounselorIn])


class FlagIn(BaseModel):
    """알림 목록에 담기·빼기."""

    model_config = ConfigDict(extra="forbid")
    txn_id: str = Field(min_length=1, max_length=MAX_TXN_ID_CHARS)

    @field_validator("txn_id")
    @classmethod
    def _txn_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("거래를 골라 주세요.")
        return value


def _clean_txn_ids(values: list[str]) -> list[str]:
    """거래 id 목록: 앞뒤 빈칸을 떼고 빈 값은 빼며 겹치면 한 번만(들어온 순서대로). 너무 긴 id는 오류."""
    out = [v.strip() for v in values if v and v.strip()]
    if any(len(v) > MAX_TXN_ID_CHARS for v in out):
        raise ValueError("거래 번호가 너무 길어요.")
    return list(dict.fromkeys(out))


class NoticeRecipientIn(BaseModel):
    """알림을 받은 사람(조력자·상담하는 곳). 번호·메일 같은 다른 칸은 받아도 저장하지 않는다."""

    model_config = ConfigDict(extra="ignore")
    kind: Literal["helper", "counselor"]
    id: str = Field("", max_length=40)
    name: str = Field(min_length=1, max_length=30)

    @field_validator("id", "name")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        if not value:
            raise ValueError("이름을 적어 주세요.")
        return value


class NoticeRecordIn(BaseModel):
    """문자·메일 앱으로 직접 보낸 알림 기록(v0.3)."""

    model_config = ConfigDict(extra="forbid")
    channel: NoticeChannel
    recipients: list[NoticeRecipientIn] = Field(min_length=1, max_length=MAX_NOTICE_RECIPIENTS)
    txn_ids: list[str] = Field(default_factory=list, max_length=MAX_NOTICE_TXNS)
    message: str = Field(min_length=1, max_length=MAX_NOTICE_MESSAGE)

    @field_validator("txn_ids")
    @classmethod
    def _txn_ids(cls, values: list[str]) -> list[str]:
        return _clean_txn_ids(values)

    @field_validator("message")
    @classmethod
    def _message_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("보낼 글을 적어 주세요.")
        return value


class SuggestIn(BaseModel):
    """알림 보내기의 받는 사람 추천(v0.3 돈 보내기 설계). 고른 거래 0~20개(없으면 조력자 설정만 본다)."""

    model_config = ConfigDict(extra="forbid")
    txn_ids: list[str] = Field(default_factory=list, max_length=MAX_NOTICE_TXNS)

    @field_validator("txn_ids")
    @classmethod
    def _txn_ids(cls, values: list[str]) -> list[str]:
        return _clean_txn_ids(values)


class PendingIn(BaseModel):
    """보내려는 거래(아직 보내지 않음). check 응답의 pending(거래 dict)을 그대로 받아도 된다."""

    model_config = ConfigDict(extra="ignore")
    to: str = Field(min_length=1, max_length=40, validation_alias=AliasChoices("to", "counterparty"))
    amount: int = Field(gt=0, le=10_000_000_000)
    channel: PendingChannel = "transfer"
    to_id: str = Field("", max_length=60, validation_alias=AliasChoices("to_id", "counterparty_id"))
    line_id: str = Field("", max_length=30)
    ts: Optional[datetime] = None
    time: Optional[str] = Field(None, pattern=r"^([01]?\d|2[0-3]):[0-5]\d$")
    # check가 정한 연습 거래 id(live-…). decide에 같은 id를 다시 보내면 같은 시도로 보고 두 번 적지 않는다
    id: Optional[str] = Field(None, max_length=40)

    @field_validator("to")
    @classmethod
    def _to_required(cls, value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            raise ValueError("받는 사람을 적어 주세요.")
        return value

    @field_validator("ts")
    @classmethod
    def _ts_in_range(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and not MIN_YEAR <= value.year <= MAX_YEAR:
            raise ValueError(f"시각은 {MIN_YEAR}~{MAX_YEAR}년 사이여야 해요.")
        return value


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pending: PendingIn
    decision: Decision
    # '조력자에게 물어볼래요'에서 당사자가 고른 조력자(없으면 당사자가 정한 범위 안의 조력자)
    helper_ids: Optional[list[str]] = Field(None, max_length=MAX_HELPERS)

    @field_validator("helper_ids")
    @classmethod
    def _clean_ids(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        out = [v.strip() for v in values if v and v.strip()]
        if any(len(v) > 40 for v in out):
            raise ValueError("조력자 번호가 너무 길어요.")
        return list(dict.fromkeys(out))


class SampleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: str = "worker"
    seed: int = Field(1, ge=0, le=1_000_000)
    scenarios: StrictBool = True
    days: int = Field(120, ge=SCENARIO_WINDOW_DAYS + 1, le=365)

    @field_validator("persona")
    @classmethod
    def _known_persona(cls, value: str) -> str:
        if value not in PERSONA_KEYS:
            raise ValueError(f"인물은 {', '.join(PERSONA_KEYS)} 중 하나예요.")
        return value


class EvalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seeds: int = Field(5, ge=1, le=MAX_EVAL_SEEDS)
    personas: Optional[list[str]] = Field(None, min_length=1)
    modes: list[EvalMode] = Field(default_factory=lambda: ["fused"], min_length=1, max_length=3)

    @field_validator("personas")
    @classmethod
    def _known_personas(cls, values: Optional[list[str]]) -> Optional[list[str]]:
        if values is None:
            return None
        unknown = [v for v in values if v not in PERSONA_KEYS]
        if unknown:
            raise ValueError(f"알 수 없는 인물: {', '.join(unknown)}")
        return list(dict.fromkeys(values))


class TxnQuery(BaseModel):
    """거래 목록 조회 조건(쪽 나눔: offset·limit. limit=0이면 전부). level=flagged는 담은 거래만."""

    model_config = ConfigDict(extra="ignore")
    level: Literal["all", "caution", "high", "flagged"] = "all"
    limit: int = Field(0, ge=0, le=100_000)
    offset: int = Field(0, ge=0, le=10_000_000)


class CardsQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")
    limit: int = Field(20, ge=1, le=500)
