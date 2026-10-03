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

v0.3(착취를 알아차리는 앱)
- 조력자 번호·메일 원본은 이 기기에만 저장한다(문자·메일 앱을 열 때 씀). 화면 목록·내보내기·알림 기록에는 가린 값만.
- 상담하는 곳(counselors.json), 알림 목록에 담은 거래(flags.json), 직접 보낸 알림 기록(notices.json의 kind "manual").
- 돈 흐름 분석(insights): 저장된 마지막 거래가 있는 달을 기준 달로 본다.
- 돈 보내기(docs/v03_spec_money.md): check/decide/payees는 보내기 전 확인에 쓴다. SafePause는 돈을 옮기지 않고,
  본인이 고른 은행 앱을 화면이 연다. 응답 글에 연습이라는 말을 쓰지 않는다(practice_note는 빈 글).
- 받는 사람 추천(notify_suggest): 조력자 설정(등급·범위·자동으로 알리기)과 이해충돌을 policy 그대로 쓴다.

v0.3 수정(docs/v03_fixplan.md, 적대적 검증 반영)
- 확인한 거래(live id)는 돈 흐름 분석에서 뺀다(실제로 보냈는지 모름). 날짜는 실제 거래가 45일 안이면 오늘,
  아니면 마지막 실제 거래 날짜(여러 번 확인해도 하루씩 밀지 않음). [이 확인 기록 지우기] API.
- 내가 한 거예요(reviews.json): 탐지 등급은 그대로, 표시와 일부 집계(꼭 확인할 거래 수·상담 안내 기준)만 바꾼다.
- 항목 칸 reviewed·notified_at·ai(AI가 본 것). 받는 사람 추천은 저장하지 않은 확인 거래(pending)도 보고,
  이해충돌은 나간 돈만, 알릴 조력자가 모두 돈을 받은 사람이면 상담하는 곳을 추천한다.
- 파일 올리기 mode(replace·append), .xlsx, 직접 보낸 알림 기록 지우기, 번호·메일 가리기 견고화.
"""
from __future__ import annotations

import calendar
import csv
import io
import json
import logging
import math
import re
import threading
import time as _clock
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from datetime import time as dtime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from safepause import __version__
from safepause.api.constants import (
    AI_FEATURE_TEXT,
    AI_NIGHT_TEXT,
    CHANNEL_KO,
    CONFLICT_REASON,
    COUNSELOR_PRESETS,
    INSIGHT_MONTHS,
    LABELED_NOTE,
    LEGACY_PRACTICE_MEMOS,
    LIVE_ID_DIGITS,
    LIVE_ID_PREFIX,
    LIVE_IDS_USED_UP,
    LIVE_RECENT_DAYS,
    MAX_COUNSELORS,
    MAX_HELPERS,
    MAX_MAPPING_CHARS,
    MAX_REMEMBERED_LIVE_IDS,
    MAX_UPLOAD_BYTES,
    MIN_MONTHLY_DAYS,
    MIN_TRAIN,
    NO_FILE,
    NO_MONITORING,
    NORMAL_LABEL,
    NOTICE_NOT_FOUND,
    NOTICES_NOTE,
    ONLY_CHECKED,
    PERSONA_KEYS,
    PRACTICE_MEMO,
    REPORT_SEED_START,
    REPORT_SEEDS,
    REVIEW_OK,
    SCENARIO_WINDOW_DAYS,
    SIGNAL_KO,
    SIGNAL_KO_NEUTRAL,
    SUPERSEDED,
    SYNTHETIC_NOTE,
    TOO_BIG,
    TOP_PAYEES,
    TRAIN_RATIO,
    TS_NOTE,
    TXN_NOT_FOUND,
    UPLOAD_MODES,
)
from safepause.api.schemas import (
    ConsentIn,
    CounselorIn,
    DecideIn,
    EvalIn,
    FlagIn,
    HelperIn,
    NoticeRecordIn,
    NoticeRemoveIn,
    PendingIn,
    SampleIn,
    SuggestIn,
)
from safepause.config import Settings
from safepause.explain.easy_card import channel_words, practice_result, render_card
from safepause.guardian import policy
from safepause.guardian.outbox import DELIVERY_NOTE, Outbox
from safepause.models import (
    Channel,
    Consent,
    Counselor,
    Decision,
    Direction,
    Helper,
    NotifyPlan,
    RiskAssessment,
    RiskLevel,
    Transaction,
)
from safepause.store import FileSignature, Store, StoreError

log = logging.getLogger("safepause.service")

LIVE_ID_RE = re.compile(rf"{LIVE_ID_PREFIX}(\d{{1,{LIVE_ID_DIGITS}}})")
UPLOADED_LIVE_PREFIX = "csv-"          # 올린 파일의 id가 live-로 시작하면 이 접두어를 붙여 연습 거래와 섞이지 않게
MAX_SNAPSHOT_TRIES = 3

# (인물 목록, seed 목록, 방식 목록, intensity="standard"|"subtle" 키워드) → {방식: 결과 dict}
Evaluator = Callable[..., dict[str, dict[str, Any]]]


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
    # fit(ordered[:n_train]) 뒤 assess_many(ordered)와 같은 결과. 학습 구간은 평가 걷기의 앞부분이라 한 번만 걷는다.
    # 30건 미만이면 모델 없이 룰만 쓴다
    assessments = engine.fit_assess(ordered[:n_train], [(ordered, None)], [engine.mode])[0][engine.mode]
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


# 메일: 입력 검사(models.EMAIL_RE: 앞뒤 아무 글자)가 받는 모양을 모두 가린다(한글 앞부분·한글 도메인·밑줄 도메인, BE-2).
# 앞부분·도메인에는 공백·@·흔한 묶음 기호만 빼고 모든 글자를 받는다. 도메인은 가리지 않는다
_EMAIL_CHARS = r"[^\s@,;:<>()\[\]{}\"]"
_EMAIL_RE = re.compile(rf"({_EMAIL_CHARS}+)@({_EMAIL_CHARS}+(?:\.{_EMAIL_CHARS}+)+)")
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
    """연락처를 가린다(화면 목록·알림 기록용). v0.3부터 번호·메일 원본은 phone·email에 따로 저장한다.

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


def _txn_out(txn: Transaction) -> dict[str, Any]:
    """화면에 줄 거래 dict. v0.2가 보내기 전 확인 거래에 적은 옛 메모(안전 정지 연습)는 지금 이름으로 보인다(저장은 그대로)."""
    d = txn.to_dict()
    if d.get("memo") in LEGACY_PRACTICE_MEMOS and LIVE_ID_RE.fullmatch(txn.id):
        d["memo"] = PRACTICE_MEMO
    return d


def _is_live(txn_id: object) -> bool:
    """보내기 전 확인으로 내 거래에 적은 거래(live-숫자)인지."""
    return bool(LIVE_ID_RE.fullmatch(str(txn_id)))


def _ai_top_feature(assessment: RiskAssessment) -> Optional[str]:
    """AI가 본 것 한 줄: 평균과 가장 다른 특징 1가지(detect.anomaly.explain_features가 |z| 큰 순으로 준 첫 근거).

    엔진은 이상 점수가 높을 때(0.90 이상)만 이 근거를 붙인다. 근거가 없으면 None(쉬운 말로 꾸며 내지 않는다).
    모델 기여도가 아니라 '평소 내 거래 평균과 가장 다른 점'이다.
    """
    for reason in assessment.reasons:
        if not reason.code.startswith("anomaly:"):
            continue
        feature = reason.code.split(":", 1)[1]
        detail = reason.detail if isinstance(reason.detail, dict) else {}
        if feature in ("hour_sin", "hour_cos", "is_night") and detail.get("is_night") is True:
            return AI_NIGHT_TEXT
        if feature == "cp_count_7d":
            value = detail.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 2:
                return f"7일 동안 같은 상대와 {int(round(value))}번 거래해 평소보다 잦았어요."
        return AI_FEATURE_TEXT.get(feature)
    return None


def _ai_view(assessment: RiskAssessment, fitted: bool) -> dict[str, Any]:
    """항목의 ai 칸(v0.3 수정 계획 D). 탐지 결과를 바꾸지 않고 보여 주기만 한다.

    - fitted: 개인 기준 AI를 배웠는지(거래 30건 미만이면 False)
    - percentile: 평소보다 다른 정도 0~100(클수록 다름, 학습 거래 가운데 이 거래보다 덜 다른 거래의 비율).
      배우지 않았으면 None. 평소 기준 구간이 아직 없던 이른 거래는 0이다.
    - top_feature: AI가 본 것 한 줄(_ai_top_feature) 또는 None
    - only_ai: 규칙 신호 없이 AI만 걱정한 거래
    - raised: 규칙은 확인할 거래로 봤는데 AI도 걱정해서 꼭 확인할 거래로 올린 거래
    """
    hits = assessment.rule_hits
    level = assessment.level
    return {
        "fitted": bool(fitted),
        "percentile": round(float(assessment.anomaly_score) * 100, 1) if fitted else None,
        "top_feature": _ai_top_feature(assessment),
        "only_ai": level != RiskLevel.NONE and not hits,
        "raised": level == RiskLevel.HIGH and bool(hits) and not any(h.severity == RiskLevel.HIGH for h in hits),
    }


