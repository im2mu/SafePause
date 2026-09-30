"""SafePause 로컬 웹 서버(FastAPI). SPEC §10, 제안서 S20~S23·S35·S37·S38.

원칙
- 127.0.0.1 전용: Host 머리글이 loopback 이름이 아니면 거절한다(DNS 리바인딩 방지).
  바인드 주소는 CLI(``python -m safepause serve``)가 127.0.0.1로 고정한다.
- 상태를 바꾸는 요청(POST/PUT)은 ``X-SafePause: 1`` 머리글이 있어야 하고, Origin 머리글이 있으면
  같은 출처여야 한다('null' 출처도 거절). 다른 웹사이트가 사용자의 브라우저로 몰래 보내는 요청
  (예: 데이터 지우기)을 막기 위함이다. 화면(app.js)은 늘 머리글을 붙이고 null 출처를 보내지 않는다.
- 보내기 연습 거래 id(live-…)는 check마다 새로 주고 거래 내용(지문)과 묶어 기억한다. decide는 같은
  id·같은 내용일 때만 '같은 시도'로 보고, 내용이 다르면 새 id를 준다(다른 탭의 거래를 덮어쓰지 않음).
- 거래 분석(내 거래 평가·안전 정지·알림 카드)은 당사자의 '거래 살펴보기'(monitoring) 동의가
  있을 때만 한다. 동의가 없으면 403과 한국어 안내를 돌려준다.
- 어떤 경우에도 거래를 막지 않는다. "그래도 보낼래요"는 늘 기록된다. 실제 송금·알림 발송은 없다.
- 외부 네트워크 호출 없음. 모든 데이터는 로컬 JSON 저장소(store.Store)에만 둔다.
- 메모리에 든 분석 결과는 저장 파일(transactions.json)의 표식이 바뀌면 버리고 다시 만든다.
  서버 밖(``python -m safepause wipe``, 다른 serve 창)에서 지운 거래가 되살아나지 않게 하기 위함이다.
- 지우기·동의 끄기는 '세대 번호'를 올린다. 오래 걸리는 저장(파일 올리기·연습용 거래 불러오기)은
  시작 때의 세대 번호와 저장 직전의 번호가 다르면 저장하지 않는다(철회·지우기가 먼저).
- 올린 파일은 메모리에서만 읽는다(시스템 임시 폴더에 쓰지 않음). 크기는 받는 동안 센다.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time as _clock
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from datetime import time as dtime
from email import policy as _email_policy
from email.parser import BytesParser
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictBool, field_validator
from starlette.concurrency import run_in_threadpool

from safepause import __version__, config
from safepause.config import Settings
from safepause.data import synth
from safepause.data.loader import LoaderError, load_csv
from safepause.detect.anomaly import MIN_TRAIN
from safepause.detect.engine import RiskEngine
from safepause.explain.easy_card import channel_words, practice_result, render_card
from safepause.guardian import policy
from safepause.guardian.outbox import DELIVERY_NOTE, Outbox
from safepause.models import (
    Channel,
    Consent,
    Decision,
    Direction,
    Helper,
    NotifyPlan,
    RiskAssessment,
    RiskLevel,
    SignalCode,
    Transaction,
)
from safepause.store import FileSignature, Store, StoreError

# ---- 상수 -----------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent / "static"
ALLOWED_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
CLIENT_HEADER = "x-safepause"          # 상태 변경 요청에 필요한 머리글(값 "1")

TRAIN_RATIO = 0.75                     # 저장된 거래 앞 75%로 학습(최소 MIN_TRAIN건)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
UPLOAD_OVERHEAD_BYTES = 64 * 1024      # multipart 머리글 등 파일 밖 여유분
UPLOAD_PATH = "/api/data/upload"
MAX_HELPERS = 10
MAX_EVAL_SEEDS = 20
LIVE_ID_PREFIX = "live-"               # 안전 정지 연습으로 더한 거래 id
LIVE_ID_RE = re.compile(rf"{LIVE_ID_PREFIX}(\d{{1,9}})")
MAX_REMEMBERED_LIVE_IDS = 1000         # check가 준 연습 거래 id를 이만큼 기억한다(오래된 것부터 잊음)
PRACTICE_MEMO = "안전 정지 연습"
MIN_YEAR, MAX_YEAR = synth.MIN_YEAR, synth.MAX_YEAR

PRACTICE_NOTE = "연습 화면이에요. 실제로 돈이 나가지 않아요."
TS_NOTE = ("연습 거래는 저장된 거래의 마지막 날에 이어서 적어요. "
           "그래서 날짜가 오늘과 달라요. 시각만 고른 대로예요.")
TOO_BIG = "파일이 너무 커요(5MB까지)."
NO_MONITORING = ("거래 살펴보기에 동의하지 않아서 분석하지 않았어요. "
                 "① 동의 화면에서 '거래 살펴보기'를 켜 주세요.")
SUPERSEDED = ("지우기(또는 동의 끄기)가 먼저 처리돼서 이번 거래는 저장하지 않았어요. "
              "필요하면 다시 해 주세요.")
NO_FILE = "올린 파일을 찾지 못했어요. CSV 파일을 골라 다시 올려 주세요."
SYNTHETIC_NOTE = "합성 데이터 기준, 실제 피해 데이터 검증 아님"
LABELED_NOTE = ("지금 저장된 거래에는 연습용으로 섞은 걱정되는 거래가 있어요. "
                "이 숫자는 잘못 알린 비율이 아니에요.")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 화면에서 입력할 수 있는 거래 방법(입금은 제외: 안전 정지는 돈이 나갈 때만)
PendingChannel = Literal["transfer", "card", "micropay", "telecom_bill", "atm", "other"]
EvalMode = Literal["fused", "rules", "anomaly"]
# (인물 목록, seed 목록, 방식 목록) → {방식: 결과 dict}
Evaluator = Callable[[list[str], list[int], list[str]], dict[str, dict[str, Any]]]

_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'")

# 입력 오류 안내용 항목 이름
_FIELD_KO: dict[str, str] = {
    "to": "받는 사람", "counterparty": "받는 사람", "amount": "금액", "channel": "보내는 방법",
    "ts": "시각", "time": "시각", "to_id": "계좌번호", "counterparty_id": "계좌번호",
    "line_id": "회선", "pending": "보낼 거래", "decision": "고른 것",
    "name": "이름", "relation": "관계", "contact": "연락처", "identifiers": "계좌번호·이름",
    "min_level": "알림 등급", "signal_scope": "알릴 범위", "active": "자동으로 알리기", "id": "번호",
    "monitoring": "거래 살펴보기", "helper_alerts": "조력자 알림",
    "counseling_referral": "상담 연결", "given_by": "동의한 사람",
    "persona": "인물", "seed": "번호(seed)", "scenarios": "걱정되는 거래 섞기", "days": "기간",
    "seeds": "반복 횟수", "personas": "인물", "modes": "방식", "helper_ids": "물어볼 조력자",
}


class EvalUnavailable(RuntimeError):
    """성능 평가 모듈을 쓸 수 없을 때."""


# ---- 요청 형식 ------------------------------------------------------------

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


class PendingIn(BaseModel):
    """보내려는 거래(아직 보내지 않음). check 응답의 pending(거래 dict)을 그대로 받아도 된다."""

    model_config = ConfigDict(extra="ignore")
    to: str = Field(min_length=1, max_length=40,
                    validation_alias=AliasChoices("to", "counterparty"))
    amount: int = Field(gt=0, le=10_000_000_000)
    channel: PendingChannel = "transfer"
    to_id: str = Field("", max_length=60,
                       validation_alias=AliasChoices("to_id", "counterparty_id"))
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
    days: int = Field(120, ge=synth.SCENARIO_WINDOW_DAYS + 1, le=365)

    @field_validator("persona")
    @classmethod
    def _known_persona(cls, value: str) -> str:
        if value not in synth.PERSONAS:
            raise ValueError(f"인물은 {', '.join(synth.PERSONAS)} 중 하나예요.")
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
        unknown = [v for v in values if v not in synth.PERSONAS]
        if unknown:
            raise ValueError(f"알 수 없는 인물: {', '.join(unknown)}")
        return list(dict.fromkeys(values))


# ---- 분석 상태 ------------------------------------------------------------

@dataclass(frozen=True)
class _Snapshot:
    """저장된 거래로 학습한 엔진과 그 평가 결과(시간순)."""

    txns: tuple[Transaction, ...]
    assessments: tuple[RiskAssessment, ...]
    engine: RiskEngine
    train_count: int


def train_count(txns: Sequence[Transaction]) -> int:
    """시간순 거래 가운데 앞쪽 몇 건으로 개인 기준(AI)을 배울지.

    - 걱정되는 거래를 섞은 합성 데이터(시나리오 라벨이 있음): 마지막 SCENARIO_WINDOW_DAYS일
      이전 거래만(eval.metrics.synthetic_case와 같은 날짜 경계). 섞은 거래를 '평소'로 배우지 않게
      하고, ⑥ 성능 확인 보고서와 같은 방식으로 보여 주기 위함이다. 라벨은 경계를 정하는 데만 쓴다.
    - 그 밖(실제 거래내역 등): 앞 75%(올림, 최소 MIN_TRAIN건). eval.metrics.split_baseline과 같다.
    """
    if any(t.label and t.label != synth.NORMAL_LABEL for t in txns):
        last = max(t.ts for t in txns if t.label)       # 연습 거래(라벨 없음)는 빼고 본다
        cutoff = datetime.combine(last.date() - timedelta(days=synth.SCENARIO_WINDOW_DAYS - 1),
                                  dtime.min)
        return sum(1 for t in txns if t.ts < cutoff)
    return min(len(txns), max(MIN_TRAIN, math.ceil(len(txns) * TRAIN_RATIO)))


class _State:
    """앱 하나의 저장소·엔진 상태. 요청은 잠금으로 직렬화한다(당사자 한 명용 로컬 앱)."""

    def __init__(self, root: Path, settings: Settings, seed: int,
                 evaluator: Optional[Evaluator], now: Callable[[], datetime]) -> None:
        self.store = Store(root)
        self.outbox = Outbox(self.store)
        self.settings = settings
        self.seed = seed
        self.evaluator = evaluator
        self.now = now
        self.lock = threading.RLock()
        self.generation = 0   # 지우기·동의 끄기마다 1씩 오른다(늦게 끝난 저장을 버리는 데 씀)
        self._snap: Optional[_Snapshot] = None
        self._snap_sig: Optional[FileSignature] = None
        # check가 준 연습 거래 id → 거래 지문. 번호 최댓값은 지우기 뒤에도 이어 간다(열린 탭의 옛 id와 겹치지 않게)
        self._live_ids: "OrderedDict[str, tuple[Any, ...]]" = OrderedDict()
        self._live_high = 0

    def reset(self) -> None:
        """메모리에 든 모델·평가 결과를 버린다(데이터 변경·동의 철회·지우기)."""
        with self.lock:
            self._snap = None
            self._snap_sig = None

    def revoke(self) -> None:
        """지우기·동의 끄기: 메모리 결과(연습 거래 지문 포함)를 버리고 세대 번호를 올린다."""
        with self.lock:
            self.generation += 1
            self._live_ids.clear()   # 받는 사람·금액이 든 지문도 버린다(번호 최댓값만 남김)
            self.reset()

    # ---- 보내기 연습 거래 id ----
    def issue_live_id(self, used_ids: Iterable[str]) -> str:
        """저장된 거래·결정 기록·이미 준 id 어느 것과도 겹치지 않는 다음 연습 거래 id."""
        with self.lock:
            number = max([_live_number(x) for x in used_ids] + [self._live_high]) + 1
            self._live_high = number
            return f"{LIVE_ID_PREFIX}{number:05d}"

    def remember_live(self, txn: Transaction) -> None:
        """연습 거래 id와 그 내용(지문)을 묶어 기억한다."""
        with self.lock:
            self._live_ids[txn.id] = _fingerprint(txn)
            self._live_ids.move_to_end(txn.id)
            self._live_high = max(self._live_high, _live_number(txn.id))
            while len(self._live_ids) > MAX_REMEMBERED_LIVE_IDS:
                self._live_ids.popitem(last=False)

    def live_fingerprint(self, txn_id: str) -> Optional[tuple[Any, ...]]:
        with self.lock:
            return self._live_ids.get(txn_id)

    def snapshot(self) -> _Snapshot:
        """필요하면 다시 학습한다: 저장된 거래 앞쪽(train_count)으로 학습, 전체를 평가.

        저장 파일 표식(수정 시각·크기·파일 번호)이 바뀌었으면(서버 밖에서 지우거나 고친 경우 포함)
        메모리 결과를 버리고 디스크에서 다시 읽는다.
        """
        with self.lock:
            sig = self.store.signature()  # 읽기 전에 표식을 잡는다(그 사이 바뀌면 다음에 다시 읽음)
            if self._snap is None or sig != self._snap_sig:
                txns = sorted(self.store.load_transactions(), key=lambda t: t.ts)
                n_train = train_count(txns)
                engine = RiskEngine(self.settings, self.seed)
                engine.fit(txns[:n_train])  # 30건 미만이면 모델 없이 룰만 쓴다
                assessments = engine.assess_many(txns) if txns else []
                self._snap = _Snapshot(tuple(txns), tuple(assessments), engine, n_train)
                self._snap_sig = sig
            return self._snap

    def timestamp(self) -> str:
        return self.now().isoformat(timespec="seconds")


# ---- 도우미 ---------------------------------------------------------------

def _plain(obj: Any) -> Any:
    """JSON으로 보낼 수 있게 바꾼다(numpy 값·NaN 처리)."""
    if isinstance(obj, Enum):
        return _plain(obj.value)
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_plain(v) for v in obj]
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float)):
        # numpy.float64처럼 float·int를 이어받은 값도 내장 형으로 바꾼다(pydantic 버전과 관계없이 직렬화)
        if isinstance(obj, float):
            return float(obj) if math.isfinite(obj) else None
        return int(obj)
    if isinstance(obj, (datetime, dtime)):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy 스칼라
        return _plain(obj.item())
    if hasattr(obj, "tolist"):  # numpy 배열
        return _plain(obj.tolist())
    return str(obj)


def _norm_name(name: str) -> str:
    return "".join((name or "").split()).casefold()


_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+*\-]+)@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
# 1단계: 숫자와 그 사이의 흔한 구분 기호(공백·하이픈·점·괄호·+·여러 대시)가 이어진 구간
_DASHES = "‐‑‒–—―−"
_NUMBER_RUN_RE = re.compile(rf"[+(]*\d(?:[\d\s().\-{_DASHES}+]*\d)?")
# 2단계: 숫자와 글자(한글 음절·영문)·가림표(*)·@가 아닌 모든 문자를 구분 기호로 본 구간
# (예: '010ㆍ1234ㆍ5678', '010/1234/5678', '010_1234_5678', '010ㅡ1234ㅡ5678')
_ANY_SEP_RUN_RE = re.compile(r"[+(]*\d(?:[^0-9A-Za-z가-힣*@]*\d)*")
# 이미 가린 모양(010-****-5678, ***5678). 2·3단계에서 건드리지 않는다
_MASKED_RE = re.compile(r"(0\d{1,2}-?\*{3,4}-?\d{4}|\*{3,}\d{4})")
_MIN_MASK_DIGITS = 7   # 숫자가 이만큼 있으면 전화·계좌 같은 번호로 보고 가린다
_KEEP_DIGITS = 4       # 가린 뒤 보여 주는 끝자리 수


def _mask_number(run: str) -> str:
    """번호 구간 하나를 가린다. 전화번호는 010-****-5678 모양, 그 밖은 끝 4자리만."""
    digits = re.sub(r"\D", "", run)
    if len(digits) < _MIN_MASK_DIGITS:
        return run
    if run.lstrip("(").startswith("+82"):          # 국제 표기(+82 10 …) → 국내 번호(010 …)
        digits = "0" + digits[2:].lstrip("0")
    lead = "(" if run.startswith("(") and ")" not in run else ""   # 짝 없는 여는 괄호는 남긴다
    if digits.startswith("0") and 9 <= len(digits) <= 11:
        prefix = "02" if digits.startswith("02") else digits[:3]
        return f"{lead}{prefix}-****-{digits[-_KEEP_DIGITS:]}"
    return lead + "*" * (len(digits) - _KEEP_DIGITS) + digits[-_KEEP_DIGITS:]


def _mask_plain(text: str) -> str:
    """가린 모양 밖의 글: 어떤 구분 기호로 나눠 적었어도 숫자 7개 이상 구간을 가린다.

    그래도 숫자가 7개 이상 남으면(글자 사이에 끼워 적은 번호 등) 끝 4자리만 남기고 모두 가린다.
    """
    text = _ANY_SEP_RUN_RE.sub(lambda m: _mask_number(m.group(0)), text)
    pieces = _MASKED_RE.split(text)      # 홀수 번째 조각 = 가린 모양
    plain_digits = sum(ch.isdigit() for k, piece in enumerate(pieces) if k % 2 == 0 for ch in piece)
    if plain_digits < _MIN_MASK_DIGITS:
        return text
    keep = _KEEP_DIGITS
    out: list[str] = []
    for k in range(len(pieces) - 1, -1, -1):   # 뒤에서부터 끝 4자리만 남긴다
        piece = pieces[k]
        if k % 2:
            out.append(piece)
            continue
        chars = list(piece)
        for i in range(len(chars) - 1, -1, -1):
            if chars[i].isdigit():
                if keep > 0:
                    keep -= 1
                else:
                    chars[i] = "*"
        out.append("".join(chars))
    return "".join(reversed(out))


def _mask_contact(value: str) -> str:
    """조력자 연락처를 가려서 저장한다(보여 주기용. 발송 기능이 없어 전체 값을 둘 까닭이 없음).

    1) 메일 abcd@x.kr → ab***@x.kr.
    2) 숫자·흔한 구분 기호가 이어진 구간에 숫자가 7개 이상이면 전화번호(010 1234 5678,
       (010)1234-5678, +82-10-1234-5678 등)는 010-****-5678로, 그 밖의 번호는 끝 4자리만 남긴다.
    3) 가린 모양 밖에 숫자가 아직 7개 이상이면, 숫자·글자가 아닌 모든 문자를 구분 기호로 보고 다시
       가린다('010ㆍ1234ㆍ5678' → 010-****-5678). 그래도 남으면 끝 4자리만 남긴다.
    이미 가린 값(010-****-5678)은 그대로다.
    """
    text = (value or "").strip()
    if not text:
        return ""

    def email(m: "re.Match[str]") -> str:
        local = m.group(1)
        keep = (local[:2] if len(local) > 2 else local[:1]).rstrip("*")
        return f"{keep}***@{m.group(2)}"

    text = _EMAIL_RE.sub(email, text)
    text = _NUMBER_RUN_RE.sub(lambda m: _mask_number(m.group(0)), text)
    pieces = _MASKED_RE.split(text)
    return "".join(piece if k % 2 else _mask_plain(piece) for k, piece in enumerate(pieces))


def _require_monitoring(store: Store) -> Consent:
    consent = store.load_consent()
    if not consent.monitoring:
        raise HTTPException(status_code=403, detail=NO_MONITORING)
    return consent


def _summary(txns: Sequence[Transaction]) -> dict[str, Any]:
    ordered = sorted(txns, key=lambda t: t.ts)
    labels = Counter(t.label for t in ordered if t.label and t.label != synth.NORMAL_LABEL)
    return {
        "count": len(ordered),
        "first_ts": ordered[0].ts.isoformat(timespec="seconds") if ordered else None,
        "last_ts": ordered[-1].ts.isoformat(timespec="seconds") if ordered else None,
        "channels": dict(Counter(t.channel.value for t in ordered)),
        "scenario_labels": dict(labels),   # 합성 데이터 정답(탐지에는 쓰지 않음)
    }


def _item(txn: Transaction, assessment: RiskAssessment) -> dict[str, Any]:
    return _plain({
        "txn": txn.to_dict(),
        "level": assessment.level.value,
        "signals": [h.code.value for h in assessment.rule_hits],
        "anomaly_score": round(float(assessment.anomaly_score), 4),
        "reasons": [{"code": r.code, "detail": r.detail} for r in assessment.reasons],
        "practice": txn.id.startswith(LIVE_ID_PREFIX),
    })


def _known_counterparty_id(history: Sequence[Transaction], channel: Channel, name: str) -> str:
    """같은 방법으로 같은 이름에게 보낸 적이 있으면 그때의 식별값(계좌 등)을 쓴다."""
    key = _norm_name(name)
    for t in reversed(history):
        if t.channel == channel and t.direction == Direction.OUT and _norm_name(t.counterparty) == key:
            return t.counterparty_id
    return ""


def _known_line(history: Sequence[Transaction]) -> str:
    """당사자 본인 회선(가장 최근 통신요금 청구 회선)."""
    for t in reversed(history):
        if t.channel == Channel.TELECOM_BILL and t.line_id:
            return t.line_id
    for t in reversed(history):
        if t.channel == Channel.MICROPAY and t.line_id:
            return t.line_id
    return ""


def _live_number(txn_id: object) -> int:
    """'live-00012' → 12. 연습 거래 id가 아니면 0."""
    m = re.fullmatch(rf"{LIVE_ID_PREFIX}(\d+)", str(txn_id))
    return int(m.group(1)) if m else 0


def _fingerprint(txn: Transaction) -> tuple[Any, ...]:
    """연습 거래의 내용 지문(받는 사람·계좌·회선·금액·방법·시각). 같은 id가 같은 거래인지 볼 때 쓴다."""
    return (txn.counterparty, txn.counterparty_id, txn.line_id, int(txn.amount), txn.channel.value,
            txn.ts.isoformat(timespec="seconds"))


def _resolve_ts(ts: Optional[datetime], clock: Optional[str],
                history: Sequence[Transaction], now: datetime) -> datetime:
    """보낼 시각을 정한다.

    - ts를 주면 그대로(시간대가 있으면 이 컴퓨터 시각으로 바꿈).
    - 아니면 '저장된 거래의 마지막 날'에 고른 시각(없으면 지금 시각)을 둔다. 그 시각이 마지막
      거래보다 이르면 하루 뒤로 둔다. 개인 기준 창(최근 7일·평소 90일)이 비지 않게 하기 위함이다.
    """
    if ts is not None:
        if ts.tzinfo is not None:
            ts = ts.astimezone().replace(tzinfo=None)
        return ts.replace(microsecond=0)
    if clock:
        hh, mm = (int(x) for x in clock.split(":"))
        wanted = dtime(hh, mm)
    else:
        wanted = dtime(now.hour, now.minute)
    last = max((t.ts for t in history), default=None)
    base = last.date() if last else now.date()
    candidate = datetime.combine(base, wanted)
    if last is not None and candidate <= last:
        try:
            candidate += timedelta(days=1)
        except OverflowError:   # 저장된 거래가 날짜 끝(9999-12-31)에 있으면 그 시각을 그대로 쓴다
            candidate = last
    return candidate


def _build_pending(req: PendingIn, history: Sequence[Transaction], now: datetime,
                   tid: str) -> Transaction:
    """보낼 거래를 만든다(id는 호출자가 정한다: check는 새 id, decide는 확인한 id)."""
    channel = Channel(req.channel)
    counterparty_id = req.to_id.strip() or _known_counterparty_id(history, channel, req.to)
    line_id = req.line_id.strip()
    if not line_id and channel in (Channel.MICROPAY, Channel.TELECOM_BILL):
        line_id = _known_line(history)
    return Transaction(
        id=tid,
        ts=_resolve_ts(req.ts, req.time, history, now),
        amount=int(req.amount),
        direction=Direction.OUT,
        channel=channel,
        counterparty=req.to,
        counterparty_id=counterparty_id,
        line_id=line_id,
        memo=PRACTICE_MEMO,
        label=None,
    )


def _same_attempt(state: "_State", given: str, candidate: Transaction,
                  stored: Sequence[Transaction], decided_ids: set[str]) -> bool:
    """decide에 온 연습 거래 id(given)를 이 거래에 그대로 써도 되는지(같은 시도의 재시도인지).

    - check가 준 id면: 그때 기억한 지문과 내용이 같아야 한다.
    - 저장된 거래의 id면: 그 거래와 내용이 같아야 한다.
    - 결정 기록에만 있는 id(내용을 확인할 수 없음)면: 쓰지 않는다.
    - 어디에도 없는 id(서버를 다시 켠 뒤 등)면: 그대로 쓰고 기억한다.
    """
    if not LIVE_ID_RE.fullmatch(given):
        return False
    known = state.live_fingerprint(given)
    if known is not None:
        return known == _fingerprint(candidate)
    same_id = next((t for t in stored if t.id == given), None)
    if same_id is not None:
        return _fingerprint(same_id) == _fingerprint(candidate)
    return given not in decided_ids


def _parse_at(value: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at.replace(tzinfo=None) if at.tzinfo is not None else at


def _recent_high(snap: _Snapshot, pending: Transaction, assessment: RiskAssessment,
                 settings: Settings, decisions: Sequence[dict[str, Any]], now: datetime) -> int:
    """최근 30일 고위험 건수(S23 반복 고위험 → 상담 연계). 이번 건(고위험이면)을 한 번 포함한다.

    - 저장된 거래: 거래 시각 기준 (보낼 시각 - 30일, 보낼 시각].
    - 결정 기록: '안 보낼래요'·'물어볼래요'로 멈춘 고위험 시도도 센다. 연습 거래 시각은 저장된
      거래의 날짜로 옮겨지므로, 결정 기록은 기록한 실제 시각(at) 기준 (지금 - 30일, 지금]으로 본다.
      이력에 든 거래(보낸 연습 거래)는 이력 쪽에서만 센다. 같은 거래 id는 한 번만 센다.
    """
    days = settings.window_long_days
    lo = pending.ts - timedelta(days=days)
    counted: set[str] = {pending.id}
    history_ids = {t.id for t in snap.txns}
    count = 0
    for t, a in zip(snap.txns, snap.assessments):
        if t.id not in counted and a.level == RiskLevel.HIGH and lo < t.ts <= pending.ts:
            counted.add(t.id)
            count += 1
    now_lo = now - timedelta(days=days)
    for d in decisions:
        tid = str(d.get("txn_id", ""))
        if not tid or tid in counted or tid in history_ids or d.get("level") != RiskLevel.HIGH.value:
            continue
        at = _parse_at(d.get("at"))
        if at is not None and now_lo < at <= now:
            counted.add(tid)
            count += 1
    return count + (1 if assessment.level == RiskLevel.HIGH else 0)


def _merge_plans(base: NotifyPlan, asked: NotifyPlan) -> NotifyPlan:
    """자동 알림 계획 + 당사자가 직접 고른 '조력자에게 물어볼래요' 계획(조력자 중복 제거).

    안내 문장: 물어보는 사람(asked) 문장 + 따로 자동으로 알리는 사람(extra)만 이름을 붙인 문장.
    """
    seen = {n.helper_id for n in asked.notices}
    extra = [n for n in base.notices if n.helper_id not in seen]
    notices = list(asked.notices) + extra
    suggest = base.suggest_counseling or asked.suggest_counseling
    also = ""
    if extra:
        names = policy.names_phrase([n.helper_name for n in extra])
        also = f"{names}에게도 알려 드릴게요." if asked.notices else f"{names}에게 알려 드릴게요."
    notes = [asked.note_to_person, also]
    return NotifyPlan(
        notices=notices,
        excluded_conflict=list(dict.fromkeys([*asked.excluded_conflict, *base.excluded_conflict])),
        suggest_counseling=suggest,
        counseling_orgs=list(policy.COUNSELING_ORGS) if suggest else [],
        note_to_person=" ".join(n for n in notes if n) or base.note_to_person,
    )


def _assign_helper_ids(items: list[HelperIn]) -> list[Helper]:
    """빈 id·겹치는 id에는 h1, h2… 를 붙인다."""
    used: set[str] = set()
    helpers: list[Helper] = []
    pending_ids: list[int] = []
    for k, item in enumerate(items):
        hid = (item.id or "").strip()
        if hid and hid not in used:
            used.add(hid)
        else:
            hid = ""
            pending_ids.append(k)
        helpers.append(Helper(
            id=hid, name=item.name, relation=item.relation, contact=_mask_contact(item.contact),
            identifiers=list(item.identifiers), min_level=RiskLevel(item.min_level),
            signal_scope=[s.value for s in dict.fromkeys(item.signal_scope)], active=item.active,
        ))
    n = 1
    for k in pending_ids:
        while f"h{n}" in used:
            n += 1
        helpers[k].id = f"h{n}"
        used.add(f"h{n}")
    return helpers


def _metrics_module() -> Any:
    try:
        from safepause.eval import metrics
    except ImportError as exc:  # 평가 모듈이 없는 배포본
        raise EvalUnavailable("성능 평가 모듈(safepause.eval.metrics)을 찾을 수 없어요.") from exc
    return metrics


def _default_evaluator(persona_keys: list[str], seeds: list[int],
                       modes: list[str]) -> dict[str, dict[str, Any]]:
    """(인물, seed)마다 한 번 학습하고 여러 방식으로 평가한다(metrics.compare_modes)."""
    return _metrics_module().compare_modes(persona_keys, seeds, modes)["modes"]


def _ts_note(req: PendingIn, pending: Transaction, now: datetime) -> str:
    """'지금 시각'을 골랐는데 날짜가 연습 기록 쪽으로 옮겨졌으면 까닭을 알려 준다."""
    if req.ts is None and pending.ts.date() != now.date():
        return TS_NOTE
    return ""


def _decision_message(decision: Decision, plan: NotifyPlan, pending: Optional[Transaction] = None,
                      asked_count: Optional[int] = None) -> str:
    if decision == Decision.SEND:
        return "보냈어요."
    if decision == Decision.CANCEL:
        return "안 보냈어요."
    if asked_count == 0:   # 물어볼 조력자가 없었음: 물어봤다고 말하지 않는다
        words = channel_words(pending.channel if pending else Channel.TRANSFER)
        return f"물어볼 조력자가 없어요. 아직 {words.not_done}."
    return plan.note_to_person or "조력자에게 물어볼게요."


def _host_of(value: str) -> str:
    """'127.0.0.1:8765', '[::1]:8765' → 호스트 이름."""
    try:
        return (urlsplit("//" + value).hostname or "").lower()
    except ValueError:
        return ""


async def _read_body_limited(request: Request, limit: int) -> bytes:
    """요청 본문을 메모리로 읽는다. 받는 동안 크기를 세어 limit를 넘으면 바로 413.

    Content-Length 값이 틀리거나 없는 요청(chunked)이어도 한도가 지켜진다.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=TOO_BIG)
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_form(content_type: str, body: bytes) -> dict[str, bytes]:
    """multipart/form-data 본문을 메모리에서 나눈다({칸 이름: 내용}). 임시 파일을 쓰지 않는다.

    표준 라이브러리 email 파서를 쓴다(내용 바이트는 바꾸지 않음). 같은 이름이 여러 번이면 첫 칸.
    """
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type:
        raise HTTPException(status_code=400, detail=NO_FILE)
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "replace")
    message = BytesParser(policy=_email_policy.HTTP).parsebytes(head + body)
    if not message.is_multipart():
        raise HTTPException(status_code=400, detail=NO_FILE)
    fields: dict[str, bytes] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or name in fields:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            fields[name] = payload
    return fields


