"""요청 형식(pydantic)과 한국어 입력 오류 문구. PC(FastAPI)와 앱(Pyodide)이 같은 규칙으로 검사한다."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictBool, TypeAdapter, field_validator

from safepause.api.constants import MAX_EVAL_SEEDS, MAX_HELPERS, MAX_YEAR, MIN_YEAR, PERSONA_KEYS, SCENARIO_WINDOW_DAYS
from safepause.models import Decision, SignalCode

# 화면에서 입력할 수 있는 거래 방법(입금은 제외: 안전 정지는 돈이 나갈 때만)
PendingChannel = Literal["transfer", "card", "micropay", "telecom_bill", "atm", "other"]
EvalMode = Literal["fused", "rules", "anomaly"]

# 입력 오류 안내용 항목 이름
FIELD_KO: dict[str, str] = {
    "to": "받는 사람", "counterparty": "받는 사람", "amount": "금액", "channel": "보내는 방법",
    "ts": "시각", "time": "시각", "to_id": "계좌번호", "counterparty_id": "계좌번호",
    "line_id": "회선", "pending": "보낼 거래", "decision": "고른 것",
    "name": "이름", "relation": "관계", "contact": "연락처", "identifiers": "계좌번호·이름",
    "min_level": "알림 등급", "signal_scope": "알릴 범위", "active": "자동으로 알리기", "id": "번호",
    "monitoring": "거래 살펴보기", "helper_alerts": "조력자 알림",
    "counseling_referral": "상담 연결", "given_by": "동의한 사람",
    "persona": "인물", "seed": "번호(seed)", "scenarios": "걱정되는 거래 섞기", "days": "기간",
    "seeds": "반복 횟수", "personas": "인물", "modes": "방식", "helper_ids": "물어볼 조력자",
    "level": "보기", "limit": "개수", "offset": "시작 위치",
}


def validation_detail(errors: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """pydantic 오류 목록 → ('입력한 값을 확인해 주세요: 금액, 받는 사람', [{loc, type}])."""
    names: list[str] = []
    out: list[dict[str, Any]] = []
    for err in errors:
        loc = [str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path")]
        label = next((FIELD_KO[x] for x in reversed(loc) if x in FIELD_KO), None)
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


class HelperIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = Field(None, max_length=40, pattern=r"^[A-Za-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=30)
    relation: str = Field("", max_length=40)
    contact: str = Field("", max_length=60)
    identifiers: list[str] = Field(default_factory=list, max_length=20)
    min_level: Literal["caution", "high"] = "high"   # 기본: 고위험만(S22)
    signal_scope: list[SignalCode] = Field(default_factory=list)
    active: StrictBool = True

    @field_validator("name", "relation", "contact")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

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
    """거래 목록 조회 조건(쪽 나눔: offset·limit. limit=0이면 전부)."""

    model_config = ConfigDict(extra="ignore")
    level: Literal["all", "caution", "high"] = "all"
    limit: int = Field(0, ge=0, le=100_000)
    offset: int = Field(0, ge=0, le=10_000_000)


class CardsQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")
    limit: int = Field(20, ge=1, le=500)
