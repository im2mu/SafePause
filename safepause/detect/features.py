"""개인 기준 이력(History)과 이상탐지 입력 특징량.

시간 창 정의 (모두 평가 시각 as_of 기준, 누수 방지):
- 최근 창: (as_of - window_short_days, as_of]. 평가 대상 거래는 따로 더한다(대상 포함 집계).
- 평소 기준 구간: [max(as_of - baseline_days, 첫 거래 시각), as_of - window_short_days].
  최근 창을 빼서, 지금 일어나는 급증이 '평소' 값을 끌어올리지 않게 한다.
  구간 길이가 window_short_days 미만이면 평소 값을 알 수 없다고 보고 0을 돌려준다
  (이때 각 룰은 명세의 하한 기준을 쓴다).
- 이력 조회는 항상 as_of 이하 시각의 거래만 본다. 목록으로 받은 이력에서는 walk()와 같은
  순서 규칙으로 '대상보다 앞선 거래'만 남긴다. 대상이 목록 안에 있으면 대상보다 이른 시각의
  거래와, 같은 시각이면서 목록에서 대상보다 앞에 있는 거래만 쓴다(뒤의 같은 시각 거래는 누수).
  대상이 목록에 없으면 목록 전체가 호출자가 준 과거 이력이므로 대상 시각 이하의 거래를 모두
  쓴다(walk의 context와 같은 규칙: 같은 시각이면 context가 먼저).
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Optional, Union

import numpy as np

from safepause.config import Settings
from safepause.models import Channel, Direction, Transaction

# 이상탐지 모델 입력 순서 (바꾸면 학습된 모델과 맞지 않게 된다)
FEATURE_NAMES: list[str] = [
    "log_amount",              # log(1 + 금액)
    "amount_vs_p95",           # 금액 / 같은 채널·방향 평소 p95
    "hour_sin",                # 시각(24시간 주기) 사인
    "hour_cos",                # 시각(24시간 주기) 코사인
    "is_night",                # 심야(설정 기준) 여부
    "new_counterparty",        # 같은 채널·방향에서 처음 보는 상대
    "cp_count_7d",             # 같은 상대 최근 7일 건수(대상 포함)
    "cp_sum_7d_ratio",         # 같은 상대 7일 합계 / 같은 채널 평소 7일 합계(이체면 평소 7일 송금 합)
    "channel_count_7d_ratio",  # 같은 채널 7일 건수 / 평소 7일 건수 (1 미만은 1)
    "new_line",                # 통신요금이 청구된 적 없는 회선
    "is_out",                  # 출금 여부
]

# 값이 클수록 위험 쪽인 특징. 설명(explain)에서 평소보다 작은 쪽 편차는 이유로 내지 않는다.
UPPER_RISK_FEATURES: frozenset[str] = frozenset({
    "log_amount", "amount_vs_p95", "is_night", "new_counterparty", "cp_count_7d",
    "cp_sum_7d_ratio", "channel_count_7d_ratio", "new_line", "is_out",
})

MIN_P95_SAMPLES = 5         # p95 계산에 필요한 최소 표본 수 (미만이면 0 = 기준 없음)
AMOUNT_REF_FLOOR = 10_000   # 금액 비율 분모 하한(원). 기준이 없을 때 0으로 나누지 않기 위한 값
COUNT_REF_FLOOR = 1.0       # 건수 비율 분모 하한(7일당 건수)

_LINE_CHANNELS = (Channel.TELECOM_BILL, Channel.MICROPAY)

HistoryLike = Union[Sequence[Transaction], "History"]


def counterparty_key(txn: Transaction) -> str:
    """같은 상대 판별 키. 식별값(계좌·가맹점 ID)이 있으면 우선, 없으면 이름(공백 제거·소문자)."""
    cid = "".join(txn.counterparty_id.split()).lower()
    if cid:
        return "id:" + cid
    name = "".join(txn.counterparty.split()).lower()
    return "name:" + name if name else ""


def line_key(line_id: str) -> str:
    """회선 식별값 정규화(공백 제거)."""
    return "".join(line_id.split())


def _is_night_transfer(txn: Transaction, settings: Settings) -> bool:
    return (txn.channel == Channel.TRANSFER and txn.direction == Direction.OUT
            and settings.is_night(txn.ts.hour))


class _Series:
    """시간순 거래 묶음. 이분 탐색과 누적합으로 구간 건수·합계를 O(log n)에 구한다."""

    __slots__ = ("ts", "amounts", "cum", "txns")

    def __init__(self) -> None:
        self.ts: list[datetime] = []
        self.amounts: list[int] = []
        self.cum: list[int] = [0]
        self.txns: list[Transaction] = []

    def add(self, txn: Transaction) -> None:
        self.ts.append(txn.ts)
        self.amounts.append(txn.amount)
        self.cum.append(self.cum[-1] + txn.amount)
        self.txns.append(txn)

    def recent(self, as_of: datetime, days: int) -> tuple[int, int]:
        """(as_of - days, as_of] 구간의 인덱스 범위."""
        return bisect_right(self.ts, as_of - timedelta(days=days)), bisect_right(self.ts, as_of)

    def between(self, start: datetime, end: datetime) -> tuple[int, int]:
        """[start, end] 구간의 인덱스 범위."""
        return bisect_left(self.ts, start), bisect_right(self.ts, end)

    def total(self, i: int, j: int) -> int:
        return self.cum[j] - self.cum[i]


class History:
    """평가 대상 이전 거래로 만든 개인 기준 통계.

    시간순으로만 추가(append)할 수 있어 증분 계산에 쓸 수 있다. 조회 메서드의 `as_of`를 생략하면
    생성 시 지정한 as_of, 그것도 없으면 마지막 거래 시각을 기준으로 한다.
    """

    def __init__(self, txns: Iterable[Transaction] = (), settings: Settings | None = None,
                 as_of: datetime | None = None) -> None:
        self.settings: Settings = settings or Settings()
        self._as_of = as_of
        self._txns: list[Transaction] = []
        self._ids: set[str] = set()
        self._by_channel: dict[tuple[Channel, Direction], _Series] = {}
        self._by_cp: dict[tuple[Channel, Direction, str], _Series] = {}
        self._night_transfers = _Series()     # 심야 출금 이체
        self._new_merchant_cards = _Series()  # 그 가맹점과의 첫 카드 결제
        self._bills = _Series()               # 통신요금 청구(회선 있는 것)
        self._line_first: dict[str, datetime] = {}
        for txn in sorted(txns, key=lambda t: t.ts):  # 안정 정렬: 같은 시각은 입력 순서 유지
            self.append(txn)

    # ---- 추가 ----
    def append(self, txn: Transaction) -> None:
        """거래 1건을 이력 끝에 추가한다. 시간을 거슬러 추가하면 ValueError."""
        if self._txns and txn.ts < self._txns[-1].ts:
            raise ValueError("이력에는 시간순으로만 거래를 추가할 수 있습니다.")
        self._txns.append(txn)
        self._ids.add(txn.id)
        self._by_channel.setdefault((txn.channel, txn.direction), _Series()).add(txn)
        key = counterparty_key(txn)
        if key:
            cp = (txn.channel, txn.direction, key)
            series = self._by_cp.get(cp)
            if series is None:
                series = self._by_cp[cp] = _Series()
                if txn.channel == Channel.CARD and txn.direction == Direction.OUT:
                    self._new_merchant_cards.add(txn)
            series.add(txn)
        if _is_night_transfer(txn, self.settings):
            self._night_transfers.add(txn)
        line = line_key(txn.line_id)
        if txn.channel == Channel.TELECOM_BILL and txn.direction == Direction.OUT and line:
            self._bills.add(txn)
            self._line_first.setdefault(line, txn.ts)

    # ---- 기본 정보 ----
    def __len__(self) -> int:
        return len(self._txns)

    def __contains__(self, txn_id: object) -> bool:
        return txn_id in self._ids

    @property
    def transactions(self) -> tuple[Transaction, ...]:
        return tuple(self._txns)

    @property
    def start(self) -> Optional[datetime]:
        """이력의 첫 거래 시각(이력이 담은 기간의 시작). 없으면 None."""
        return self._txns[0].ts if self._txns else None

    @property
    def as_of(self) -> Optional[datetime]:
        if self._as_of is not None:
            return self._as_of
        return self._txns[-1].ts if self._txns else None

    def _resolve(self, as_of: datetime | None) -> Optional[datetime]:
        return as_of if as_of is not None else self.as_of

    def _days(self, days: int | None) -> int:
        return self.settings.window_short_days if days is None else days

    # ---- 평소 기준 ----
    def baseline_bounds(self, as_of: datetime | None = None
                        ) -> Optional[tuple[datetime, datetime, float]]:
        """평소 기준 구간 (시작, 끝, 길이[일]). 길이가 짧으면 None."""
        t = self._resolve(as_of)
        if t is None or not self._txns:
            return None
        s = self.settings
        start = max(t - timedelta(days=s.baseline_days), self._txns[0].ts)
        end = t - timedelta(days=s.window_short_days)
        span_days = (end - start).total_seconds() / 86400.0
        if span_days < s.window_short_days:
            return None
        return start, end, span_days

    def baseline_ready(self, as_of: datetime | None = None) -> bool:
        return self.baseline_bounds(as_of) is not None

    def _usual(self, channel: Channel, direction: Direction, as_of: datetime | None,
               by_amount: bool) -> float:
        bounds = self.baseline_bounds(as_of)
        series = self._by_channel.get((channel, direction))
        if bounds is None or series is None:
            return 0.0
        start, end, span_days = bounds
        i, j = series.between(start, end)
        value = series.total(i, j) if by_amount else (j - i)
        return value / span_days * self.settings.window_short_days

    def usual_7d_sum(self, channel: Channel, direction: Direction,
                     as_of: datetime | None = None) -> float:
        """평소 7일(window_short_days)당 금액 합계. 기준이 없으면 0."""
        return self._usual(channel, direction, as_of, by_amount=True)

    def usual_7d_count(self, channel: Channel, direction: Direction,
                       as_of: datetime | None = None) -> float:
        """평소 7일(window_short_days)당 건수. 기준이 없으면 0."""
        return self._usual(channel, direction, as_of, by_amount=False)

    def amount_p95(self, channel: Channel, direction: Direction,
                   as_of: datetime | None = None) -> float:
        """평소 기준 구간의 금액 95백분위. 표본이 MIN_P95_SAMPLES 미만이면 0."""
        t = self._resolve(as_of)
        series = self._by_channel.get((channel, direction))
        if t is None or series is None:
            return 0.0
        s = self.settings
        i, j = series.between(t - timedelta(days=s.baseline_days),
                              t - timedelta(days=s.window_short_days))
        if j - i < MIN_P95_SAMPLES:
            return 0.0
        return float(np.percentile(series.amounts[i:j], 95))

    # ---- 최근 창 ----
    def _recent(self, series: _Series | None, as_of: datetime | None,
                days: int | None) -> list[Transaction]:
        t = self._resolve(as_of)
        if series is None or t is None:
            return []
        i, j = series.recent(t, self._days(days))
        return series.txns[i:j]

    def _recent_stats(self, series: _Series | None, as_of: datetime | None,
                      days: int | None) -> tuple[int, int]:
        t = self._resolve(as_of)
        if series is None or t is None:
            return 0, 0
        i, j = series.recent(t, self._days(days))
        return j - i, series.total(i, j)

    def channel_recent(self, channel: Channel, direction: Direction,
                       as_of: datetime | None = None, days: int | None = None) -> list[Transaction]:
        return self._recent(self._by_channel.get((channel, direction)), as_of, days)

    def channel_window(self, channel: Channel, direction: Direction,
                       as_of: datetime | None = None, days: int | None = None) -> tuple[int, int]:
        """최근 창 (건수, 합계)."""
        return self._recent_stats(self._by_channel.get((channel, direction)), as_of, days)

    def counterparty_recent(self, channel: Channel, direction: Direction, key: str,
                            as_of: datetime | None = None, days: int | None = None
                            ) -> list[Transaction]:
        return self._recent(self._by_cp.get((channel, direction, key)), as_of, days)

    def counterparty_window(self, channel: Channel, direction: Direction, key: str,
                            as_of: datetime | None = None, days: int | None = None
                            ) -> tuple[int, int]:
        """같은 상대 최근 창 (건수, 합계)."""
        return self._recent_stats(self._by_cp.get((channel, direction, key)), as_of, days)

    def night_transfers_recent(self, as_of: datetime | None = None,
                               days: int | None = None) -> list[Transaction]:
        return self._recent(self._night_transfers, as_of, days)

    def new_merchant_cards_recent(self, as_of: datetime | None = None,
                                  days: int | None = None) -> list[Transaction]:
        """최근 창 안에서 '그 가맹점과의 첫 카드 결제'였던 거래."""
        return self._recent(self._new_merchant_cards, as_of, days)

    def bills_recent(self, as_of: datetime | None = None,
                     days: int | None = None) -> list[Transaction]:
        return self._recent(self._bills, as_of, days)

    # ---- 처음 보는 상대·회선 ----
    def first_seen(self, channel: Channel, direction: Direction, key: str,
                   as_of: datetime | None = None) -> Optional[datetime]:
        """해당 상대와의 첫 거래 시각. as_of 이후에만 있거나 없으면 None."""
        series = self._by_cp.get((channel, direction, key))
        t = self._resolve(as_of)
        if series is None or t is None or series.ts[0] > t:
            return None
        return series.ts[0]

    def is_known(self, channel: Channel, direction: Direction, key: str,
                 as_of: datetime | None = None) -> bool:
        return self.first_seen(channel, direction, key, as_of) is not None

    def line_first_seen(self, line_id: str, as_of: datetime | None = None) -> Optional[datetime]:
        """해당 회선의 첫 통신요금 청구 시각. 없으면 None."""
        first = self._line_first.get(line_key(line_id))
        t = self._resolve(as_of)
        if first is None or t is None or first > t:
            return None
        return first

    def line_known(self, line_id: str, as_of: datetime | None = None) -> bool:
        return self.line_first_seen(line_id, as_of) is not None

    def first_line(self, as_of: datetime | None = None) -> Optional[str]:
        """가장 먼저 통신요금이 청구된 회선(평소 회선으로 본다). 없으면 None."""
        t = self._resolve(as_of)
        known = [(first, line) for line, first in self._line_first.items()
                 if t is not None and first <= t]
        return min(known)[1] if known else None

    def _known_keys(self, channel: Channel) -> set[str]:
        t = self.as_of
        return {key for (ch, d, key), s in self._by_cp.items()
                if ch == channel and d == Direction.OUT and t is not None and s.ts[0] <= t}

    # ---- 명세 §5 요약 속성 (as_of 기준) ----
    @property
    def known_payees(self) -> set[str]:
        """이체를 보낸 적 있는 상대 키."""
        return self._known_keys(Channel.TRANSFER)

    @property
    def known_merchants(self) -> set[str]:
        """카드 결제한 적 있는 가맹점 키."""
        return self._known_keys(Channel.CARD)

    @property
    def known_lines(self) -> set[str]:
        """통신요금이 청구된 적 있는 회선."""
        t = self.as_of
        return {line for line, first in self._line_first.items() if t is not None and first <= t}

    @property
    def card_amount_p95(self) -> float:
        return self.amount_p95(Channel.CARD, Direction.OUT)

    @property
    def transfer_7d_mean(self) -> float:
        """평소 7일 송금 합계(원)."""
        return self.usual_7d_sum(Channel.TRANSFER, Direction.OUT)

    @property
    def micropay_7d_mean(self) -> float:
        """평소 7일 소액결제 건수."""
        return self.usual_7d_count(Channel.MICROPAY, Direction.OUT)


def as_history(txn: Transaction, history_before: HistoryLike,
               settings: Settings | None = None) -> History:
    """평가용 History 준비. 목록이면 대상보다 앞선 거래만 남긴다(누수 방지).

    대상이 목록 안에 있으면 walk()·assess_many와 같게, 같은 시각 거래는 목록에서 대상보다 앞에
    있는 것만 이력으로 본다. 대상이 목록에 없으면 대상 시각 이하의 거래를 모두 쓴다
    (walk의 context 규칙과 같음). 대상 시각보다 뒤의 거래는 어느 경우에도 쓰지 않는다.
    History 객체를 그대로 받으면 그 객체의 settings를 쓰며, 대상 거래가 들어 있으면 ValueError.
    """
    if isinstance(history_before, History):
        if txn.id in history_before:
            raise ValueError(f"평가 대상 거래({txn.id})가 이력에 들어 있습니다.")
        return history_before
    items = list(history_before)
    position = next((k for k, t in enumerate(items) if t.id == txn.id), None)
    past = [t for k, t in enumerate(items)
            if t.id != txn.id and (t.ts < txn.ts
                                   or (t.ts == txn.ts and (position is None or k < position)))]
    return History(past, settings, as_of=txn.ts)


def walk(txns: Sequence[Transaction], settings: Settings | None = None,
         context: Iterable[Transaction] = ()) -> Iterator[tuple[int, Transaction, History]]:
    """시간순으로 (입력 인덱스, 거래, 그 직전까지의 이력)을 차례로 돌려준다.

    context는 평가하지 않고 이력에만 쓰는 과거 거래(같은 id가 txns에 있으면 무시).
    돌려받은 History는 다음 반복에서 갱신되므로 반복 안에서만 사용한다.
    """
    eval_ids = {t.id for t in txns}
    events: list[tuple[datetime, int, int, Transaction]] = [
        (t.ts, 0, k, t) for k, t in enumerate(context) if t.id not in eval_ids
    ]
    events.extend((t.ts, 1, i, t) for i, t in enumerate(txns))
    events.sort(key=lambda e: (e[0], e[1], e[2]))  # 같은 시각이면 context 먼저, 그다음 입력 순서
    hist = History(settings=settings)
    for _, kind, idx, txn in events:
        if kind == 1:
            yield idx, txn, hist
        hist.append(txn)


def compute_features(txn: Transaction, hist: History,
                     as_of: datetime | None = None) -> dict[str, float]:
    """이력(hist)과 평가 시각(as_of, 기본 txn.ts)으로 대상 거래의 특징량을 계산한다."""
    t = as_of if as_of is not None else txn.ts
    ch, dr = txn.channel, txn.direction
    key = counterparty_key(txn)

    ref_amount = max(hist.amount_p95(ch, dr, t), AMOUNT_REF_FLOOR)
    hour = txn.ts.hour + txn.ts.minute / 60.0
    angle = 2.0 * math.pi * hour / 24.0

    if key:
        cp_count, cp_sum = hist.counterparty_window(ch, dr, key, t)
        new_cp = 0.0 if hist.is_known(ch, dr, key, t) else 1.0
        cp_count_7d = float(cp_count + 1)
        cp_ratio = (cp_sum + txn.amount) / max(hist.usual_7d_sum(ch, dr, t), AMOUNT_REF_FLOOR)
    else:  # 상대를 알 수 없는 거래(예: 현금 인출)
        new_cp, cp_count_7d, cp_ratio = 0.0, 0.0, 0.0

    ch_count, _ = hist.channel_window(ch, dr, t)
    ch_ratio = (ch_count + 1) / max(hist.usual_7d_count(ch, dr, t), COUNT_REF_FLOOR)
    ch_ratio = max(ch_ratio, 1.0)  # 평소보다 적게 쓴 주는 위험 신호가 아니므로 1로 본다

    line = line_key(txn.line_id)
    new_line = 1.0 if (ch in _LINE_CHANNELS and line and not hist.line_known(line, t)) else 0.0

    return {
        "log_amount": math.log1p(max(txn.amount, 0)),
        "amount_vs_p95": txn.amount / ref_amount,
        "hour_sin": math.sin(angle),
        "hour_cos": math.cos(angle),
        "is_night": 1.0 if hist.settings.is_night(txn.ts.hour) else 0.0,
        "new_counterparty": new_cp,
        "cp_count_7d": cp_count_7d,
        "cp_sum_7d_ratio": cp_ratio,
        "channel_count_7d_ratio": ch_ratio,
        "new_line": new_line,
        "is_out": 1.0 if dr == Direction.OUT else 0.0,
    }


def txn_features(txn: Transaction, history_before: HistoryLike,
                 settings: Settings | None = None) -> dict[str, float]:
    """이상탐지 모델 입력 특징량. history_before에서 txn.ts 이후 거래는 쓰지 않는다."""
    hist = as_history(txn, history_before, settings)
    return compute_features(txn, hist, txn.ts)


def iter_features(txns: Sequence[Transaction], settings: Settings | None = None,
                  context: Iterable[Transaction] = ()
                  ) -> Iterator[tuple[int, Transaction, dict[str, float]]]:
    """각 거래를 그 이전 이력만으로 특징화(증분 계산). (입력 인덱스, 거래, 특징량)."""
    for idx, txn, hist in walk(txns, settings, context):
        yield idx, txn, compute_features(txn, hist, txn.ts)


def feature_vector(feats: Mapping[str, float]) -> list[float]:
    """FEATURE_NAMES 순서의 숫자 목록."""
    return [float(feats[name]) for name in FEATURE_NAMES]