# ---- 앱 팩토리 ------------------------------------------------------------

def create_app(home: Path | str | None = None, *, settings: Settings | None = None,
               seed: int = 0, evaluator: Optional[Evaluator] = None,
               allowed_hosts: Iterable[str] = ALLOWED_HOSTS,
               now: Callable[[], datetime] = datetime.now) -> FastAPI:
    """SafePause FastAPI 앱을 만든다.

    home: 저장 폴더(없으면 config.data_dir()). 테스트는 tmp_path를 넘긴다.
    evaluator: 성능 평가 함수(기본: safepause.eval.metrics.evaluate).
    now: 기록 시각을 정하는 함수(테스트용).
    """
    root = Path(home) if home is not None else config.data_dir()
    state = _State(root, settings or Settings(), seed, evaluator, now)
    hosts = frozenset(h.lower() for h in allowed_hosts)

    # docs_url/redoc_url은 외부 CDN을 쓰므로 끈다(오프라인 원칙).
    app = FastAPI(title="SafePause", version=__version__, docs_url=None, redoc_url=None)
    app.state.safepause = state

    # ---- 보안 머리글·요청 확인 ----
    @app.middleware("http")
    async def _guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        host = _host_of(request.headers.get("host", ""))
        if host not in hosts:
            return JSONResponse(status_code=400, content={
                "detail": "이 주소로는 열 수 없어요. http://127.0.0.1 주소로 열어 주세요."})
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            # Origin이 있으면 같은 출처여야 한다. 'null'(파일·샌드박스 등 출처를 숨긴 요청)도 거절한다
            if origin is not None and (origin.strip().lower() == "null" or
                                       urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()):
                return JSONResponse(status_code=403, content={
                    "detail": "다른 사이트에서 보낸 요청은 받지 않아요."})
            if request.headers.get(CLIENT_HEADER) != "1":
                return JSONResponse(status_code=403, content={
                    "detail": "SafePause 화면에서 보낸 요청이 아니에요(X-SafePause 머리글 없음)."})
            if request.url.path == UPLOAD_PATH:
                # 본문을 읽기 전에 크기를 본다. 길이를 미리 알 수 없는 요청(chunked)은 받지 않는다
                # (Content-Length와 Transfer-Encoding을 함께 보내 한도를 속이는 요청 포함).
                # 받는 동안에도 크기를 다시 센다(_read_body_limited).
                length = request.headers.get("content-length")
                if length is None or "transfer-encoding" in request.headers:
                    return JSONResponse(status_code=411, content={
                        "detail": "파일 크기를 알 수 없어요. SafePause 화면에서 다시 올려 주세요."})
                try:
                    size = int(length)
                except ValueError:
                    return JSONResponse(status_code=400, content={"detail": "요청 크기 값이 잘못됐어요."})
                if size > MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD_BYTES:
                    return JSONResponse(status_code=413, content={"detail": TOO_BIG})
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", _CSP)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:   # 화면 파일: 늘 다시 확인(새 버전으로 바꾼 뒤 옛 app.js가 남지 않게)
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # ---- 오류 처리(한국어) ----
    @app.exception_handler(StoreError)
    async def _store_error(request: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(LoaderError)
    async def _loader_error(request: Request, exc: LoaderError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        names: list[str] = []
        errors: list[dict[str, Any]] = []
        for err in exc.errors():
            loc = [str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path")]
            label = next((_FIELD_KO[x] for x in reversed(loc) if x in _FIELD_KO), None)
            names.append(label or (".".join(loc) or "요청"))
            errors.append({"loc": loc, "type": str(err.get("type", ""))})
        detail = "입력한 값을 확인해 주세요: " + ", ".join(dict.fromkeys(names))
        return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})

    # ---- 상태 ----
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "offline": True}

    # ---- 동의(S18/S37: 따로 켜고 끄며 즉시 철회) ----
    @app.get("/api/consent")
    def get_consent() -> dict[str, Any]:
        return state.store.load_consent().to_dict()

    @app.put("/api/consent")
    def put_consent(body: ConsentIn) -> dict[str, Any]:
        with state.lock:
            consent = state.store.load_consent()
            was_monitoring = consent.monitoring
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(consent, key, value)
            consent.updated_at = state.timestamp()
            state.store.save_consent(consent)
            # 철회하면 메모리의 분석 결과를 바로 버리고, 다시 켜면 저장된 거래로 새로 만든다.
            # 세대 번호도 올려, 철회 전에 시작해 늦게 끝나는 저장(파일 올리기 등)을 버린다.
            if not consent.monitoring or consent.monitoring != was_monitoring:
                state.revoke()
        return consent.to_dict()

    # ---- 신뢰 조력자(S22/S37) ----
    @app.get("/api/helpers")
    def get_helpers() -> list[dict[str, Any]]:
        return [h.to_dict() for h in state.store.load_helpers()]

    @app.put("/api/helpers")
    def put_helpers(helpers: list[HelperIn]) -> list[dict[str, Any]]:
        if len(helpers) > MAX_HELPERS:
            raise HTTPException(status_code=422, detail=f"조력자는 {MAX_HELPERS}명까지 정할 수 있어요.")
        saved = _assign_helper_ids(helpers)
        with state.lock:
            state.store.save_helpers(saved)
        return [h.to_dict() for h in saved]

    # ---- 데이터 ----
    def _save_if_current(txns: list[Transaction], generation: int, *, need_consent: bool) -> None:
        """시작할 때의 세대 번호 그대로이고 (필요하면) 동의가 있을 때만 저장한다(잠금 안).

        그 사이 지우기·동의 끄기가 먼저 처리됐으면 저장하지 않고 409를 돌려준다(S37 즉시 철회).
        """
        with state.lock:
            if state.generation != generation:
                raise HTTPException(status_code=409, detail=SUPERSEDED)
            if need_consent:
                _require_monitoring(state.store)
            state.store.save_transactions(txns)
            state.reset()

    @app.get("/api/data/summary")
    def data_summary() -> dict[str, Any]:
        return _summary(state.store.load_transactions())

    @app.post("/api/data/sample")
    def data_sample(body: SampleIn) -> dict[str, Any]:
        with state.lock:
            generation = state.generation
        txns = synth.make_dataset(body.persona, body.seed, days=body.days,
                                  scenarios=synth.ALL_SCENARIOS if body.scenarios else None)
        _save_if_current(txns, generation, need_consent=False)   # 가상 거래라 동의는 보지 않음
        return {"source": "sample", "persona": body.persona,
                "persona_name": synth.PERSONAS[body.persona].name, "seed": body.seed,
                "scenarios": body.scenarios, "days": body.days, **_summary(txns)}

    def _upload_begin() -> int:
        """동의 확인(잠금 안) 뒤 지금 세대 번호. 동의가 없으면 본문을 읽기 전에 403."""
        with state.lock:
            _require_monitoring(state.store)  # 실제 거래내역은 동의가 있어야 받는다
            return state.generation

    def _upload_finish(generation: int, content_type: str, body: bytes) -> dict[str, Any]:
        fields = _parse_form(content_type, body)
        raw = fields.get("file")
        if raw is None:
            raise HTTPException(status_code=400, detail=NO_FILE)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=TOO_BIG)
        if not raw.strip():
            raise HTTPException(status_code=400, detail="파일이 비어 있어요.")
        mapping = fields.get("mapping", b"").decode("utf-8", "replace")
        mapping_obj: Optional[dict[str, Any]] = None
        if mapping.strip():
            try:
                mapping_obj = json.loads(mapping)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="열 이름 지정(mapping)이 JSON 형식이 아니에요.") from exc
            if not isinstance(mapping_obj, dict):
                raise HTTPException(status_code=400, detail="열 이름 지정(mapping)은 {…} 모양이어야 해요.")
        txns, report = load_csv(raw, mapping_obj)   # 오래 걸릴 수 있어 잠금 밖에서 읽는다
        if not txns:
            raise HTTPException(status_code=400, detail="읽을 수 있는 거래가 없어요.")
        # 읽는 사이 지우기·동의 끄기가 있었으면 저장하지 않는다(철회가 먼저)
        _save_if_current(txns, generation, need_consent=True)
        return {"source": "upload", "report": _plain(report), "summary": _summary(txns)}

    @app.post(UPLOAD_PATH)
    async def data_upload(request: Request) -> dict[str, Any]:
        """거래내역 CSV 올리기(multipart: file, 선택 mapping). 파일은 메모리에서만 읽는다."""
        generation = await run_in_threadpool(_upload_begin)
        body = await _read_body_limited(request, MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD_BYTES)
        return await run_in_threadpool(_upload_finish, generation,
                                       request.headers.get("content-type", ""), body)

    # ---- 내 거래 + 평가 ----
    @app.get("/api/transactions")
    def transactions(level: Literal["all", "caution", "high"] = "all",
                     limit: int = Query(0, ge=0, le=100_000)) -> dict[str, Any]:
        with state.lock:
            _require_monitoring(state.store)
            snap = state.snapshot()
        counts = Counter(a.level.value for a in snap.assessments)
        wanted = {"all": None, "caution": {RiskLevel.CAUTION, RiskLevel.HIGH},
                  "high": {RiskLevel.HIGH}}[level]
        items = [_item(t, a) for t, a in zip(reversed(snap.txns), reversed(snap.assessments))
                 if wanted is None or a.level in wanted]
        matched = len(items)
        if limit:
            items = items[:limit]
        return {
            "count": len(snap.txns),
            "matched": matched,
            "summary": {lv.value: counts.get(lv.value, 0) for lv in RiskLevel},
            # train_count = 학습 구간 거래 수, train_rows = 실제 학습 행 수(초기 거래를 빼서 더 적을 수 있음)
            "model": {"fitted": snap.engine.fitted, "version": snap.engine.model_version(),
                      "train_count": snap.train_count, "train_rows": snap.engine.model.n_train},
            "items": items,   # 최근 거래부터
        }

    # ---- 안전 정지(S20/S21) ----
    @app.post("/api/safepause/check")
    def safepause_check(body: PendingIn) -> dict[str, Any]:
        """보내기 전 평가. 아무것도 저장하지 않는다."""
        with state.lock:
            # 동의는 잠금 안에서 읽는다(동시에 철회하면 철회가 먼저 적용되게)
            consent = _require_monitoring(state.store)
            snap = state.snapshot()
            now = state.now()
            decisions = state.store.load_decisions()
            # 연습 거래 id는 check마다 새로 준다(두 탭·두 번 확인해도 겹치지 않게). 내용과 묶어 기억한다
            tid = state.issue_live_id([*(t.id for t in snap.txns),
                                       *(str(d.get("txn_id", "")) for d in decisions)])
            pending = _build_pending(body, snap.txns, now, tid)
            state.remember_live(pending)
            assessment = snap.engine.assess_pending(pending, snap.txns)
            card = render_card(assessment, pending)
            helpers = state.store.load_helpers()
            # 고르기 전 미리 보기: 아직 한 일이 없으므로 현재형 문장(preview=True)
            preview = policy.decide(assessment, pending, helpers, consent,
                                    _recent_high(snap, pending, assessment, state.settings,
                                                 decisions, now),
                                    state.settings, now=now, preview=True)
            candidates = policy.ask_helper_candidates(assessment, pending, helpers)
            auto_ids = {n.helper_id for n in preview.notices}
            for c in candidates:   # 자동 알림 대상: 물어보기에서 빼도 ⑤에서 정한 대로 알게 됨
                c["auto"] = c["id"] in auto_ids
            # 물어볼 수 있는 사람이 없으면(모두 돈을 받는 사람) 동의 시 상담하는 곳을 미리 알려 준다
            ask_counseling: list[str] = []
            if candidates and all(c["conflict"] for c in candidates):
                every = policy.ask_helper_plan(assessment, pending, helpers, consent,
                                               helper_ids=[c["id"] for c in candidates], now=now)
                ask_counseling = every.counseling_orgs
        return _plain({
            "pending": pending.to_dict(),
            "assessment": assessment.to_dict(),
            "card": card.to_dict() if card else None,
            "notify_plan_preview": preview.to_dict(),
            # '조력자에게 물어볼래요'를 고르기 전에 누구에게 묻게 되는지 보여 주는 목록
            "ask_helper_preview": {"candidates": candidates, "counseling_orgs": ask_counseling},
            "practice_note": PRACTICE_NOTE,
            "ts_note": _ts_note(body, pending, now),
        })

    @app.post("/api/safepause/decide")
    def safepause_decide(body: DecideIn) -> dict[str, Any]:
        """당사자의 결정을 기록한다. '보낼래요'는 위험 등급과 관계없이 늘 이력에 더한다(차단 없음).

        쓰는 순서: ① 거래 이력(보낼래요) → ② 결정 기록 → ③ 조력자 알림 기록. 중간에 저장이 실패하면
        한국어 안내(StoreError)를 돌려준다. check가 준 거래 id(live-…)와 같은 내용으로 다시 보내면 같은
        시도로 보고, 이미 적은 결정·알림은 다시 적지 않는다(재시도해도 중복 기록 없음). id가 같아도
        내용이 다르면 새 id로 따로 기록한다(다른 거래를 바꾸거나 지우지 않음).
        """
        with state.lock:
            # 동의는 잠금 안에서 다시 읽는다(철회와 겹치면 철회가 먼저 적용되게)
            consent = _require_monitoring(state.store)
            snap = state.snapshot()
            now = state.now()
            decisions = state.store.load_decisions()
            decided_ids = {str(d.get("txn_id", "")) for d in decisions}
            # check가 준 id라도 내용이 다르면(다른 탭의 거래 등) 새 id를 준다: 다른 거래를 바꾸거나 지우지 않게
            given = (body.pending.id or "").strip()
            pending = _build_pending(body.pending, snap.txns, now, given)
            if not _same_attempt(state, given, pending, snap.txns, decided_ids):
                pending = replace(pending, id=state.issue_live_id(
                    [*(t.id for t in snap.txns), *decided_ids]))
            state.remember_live(pending)
            assessment = snap.engine.assess_pending(pending, snap.txns)
            helpers = state.store.load_helpers()

            # 자동 알림: 당사자가 정한 등급·범위·동의에 맞을 때만(기본 고위험만, S22)
            plan = policy.decide(assessment, pending, helpers, consent,
                                 _recent_high(snap, pending, assessment, state.settings,
                                              decisions, now),
                                 state.settings, now=now)
            asked_count: Optional[int] = None
            if body.decision == Decision.ASK_HELPER:  # 당사자가 직접 요청(묻는 사람도 당사자가 고름)
                asked = policy.ask_helper_plan(assessment, pending, helpers, consent,
                                               helper_ids=body.helper_ids, now=now)
                asked_count = len(asked.notices)
                plan = _merge_plans(plan, asked)

            # ① 거래 이력: 메모리 사본이 아니라 지금 디스크에 있는 거래에 반영한다
            #    (밖에서 지운 거래를 되살리지 않게). 같은 id의 연습 거래는 이번 결정으로 바꾼다.
            current = state.store.load_transactions()
            others = [t for t in current if t.id != pending.id]
            added = body.decision == Decision.SEND
            if added:
                state.store.save_transactions(sorted([*others, pending], key=lambda t: t.ts))
            elif len(others) != len(current):
                state.store.save_transactions(others)
            if added or len(others) != len(current):
                state.reset()

            # ② 결정 기록(같은 거래·같은 결정이 이미 있으면 다시 적지 않음)
            if not any(str(d.get("txn_id")) == pending.id and d.get("decision") == body.decision.value
                       for d in decisions):
                state.store.append_decision(pending.id, body.decision, assessment.level,
                                            state.timestamp(), asked=asked_count)

            # ③ 조력자 알림 기록(이 거래로 이미 적은 조력자는 빼기)
            noticed = {str(n.get("helper_id")) for n in state.store.load_notices()
                       if str(n.get("txn_id")) == pending.id}
            state.outbox.send_all(n for n in plan.notices if n.helper_id not in noticed)
            recorded = len(plan.notices)
        card = render_card(assessment, pending)
        result_title, result_lines = practice_result(body.decision, pending, asked_count)
        return _plain({
            "decision": body.decision.value,
            "recorded": True,
            "added_to_history": added,
            "pending": pending.to_dict(),
            "assessment": assessment.to_dict(),
            "card": card.to_dict() if card else None,
            "notify_plan": plan.to_dict(),
            "notices_recorded": recorded,
            "asked_count": asked_count,
            "message": _decision_message(body.decision, plan, pending, asked_count),
            "result_title": result_title,
            "result_lines": result_lines,
            "practice_note": PRACTICE_NOTE,
            "ts_note": _ts_note(body.pending, pending, now),
            "delivery_note": DELIVERY_NOTE,
        })

    # ---- 기록 ----
    @app.get("/api/cards")
    def cards(limit: int = Query(20, ge=1, le=500)) -> dict[str, Any]:
        with state.lock:
            _require_monitoring(state.store)
            snap = state.snapshot()
        flagged = [(t, a) for t, a in zip(snap.txns, snap.assessments) if a.level != RiskLevel.NONE]
        items: list[dict[str, Any]] = []
        for t, a in reversed(flagged[-limit:]):
            card = render_card(a, t, past=True)  # 이미 끝난 거래: 과거형, 묻지 않음
            if card is not None:
                items.append(_plain({"card": card.to_dict(), "txn": t.to_dict(),
                                     "signals": [h.code.value for h in a.rule_hits]}))
        return {"total": len(flagged), "items": items}

    @app.get("/api/notices")
    def notices() -> dict[str, Any]:
        return {"items": list(reversed(state.store.load_notices())), "delivery_note": DELIVERY_NOTE}

    @app.get("/api/decisions")
    def decisions() -> dict[str, Any]:
        return {"items": list(reversed(state.store.load_decisions()))}

    # ---- 성능 확인 ----
    @app.post("/api/eval/run")
    def eval_run(body: Optional[EvalIn] = None) -> dict[str, Any]:
        """합성 데이터로 빠르게 평가한다(기본 fused 한 가지 방식)."""
        req = body or EvalIn()
        personas = req.personas or list(synth.PERSONAS)
        seeds = list(range(1, req.seeds + 1))
        modes = list(dict.fromkeys(req.modes))
        run = state.evaluator or _default_evaluator
        started = _clock.perf_counter()
        try:
            results = run(personas, seeds, modes)
        except EvalUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _plain({
            "personas": personas, "seeds": seeds, "modes": modes, "results": results,
            "elapsed_sec": round(_clock.perf_counter() - started, 2), "note": SYNTHETIC_NOTE,
        })

    @app.post("/api/eval/file")
    def eval_file() -> dict[str, Any]:
        """저장된 거래(모두 정상으로 가정)로 알림 비율 = 오탐 근사(metrics.evaluate_file)."""
        with state.lock:
            _require_monitoring(state.store)
            snap = state.snapshot()
        if not snap.txns:
            raise HTTPException(status_code=400, detail="저장된 거래가 없어요. ② 내 거래에서 먼저 불러와 주세요.")
        try:
            result = _metrics_module().evaluate_file(list(snap.txns), TRAIN_RATIO,
                                                     settings=state.settings, seed=state.seed)
        except EvalUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:  # 거래가 너무 적음 등
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        labeled = any(t.label and t.label != synth.NORMAL_LABEL for t in snap.txns)
        return _plain({**result, "has_scenario_labels": labeled,
                       "labeled_note": LABELED_NOTE if labeled else ""})

    # ---- 즉시 철회: 모두 지우기 ----
    @app.post("/api/wipe")
    def wipe() -> dict[str, Any]:
        with state.lock:
            try:
                removed = state.store.wipe()  # 일부 실패하면 WipeIncomplete(한국어 안내, 500)
            finally:
                state.revoke()                # 실패해도 메모리 결과를 버리고, 진행 중인 저장도 막는다
        return {"removed": removed, "message": "저장한 데이터를 모두 지웠어요."}

    # ---- 화면 ----
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


__all__ = ["ALLOWED_HOSTS", "CLIENT_HEADER", "EvalUnavailable", "PRACTICE_NOTE", "create_app"]
