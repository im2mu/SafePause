"""SafePause 업무 로직(프레임워크 없음). SPEC §10, 제안서 S20~S23·S35·S37·S38.

PC판 FastAPI 서버(safepause.server.app)와 안드로이드 앱의 Pyodide 브리지(safepause.api.bridge)가 이 코드를 같이 쓴다.
오류는 ServiceError(HTTP 상태 코드 + 한국어 문장)로 알린다. HTTP 머리글·보안 검사·파일 받기는 각 틀이 맡는다.

원칙(v0.1에서 이어짐)
- 거래 분석(내 거래 평가·안전 정지·알림 카드)은 '거래 살펴보기'(monitoring) 동의가 있을 때만 한다(403).
- 어떤 경우에도 거래를 막지 않는다. "그래도 보낼래요"는 늘 기록된다. 실제 송금·알림 발송은 없다.
- 외부 네트워크 호출 없음. 모든 데이터는 로컬 JSON 저장소(store.Store)에만 둔다.
- 지우기·동의 끄기는 '세대 번호'를 올린다. 오래 걸리는 저장(파일 올리기·연습용 거래 불러오기)은 시작 때와
  저장 직전의 세대 번호가 다르면 저장하지 않는다(철회·지우기가 먼저, 409).

v0.2에서 고친 것(전문가 리뷰)
- 저장 경쟁: 안전 정지 결정·저장은 store.transaction()(프로세스 사이 폴더 잠금) 안에서 동의 확인부터 기록까지
  한 번에 한다. 다른 창·명령행의 '모두 지우기'와 겹쳐도 지운 거래가 되살아나지 않는다.
- 잠금 밖 학습: 거래가 많을 때 AI 학습(수 초) 동안 동의 끄기·지우기가 기다리지 않게, 학습은 잠금 밖에서 하고
  세대 번호·파일 표식이 그대로일 때만 결과를 쓴다.
- 연습 거래 id: 발급·재시도 판정이 같은 규칙(live-숫자 1~9자리)을 쓴다. 올린 파일의 live- id는 바꿔 저장한다.
- 거래 목록 쪽 나눔(offset·limit): 필요한 쪽만 만든다(4만 건 목록 13.6MB → 한 쪽).
- numpy·scikit-learn은 필요할 때만 싣는다(앱은 동의·조력자 화면을 AI 준비 전에 먼저 쓸 수 있음).
"""
from __future__ import annotations

import csv
import io
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
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from safepause import __version__
from safepause.api.constants import (
    LABELED_NOTE,
    LIVE_ID_DIGITS,
    LIVE_ID_PREFIX,
    MAX_HELPERS,
    MAX_MAPPING_CHARS,
    MAX_REMEMBERED_LIVE_IDS,
    MAX_UPLOAD_BYTES,
    MIN_MONTHLY_DAYS,
    MIN_TRAIN,
    NO_FILE,
    NO_MONITORING,
    NORMAL_LABEL,
    PERSONA_KEYS,
    PRACTICE_MEMO,
    PRACTICE_NOTE,
    SCENARIO_WINDOW_DAYS,
    SUPERSEDED,
    SYNTHETIC_NOTE,
    TOO_BIG,
    TRAIN_RATIO,
    TS_NOTE,
)
from safepause.api.schemas import ConsentIn, DecideIn, EvalIn, HelperIn, PendingIn, SampleIn
from safepause.config import Settings
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
    Transaction,
)
from safepause.store import FileSignature, Store

LIVE_ID_RE = re.compile(rf"{LIVE_ID_PREFIX}(\d{{1,{LIVE_ID_DIGITS}}})")
UPLOADED_LIVE_PREFIX = "csv-"          # 올린 파일의 id가 live-로 시작하면 이 접두어를 붙여 연습 거래와 섞이지 않게
MAX_SNAPSHOT_TRIES = 3

# (인물 목록, seed 목록, 방식 목록) → {방식: 결과 dict}
Evaluator = Callable[[list[str], list[int], list[str]], dict[str, dict[str, Any]]]


