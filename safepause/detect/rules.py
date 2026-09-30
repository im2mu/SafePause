"""제안서 S19의 착취 시그널 5종 룰 필터.

모든 룰은 평가 대상 거래 시점(as_of) 기준, 대상 거래를 포함한 최근 창에서 판단한다.
출금(Direction.OUT) 거래만 대상이다. 기준값은 SPEC.md §5를 옮긴 것이다
(PAYEE_SURGE의 금액 하한·HIGH 조건, MULTI_LINE_TELECOM 평소 회선 제외, '처음인지 알 수 없음'
처리는 오탐 확인 뒤 SPEC에 더한 보완이다).

'처음인지 알 수 없음'(evidence.newness_unknown): 상대·가게·회선을 처음 본 때가 이력 첫 거래 뒤
window_long_days(30일) 안이면, 이력이 그 전을 담지 않아 정말 처음인지 알 수 없다(예: 1개월치
CSV의 늘 가던 병원, 매달 내는 인터넷 요금). 이때는 CAUTION까지만 내고, 카드도 '처음'이라고
말하지 않는다. 엔진도 이 근거만으로는 이상 점수로 HIGH를 올리지 않는다(engine.combine_level).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Optional

from safepause.config import Settings
from safepause.detect.features import History, HistoryLike, as_history, counterparty_key, line_key
from safepause.models import Channel, Direction, RiskLevel, SignalCode, SignalHit, Transaction

# 심야 반복 이체
NIGHT_HIGH_COUNT = 3
NIGHT_CAUTION_COUNT = 2
# 특정 계좌 앞 송금 급증
PAYEE_MIN_COUNT = 3
PAYEE_MIN_RATIO = 3.0
PAYEE_FALLBACK_SUM = 300_000      # 금액 경로의 7일 합계 하한(원). 평소 송금 합계가 0이면 이것만 본다
PAYEE_HIGH_COUNT = 4
PAYEE_HIGH_RATIO = 5.0
PAYEE_RATIO_HIGH_MIN_COUNT = 2    # 배율만으로 HIGH가 되려면 7일 건수(대상 포함)가 이 이상
# 통신 소액결제 급증
MICROPAY_MIN_COUNT = 5
MICROPAY_RATIO = 3.0
MICROPAY_HIGH_COUNT = 8
# 신규 가맹점 고액 결제
MERCHANT_P95_MULT = 3.0
MERCHANT_MIN_AMOUNT = 100_000     # 고액 판단 하한(원)
MERCHANT_HIGH_COUNT = 2
# 단기간 다회선 통신요금 청구
LINE_MIN_DISTINCT = 2
LINE_HIGH_NEW = 2

RuleFn = Callable[[Transaction, History, datetime], Optional[SignalHit]]


def _is_out(txn: Transaction, channel: Channel) -> bool:
    return txn.channel == channel and txn.direction == Direction.OUT


def _newness_unknown(hist: History, first: datetime) -> bool:
    """처음 본 때(first)가 이력 시작 뒤 window_long_days 안이면 True(그 전 이력이 없어 알 수 없음).

    이력이 비어 있으면(평가 대상이 첫 거래) 알 수 없다고 본다.
    """
    start = hist.start
    return start is None or first < start + timedelta(days=hist.settings.window_long_days)


def _hit(code: SignalCode, severity: RiskLevel, evidence: dict[str, Any],
         prior: list[Transaction], txn: Transaction) -> SignalHit:
    return SignalHit(code=code, severity=severity, evidence=evidence,
                     related_txn_ids=[p.id for p in prior] + [txn.id])


def night_repeat_transfer(txn: Transaction, hist: History, as_of: datetime) -> Optional[SignalHit]:
    """심야 출금 이체이고 최근 7일 심야 이체(대상 포함) 3건 이상 HIGH, 2건 CAUTION."""
    s = hist.settings
    if not (_is_out(txn, Channel.TRANSFER) and s.is_night(txn.ts.hour)):
        return None
    prior = hist.night_transfers_recent(as_of, s.window_short_days)
    count = len(prior) + 1
    if count >= NIGHT_HIGH_COUNT:
        severity = RiskLevel.HIGH
    elif count >= NIGHT_CAUTION_COUNT:
        severity = RiskLevel.CAUTION
    else:
        return None
    evidence = {
        "count_7d": count,
        "window_days": s.window_short_days,
        "night_start_hour": s.night_start_hour,
        "night_end_hour": s.night_end_hour,
        "hour": txn.ts.hour,
        "amount": txn.amount,
        "sum_7d": sum(p.amount for p in prior) + txn.amount,
    }
    return _hit(SignalCode.NIGHT_REPEAT_TRANSFER, severity, evidence, prior, txn)


def payee_surge(txn: Transaction, hist: History, as_of: datetime) -> Optional[SignalHit]:
    """첫 거래 30일 이내(또는 처음)인 상대에게 7일 3건 이상, 또는 7일 합계가 큰 경우.

    금액 경로: 7일 합계 ≥ 30만 원이고 (평소 7일 송금 합이 있으면) 그 3배 이상.
    HIGH: 7일 합계 ≥ 30만 원이면서 (건수 ≥ 4, 또는 배율 ≥ 5이고 건수 ≥ 2).
    (평소 송금이 적은 사람의 소액 송금이 건수·배율만으로 고위험·조력자 알림이 되지 않게 한다, S38)

    이력 시작 뒤 30일 안에 처음 보인 상대는 이력이 그 전을 담지 않아 '새 상대'인지 알 수 없다
    (예: 1개월치 CSV의 늘 보내던 가족). 이때는 금액 경로로만 판단하고 CAUTION까지만 낸다.
    """
    s = hist.settings
    if not _is_out(txn, Channel.TRANSFER):
        return None
    key = counterparty_key(txn)
    if not key:
        return None
    first = hist.first_seen(Channel.TRANSFER, Direction.OUT, key, as_of)
    if first is not None and first < as_of - timedelta(days=s.window_long_days):
        return None  # 오래 알던 상대
    newness_unknown = _newness_unknown(hist, first if first is not None else as_of)
    prior = hist.counterparty_recent(Channel.TRANSFER, Direction.OUT, key, as_of, s.window_short_days)
    count = len(prior) + 1
    total = sum(p.amount for p in prior) + txn.amount
    usual = hist.usual_7d_sum(Channel.TRANSFER, Direction.OUT, as_of)
    ratio: Optional[float] = total / usual if usual > 0 else None
    big_sum = total >= PAYEE_FALLBACK_SUM
    by_amount = big_sum and (ratio is None or ratio >= PAYEE_MIN_RATIO)
    by_count = count >= PAYEE_MIN_COUNT and not newness_unknown
    if not (by_count or by_amount):
        return None
    high = big_sum and not newness_unknown and (
        count >= PAYEE_HIGH_COUNT
        or (ratio is not None and ratio >= PAYEE_HIGH_RATIO and count >= PAYEE_RATIO_HIGH_MIN_COUNT))
    evidence = {
        "count_7d": count,
        "sum_7d": total,
        "min_sum_7d": PAYEE_FALLBACK_SUM,
        "baseline_7d_sum": round(usual),
        "ratio": round(ratio, 2) if ratio is not None else None,
        "first_seen_days_ago": (round((as_of - first).total_seconds() / 86400.0, 1)
                                if first is not None else None),
        "newness_unknown": newness_unknown,   # 이력이 짧아 새 상대인지 알 수 없음(최대 CAUTION)
        "window_days": s.window_short_days,
        "amount": txn.amount,
        "counterparty": txn.counterparty,
    }
    return _hit(SignalCode.PAYEE_SURGE, RiskLevel.HIGH if high else RiskLevel.CAUTION,
                evidence, prior, txn)


def micropay_surge(txn: Transaction, hist: History, as_of: datetime) -> Optional[SignalHit]:
    """소액결제 7일 건수(대상 포함) ≥ max(5, 평소 7일 평균×3). 8건 이상이면 HIGH."""
    s = hist.settings
    if not _is_out(txn, Channel.MICROPAY):
        return None
    prior = hist.channel_recent(Channel.MICROPAY, Direction.OUT, as_of, s.window_short_days)
    count = len(prior) + 1
    usual = hist.usual_7d_count(Channel.MICROPAY, Direction.OUT, as_of)
    threshold = max(float(MICROPAY_MIN_COUNT), usual * MICROPAY_RATIO)
    if count < threshold:
        return None
    evidence = {
        "count_7d": count,
        "baseline_7d": round(usual, 2),
        "threshold": round(threshold, 2),
        "sum_7d": sum(p.amount for p in prior) + txn.amount,
        "window_days": s.window_short_days,
        "amount": txn.amount,
    }
    severity = RiskLevel.HIGH if count >= MICROPAY_HIGH_COUNT else RiskLevel.CAUTION
    return _hit(SignalCode.MICROPAY_SURGE, severity, evidence, prior, txn)


def new_merchant_high_value(txn: Transaction, hist: History, as_of: datetime
                            ) -> Optional[SignalHit]:
    """처음 보는 가맹점 카드 결제가 max(개인 카드 p95×3, 10만 원) 이상.

    최근 7일 같은 조건 거래(대상 포함) 2건 이상이면 HIGH. 과거 거래의 '고액' 여부는
    현재 기준 금액으로 다시 판단한다. 이력 시작 뒤 30일 안이면 처음 가는 가게인지 알 수 없어
    (newness_unknown) CAUTION까지만 내고, 그런 과거 거래는 '새 가게' 건수에 넣지 않는다.
    """
    s = hist.settings
    if not _is_out(txn, Channel.CARD):
        return None
    key = counterparty_key(txn)
    if not key or hist.is_known(Channel.CARD, Direction.OUT, key, as_of):
        return None
    p95 = hist.amount_p95(Channel.CARD, Direction.OUT, as_of)
    threshold = max(p95 * MERCHANT_P95_MULT, float(MERCHANT_MIN_AMOUNT))
    if txn.amount < threshold:
        return None
    newness_unknown = _newness_unknown(hist, as_of)
    prior = [p for p in hist.new_merchant_cards_recent(as_of, s.window_short_days)
             if p.amount >= threshold and not _newness_unknown(hist, p.ts)]
    count = len(prior) + 1
    evidence = {
        "count_7d": count,
        "amount": txn.amount,
        "threshold": round(threshold),
        "card_p95": round(p95),
        "ratio_vs_p95": round(txn.amount / p95, 2) if p95 > 0 else None,
        "newness_unknown": newness_unknown,   # 이력이 짧아 처음 가는 가게인지 알 수 없음(최대 CAUTION)
        "window_days": s.window_short_days,
        "merchant": txn.counterparty,
    }
    high = count >= MERCHANT_HIGH_COUNT and not newness_unknown
    return _hit(SignalCode.NEW_MERCHANT_HIGH_VALUE, RiskLevel.HIGH if high else RiskLevel.CAUTION,
                evidence, prior, txn)


def multi_line_telecom(txn: Transaction, hist: History, as_of: datetime) -> Optional[SignalHit]:
    """처음 보는 회선의 통신요금이고 최근 30일 서로 다른 회선 청구 2개 이상.

    '새 회선' = 첫 청구가 최근 30일 안에 있는 회선. 다음 회선은 새 회선으로 세지 않는다.
    - 이력에서 가장 먼저 청구된 회선: 당사자의 평소 회선으로 본다.
    - 첫 청구가 이력 시작 뒤 30일 안인 회선: 이력이 그 전 달을 담지 않아 새 회선인지 알 수 없다
      (1개월치 CSV의 휴대폰·인터넷·태블릿 요금 등). 대상 회선이 이런 경우면 newness_unknown.
    새 회선 2개 이상 HIGH, 그 밖 CAUTION(대상의 새 회선 여부를 알 수 없으면 늘 CAUTION).
    """
    s = hist.settings
    line = line_key(txn.line_id)
    if not (_is_out(txn, Channel.TELECOM_BILL) and line):
        return None
    if hist.line_known(line, as_of):
        return None
    prior = hist.bills_recent(as_of, s.window_long_days)
    lines = {line_key(p.line_id) for p in prior} | {line}
    if len(lines) < LINE_MIN_DISTINCT:
        return None
    window_start = as_of - timedelta(days=s.window_long_days)
    usual_line = hist.first_line(as_of)
    new_lines: set[str] = set()
    unknown_lines: set[str] = set()
    for ln in lines:
        if ln == usual_line:
            continue
        first = hist.line_first_seen(ln, as_of) or as_of   # 대상 회선은 지금이 첫 청구
        if first <= window_start:
            continue                                        # 30일보다 전부터 내던 회선
        (unknown_lines if _newness_unknown(hist, first) else new_lines).add(ln)
    newness_unknown = line in unknown_lines
    evidence = {
        "distinct_lines_30d": len(lines),
        "new_lines_30d": len(new_lines),
        "unknown_lines_30d": len(unknown_lines),   # 이력이 짧아 새 회선인지 알 수 없어 세지 않은 회선
        "newness_unknown": newness_unknown,
        "usual_line": usual_line,
        "window_days": s.window_long_days,
        "line_id": txn.line_id,
        "amount": txn.amount,
    }
    high = len(new_lines) >= LINE_HIGH_NEW and not newness_unknown
    related = [p for p in prior if line_key(p.line_id) in new_lines]
    return _hit(SignalCode.MULTI_LINE_TELECOM, RiskLevel.HIGH if high else RiskLevel.CAUTION,
                evidence, related, txn)


# 평가 순서 = SignalCode 정의 순서
RULES: tuple[RuleFn, ...] = (
    night_repeat_transfer,
    payee_surge,
    micropay_surge,
    new_merchant_high_value,
    multi_line_telecom,
)


def evaluate_rules_on(txn: Transaction, hist: History,
                      as_of: datetime | None = None) -> list[SignalHit]:
    """준비된 이력(hist)으로 5개 룰을 평가한다. as_of 기본값은 txn.ts."""
    t = as_of if as_of is not None else txn.ts
    hits: list[SignalHit] = []
    for rule in RULES:
        hit = rule(txn, hist, t)
        if hit is not None:
            hits.append(hit)
    return hits


def evaluate_rules(txn: Transaction, history_before: HistoryLike,
                   settings: Settings | None = None) -> list[SignalHit]:
    """대상 거래 시점 기준 5개 시그널 룰 평가. history_before의 txn.ts 이후 거래는 쓰지 않는다."""
    hist = as_history(txn, history_before, settings)
    return evaluate_rules_on(txn, hist, txn.ts)