def _item(txn: Transaction, assessment: RiskAssessment, flagged: bool = False, *, reviewed: bool = False,
          notified_at: Optional[str] = None, fitted: bool = False) -> dict[str, Any]:
    return _plain({
        "txn": _txn_out(txn),
        "level": assessment.level.value,
        "signals": [h.code.value for h in assessment.rule_hits],
        "anomaly_score": round(float(assessment.anomaly_score), 4),
        "reasons": [{"code": r.code, "detail": r.detail} for r in assessment.reasons],
        "practice": _is_live(txn.id),
        "flagged": bool(flagged),   # 알림 목록에 담은 거래인지(v0.3)
        "reviewed": bool(reviewed),            # 내가 한 거예요로 표시했는지(등급은 그대로)
        "notified_at": notified_at,            # 직접 보낸 알림 기록 가운데 이 거래가 든 가장 최근 시각(없으면 None)
        "ai": _ai_view(assessment, fitted),    # AI가 본 것
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
    """보낼 시각을 정한다(v0.3 수정 계획 A).

    - ts를 주면 그대로(시간대가 있으면 이 기기 시각으로 바꿈).
    - 아니면 저장된 실제 거래(보내기 전 확인 거래 live-는 빼고)의 마지막 시각을 본다.
      그 시각이 지금부터 LIVE_RECENT_DAYS(45)일 안이면(실사용) 오늘, 더 오래됐으면(합성·옛 데이터) 그 마지막 날에
      고른 시각(없으면 지금 시각)을 붙인다. 개인 기준 창(최근 7일·평소 90일)이 비지 않게 하기 위함이다.
    - 그 시각이 마지막 실제 거래보다 이르면 하루 뒤로 둔다. 확인한 거래가 실제 거래 사이에 끼어 실제 거래의
      판단(이력)을 바꾸지 않게 하기 위함이다. 확인한 거래는 날짜 기준에서 빼므로 여러 번 확인해도 하루씩
      더 밀리지 않는다(마지막 실제 거래 날짜 또는 그다음 날에 머문다).
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
    last = _last_real_ts(history)
    candidate = datetime.combine(now.date() if _recent_data(last, now) else last.date(), wanted)  # type: ignore[union-attr]
    if last is not None and candidate <= last:
        try:
            candidate += timedelta(days=1)
        except OverflowError:   # 저장된 거래가 날짜 끝(9999-12-31)에 있으면 그 시각을 그대로 쓴다
            candidate = last
    return candidate


def _last_real_ts(history: Sequence[Transaction]) -> Optional[datetime]:
    """저장된 실제 거래(보내기 전 확인 거래 live-는 빼고)의 마지막 시각."""
    return max((t.ts for t in history if not _is_live(t.id)), default=None)


def _recent_data(last: Optional[datetime], now: datetime) -> bool:
    """저장된 실제 거래가 없거나 마지막 실제 거래가 지금부터 LIVE_RECENT_DAYS일 안이면 True(실사용)."""
    return last is None or now - last <= timedelta(days=LIVE_RECENT_DAYS)


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
                 settings: Settings, decisions: Sequence[dict[str, Any]], now: datetime,
                 reviewed: frozenset[str] = frozenset()) -> int:
    """최근 30일 고위험 건수(S23 반복 고위험 → 상담 연계). 이번 건(고위험이면)을 한 번 포함한다.

    reviewed: 내가 한 거예요로 표시한 거래 id. 저장된 거래 쪽에서 세지 않는다(v0.3 수정 계획 C, 등급은 그대로).

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
        if t.id not in counted and t.id not in reviewed and a.level == RiskLevel.HIGH and lo < t.ts <= pending.ts:
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
        # 실제로 보내지 않으므로 보낸다는 약속을 쓰지 않는다(v0.3 수정 계획 A): 알릴 수 있게 적어 둔다
        also = (f"{names}에게도 알릴 수 있게 적어 두었어요." if asked.notices
                else f"{names}에게 알릴 수 있게 적어 두었어요.")
    notes = [asked.note_to_person, also]
    return NotifyPlan(
        notices=notices,
        excluded_conflict=list(dict.fromkeys([*asked.excluded_conflict, *base.excluded_conflict])),
        suggest_counseling=suggest,
        counseling_orgs=list(policy.COUNSELING_ORGS) if suggest else [],
        note_to_person=" ".join(n for n in notes if n) or base.note_to_person,
    )


def _with_counseling(plan: NotifyPlan, names: Sequence[str]) -> NotifyPlan:
    """상담 안내의 기관 이름을 사용자가 정한 상담하는 곳 이름으로 바꾼다(없으면 기본 2곳)."""
    plan.counseling_orgs = list(names) if plan.suggest_counseling else []
    return plan


def _fill_ids(given: Sequence[Optional[str]], prefix: str) -> list[str]:
    """빈 id·겹치는 id에는 prefix + 번호(h1, c1…)를 붙인다. 이미 쓴 번호는 건너뛴다."""
    used: set[str] = set()
    out: list[str] = []
    pending: list[int] = []
    for k, raw in enumerate(given):
        value = (raw or "").strip()
        if value and value not in used:
            used.add(value)
            out.append(value)
        else:
            out.append("")
            pending.append(k)
    n = 1
    for k in pending:
        while f"{prefix}{n}" in used:
            n += 1
        out[k] = f"{prefix}{n}"
        used.add(out[k])
    return out


def _assign_helper_ids(items: list[HelperIn]) -> list[Helper]:
    """빈 id·겹치는 id에는 h1, h2… 를 붙인다. 번호·메일 원본은 그대로, 나누지 못한 옛 연락처는 가려서 저장한다."""
    ids = _fill_ids([item.id for item in items], "h")
    return [Helper(
        id=hid, name=item.name, relation=item.relation,
        contact="" if (item.phone or item.email) else _mask_contact(item.contact),
        identifiers=list(item.identifiers), min_level=RiskLevel(item.min_level),
        signal_scope=[s.value for s in dict.fromkeys(item.signal_scope)], active=item.active,
        phone=item.phone, email=item.email,
    ) for hid, item in zip(ids, items)]


def _helper_view(h: Helper) -> dict[str, Any]:
    """GET /api/helpers 항목: 원본(phone·email, 문자·메일 앱용) + 가린 표시(목록용)."""
    legacy = _mask_contact(h.contact)
    phone_masked = _mask_contact(h.phone) if h.phone else ""
    email_masked = _mask_contact(h.email) if h.email else ""
    if legacy and not (h.phone or h.email):   # 옛 가린 값: 표시만 한다(원본이 없어 보낼 수는 없음)
        if "@" in legacy:
            email_masked = legacy
        elif any(ch.isdigit() for ch in legacy):
            phone_masked = legacy
    contact = " · ".join(x for x in (phone_masked, email_masked) if x) or legacy
    return {
        "id": h.id, "name": h.name, "relation": h.relation, "phone": h.phone, "email": h.email,
        "phone_masked": phone_masked, "email_masked": email_masked,
        "identifiers": list(h.identifiers), "min_level": h.min_level.value,
        "signal_scope": list(h.signal_scope), "active": h.active, "contact": contact,
    }


# 번호 숫자 사이에 끼울 수 있는 구분 기호(공백·하이픈·점·괄호·슬래시 등, 숫자·글자·가림표가 아닌 것 0~3자)
_DIGIT_GAP = r"[^0-9A-Za-z가-힣*@]{0,3}"


def _national_digits(value: str) -> str:
    """번호 → 국내 표기 숫자('+82-10-1234-5678' → '01012345678'). 숫자가 7개보다 적으면 빈 글."""
    digits = re.sub(r"\D", "", value)
    if value.strip().lstrip("(").startswith("+82") and digits.startswith("82"):
        digits = "0" + digits[2:].lstrip("0")
    return digits if len(digits) >= _MIN_MASK_DIGITS else ""


def _number_pattern(national: str) -> "re.Pattern[str]":
    """같은 번호를 어떤 구분 기호·국제 표기(+82, +82 (0)10 …)로 적어도 찾는 정규식(BE-1)."""
    body = _DIGIT_GAP.join(re.escape(ch) for ch in national[1:]) if national.startswith("0") else ""
    forms = [_DIGIT_GAP.join(re.escape(ch) for ch in national)]
    if body:   # 국제 표기: +82 / 82 다음에 (0)이 있거나 없거나. 앞의 띄어쓰기는 먹지 않게 +나 8로 시작한다
        forms.append(rf"(?:\+{_DIGIT_GAP})?8{_DIGIT_GAP}2{_DIGIT_GAP}(?:\(?0\)?{_DIGIT_GAP})?{body}")
    return re.compile(r"(?<!\d)\(?(?:" + "|".join(forms) + r")(?!\d)")


def _scrub_contacts(text: str, values: Iterable[str]) -> str:
    """알림 기록 글에 조력자·상담하는 곳의 번호·메일 원본이 있으면 가린 값으로 바꾼다.

    같은 값을 다른 모양으로 적어도 찾는다(BE-1): 번호는 띄어쓰기·하이픈·점·괄호·+82 국제 표기,
    메일은 대소문자를 가리지 않는다.
    """
    for value in sorted({v.strip() for v in values if v and v.strip()}, key=len, reverse=True):
        masked = _mask_contact(value)
        if "@" in value:
            text = re.sub(re.escape(value), lambda _m: masked, text, flags=re.IGNORECASE)
            continue
        text = text.replace(value, masked)
        national = _national_digits(value)
        if national:
            shown = _mask_contact(national)
            text = _number_pattern(national).sub(lambda _m: shown, text)
    return text


def _manual_number(record_id: object) -> int:
    m = re.fullmatch(r"m(\d{1,9})", str(record_id or ""))
    return int(m.group(1)) if m else 0


# ---- 돈 흐름 분석(insights) ----
_TIME_BANDS: tuple[tuple[str, str, int, int], ...] = (
    ("dawn", "0-6", 0, 6), ("morning", "6-12", 6, 12), ("day", "12-18", 12, 18), ("evening", "18-24", 18, 24),
)
_PAYEE_CHANNELS = (Channel.TRANSFER, Channel.CARD)   # 많이 보낸 곳: 계좌 이체·카드 결제


def _month_key(ts: datetime) -> str:
    return f"{ts.year:04d}-{ts.month:02d}"


def _recent_months(first: datetime, last: datetime, n: int) -> list[str]:
    """마지막 거래가 있는 달부터 거꾸로 n달(첫 거래가 있는 달보다 앞은 빼고), 시간 순."""
    keys: list[str] = []
    year, month = last.year, last.month
    while len(keys) < n and (year, month) >= (first.year, first.month):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return list(reversed(keys))


def _month_stats(month: str, pairs: Sequence[tuple[Transaction, RiskAssessment]]) -> dict[str, Any]:
    out = [t for t, _ in pairs if t.direction == Direction.OUT]
    return {
        "month": month,
        "out_total": sum(int(t.amount) for t in out),
        "in_total": sum(int(t.amount) for t, _ in pairs if t.direction == Direction.IN),
        "out_count": len(out),
        "flagged": {"caution": sum(1 for _, a in pairs if a.level == RiskLevel.CAUTION),
                    "high": sum(1 for _, a in pairs if a.level == RiskLevel.HIGH)},
    }


def _channel_shares(pairs: Sequence[tuple[Transaction, RiskAssessment]]) -> list[dict[str, Any]]:
    totals: dict[str, list[int]] = {}
    for t, _ in pairs:
        if t.direction == Direction.OUT:
            row = totals.setdefault(t.channel.value, [0, 0])
            row[0] += int(t.amount)
            row[1] += 1
    whole = sum(v[0] for v in totals.values())
    rows = [{"channel": c, "out_total": v[0], "out_count": v[1],
             "share": round(v[0] / whole, 3) if whole else 0.0} for c, v in totals.items()]
    return sorted(rows, key=lambda r: (-r["out_total"], -r["out_count"], r["channel"]))


def _time_bands(pairs: Sequence[tuple[Transaction, RiskAssessment]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for band, hours, lo, hi in _TIME_BANDS:
        inside = [(t, a) for t, a in pairs if lo <= t.ts.hour < hi]
        out.append({"band": band, "hours": hours,
                    "flagged": sum(1 for _, a in inside if a.level != RiskLevel.NONE),
                    "out_count": sum(1 for t, _ in inside if t.direction == Direction.OUT)})
    return out


def _top_payees(pairs: Sequence[tuple[Transaction, RiskAssessment]], n: int) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for t, a in pairs:
        name = re.sub(r"\s+", " ", t.counterparty or "").strip()
        if t.direction != Direction.OUT or t.channel not in _PAYEE_CHANNELS or not name:
            continue
        row = rows.setdefault(name, {"name": name, "out_total": 0, "out_count": 0, "flagged": 0})
        row["out_total"] += int(t.amount)
        row["out_count"] += 1
        row["flagged"] += int(a.level != RiskLevel.NONE)
    return sorted(rows.values(), key=lambda r: (-r["out_total"], -r["out_count"], r["name"]))[:n]


def _same_period_compare(by_month: dict[str, list[tuple[Transaction, RiskAssessment]]], keys: Sequence[str],
                         first: datetime, last: datetime) -> Optional[dict[str, Any]]:
    """지난달 같은 날짜 범위(1일~기준일)의 나간 돈(v0.3 수정 FN-01). 이번 달은 기준일까지만 있으므로 이것과 견준다.

    지난달이 더 짧으면 지난달 끝 날까지 본다(예: 3월 31일 기준 → 2월 1~28일).
    저장된 거래가 지난달 1일보다 늦게 시작하면(그 기간을 다 모름) None.
    """
    if len(keys) < 2:
        return None
    prev = keys[-2]
    year, month = (int(x) for x in prev.split("-"))
    if first.date() > datetime(year, month, 1).date():
        return None
    prev_days = min(last.day, calendar.monthrange(year, month)[1])
    out = [t for t, _ in by_month.get(prev, []) if t.direction == Direction.OUT and t.ts.day <= prev_days]
    return {"month": prev, "days": last.day, "prev_days": prev_days,
            "prev_same_period_out": sum(int(t.amount) for t in out), "prev_same_period_count": len(out)}


def _metrics_module() -> Any:
    try:
        from safepause.eval import metrics
    except ImportError as exc:  # 평가 모듈이 없는 배포본
        raise EvalUnavailable("성능 평가 모듈(safepause.eval.metrics)을 찾을 수 없어요.") from exc
    return metrics


def _default_evaluator(persona_keys: list[str], seeds: list[int], modes: list[str], *,
                       intensity: str = "standard") -> dict[str, dict[str, Any]]:
    """(인물, seed)마다 한 번 학습하고 여러 방식으로 평가한다(metrics.compare_modes, 보고서 원자료와 같은 함수)."""
    return _metrics_module().compare_modes(persona_keys, seeds, modes, intensity=intensity)["modes"]


def _is_report_set(personas: Sequence[str], seeds: Sequence[int]) -> bool:
    """제출 보고서 검증 세트(인물 3명 × seed 21~40)와 같은 설정인지. 방식 수와 강도는 따지지 않는다.

    방식마다 결과는 따로 계산되고(compare_modes), 강도는 표준·경계 변형 세트 가운데 무엇과 견줄지만 정한다.
    """
    return (set(personas) == set(PERSONA_KEYS)
            and list(seeds) == list(range(REPORT_SEED_START, REPORT_SEED_START + REPORT_SEEDS)))


def _ts_note(req: PendingIn, pending: Transaction, now: datetime,
             history: Sequence[Transaction] = ()) -> str:
    """저장된 거래가 오래돼(합성·옛 데이터) 확인한 거래의 날짜를 저장된 거래 끝으로 옮겼으면 까닭을 알려 준다."""
    if req.ts is None and pending.ts.date() != now.date() and not _recent_data(_last_real_ts(history), now):
        return TS_NOTE
    return ""


def _decision_message(decision: Decision, plan: NotifyPlan, pending: Optional[Transaction] = None,
                      asked_count: Optional[int] = None) -> str:
    """결정 뒤 한 문장. SafePause는 돈을 옮기지 않으므로 보냈다고 말하지 않는다(v0.3 돈 보내기)."""
    words = channel_words(pending.channel if pending else Channel.TRANSFER)
    if decision == Decision.SEND:
        return f"{words.self_do}."          # 계좌 이체: 내 은행 앱에서 보내 주세요.
    if decision == Decision.CANCEL:
        return f"{words.not_done}."         # 계좌 이체: 보내지 않았어요.
    if asked_count == 0:   # 물어볼 조력자가 없었음: 물어봤다고 말하지 않는다
        return f"물어볼 조력자가 없어요. 아직 {words.not_done}."
    return plan.note_to_person or "조력자에게 물어봐요."


def _load_upload(raw: bytes, mapping: Optional[dict[str, Any]]) -> tuple[list[Transaction], dict[str, Any]]:
    """올린 CSV를 읽는다(데이터 연결 어댑터 사용). 테스트는 이 함수를 바꿔 끼울 수 있다.
    mapping 없이 올리면(화면의 파일 올리기) 안내 글의 mapping 안내를 쉬운 말로 바꾼다."""
    from safepause.data.loader import LoaderError, plain_message
    from safepause.data.sources import CsvUploadSource
    try:
        txns, report = CsvUploadSource(raw, mapping).load()
    except LoaderError as exc:   # 파일 모양 문제: 한국어 안내 그대로(400)
        raise ServiceError(400, str(exc) if mapping else plain_message(str(exc))) from exc
    if not mapping and report and report.get("warnings"):
        report = {**report, "warnings": [plain_message(w) for w in report["warnings"]]}
    return txns, report


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


def _same_txn_key(txn: Transaction) -> tuple[Any, ...]:
    """이어 붙여 올릴 때 같은 거래인지 보는 지문: 시각·금액·방향·방법·상대(공백·대소문자 무시)."""
    return (txn.ts.isoformat(timespec="seconds"), int(txn.amount), txn.direction.value, txn.channel.value,
            _norm_name(txn.counterparty))


def _append_new(existing: Sequence[Transaction], incoming: Sequence[Transaction],
                taken: Iterable[str]) -> tuple[list[Transaction], int]:
    """이어 붙이기(v0.3 수정 AUG-03): 이미 저장된 거래와 같은 거래는 한 번만 둔다(개수까지 세는 비교).

    새 파일 안에서 똑같은 거래가 두 번 있으면(같은 시각 같은 가게 두 번 결제 등), 저장된 쪽에 하나만 있을 때
    하나만 겹친 것으로 본다. 새로 더하는 거래의 id가 저장된 거래·담은 거래·확인 표시와 겹치면 -2, -3…을 붙인다
    (옛 담음 표시가 엉뚱한 새 거래에 붙지 않게). 돌려주는 값: (더할 거래, 겹쳐서 뺀 수).
    """
    left = Counter(_same_txn_key(t) for t in existing)
    used = {*taken, *(t.id for t in existing)}
    added: list[Transaction] = []
    duplicates = 0
    for t in incoming:
        key = _same_txn_key(t)
        if left[key] > 0:
            left[key] -= 1
            duplicates += 1
            continue
        if t.id in used:
            base, n = t.id[:100], 2
            while f"{base}-{n}" in used:
                n += 1
            t = replace(t, id=f"{base}-{n}")
        used.add(t.id)
        added.append(t)
    return added, duplicates


def _signal_names(assessment: RiskAssessment) -> str:
    """걸린 약속의 화면 이름(명사형, labels.js SIGNAL_KO와 같은 글). 처음인지 알 수 없을 때는 중립 이름."""
    names: list[str] = []
    for h in assessment.rule_hits:
        code = h.code.value
        neutral = (h.evidence or {}).get("newness_unknown") and code in SIGNAL_KO_NEUTRAL
        names.append(SIGNAL_KO_NEUTRAL[code] if neutral else SIGNAL_KO.get(code, code))
    return ", ".join(dict.fromkeys(names))


# 자동 기록 글의 당사자 결정 문장(옛 기록 포함). 당사자 화면에 보이므로 빼고 보인다(v0.3 수정 RF-11)
_DECISION_SENTENCE_RE = re.compile(r" ?결정은 [^.]{1,20}?(?:해요|합니다)\.")


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
                raise ServiceError(409, LIVE_IDS_USED_UP)
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
        return [_helper_view(h) for h in self.store.load_helpers()]

    def put_helpers(self, helpers: list[HelperIn]) -> list[dict[str, Any]]:
        if len(helpers) > MAX_HELPERS:
            raise ServiceError(422, f"조력자는 {MAX_HELPERS}명까지 정할 수 있어요.")
        saved = _assign_helper_ids(helpers)
        with self.lock, self.store.transaction():
            try:
                stored = {h.id: h for h in self.store.load_helpers()}
            except StoreError:   # 손상된 파일은 새 목록으로 덮어쓴다
                stored = {}
            for h, item in zip(saved, helpers):
                old = stored.get(h.id)
                # v0.2에서 옮겨 온 가린 연락처(원본 없음)는 번호·메일을 비워 보내도 지킨다(BE-8). 지우려면 clear_contact
                if (old is not None and old.contact and not (old.phone or old.email)
                        and not (h.phone or h.email or h.contact) and not item.clear_contact):
                    h.contact = old.contact
            self.store.save_helpers(saved)
        return [_helper_view(h) for h in saved]

    # ---- 상담하는 곳(v0.3: 사용자가 직접 추가·지정) ----
    def get_counselors(self) -> dict[str, Any]:
        """손상된 파일은 빈 목록으로 보인다(다시 저장하면 새 목록으로 덮어씀, BE-6)."""
        return {"items": [c.to_dict() for c in self._counselors_safe()],
                "presets": [dict(p) for p in COUNSELOR_PRESETS]}

    def put_counselors(self, items: list[CounselorIn]) -> dict[str, Any]:
        if len(items) > MAX_COUNSELORS:
            raise ServiceError(422, f"상담하는 곳은 {MAX_COUNSELORS}곳까지 정할 수 있어요.")
        ids = _fill_ids([item.id for item in items], "c")
        saved = [Counselor(id=cid, name=item.name, kind=item.kind, phone=item.phone, email=item.email,
                           memo=item.memo, active=item.active) for cid, item in zip(ids, items)]
        with self.lock:
            self.store.save_counselors(saved)
        return {"items": [c.to_dict() for c in saved]}

    def counseling_names(self) -> list[str]:
        """상담 안내에 쓸 이름: 사용 중인 상담하는 곳(없으면 기본 2곳). 파일이 손상돼도 알림 화면은 열린다(BE-6)."""
        names = [c.name for c in self._counselors_safe() if c.active]
        return names or list(policy.COUNSELING_ORGS)

    def _counselors_safe(self) -> list[Counselor]:
        try:
            return self.store.load_counselors()
        except StoreError as exc:
            log.warning("상담하는 곳 파일을 읽지 못해 빈 목록으로 봐요: %s", exc)
            return []

    # ---- 보조 파일(담은 거래·내가 확인함·보낸 알림): 손상돼도 핵심 화면은 열리게(BE-6) ----
    def _flags_safe(self) -> list[dict[str, Any]]:
        try:
            return self.store.load_flags()
        except StoreError as exc:
            log.warning("담은 거래 파일을 읽지 못해 빈 목록으로 봐요: %s", exc)
            return []

    def _reviews_safe(self) -> list[dict[str, Any]]:
        try:
            return self.store.load_reviews()
        except StoreError as exc:
            log.warning("내가 확인한 거래 파일을 읽지 못해 빈 목록으로 봐요: %s", exc)
            return []

    def _reviewed_ids(self) -> frozenset[str]:
        return frozenset(r["txn_id"] for r in self._reviews_safe() if r.get("status", REVIEW_OK) == REVIEW_OK)

    def _notified_map(self) -> dict[str, str]:
        """거래 id → 직접 보낸 알림 기록(kind manual) 가운데 그 거래가 든 가장 최근 시각(AUG-04)."""
        try:
            records = self.store.load_notices()
        except StoreError as exc:
            log.warning("알림 기록 파일을 읽지 못했어요: %s", exc)
            return {}
        out: dict[str, str] = {}
        for r in records:
            at = str(r.get("created_at", "") or "")
            ids = r.get("txn_ids")
            if r.get("kind") != "manual" or not at or not isinstance(ids, list):
                continue
            for tid in ids:
                key = str(tid)
                if at > out.get(key, ""):
                    out[key] = at
        return out

    # ---- 데이터 ----
    def _save_if_current(self, txns: list[Transaction], generation: int, *, need_consent: bool,
                         mode: str = "replace") -> tuple[list[Transaction], int, int]:
        """시작할 때의 세대 번호 그대로이고 (필요하면) 동의가 있을 때만 저장한다(S37 즉시 철회, 409).

        mode replace: 거래를 통째로 바꾼다. 담은 거래·내가 확인한 표시를 먼저 비운다(BE-7: 비우기가 실패하면 거래도
        그대로라 옛 표시가 새 거래에 붙지 않는다). mode append: 저장된 거래 뒤에 붙이고 같은 거래는 한 번만(AUG-03),
        담은 거래·내가 확인한 표시는 그대로 둔다. 돌려주는 값: (저장된 거래 전체, 더한 수, 겹쳐서 뺀 수).
        """
        with self.lock, self.store.transaction():
            if self.generation != generation:
                raise ServiceError(409, SUPERSEDED)
            if need_consent:
                self._require_monitoring()
            if mode == "append":
                existing = self.store.load_transactions()
                taken = {f["txn_id"] for f in self._flags_safe()} | {r["txn_id"] for r in self._reviews_safe()}
                added, duplicates = _append_new(existing, txns, taken)
                merged = sorted([*existing, *added], key=lambda t: t.ts)
                if added:
                    self.store.save_transactions(merged)
                    self.reset()
                return merged, len(added), duplicates
            self.store.clear_flags()     # 거래를 통째로 바꾸면 담은 거래도 비운다(v0.3)
            self.store.clear_reviews()   # 내가 확인한 표시도 비운다(v0.3 수정 계획 C)
            self.store.save_transactions(txns)
            self.reset()
            return list(txns), len(txns), 0

    def _level_stats(self) -> dict[str, Any]:
        """불러온 뒤 요약(AUG-07·J3): 등급별 건수와 AI만 먼저 잡은 거래 수. 분석 결과는 캐시에 남아 다음 화면이 빠르다."""
        try:
            snap = self.snapshot()
        except ServiceError:   # 그 사이 데이터가 바뀜: 요약 없이 돌려준다
            return {"levels": None, "ai_only": None}
        levels = Counter(a.level.value for a in snap.assessments)
        return {"levels": {lv.value: levels.get(lv.value, 0) for lv in RiskLevel},
                "ai_only": sum(1 for a in snap.assessments if a.level != RiskLevel.NONE and not a.rule_hits)}

    def data_summary(self) -> dict[str, Any]:
        return _summary(self.store.load_transactions())

    def data_sample(self, body: SampleIn) -> dict[str, Any]:
        from safepause.data.sources import SyntheticSampleSource   # numpy를 여기서 싣는다
        with self.lock:
            generation = self.generation
        source = SyntheticSampleSource(body.persona, body.seed, scenarios=body.scenarios, days=body.days)
        txns, _report = source.load()
        self._save_if_current(txns, generation, need_consent=False)   # 가상 거래라 동의는 보지 않음
        # 등급 요약(ai_only: AI만 먼저 잡은 거래 수, v0.3 수정 계획 D)은 거래 살펴보기 동의가 있을 때만 판단해 준다
        # (분석은 동의가 있을 때만 한다는 원칙을 가상 거래에도 지킨다. 동의가 없으면 None)
        stats = (self._level_stats() if self.store.load_consent().monitoring
                 else {"levels": None, "ai_only": None})
        return {"source": "sample", "persona": body.persona, "persona_name": source.persona_name,
                "seed": body.seed, "scenarios": body.scenarios, "days": body.days, **_summary(txns), **stats}

    def upload_begin(self) -> int:
        """동의 확인 뒤 지금 세대 번호. 동의가 없으면 파일을 읽기 전에 403."""
        with self.lock:
            self._require_monitoring()   # 실제 거래내역은 동의가 있어야 받는다
            return self.generation

    def upload_finish(self, generation: int, raw: Optional[bytes], mapping_text: str = "",
                      mode: Optional[str] = None) -> dict[str, Any]:
        """올린 파일(바이트, CSV·TXT·XLSX)을 읽어 저장한다. 파일은 메모리에서만 읽는다(임시 파일 없음).

        mode: "replace"(기본, 모두 바꾸기) 또는 "append"(이어 붙이기, 같은 거래는 한 번만).
        """
        mode = (mode or "").strip() or "replace"
        if mode not in UPLOAD_MODES:
            raise ServiceError(422, "입력한 값을 확인해 주세요: 올리는 방법",
                               errors=[{"loc": ["mode"], "type": "literal_error"}])
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
        # 파일에 보내기 전 확인 거래와 같은 모양의 id(live-…)가 있으면 바꿔 저장한다(확인 거래로 오인·중복 기록 방지).
        # 바꾼 id가 파일의 다른 id와 겹치지 않게 한다(v0.2 2차 검증)
        fixed, renamed = _unique_ids(txns)
        if renamed:
            report = {**report, "warnings": [*report.get("warnings", []),
                                             f"보내기 전 확인한 거래와 같은 모양의 번호 {renamed}건은 이름을 바꿔 저장했어요."]}
        # 읽는 사이 지우기·동의 끄기가 있었으면 저장하지 않는다(철회가 먼저)
        saved, added, duplicates = self._save_if_current(fixed, generation, need_consent=True, mode=mode)
        if duplicates:
            report = {**report, "warnings": [*report.get("warnings", []),
                                             f"이미 저장된 거래와 같은 {duplicates}건은 한 번만 두었어요."]}
        out = {"source": "upload", "mode": mode, "added": added, "duplicates": duplicates,
               "report": _plain(report), "summary": _summary(saved)}
        # 읽은 거래 목록은 분석 전에 놓는다(분석은 저장 파일에서 다시 읽음). 큰 파일에서 두 벌을 함께 들지 않아
        # 메모리 최대치가 줄어든다(앱 안 엔진의 WASM 메모리는 한 번 늘면 줄지 않음)
        del txns, fixed, saved
        out.update(self._level_stats())
        return out

    def upload(self, raw: Optional[bytes], mapping_text: str = "", mode: Optional[str] = None) -> dict[str, Any]:
        return self.upload_finish(self.upload_begin(), raw, mapping_text, mode)

    # ---- 내 거래 + 평가 ----
    def transactions(self, level: str = "all", limit: int = 0, offset: int = 0, q: str = "",
                     since: Optional[date] = None, until: Optional[date] = None) -> dict[str, Any]:
        """내 거래(최근 것부터). q: 상대 이름 검색(공백·대소문자 무시), since·until: 날짜 범위(양 끝 포함, AUG-09).

        matched는 걸러 낸 수다. count·summary·open_summary는 걸러 내기와 관계없이 저장된 거래 전체다.
        """
        snap = self._analysis()
        key = _norm_name(q)
        counts = Counter(a.level.value for a in snap.assessments)
        flagged = {f["txn_id"] for f in self._flags_safe()}
        reviewed = self._reviewed_ids()
        notified = self._notified_map()
        fitted = bool(snap.engine.fitted)
        wanted = {"all": None, "flagged": None, "caution": {RiskLevel.CAUTION, RiskLevel.HIGH},
                  "high": {RiskLevel.HIGH}}[level]
        pairs = [(t, a) for t, a in zip(reversed(snap.txns), reversed(snap.assessments))
                 if (wanted is None or a.level in wanted) and (level != "flagged" or t.id in flagged)
                 and (not key or key in _norm_name(t.counterparty))
                 and (since is None or t.ts.date() >= since) and (until is None or t.ts.date() <= until)]
        matched = len(pairs)
        page = pairs[offset:offset + limit] if limit else pairs[offset:]
        items = [_item(t, a, t.id in flagged, reviewed=t.id in reviewed, notified_at=notified.get(t.id),
                       fitted=fitted) for t, a in page]   # 보여 줄 쪽만 만든다(리뷰 M9)
        open_counts = Counter(a.level.value for t, a in zip(snap.txns, snap.assessments) if t.id not in reviewed)
        return {
            "count": len(snap.txns),
            "matched": matched,
            "offset": offset,
            "flagged_count": sum(1 for t in snap.txns if t.id in flagged),
            "summary": {lv.value: counts.get(lv.value, 0) for lv in RiskLevel},
            # 내가 한 거예요로 표시한 거래를 뺀 등급별 수(홈의 꼭 확인할 거래 N건). summary와의 차이가 뺀 건수다
            "open_summary": {lv.value: open_counts.get(lv.value, 0) for lv in RiskLevel},
            "reviewed_count": sum(1 for t in snap.txns if t.id in reviewed),
            # train_count = 학습 구간 거래 수, train_rows = 실제 학습 행 수(초기 거래를 빼서 더 적을 수 있음)
            "model": {"fitted": snap.engine.fitted, "version": snap.engine.model_version(),
                      "train_count": snap.train_count, "train_rows": snap.engine.model.n_train},
            "items": items,   # 최근 거래부터
        }

    def payees(self, limit: int = 30) -> dict[str, Any]:
        """돈 보내기 자동완성: 최근에 계좌로 돈을 보낸 사람 이름(최근 것부터, 겹침 없이)."""
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
        """보내기 전 평가. 아무것도 저장하지 않는다(확인 거래 id와 지문만 메모리에 기억)."""
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
            names = self.counseling_names()
            reviewed = self._reviewed_ids()
            preview = _with_counseling(policy.decide(assessment, pending, helpers, consent,
                                                     _recent_high(snap, pending, assessment, self.settings,
                                                                  decisions, now, reviewed),
                                                     self.settings, now=now, preview=True), names)
            candidates = policy.ask_helper_candidates(assessment, pending, helpers)
            auto_ids = {n.helper_id for n in preview.notices}
            for c in candidates:   # 자동 알림 대상: 물어보기에서 빼도 조력자 설정대로 알게 됨
                c["auto"] = c["id"] in auto_ids
            # 물어볼 수 있는 사람이 없으면(모두 돈을 받는 사람) 동의 시 상담하는 곳을 미리 알려 준다
            ask_counseling: list[str] = []
            if candidates and all(c["conflict"] for c in candidates):
                every = policy.ask_helper_plan(assessment, pending, helpers, consent,
                                               helper_ids=[c["id"] for c in candidates], now=now)
                ask_counseling = _with_counseling(every, names).counseling_orgs
        return _plain({
            "pending": pending.to_dict(),
            "assessment": assessment.to_dict(),
            "ai": _ai_view(assessment, snap.engine.fitted),   # AI가 본 것(거래 30건 미만이면 fitted False)
            "card": card.to_dict() if card else None,
            "notify_plan_preview": preview.to_dict(),
            # '조력자에게 물어볼래요'를 고르기 전에 누구에게 묻게 되는지 보여 주는 목록
            "ask_helper_preview": {"candidates": candidates, "counseling_orgs": ask_counseling},
            "practice_note": "",   # v0.3: 연습 안내를 쓰지 않는다(키는 옛 화면 호환용)
            "ts_note": _ts_note(body, pending, now, snap.txns),
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
                                 _recent_high(snap, pending, assessment, self.settings, decisions, now,
                                              self._reviewed_ids()),
                                 self.settings, now=now)
            asked_count: Optional[int] = None
            if body.decision == Decision.ASK_HELPER:  # 당사자가 직접 요청(묻는 사람도 당사자가 고름)
                asked = policy.ask_helper_plan(assessment, pending, helpers, consent,
                                               helper_ids=body.helper_ids, now=now)
                asked_count = len(asked.notices)
                plan = _merge_plans(plan, asked)
            plan = _with_counseling(plan, self.counseling_names())

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
            # 이름이 번호·메일 모양이어도 기록에는 가린 값만(직접 보낸 기록과 같게, BE-3)
            self.outbox.send_all(replace(n, helper_name=_mask_contact(n.helper_name))
                                 for n in plan.notices if n.helper_id not in noticed)
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
            "practice_note": "",   # v0.3: 연습 안내를 쓰지 않는다(키는 옛 화면 호환용)
            "ts_note": _ts_note(body.pending, pending, now, snap.txns),
            "delivery_note": DELIVERY_NOTE,
        })

    # ---- 기록 ----
    def cards(self, limit: int = 20) -> dict[str, Any]:
        snap = self._analysis()
        flagged = [(t, a) for t, a in zip(snap.txns, snap.assessments) if a.level != RiskLevel.NONE]
        marked = {f["txn_id"] for f in self._flags_safe()}
        reviewed = self._reviewed_ids()
        notified = self._notified_map()
        fitted = bool(snap.engine.fitted)
        items: list[dict[str, Any]] = []
        for t, a in reversed(flagged[-limit:]):
            card = render_card(a, t, past=True)  # 이미 끝난 거래: 과거형, 묻지 않음
            if card is not None:
                items.append(_plain({"card": card.to_dict(), "txn": _txn_out(t),
                                     "signals": [h.code.value for h in a.rule_hits],
                                     "flagged": t.id in marked, "reviewed": t.id in reviewed,
                                     "notified_at": notified.get(t.id), "ai": _ai_view(a, fitted)}))
        done = sum(1 for t, _ in flagged if t.id in reviewed)
        # total은 탐지 그대로, open은 내가 한 거예요로 표시한 것을 뺀 수(알림 탭 걱정되는 거래 수), reviewed는 뺀 수
        return {"total": len(flagged), "open": len(flagged) - done, "reviewed": done, "items": items,
                "counseling": self._counseling_hint(snap, reviewed)}

    def _counseling_hint(self, snap: Snapshot, reviewed: Optional[frozenset[str]] = None) -> dict[str, Any]:
        """알림 탭의 상담 안내 띠: 상담하는 곳에 알려 주기 동의 + 마지막 거래 기준 30일 고위험 3건 이상(S23).

        내가 한 거예요로 표시한 거래는 세지 않는다(v0.3 수정 계획 C, 등급은 그대로).
        """
        threshold = self.settings.high_repeat_for_counseling
        skip = self._reviewed_ids() if reviewed is None else reviewed
        recent = 0
        if snap.txns:
            last = snap.txns[-1].ts
            lo = last - timedelta(days=self.settings.window_long_days)
            recent = sum(1 for t, a in zip(snap.txns, snap.assessments)
                         if a.level == RiskLevel.HIGH and lo < t.ts <= last and t.id not in skip)
        suggest = self.store.load_consent().counseling_referral and recent >= threshold
        return {"suggest": bool(suggest), "recent_high": recent, "threshold": threshold,
                "orgs": self.counseling_names() if suggest else []}

    def notices(self) -> dict[str, Any]:
        """자동 기록(kind "auto")과 직접 보낸 기록(kind "manual")을 함께, 최근 것부터.

        자동 기록은 보내지 않고 적어 둔 기록이다(화면은 보낸 알림과 구분해 보인다). 당사자 화면에 보이므로
        조력자용 글의 결정 문장은 빼고, 조력자 이름이 번호·메일 모양이면 가린다(옛 기록 포함, RF-11·BE-3).
        """
        items: list[dict[str, Any]] = []
        for r in reversed(self.store.load_notices()):
            if r.get("kind") == "manual":
                items.append(r)
                continue
            message = _DECISION_SENTENCE_RE.sub("", str(r.get("message", "") or "")).strip()
            items.append({**r, "kind": "auto", "helper_name": _mask_contact(str(r.get("helper_name", "") or "")),
                          "message": message})
        return {"items": items, "delivery_note": NOTICES_NOTE}

    def remove_notice(self, body: NoticeRemoveIn) -> dict[str, Any]:
        """직접 보낸 알림 기록 하나를 지운다(AUG-06). 자동 기록은 지우지 않는다(없으면 404). 동의는 보지 않는다."""
        with self.lock, self.store.transaction():
            records = self.store.load_notices()
            kept = [r for r in records if not (r.get("kind") == "manual" and str(r.get("id", "")) == body.id)]
            if len(kept) == len(records):
                raise ServiceError(404, NOTICE_NOT_FOUND)
            self.store.save_notices(kept)
        return {"ok": True, "count": len(kept)}

    def record_notice(self, body: NoticeRecordIn) -> dict[str, Any]:
        """문자·메일 앱으로 직접 보낸 알림을 기록한다. 받는 사람은 종류·이름만, 번호·메일 원본은 넣지 않는다."""
        with self.lock, self.store.transaction():
            helpers = {h.id: h for h in self.store.load_helpers()}
            counselors = {c.id: c for c in self._counselors_safe()}
            recipients: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for r in body.recipients:
                known = (helpers if r.kind == "helper" else counselors).get(r.id) if r.id else None
                # id는 저장된 조력자·상담하는 곳일 때만 남긴다(다시 보내기용, AUG-06). 번호·메일 원본은 넣지 않는다
                entry = {"kind": r.kind, "id": r.id if known else "",
                         "name": _mask_contact(known.name if known else r.name)}
                key = (r.kind, entry["id"] or "name:" + entry["name"])
                if key not in seen:
                    seen.add(key)
                    recipients.append(entry)
            raw = [v for x in [*helpers.values(), *counselors.values()] for v in (x.phone, x.email)]
            records = self.store.load_notices()
            number = 1 + max((_manual_number(x.get("id")) for x in records if x.get("kind") == "manual"),
                             default=0)
            record = {"id": f"m{number}", "kind": "manual", "channel": body.channel, "recipients": recipients,
                      "txn_ids": list(body.txn_ids), "message": _scrub_contacts(body.message, raw),
                      "created_at": self.timestamp()}
            self.store.append_notice_record(record)
        return record

    def notify_suggest(self, body: SuggestIn) -> dict[str, Any]:
        """알림 보내기의 받는 사람 추천(docs/v03_spec_money.md 받는 사람 추천).

        조력자 추천은 자동 알림(policy.decide)과 같은 규칙이다: 조력자에게 알리기 동의 + 자동으로 알리기(active)
        + 고른 거래 가운데 하나 이상이 그 조력자의 등급·범위에 듦(policy.is_eligible) + 고른 거래 가운데 나간 돈의
        상대방이 아님(policy.is_conflict). 들어온 돈을 보낸 조력자는 이해충돌이 아니다(BE-4). 거래를 고르지 않았으면
        동의와 active만 본다.
        pending(선택): 저장하지 않은 보내기 전 확인 거래. 그 자리에서 판단해 고른 거래처럼 본다(RF-1). 저장하지 않는다.
        상담하는 곳 추천(counseling_reason)
        - "repeat": 알림 탭의 상담 안내와 같은 기준(_counseling_hint, 내가 확인한 거래는 뺌)을 넘음 = counseling_due
        - "conflict": 상담하는 곳에 알려 주기 동의 + 범위에 드는 조력자가 있는데 모두 돈을 받은 사람(policy의
          all_conflicted와 같은 판단, BE-5)
        사용 중(active)인 상담하는 곳만 추천한다. 거래 살펴보기 동의가 필요하다(403). 고른 거래 가운데 하나라도 없으면 404.
        """
        snap = self._analysis()
        with self.lock:
            # 동의·분석 결과는 잠금 안에서 다시 본다(그 사이 동의를 끄면 403, 거래가 바뀌면 다시 만듦)
            consent = self._require_monitoring()
            snap = self._current(snap)
            index = {t.id: (t, a) for t, a in zip(snap.txns, snap.assessments)}
            if any(tid not in index for tid in body.txn_ids):
                raise ServiceError(404, TXN_NOT_FOUND)
            pairs = [index[tid] for tid in body.txn_ids]
            if body.pending is not None:
                given = (body.pending.id or "").strip()
                if given and given in index:              # 그래도 보낼래요로 이미 적힌 확인 거래
                    if index[given] not in pairs:
                        pairs.append(index[given])
                else:
                    pending = _build_pending(body.pending, snap.txns, self.now(), given or "pending")
                    pairs.append((pending, snap.engine.assess_pending(pending, snap.txns)))
            due = bool(self._counseling_hint(snap)["suggest"])
            stored_helpers = self.store.load_helpers()
            stored_counselors = self._counselors_safe()
        helpers: list[dict[str, Any]] = []
        eligible_conflicts: list[bool] = []
        for h in stored_helpers:
            conflict = any(policy.is_conflict(h, t) for t, _ in pairs if t.direction == Direction.OUT)
            fits = any(policy.is_eligible(h, a) for _, a in pairs) if pairs else h.active
            if pairs and fits and h.active:
                eligible_conflicts.append(conflict)
            helpers.append({"id": h.id, "name": h.name,
                            "suggested": bool(consent.helper_alerts and h.active and fits and not conflict),
                            "conflict": conflict, "reason": CONFLICT_REASON if conflict else ""})
        all_conflicted = bool(eligible_conflicts) and all(eligible_conflicts)
        reason = "repeat" if due else ("conflict" if all_conflicted and consent.counseling_referral else "")
        counselors = [{"id": c.id, "name": c.name, "suggested": bool(reason and c.active)}
                      for c in stored_counselors]
        return {"helpers": helpers, "counselors": counselors, "counseling_due": due,
                "counseling_reason": reason}

    # ---- 알림 목록에 담은 거래(v0.3) ----
    def _stored_txn_ids(self) -> set[str]:
        """(잠금 안에서) 저장된 거래 id. 분석 결과가 저장 파일과 맞으면 그것을 쓴다(큰 파일을 다시 읽지 않게)."""
        if self._snap is not None and self.store.signature() == self._snap_sig:
            return {t.id for t in self._snap.txns}
        return {t.id for t in self.store.load_transactions()}

    def get_flags(self) -> dict[str, Any]:
        snap = self._analysis()
        index = {t.id: (t, a) for t, a in zip(snap.txns, snap.assessments)}
        reviewed = self._reviewed_ids()
        notified = self._notified_map()
        fitted = bool(snap.engine.fitted)
        items: list[dict[str, Any]] = []
        for f in reversed(self._flags_safe()):   # 최근 담은 것부터, 사라진 거래는 뺀다
            pair = index.get(f["txn_id"])
            if pair is not None:
                items.append({"txn_id": f["txn_id"], "created_at": str(f.get("created_at", "")),
                              "item": _item(*pair, True, reviewed=f["txn_id"] in reviewed,
                                            notified_at=notified.get(f["txn_id"]), fitted=fitted)})
        return {"items": items}

    def add_flag(self, body: FlagIn) -> dict[str, Any]:
        with self.lock, self.store.transaction():
            self._require_monitoring()
            ids = self._stored_txn_ids()
            if body.txn_id not in ids:
                raise ServiceError(404, TXN_NOT_FOUND)
            flags = self._flags_safe()   # 손상된 파일은 새 목록으로 덮어쓴다(BE-6)
            kept = [f for f in flags if f["txn_id"] in ids]   # 사라진 거래는 이참에 뺀다
            if not any(f["txn_id"] == body.txn_id for f in kept):
                kept.append({"txn_id": body.txn_id, "created_at": self.timestamp()})
            if kept != flags:
                self.store.save_flags(kept)
        return {"ok": True, "count": len(kept)}

    def remove_flag(self, body: FlagIn) -> dict[str, Any]:
        """담기 취소. 빼는 일이라 동의를 보지 않는다(담겨 있지 않아도 그대로 성공). 손상된 파일은 비운다(BE-6)."""
        with self.lock, self.store.transaction():
            try:
                flags: Optional[list[dict[str, Any]]] = self.store.load_flags()
            except StoreError:
                flags = None
            kept = [f for f in flags or [] if f["txn_id"] != body.txn_id]
            if flags is None or len(kept) != len(flags):
                self.store.save_flags(kept)
        return {"ok": True, "count": len(kept)}

    # ---- 내가 한 거예요(v0.3 수정 계획 C): 표시와 일부 집계만 바꾸고 탐지 등급·평가 수치는 그대로 ----
    def add_review(self, body: FlagIn) -> dict[str, Any]:
        """내가 한 거래로 표시한다. 거래 살펴보기 동의가 필요하고(403), 없는 거래는 404."""
        with self.lock, self.store.transaction():
            self._require_monitoring()
            ids = self._stored_txn_ids()
            if body.txn_id not in ids:
                raise ServiceError(404, TXN_NOT_FOUND)
            rows = self._reviews_safe()
            kept = [r for r in rows if r["txn_id"] in ids]   # 사라진 거래는 이참에 뺀다
            if not any(r["txn_id"] == body.txn_id for r in kept):
                kept.append({"txn_id": body.txn_id, "status": REVIEW_OK, "created_at": self.timestamp()})
            if kept != rows:
                self.store.save_reviews(kept)
        return {"ok": True, "count": len(kept)}

    def remove_review(self, body: FlagIn) -> dict[str, Any]:
        """확인 취소. 빼는 일이라 동의를 보지 않는다(표시돼 있지 않아도 그대로 성공). 손상된 파일은 비운다."""
        with self.lock, self.store.transaction():
            try:
                rows: Optional[list[dict[str, Any]]] = self.store.load_reviews()
            except StoreError:
                rows = None
            kept = [r for r in rows or [] if r["txn_id"] != body.txn_id]
            if rows is None or len(kept) != len(rows):
                self.store.save_reviews(kept)
        return {"ok": True, "count": len(kept)}

    # ---- 보내기 전 확인 기록 지우기(v0.3 수정 계획 A) ----
    def remove_checked(self, body: FlagIn) -> dict[str, Any]:
        """그래도 보낼래요로 내 거래에 적힌 확인 기록(live-숫자) 하나를 지운다. 담은 거래·내가 확인한 표시도 정리한다.

        다른 거래는 지우지 않는다(400). 없으면 404. 지우는 일이라 동의는 보지 않는다. 결정 기록(decisions)은 남긴다.
        """
        if not _is_live(body.txn_id):
            raise ServiceError(400, ONLY_CHECKED)
        with self.lock, self.store.transaction():
            current = self.store.load_transactions()
            kept = [t for t in current if t.id != body.txn_id]
            if len(kept) == len(current):
                raise ServiceError(404, TXN_NOT_FOUND)
            self.store.save_transactions(kept)
            self.reset()
            flags = self._flags_safe()
            if any(f["txn_id"] == body.txn_id for f in flags):
                self.store.save_flags([f for f in flags if f["txn_id"] != body.txn_id])
            rows = self._reviews_safe()
            if any(r["txn_id"] == body.txn_id for r in rows):
                self.store.save_reviews([r for r in rows if r["txn_id"] != body.txn_id])
        return {"ok": True, "count": len(kept)}

    # ---- 돈 흐름 분석(v0.3, 기준 달 = 저장된 마지막 거래가 있는 달) ----
    def insights(self) -> dict[str, Any]:
        """월별 나간 돈·들어온 돈, 기준 달의 결제 방법별 비율·시간대·많이 보낸 곳.

        보내기 전 확인 기록(live-)은 모두 뺀다: 실제로 보냈는지 모르기 때문이다(v0.3 수정 계획 A). 뺀 수는
        checked_excluded. compare는 지난달 같은 날짜 범위(1일~기준일)의 나간 돈이다(FN-01). 시간대 이름은 화면이 붙인다.
        """
        snap = self._analysis()
        pairs = [(t, a) for t, a in zip(snap.txns, snap.assessments) if not _is_live(t.id)]   # 시간순
        checked = len(snap.txns) - len(pairs)
        flagged_total = {"caution": sum(1 for _, a in pairs if a.level == RiskLevel.CAUTION),
                         "high": sum(1 for _, a in pairs if a.level == RiskLevel.HIGH)}
        if not pairs:
            return {"as_of": None, "months": [], "this_month": None, "prev_month": None, "compare": None,
                    "channels": [], "time_bands": _time_bands([]), "top_payees": [], "flagged_total": flagged_total,
                    "checked_excluded": checked}
        by_month: dict[str, list[tuple[Transaction, RiskAssessment]]] = {}
        for t, a in pairs:
            by_month.setdefault(_month_key(t.ts), []).append((t, a))
        first, last = pairs[0][0].ts, pairs[-1][0].ts
        keys = _recent_months(first, last, INSIGHT_MONTHS)
        months = [_month_stats(k, by_month.get(k, [])) for k in keys]
        current = by_month.get(keys[-1], [])
        return {
            "as_of": last.date().isoformat(),
            "months": months,
            "this_month": months[-1],
            "prev_month": months[-2] if len(months) > 1 else None,
            "compare": _same_period_compare(by_month, keys, first, last),
            "channels": _channel_shares(current),
            "time_bands": _time_bands(current),
            "top_payees": _top_payees(current, TOP_PAYEES),
            "flagged_total": flagged_total,
            "checked_excluded": checked,
        }

    def decisions(self) -> dict[str, Any]:
        return {"items": list(reversed(self.store.load_decisions()))}

    # ---- 성능 확인 ----
    def eval_run(self, body: Optional[EvalIn] = None) -> dict[str, Any]:
        """합성 데이터로 평가한다(기본: fused 한 가지 방식, seed 1부터 5개, 표준 시나리오).

        seed_start·seeds·intensity로 제출 보고서 검증 세트(seed 21~40, 표준·경계 변형)와 같은 설정을 고를 수 있다.
        응답의 seed_start·seed_end·intensity는 실제로 쓴 값, report_set은 인물 3명 × seed 21~40인지다
        (참이면 results가 docs/eval *_holdout.json·화면 eval_reference.json과 같은 설정으로 계산한 값이다).
        """
        req = body or EvalIn()
        personas = req.personas or list(PERSONA_KEYS)
        seeds = list(range(req.seed_start, req.seed_start + req.seeds))
        modes = list(dict.fromkeys(req.modes))
        run = self.evaluator or _default_evaluator
        started = _clock.perf_counter()
        try:
            results = run(personas, seeds, modes, intensity=req.intensity)
        except EvalUnavailable as exc:
            raise ServiceError(503, str(exc)) from exc
        return _plain({
            "personas": personas, "seeds": seeds, "seed_start": seeds[0], "seed_end": seeds[-1],
            "intensity": req.intensity, "report_set": _is_report_set(personas, seeds),
            "modes": modes, "results": results,
            "elapsed_sec": round(_clock.perf_counter() - started, 2), "note": SYNTHETIC_NOTE,
        })

    def eval_file(self) -> dict[str, Any]:
        """저장된 거래(모두 정상으로 가정)로 알림 비율 = 오탐 근사(metrics.evaluate_file)."""
        snap = self._analysis()
        if not snap.txns:
            raise ServiceError(400, "저장된 거래가 없어요. 내 거래에서 먼저 불러와 주세요.")
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
        w.writerow(["거래일시", "나감/들어옴", "방법", "상대", "금액(원)", "판단", "걸린 약속", "AI 점수(0~1)", "보내기 전 확인"])
        level_ko = {"none": "괜찮아요", "caution": "확인해요", "high": "꼭 확인해요"}
        for t, a in zip(snap.txns, snap.assessments):
            # 방법·걸린 약속은 화면과 같은 한국어 이름(C16·FN-08)
            w.writerow([t.ts.isoformat(sep=" ", timespec="minutes"), "나감" if t.direction == Direction.OUT else "들어옴",
                        CHANNEL_KO.get(t.channel.value, t.channel.value), _csv_text(t.counterparty), int(t.amount),
                        level_ko[a.level.value], _signal_names(a), f"{float(a.anomaly_score):.4f}",
                        "예" if _is_live(t.id) else ""])
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
        practice = sum(1 for t in snap.txns if _is_live(t.id))
        reviewed = self._reviewed_ids()
        reviewed_alerts = sum(1 for t, a in zip(snap.txns, snap.assessments)
                              if a.level != RiskLevel.NONE and t.id in reviewed)
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
                "reviewed_ok": reviewed_alerts,   # 걱정되는 거래 가운데 내가 한 거예요로 표시한 수(등급은 그대로)
            },
            "decisions": dict(Counter(str(d.get("decision", "")) for d in decisions)),
            "helper_notices": sum(1 for n in notices if n.get("kind") != "manual"),
            "manual_notices": sum(1 for n in notices if n.get("kind") == "manual"),
        }
        return {"filename": f"safepause-validation-{self.now():%Y%m%d}.json", "mime": "application/json",
                "text": json.dumps(payload, ensure_ascii=False, indent=2), "summary": payload}

    def export_summary(self) -> dict[str, Any]:
        """조력자·기관에게 보여 줄 한 장 요약(글, AUG-10). 이름·계좌번호 없이 집계만 담는다.

        달마다 나간 돈(보내기 전 확인 기록은 뺌), 걱정되는 거래 수(내가 한 거예요로 표시한 것은 따로), 걸린 약속별
        건수(화면과 같은 명사형 이름), AI만 먼저 알아챈 거래 수, 알림 기록 수. 한 줄에 한 문장.
        """
        snap = self._analysis()
        insight = self.insights()
        reviewed = self._reviewed_ids()
        pairs = list(zip(snap.txns, snap.assessments))
        open_levels = Counter(a.level.value for t, a in pairs if t.id not in reviewed)
        done = sum(1 for t, a in pairs if a.level != RiskLevel.NONE and t.id in reviewed)
        signals = Counter(name for _, a in pairs for name in _signal_names(a).split(", ") if name)
        ai_only = sum(1 for _, a in pairs if a.level != RiskLevel.NONE and not a.rule_hits)
        try:
            records = self.store.load_notices()
        except StoreError:
            records = []
        manual = sum(1 for r in records if r.get("kind") == "manual")
        labeled = any(t.label and t.label != NORMAL_LABEL for t in snap.txns)
        real = [t for t in snap.txns if not _is_live(t.id)]
        lines = ["SafePause 요약", f"만든 날: {self.now():%Y-%m-%d}"]
        if labeled:
            lines.append("연습용 가상 거래로 만든 요약이에요.")
        if real:
            lines.append(f"기간: {real[0].ts:%Y-%m-%d} ~ {real[-1].ts:%Y-%m-%d} (저장된 거래 {len(real):,}건)")
        lines += ["", "[달마다 나간 돈]"]
        lines += [f"{m['month']}: {m['out_total']:,}원 ({m['out_count']:,}건)" for m in insight["months"]] or [
            "저장된 거래가 없어요."]
        lines += ["", "[걱정되는 거래]",
                  f"꼭 확인할 거래 {open_levels.get('high', 0):,}건, 확인할 거래 {open_levels.get('caution', 0):,}건이에요."]
        if done:
            lines.append(f"본인이 직접 한 거래라고 표시한 {done:,}건은 빼고 셌어요.")
        if ai_only:
            lines.append(f"규칙에 걸리지 않았는데 AI가 걱정한 거래가 {ai_only:,}건 있어요.")
        if signals:
            lines += ["", "[걸린 약속별 건수]"]
        lines += [f"{name}: {n:,}건" for name, n in sorted(signals.items(), key=lambda kv: (-kv[1], kv[0]))]
        lines += ["", "[알림 기록]", f"직접 보낸 알림 기록 {manual:,}건, 적어 둔 기록 {len(records) - manual:,}건이에요.",
                  "", "이 요약에는 이름과 계좌번호를 넣지 않았어요."]
        text = "\n".join(lines) + "\n"
        return {"filename": f"safepause-summary-{self.now():%Y%m%d}.txt", "mime": "text/plain", "text": text,
                "note": "이름과 계좌번호 없이 거래 수와 금액 합계만 담았어요."}

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