class ServiceError(Exception):
    """요청을 처리할 수 없을 때. status는 HTTP 상태 코드, detail은 화면에 그대로 보여 줄 한국어 문장."""

    def __init__(self, status: int, detail: str, *, errors: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(detail)
        self.status = int(status)
        self.detail = detail
        self.errors = errors


class EvalUnavailable(RuntimeError):
    """성능 평가 모듈을 쓸 수 없을 때."""


# ---- 분석 상태 ------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """저장된 거래로 학습한 엔진과 그 평가 결과(시간순)."""

    txns: tuple[Transaction, ...]
    assessments: tuple[RiskAssessment, ...]
    engine: Any                      # detect.engine.RiskEngine (numpy를 늦게 싣기 위해 Any)
    train_count: int


_Snapshot = Snapshot   # v0.1 이름(테스트 호환)


def train_count(txns: Sequence[Transaction]) -> int:
    """시간순 거래 가운데 앞쪽 몇 건으로 개인 기준(AI)을 배울지.

    - 걱정되는 거래를 섞은 합성 데이터(시나리오 라벨이 있음): 마지막 SCENARIO_WINDOW_DAYS일
      이전 거래만(eval.metrics.synthetic_case와 같은 날짜 경계). 섞은 거래를 '평소'로 배우지 않게
      하고, AI 성능 확인 보고서와 같은 방식으로 보여 주기 위함이다. 라벨은 경계를 정하는 데만 쓴다.
    - 그 밖(실제 거래내역 등): 앞 75%(올림, 최소 MIN_TRAIN건). eval.metrics.split_baseline과 같다.
    """
    if any(t.label and t.label != NORMAL_LABEL for t in txns):
        last = max(t.ts for t in txns if t.label)       # 연습 거래(라벨 없음)는 빼고 본다
        cutoff = datetime.combine(last.date() - timedelta(days=SCENARIO_WINDOW_DAYS - 1), dtime.min)
        return sum(1 for t in txns if t.ts < cutoff)
    return min(len(txns), max(MIN_TRAIN, math.ceil(len(txns) * TRAIN_RATIO)))


def build_snapshot(txns: Sequence[Transaction], settings: Settings, seed: int) -> Snapshot:
    """시간순 거래로 엔진을 학습하고 전체를 평가한다(잠금 없이 부른다: 오래 걸릴 수 있음)."""
    from safepause.detect.engine import RiskEngine   # numpy·scikit-learn은 여기서 처음 싣는다

    ordered = sorted(txns, key=lambda t: t.ts)
    n_train = train_count(ordered)
    engine = RiskEngine(settings, seed)
    engine.fit(ordered[:n_train])  # 30건 미만이면 모델 없이 룰만 쓴다
    assessments = engine.assess_many(ordered) if ordered else []
    return Snapshot(tuple(ordered), tuple(assessments), engine, n_train)


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


def _summary(txns: Sequence[Transaction]) -> dict[str, Any]:
    ordered = sorted(txns, key=lambda t: t.ts)
    labels = Counter(t.label for t in ordered if t.label and t.label != NORMAL_LABEL)
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
        "practice": bool(LIVE_ID_RE.fullmatch(txn.id)),
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
    """'live-00012' → 12. 연습 거래 id 모양(live-숫자 1~9자리)이 아니면 0(발급·판정이 같은 규칙)."""
    m = LIVE_ID_RE.fullmatch(str(txn_id))
    return int(m.group(1)) if m else 0


def _fingerprint(txn: Transaction) -> tuple[Any, ...]:
    """연습 거래의 내용 지문(받는 사람·계좌·회선·금액·방법·시각). 같은 id가 같은 거래인지 볼 때 쓴다."""
    return (txn.counterparty, txn.counterparty_id, txn.line_id, int(txn.amount), txn.channel.value,
            txn.ts.isoformat(timespec="seconds"))


def _resolve_ts(ts: Optional[datetime], clock: Optional[str],
                history: Sequence[Transaction], now: datetime) -> datetime:
    """보낼 시각을 정한다.

    - ts를 주면 그대로(시간대가 있으면 이 기기 시각으로 바꿈).
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


def _build_pending(req: PendingIn, history: Sequence[Transaction], now: datetime, tid: str) -> Transaction:
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


def _parse_at(value: Any) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at.replace(tzinfo=None) if at.tzinfo is not None else at


def _recent_high(snap: Snapshot, pending: Transaction, assessment: RiskAssessment,
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
    """자동 알림 계획 + 당사자가 직접 고른 '조력자에게 물어볼래요' 계획(조력자 중복 제거)."""
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
    """빈 id·겹치는 id에는 h1, h2… 를 붙인다. 연락처는 가려서 저장한다."""
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


def _load_upload(raw: bytes, mapping: Optional[dict[str, Any]]) -> tuple[list[Transaction], dict[str, Any]]:
    """올린 CSV를 읽는다(데이터 연결 어댑터 사용). 테스트는 이 함수를 바꿔 끼울 수 있다."""
    from safepause.data.loader import LoaderError
    from safepause.data.sources import CsvUploadSource
    try:
        return CsvUploadSource(raw, mapping).load()
    except LoaderError as exc:   # 파일 모양 문제: 한국어 안내 그대로(400)
        raise ServiceError(400, str(exc)) from exc


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_text(value: Any) -> str:
    """스프레드시트가 수식으로 읽지 않게: =·+·-·@·탭·CR로 시작하는 글 앞에 '를 붙인다(CSV 수식 주입 방지)."""
    text = str(value or "")
    return "'" + text if text.startswith(_FORMULA_START) else text


def _unique_ids(txns: list[Transaction]) -> tuple[list[Transaction], int]:
    """올린 파일의 live- id를 csv- 접두어로 바꾸되, 바꾼 뒤에도 id가 겹치지 않게 -2, -3…을 붙인다."""
    used = {t.id for t in txns if not t.id.startswith(LIVE_ID_PREFIX)}
    out: list[Transaction] = []
    renamed = 0
    for t in txns:
        if t.id.startswith(LIVE_ID_PREFIX):
            base = f"{UPLOADED_LIVE_PREFIX}{t.id}"[:100]
            new_id, k = base, 2
            while new_id in used:
                new_id = f"{base}-{k}"
                k += 1
            used.add(new_id)
            t = replace(t, id=new_id)
            renamed += 1
        out.append(t)
    return out, renamed


def _parse_mapping(text: str) -> Optional[dict[str, Any]]:
    if not text or not text.strip():
        return None
    if len(text) > MAX_MAPPING_CHARS:
        raise ServiceError(400, f"열 이름 지정(mapping)이 너무 길어요({MAX_MAPPING_CHARS}자까지).")
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ServiceError(400, "열 이름 지정(mapping)이 JSON 형식이 아니에요.") from exc
    if not isinstance(obj, dict):
        raise ServiceError(400, "열 이름 지정(mapping)은 {…} 모양이어야 해요.")
    return obj


# ---- 서비스 ---------------------------------------------------------------

class Service:
    """당사자 한 명의 SafePause 상태와 업무 로직. 요청은 잠금으로 줄 세운다(당사자 한 명용 로컬 앱)."""

    def __init__(self, root: Path | str, settings: Optional[Settings] = None, seed: int = 0,
                 evaluator: Optional[Evaluator] = None,
                 now: Callable[[], datetime] = datetime.now) -> None:
        self.store = Store(root)
        self.outbox = Outbox(self.store)
        self.settings = settings or Settings()
        self.seed = seed
        self.evaluator = evaluator
        self.now = now
        self.lock = threading.RLock()
        self.generation = 0   # 지우기·동의 끄기마다 1씩 오른다(늦게 끝난 저장을 버리는 데 씀)
        self._snap: Optional[Snapshot] = None
        self._snap_sig: Optional[FileSignature] = None
        # check가 준 연습 거래 id → 거래 지문. 번호 최댓값은 지우기 뒤에도 이어 간다(열린 탭의 옛 id와 겹치지 않게)
        self._live_ids: "OrderedDict[str, tuple[Any, ...]]" = OrderedDict()
        self._live_high = 0

    # ---- 상태 관리 ----
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

    def timestamp(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def issue_live_id(self, used_ids: Iterable[str]) -> str:
        """저장된 거래·결정 기록·이미 준 id 어느 것과도 겹치지 않는 다음 연습 거래 id."""
        with self.lock:
            number = max([_live_number(x) for x in used_ids] + [self._live_high]) + 1
            if number >= 10 ** LIVE_ID_DIGITS:
                raise ServiceError(409, "연습 거래 번호를 다 썼어요. '내 데이터'에서 모두 지운 뒤 다시 해 주세요.")
            self._live_high = number
            return f"{LIVE_ID_PREFIX}{number:05d}"

    def remember_live(self, txn: Transaction) -> None:
        with self.lock:
            self._live_ids[txn.id] = _fingerprint(txn)
            self._live_ids.move_to_end(txn.id)
            self._live_high = max(self._live_high, _live_number(txn.id))
            while len(self._live_ids) > MAX_REMEMBERED_LIVE_IDS:
                self._live_ids.popitem(last=False)

    def live_fingerprint(self, txn_id: str) -> Optional[tuple[Any, ...]]:
        with self.lock:
            return self._live_ids.get(txn_id)

    def _same_attempt(self, given: str, candidate: Transaction, stored: Sequence[Transaction],
                      decided_ids: set[str]) -> bool:
        """decide에 온 연습 거래 id(given)를 이 거래에 그대로 써도 되는지(같은 시도의 재시도인지)."""
        if not LIVE_ID_RE.fullmatch(given):
            return False
        known = self.live_fingerprint(given)
        if known is not None:
            return known == _fingerprint(candidate)
        same_id = next((t for t in stored if t.id == given), None)
        if same_id is not None:
            return _fingerprint(same_id) == _fingerprint(candidate)
        return given not in decided_ids

    def snapshot(self) -> Snapshot:
        """필요하면 다시 학습한다: 저장된 거래 앞쪽(train_count)으로 학습, 전체를 평가.

        저장 파일 표식(수정 시각·크기·파일 번호)이 바뀌었으면(밖에서 지우거나 고친 경우 포함) 다시 읽는다.
        학습은 잠금 밖에서 한다(거래가 많으면 수 초). 그 사이 지우기·동의 끄기·다른 저장이 있었으면
        결과를 버리고 다시 한다(최대 3번). 세 번 모두 바뀌면 409.
        """
        for _ in range(MAX_SNAPSHOT_TRIES):
            with self.lock:
                sig = self.store.signature()   # 읽기 전에 표식을 잡는다(그 사이 바뀌면 다음에 다시 읽음)
                if self._snap is not None and sig == self._snap_sig:
                    return self._snap
                generation = self.generation
                txns = self.store.load_transactions()
            snap = build_snapshot(txns, self.settings, self.seed)   # 잠금 밖
            with self.lock:
                if self.generation == generation and self.store.signature() == sig:
                    self._snap, self._snap_sig = snap, sig
                    return snap
        raise ServiceError(409, "그 사이 데이터가 바뀌었어요. 다시 해 주세요.")

    def _require_monitoring(self) -> Consent:
        consent = self.store.load_consent()
        if not consent.monitoring:
            raise ServiceError(403, NO_MONITORING)
        return consent

    def _analysis(self) -> Snapshot:
        """동의를 확인하고 분석 결과를 준다. 학습 중에 동의가 꺼지면 403(늦게 끝난 결과를 보여 주지 않음)."""
        with self.lock:
            self._require_monitoring()
            generation = self.generation
        snap = self.snapshot()
        with self.lock:
            if self.generation != generation:
                self._require_monitoring()   # 꺼졌으면 403
                raise ServiceError(409, "그 사이 데이터가 바뀌었어요. 다시 해 주세요.")
        return snap

    def _current(self, snap: Snapshot) -> Snapshot:
        """(잠금 안에서) 잠금 밖에서 만든 분석 결과가 아직 저장 파일과 맞는지 보고, 아니면 다시 만든다."""
        if self._snap is snap and self.store.signature() == self._snap_sig:
            return snap
        return self.snapshot()   # 잠금을 쥔 채 다시 만든다(재진입). 드문 경우: 그 사이 밖에서 거래가 바뀜

    # ---- 상태 ----
    def health(self) -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "offline": True}

    # ---- 동의(S18/S37: 따로 켜고 끄며 즉시 철회) ----
    def get_consent(self) -> dict[str, Any]:
        return self.store.load_consent().to_dict()

    def put_consent(self, body: ConsentIn) -> dict[str, Any]:
        with self.lock, self.store.transaction():
            consent = self.store.load_consent()
            was_monitoring = consent.monitoring
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(consent, key, value)
            consent.updated_at = self.timestamp()
            self.store.save_consent(consent)
            # 철회하면 메모리의 분석 결과를 바로 버리고, 다시 켜면 저장된 거래로 새로 만든다.
            # 세대 번호도 올려, 철회 전에 시작해 늦게 끝나는 저장(파일 올리기 등)을 버린다.
            if not consent.monitoring or consent.monitoring != was_monitoring:
                self.revoke()
        return consent.to_dict()

    # ---- 신뢰 조력자(S22/S37) ----
    def get_helpers(self) -> list[dict[str, Any]]:
        return [h.to_dict() for h in self.store.load_helpers()]

    def put_helpers(self, helpers: list[HelperIn]) -> list[dict[str, Any]]:
        if len(helpers) > MAX_HELPERS:
            raise ServiceError(422, f"조력자는 {MAX_HELPERS}명까지 정할 수 있어요.")
        saved = _assign_helper_ids(helpers)
        with self.lock:
            self.store.save_helpers(saved)
        return [h.to_dict() for h in saved]

    # ---- 데이터 ----
    def _save_if_current(self, txns: list[Transaction], generation: int, *, need_consent: bool) -> None:
        """시작할 때의 세대 번호 그대로이고 (필요하면) 동의가 있을 때만 저장한다(S37 즉시 철회, 409)."""
        with self.lock, self.store.transaction():
            if self.generation != generation:
                raise ServiceError(409, SUPERSEDED)
            if need_consent:
                self._require_monitoring()
            self.store.save_transactions(txns)
            self.reset()

    def data_summary(self) -> dict[str, Any]:
        return _summary(self.store.load_transactions())

    def data_sample(self, body: SampleIn) -> dict[str, Any]:
        from safepause.data.sources import SyntheticSampleSource   # numpy를 여기서 싣는다
        with self.lock:
            generation = self.generation
        source = SyntheticSampleSource(body.persona, body.seed, scenarios=body.scenarios, days=body.days)
        txns, _report = source.load()
        self._save_if_current(txns, generation, need_consent=False)   # 가상 거래라 동의는 보지 않음
        return {"source": "sample", "persona": body.persona, "persona_name": source.persona_name,
                "seed": body.seed, "scenarios": body.scenarios, "days": body.days, **_summary(txns)}

    def upload_begin(self) -> int:
        """동의 확인 뒤 지금 세대 번호. 동의가 없으면 파일을 읽기 전에 403."""
        with self.lock:
            self._require_monitoring()   # 실제 거래내역은 동의가 있어야 받는다
            return self.generation

    def upload_finish(self, generation: int, raw: Optional[bytes], mapping_text: str = "") -> dict[str, Any]:
        """올린 파일(바이트)을 읽어 저장한다. 파일은 메모리에서만 읽는다(임시 파일 없음)."""
        if raw is None:
            raise ServiceError(400, NO_FILE)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ServiceError(413, TOO_BIG)
        if not raw.strip():
            raise ServiceError(400, "파일이 비어 있어요.")
        mapping = _parse_mapping(mapping_text)
        txns, report = _load_upload(raw, mapping)   # 오래 걸릴 수 있어 잠금 밖에서 읽는다
        if not txns:
            reasons = [str(w) for w in (report or {}).get("warnings", [])][:3]
            detail = "읽을 수 있는 거래가 없어요."
            if reasons:
                detail += " " + " ".join(r if r.endswith((".", "요")) else f"{r}." for r in reasons)
            raise ServiceError(400, detail)
        # 파일에 연습 거래와 같은 모양의 id(live-…)가 있으면 바꿔 저장한다(연습 거래로 오인·중복 기록 방지).
        # 바꾼 id가 파일의 다른 id와 겹치지 않게 한다(v0.2 2차 검증)
        fixed, renamed = _unique_ids(txns)
        if renamed:
            report = {**report, "warnings": [*report.get("warnings", []),
                                             f"연습 거래와 같은 모양의 번호 {renamed}건은 이름을 바꿔 저장했어요."]}
        # 읽는 사이 지우기·동의 끄기가 있었으면 저장하지 않는다(철회가 먼저)
        self._save_if_current(fixed, generation, need_consent=True)
        return {"source": "upload", "report": _plain(report), "summary": _summary(fixed)}

    def upload(self, raw: Optional[bytes], mapping_text: str = "") -> dict[str, Any]:
        return self.upload_finish(self.upload_begin(), raw, mapping_text)

    # ---- 내 거래 + 평가 ----
    def transactions(self, level: str = "all", limit: int = 0, offset: int = 0) -> dict[str, Any]:
        snap = self._analysis()
        counts = Counter(a.level.value for a in snap.assessments)
        wanted = {"all": None, "caution": {RiskLevel.CAUTION, RiskLevel.HIGH}, "high": {RiskLevel.HIGH}}[level]
        pairs = [(t, a) for t, a in zip(reversed(snap.txns), reversed(snap.assessments))
                 if wanted is None or a.level in wanted]
        matched = len(pairs)
        page = pairs[offset:offset + limit] if limit else pairs[offset:]
        items = [_item(t, a) for t, a in page]   # 보여 줄 쪽만 만든다(리뷰 M9)
        return {
            "count": len(snap.txns),
            "matched": matched,
            "offset": offset,
            "summary": {lv.value: counts.get(lv.value, 0) for lv in RiskLevel},
            # train_count = 학습 구간 거래 수, train_rows = 실제 학습 행 수(초기 거래를 빼서 더 적을 수 있음)
            "model": {"fitted": snap.engine.fitted, "version": snap.engine.model_version(),
                      "train_count": snap.train_count, "train_rows": snap.engine.model.n_train},
            "items": items,   # 최근 거래부터
        }

    def payees(self, limit: int = 30) -> dict[str, Any]:
        """보내기 연습 자동완성: 최근에 계좌로 돈을 보낸 사람 이름(최근 것부터, 겹침 없이)."""
        snap = self._analysis()
        names: list[str] = []
        for t in reversed(snap.txns):
            if t.direction == Direction.OUT and t.channel == Channel.TRANSFER and t.counterparty \
                    and t.counterparty not in names:
                names.append(t.counterparty)
                if len(names) >= limit:
                    break
        return {"items": names}

    # ---- 안전 정지(S20/S21) ----
    def check(self, body: PendingIn) -> dict[str, Any]:
        """보내기 전 평가. 아무것도 저장하지 않는다(연습 거래 id와 지문만 메모리에 기억)."""
        snap = self._analysis()
        with self.lock:
            # 동의는 잠금 안에서 다시 읽는다(동시에 철회하면 철회가 먼저 적용되게)
            consent = self._require_monitoring()
            snap = self._current(snap)
            now = self.now()
            decisions = self.store.load_decisions()
            # 연습 거래 id는 check마다 새로 준다(두 탭·두 번 확인해도 겹치지 않게). 내용과 묶어 기억한다
            tid = self.issue_live_id([*(t.id for t in snap.txns), *(str(d.get("txn_id", "")) for d in decisions)])
            pending = _build_pending(body, snap.txns, now, tid)
            self.remember_live(pending)
            assessment = snap.engine.assess_pending(pending, snap.txns)
            card = render_card(assessment, pending)
            helpers = self.store.load_helpers()
            # 고르기 전 미리 보기: 아직 한 일이 없으므로 현재형 문장(preview=True)
            preview = policy.decide(assessment, pending, helpers, consent,
                                    _recent_high(snap, pending, assessment, self.settings, decisions, now),
                                    self.settings, now=now, preview=True)
            candidates = policy.ask_helper_candidates(assessment, pending, helpers)
            auto_ids = {n.helper_id for n in preview.notices}
            for c in candidates:   # 자동 알림 대상: 물어보기에서 빼도 조력자 설정대로 알게 됨
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

    def decide(self, body: DecideIn) -> dict[str, Any]:
        """당사자의 결정을 기록한다. '보낼래요'는 위험 등급과 관계없이 늘 이력에 더한다(차단 없음).

        쓰는 순서: ① 거래 이력(보낼래요) → ② 결정 기록 → ③ 조력자 알림 기록. 동의 확인부터 ③까지를
        store.transaction()(프로세스 사이 잠금) 안에서 한 번에 한다(리뷰: 다른 창의 지우기와 겹쳐도 되살아나지 않음).
        check가 준 거래 id와 같은 내용으로 다시 보내면 같은 시도로 보고 다시 적지 않는다.
        """
        snap = self._analysis()
        with self.lock, self.store.transaction():
            consent = self._require_monitoring()
            snap = self._current(snap)
            now = self.now()
            decisions = self.store.load_decisions()
            decided_ids = {str(d.get("txn_id", "")) for d in decisions}
            given = (body.pending.id or "").strip()
            pending = _build_pending(body.pending, snap.txns, now, given)
            if not self._same_attempt(given, pending, snap.txns, decided_ids):
                pending = replace(pending, id=self.issue_live_id([*(t.id for t in snap.txns), *decided_ids]))
            self.remember_live(pending)
            assessment = snap.engine.assess_pending(pending, snap.txns)
            helpers = self.store.load_helpers()

            # 자동 알림: 당사자가 정한 등급·범위·동의에 맞을 때만(기본 고위험만, S22)
            plan = policy.decide(assessment, pending, helpers, consent,
                                 _recent_high(snap, pending, assessment, self.settings, decisions, now),
                                 self.settings, now=now)
            asked_count: Optional[int] = None
            if body.decision == Decision.ASK_HELPER:  # 당사자가 직접 요청(묻는 사람도 당사자가 고름)
                asked = policy.ask_helper_plan(assessment, pending, helpers, consent,
                                               helper_ids=body.helper_ids, now=now)
                asked_count = len(asked.notices)
                plan = _merge_plans(plan, asked)

            # ① 거래 이력: 지금 디스크에 있는 거래에 반영한다(밖에서 지운 거래를 되살리지 않게)
            current = self.store.load_transactions()
            others = [t for t in current if t.id != pending.id]
            added = body.decision == Decision.SEND
            if added:
                self.store.save_transactions(sorted([*others, pending], key=lambda t: t.ts))
            elif len(others) != len(current):
                self.store.save_transactions(others)
            if added or len(others) != len(current):
                self.reset()

            # ② 결정 기록(같은 거래·같은 결정이 이미 있으면 다시 적지 않음)
            if not any(str(d.get("txn_id")) == pending.id and d.get("decision") == body.decision.value
                       for d in decisions):
                self.store.append_decision(pending.id, body.decision, assessment.level, self.timestamp(),
                                           asked=asked_count)

            # ③ 조력자 알림 기록(이 거래로 이미 적은 조력자는 빼기)
            noticed = {str(n.get("helper_id")) for n in self.store.load_notices()
                       if str(n.get("txn_id")) == pending.id}
            self.outbox.send_all(n for n in plan.notices if n.helper_id not in noticed)
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
    def cards(self, limit: int = 20) -> dict[str, Any]:
        snap = self._analysis()
        flagged = [(t, a) for t, a in zip(snap.txns, snap.assessments) if a.level != RiskLevel.NONE]
        items: list[dict[str, Any]] = []
        for t, a in reversed(flagged[-limit:]):
            card = render_card(a, t, past=True)  # 이미 끝난 거래: 과거형, 묻지 않음
            if card is not None:
                items.append(_plain({"card": card.to_dict(), "txn": t.to_dict(),
                                     "signals": [h.code.value for h in a.rule_hits]}))
        return {"total": len(flagged), "items": items}

    def notices(self) -> dict[str, Any]:
        return {"items": list(reversed(self.store.load_notices())), "delivery_note": DELIVERY_NOTE}

    def decisions(self) -> dict[str, Any]:
        return {"items": list(reversed(self.store.load_decisions()))}

    # ---- 성능 확인 ----
    def eval_run(self, body: Optional[EvalIn] = None) -> dict[str, Any]:
        """합성 데이터로 빠르게 평가한다(기본 fused 한 가지 방식)."""
        req = body or EvalIn()
        personas = req.personas or list(PERSONA_KEYS)
        seeds = list(range(1, req.seeds + 1))
        modes = list(dict.fromkeys(req.modes))
        run = self.evaluator or _default_evaluator
        started = _clock.perf_counter()
        try:
            results = run(personas, seeds, modes)
        except EvalUnavailable as exc:
            raise ServiceError(503, str(exc)) from exc
        return _plain({
            "personas": personas, "seeds": seeds, "modes": modes, "results": results,
            "elapsed_sec": round(_clock.perf_counter() - started, 2), "note": SYNTHETIC_NOTE,
        })

    def eval_file(self) -> dict[str, Any]:
        """저장된 거래(모두 정상으로 가정)로 알림 비율 = 오탐 근사(metrics.evaluate_file)."""
        snap = self._analysis()
        if not snap.txns:
            raise ServiceError(400, "저장된 거래가 없어요. '내 거래'에서 먼저 불러와 주세요.")
        try:
            result = _metrics_module().evaluate_file(list(snap.txns), TRAIN_RATIO,
                                                     settings=self.settings, seed=self.seed)
        except EvalUnavailable as exc:
            raise ServiceError(503, str(exc)) from exc
        except ValueError as exc:  # 거래가 너무 적음 등
            raise ServiceError(400, str(exc)) from exc
        labeled = any(t.label and t.label != NORMAL_LABEL for t in snap.txns)
        return _plain({**result, "has_scenario_labels": labeled, "labeled_note": LABELED_NOTE if labeled else ""})

    # ---- 내보내기(선택 사항: 샘플 결과물·현장 검증 요약) ----
    def export_results_csv(self) -> dict[str, Any]:
        """내 분석 결과(개인용). 거래마다 등급·걸린 약속(시그널)·AI 점수. 이름이 들어 있으니 남에게 보내지 마세요."""
        snap = self._analysis()
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["거래일시", "나감/들어옴", "방법", "상대", "금액(원)", "판단", "걸린 약속", "AI 점수(0~1)", "연습 거래"])
        level_ko = {"none": "괜찮아요", "caution": "확인해요", "high": "꼭 확인해요"}
        for t, a in zip(snap.txns, snap.assessments):
            w.writerow([t.ts.isoformat(sep=" ", timespec="minutes"), "나감" if t.direction == Direction.OUT else "들어옴",
                        t.channel.value, _csv_text(t.counterparty), int(t.amount), level_ko[a.level.value],
                        " ".join(h.code.value for h in a.rule_hits), f"{float(a.anomaly_score):.4f}",
                        "예" if LIVE_ID_RE.fullmatch(t.id) else ""])
        return {"filename": f"safepause-results-{self.now():%Y%m%d}.csv", "mime": "text/csv",
                "text": "﻿" + buf.getvalue(), "rows": len(snap.txns),
                "note": "이 파일에는 받는 사람 이름이 들어 있어요. 나만 보고, 다른 사람에게 보내지 마세요."}

    def export_validation(self) -> dict[str, Any]:
        """현장 검증용 요약(이름·계좌·금액·날짜 없음). 당사자가 동의하고 직접 전달하는 집계 값만 담는다."""
        snap = self._analysis()
        decisions = self.store.load_decisions()
        notices = self.store.load_notices()
        days = ((snap.txns[-1].ts - snap.txns[0].ts).total_seconds() / 86400 + 1) if snap.txns else 0
        levels = Counter(a.level.value for a in snap.assessments)
        signals = Counter(h.code.value for a in snap.assessments for h in a.rule_hits)
        ai_only = sum(1 for a in snap.assessments if a.level != RiskLevel.NONE and not a.rule_hits)
        practice = sum(1 for t in snap.txns if LIVE_ID_RE.fullmatch(t.id))
        labeled = any(t.label and t.label != NORMAL_LABEL for t in snap.txns)
        per_month = (lambda n: round(n / days * 30, 2)) if days >= MIN_MONTHLY_DAYS else (lambda n: None)
        payload = {
            "kind": "safepause-validation-summary",
            "schema": 1,
            "app_version": __version__,
            "model_version": snap.engine.model_version(),
            "created_at": self.timestamp(),
            "note": ("개인을 알아볼 수 있는 정보(이름·계좌·금액·날짜)는 넣지 않았어요. 거래 수와 알림 수만 있어요. "
                     "현장 검증에 쓰려면 본인(또는 법정대리인)이 동의한 뒤 직접 전달해 주세요."),
            "data": {
                "source": "synthetic_sample" if labeled else "user_data",
                "n_transactions": len(snap.txns),
                "n_practice": practice,
                "period_days": round(days, 1),
                "train_count": snap.train_count,
                "model_fitted": bool(snap.engine.fitted),
            },
            "alerts": {
                "by_level": {lv.value: levels.get(lv.value, 0) for lv in RiskLevel},
                "alert_rate": round((levels.get("caution", 0) + levels.get("high", 0)) / len(snap.txns), 4)
                if snap.txns else None,
                "high_rate": round(levels.get("high", 0) / len(snap.txns), 4) if snap.txns else None,
                "per_month": per_month(levels.get("caution", 0) + levels.get("high", 0)),
                "by_signal": dict(sorted(signals.items())),
                "ai_only": ai_only,
            },
            "decisions": dict(Counter(str(d.get("decision", "")) for d in decisions)),
            "helper_notices": len(notices),
        }
        return {"filename": f"safepause-validation-{self.now():%Y%m%d}.json", "mime": "application/json",
                "text": json.dumps(payload, ensure_ascii=False, indent=2), "summary": payload}

    # ---- 즉시 철회: 모두 지우기 ----
    def wipe(self) -> dict[str, Any]:
        with self.lock:
            try:
                removed = self.store.wipe()  # 일부 실패하면 WipeIncomplete(한국어 안내, 500)
            finally:
                self.revoke()                # 실패해도 메모리 결과를 버리고, 진행 중인 저장도 막는다
        return {"removed": removed, "message": "저장한 데이터를 모두 지웠어요."}


__all__ = [
    "EvalUnavailable", "Evaluator", "Service", "ServiceError", "Snapshot", "build_snapshot", "train_count",
]
