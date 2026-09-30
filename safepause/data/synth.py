"""합성 거래 데이터 생성기.

주의: 공개 통계로 보정한 데이터가 아니다. 제안서 S19의 착취 시그널 5종을 재현하려고 설계한
가정 기반 시나리오다. 인물 설정(소득·결제 빈도·금액)과 상대 이름·계좌·회선은 모두 가상의 값이다.

- ``generate_history``: 정상 거래만 만든다(label="normal"). 현실적인 잡음(가끔 새 가게 소액,
  가끔 밤 결제, 드문 새 상대 이체, 드문 큰 결제)을 넣어 오탐 평가가 의미 있게 한다.
- ``inject_scenario``: 원본을 바꾸지 않고 시나리오 거래를 더한 새 리스트를 돌려준다.
  ``intensity="subtle"``은 룰 기준에 못 미치거나 겨우 닿는 경계 변형이다(SPEC §3 [추가 r4]).
- ``make_dataset``: 정상 이력 + 시나리오(각 1회, 마지막 30일 안).
- 같은 seed면 같은 결과가 나온다(``numpy.random.default_rng``).
"""
from __future__ import annotations

import calendar
import csv
import math
import re
import zlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence

import numpy as np

from safepause.models import Channel, Direction, SignalCode, Transaction

STANDARD_COLUMNS: list[str] = [
    "id", "ts", "amount", "direction", "channel",
    "counterparty", "counterparty_id", "line_id", "memo", "label",
]
REQUIRED_STANDARD_COLUMNS: tuple[str, ...] = ("id", "ts", "amount", "direction", "channel")
AMOUNT_LIMIT = 1e15  # 이 이상 금액(1,000조 원)은 읽지 않음(계산 넘침 방지)
MIN_YEAR, MAX_YEAR = 1900, 2100   # 이 밖의 날짜(예: 빈 날짜 대용 0001-01-01)는 거래로 받지 않음
NORMAL_LABEL = "normal"
DEFAULT_START = date(2026, 3, 2)   # 가상 기간 시작일(결정론을 위해 고정)
SCENARIO_WINDOW_DAYS = 30          # 시나리오는 데이터 마지막 30일 안에 넣는다
ALL_SCENARIOS: tuple[SignalCode, ...] = tuple(SignalCode)

# 시나리오 하나가 차지하는 최대 일수(시작일 포함). make_dataset 배치에 쓴다.
SCENARIO_SPAN_DAYS: dict[SignalCode, int] = {
    SignalCode.NIGHT_REPEAT_TRANSFER: 5,
    SignalCode.PAYEE_SURGE: 7,
    SignalCode.MICROPAY_SURGE: 7,
    SignalCode.NEW_MERCHANT_HIGH_VALUE: 7,
    SignalCode.MULTI_LINE_TELECOM: 14,
}

# 시나리오 강도. "standard"는 룰 기준을 넉넉히 넘고, "subtle"은 룰 기준에 못 미치거나 겨우 닿는
# 경계 변형이다(SPEC §3 [추가 r4], 결과를 보기 전에 정한 사전 등록 정의).
INTENSITIES: tuple[str, ...] = ("standard", "subtle")
SUBTLE_SPAN_DAYS: dict[SignalCode, int] = {
    SignalCode.NIGHT_REPEAT_TRANSFER: 7,
    SignalCode.PAYEE_SURGE: 7,
    SignalCode.MICROPAY_SURGE: 7,
    SignalCode.NEW_MERCHANT_HIGH_VALUE: 1,
    SignalCode.MULTI_LINE_TELECOM: 1,
}


def check_intensity(intensity: str) -> str:
    """시나리오 강도 확인. "standard" 또는 "subtle"이 아니면 ValueError."""
    if intensity not in INTENSITIES:
        raise ValueError(f"intensity는 {', '.join(INTENSITIES)} 중 하나여야 해요: {intensity!r}")
    return intensity


@dataclass(frozen=True)
class Persona:
    """가상 인물 설정. 모든 값은 설명을 위한 가정이다."""

    name: str
    monthly_income: int                    # 월 입금액(원)
    income_day: int                        # 입금일(달의 날짜보다 크면 말일)
    daily_card_mean: int                   # 평소 카드결제 1건 평균 금액(원)
    card_count_per_week: float             # 주당 카드결제 건수(평균)
    known_payees: list[tuple[str, str]]    # (이름, 계좌) 평소 송금 상대
    known_merchants: list[tuple[str, str]] # (가맹점명, 가맹점ID) 단골 가게
    telecom_line: str                      # 본인 회선(마스킹)
    telecom_bill: int                      # 월 통신요금(원)
    micropay_per_month: float              # 월 소액결제 건수(평균)
    active_hours: tuple[int, int] = (8, 22)  # 주 활동 시간 [시작, 끝)
    # --- 이하 추가 가정(기본값 있음) ---
    income_source: tuple[str, str] = ("급여", "PAY-0001")
    income_jitter: float = 0.0             # 월 입금액 변동 폭(비율)
    transfers_per_month: float = 3.0       # 알려진 상대 송금 건수(월 평균)
    transfer_mean: int = 50_000            # 알려진 상대 송금 1건 평균(원)
    atm_per_month: float = 2.0
    telecom_carrier: tuple[str, str] = ("가나통신", "TEL-GANA")
    bill_day: int = 25
    new_merchant_share: float = 0.06       # 카드결제 중 처음 가는 가게 소액 비율
    night_card_per_month: float = 1.5      # 밤(23~01시) 카드결제 건수(월 평균)
    night_transfer_per_month: float = 0.3  # 밤(23~00시) 알려진 상대 송금(월 평균)
    new_payee_per_month: float = 0.5       # 처음 보는 상대 1회 소액 송금(월 평균)
    big_new_merchant_per_month: float = 0.2  # 처음 가는 가게 조금 큰 결제(월 평균)


PERSONAS: dict[str, Persona] = {
    "worker": Persona(
        name="가상 근로자(급여 근로)",
        monthly_income=1_900_000,
        income_day=10,
        daily_card_mean=11_000,
        card_count_per_week=9,
        known_payees=[
            ("엄마", "900-0101-100001"),
            ("동생", "900-0101-100002"),
            ("모임 회비", "900-0101-100003"),
        ],
        known_merchants=[
            ("동네편의점", "M-1001"), ("회사 구내식당", "M-1002"), ("동네마트", "M-1003"),
            ("분식집", "M-1004"), ("카페", "M-1005"), ("약국", "M-1006"),
        ],
        telecom_line="010-****-1234",
        telecom_bill=55_000,
        micropay_per_month=1.0,
        income_source=("가상회사 급여", "PAY-1001"),
        income_jitter=0.05,
        transfers_per_month=4.0,
        transfer_mean=50_000,
        atm_per_month=1.5,
        bill_day=25,
        night_card_per_month=2.0,
        night_transfer_per_month=0.3,
        new_payee_per_month=0.5,
        big_new_merchant_per_month=0.3,
    ),
    "benefit": Persona(
        name="가상 복지급여 수급자",
        monthly_income=900_000,
        income_day=20,
        daily_card_mean=8_000,
        card_count_per_week=7,
        known_payees=[
            ("엄마", "900-0202-200001"),
            ("활동 모임 회비", "900-0202-200002"),
        ],
        known_merchants=[
            ("동네편의점", "M-2001"), ("동네마트", "M-2002"), ("복지관 식당", "M-2003"),
            ("약국", "M-2004"), ("빵집", "M-2005"),
        ],
        telecom_line="010-****-5678",
        telecom_bill=33_000,
        micropay_per_month=1.0,
        income_source=("복지급여", "GOV-2001"),
        transfers_per_month=2.0,
        transfer_mean=40_000,
        atm_per_month=2.0,
        bill_day=15,
        night_card_per_month=1.0,
        night_transfer_per_month=0.2,
        new_payee_per_month=0.3,
        big_new_merchant_per_month=0.15,
    ),
    "student": Persona(
        name="가상 학생(용돈)",
        monthly_income=300_000,
        income_day=1,
        daily_card_mean=6_000,
        card_count_per_week=8,
        known_payees=[
            ("아빠", "900-0303-300001"),
            ("친구 민수", "900-0303-300002"),
            ("친구 지우", "900-0303-300003"),
        ],
        known_merchants=[
            ("학교 매점", "M-3001"), ("동네편의점", "M-3002"), ("분식집", "M-3003"),
            ("문구점", "M-3004"), ("PC방", "M-3005"),
        ],
        telecom_line="010-****-9012",
        telecom_bill=25_000,
        micropay_per_month=3.0,
        income_source=("아빠 용돈", "900-0303-300001"),
        transfers_per_month=3.0,
        transfer_mean=15_000,
        atm_per_month=1.0,
        bill_day=5,
        night_card_per_month=2.5,
        night_transfer_per_month=0.3,
        new_payee_per_month=0.6,
        big_new_merchant_per_month=0.1,
    ),
}

# 가끔 들르는 가게(처음 보는 가맹점 소액 잡음). 이름·ID는 가상.
_OCCASIONAL_MERCHANTS: list[tuple[str, str]] = [
    (name, f"M-8{i:03d}") for i, name in enumerate([
        "국밥집", "꽃집", "영화관", "서점", "옷가게", "신발가게", "생활용품점", "치킨집",
        "미용실", "세탁소", "김밥집", "중국집", "떡집", "빵집 2호점", "편의점 2호점",
    ], start=1)
]
# 정상 소액결제 상대(시나리오와 일부 겹쳐 이름만으로는 구분되지 않게 함)
_NORMAL_MICROPAY: list[tuple[str, str]] = [
    ("게임아이템", "MP-GAME"), ("음원 이용료", "MP-MUSIC"), ("웹툰 이용료", "MP-TOON"),
]
_SCENARIO_MICROPAY: list[tuple[str, str]] = [
    ("모바일상품권", "MP-GIFT"), ("게임아이템", "MP-GAME"), ("콘텐츠이용료", "MP-CONT"),
]
_HIGH_VALUE_MERCHANTS: list[tuple[str, str]] = [
    ("상품권 판매점", "M-9001"), ("전자제품 매장", "M-9002"), ("귀금속점", "M-9003"),
    ("휴대폰 매장", "M-9004"), ("중고명품 매장", "M-9005"), ("온라인 쇼핑몰", "M-9006"),
]
_CARRIERS: list[tuple[str, str]] = [
    ("가나통신", "TEL-GANA"), ("다라모바일", "TEL-DARA"), ("마바알뜰폰", "TEL-MABA"),
]
# 처음 보는 송금 상대 이름(은행 화면처럼 가운데 글자 가림). 가상.
_NEW_PAYEE_NAMES: list[str] = [
    "김*호", "이*민", "박*준", "최*서", "정*우", "강*현", "조*아", "윤*진", "장*혁", "한*솔",
]

_MEMO = {
    Channel.TRANSFER: "모바일이체",
    Channel.CARD: "체크카드",
    Channel.MICROPAY: "휴대폰결제",
    Channel.TELECOM_BILL: "통신요금",
    Channel.ATM: "ATM출금",
    Channel.INCOME: "입금",
}


@dataclass(frozen=True)
class _Row:
    """Transaction 생성 전 중간 표현."""

    ts: datetime
    amount: int
    direction: Direction
    channel: Channel
    counterparty: str
    counterparty_id: str = ""
    line_id: str = ""


# ---------------------------------------------------------------------------
# 정상 이력
# ---------------------------------------------------------------------------

def generate_history(persona: Persona, start: date, days: int, seed: int) -> list[Transaction]:
    """정상 거래만 만든다(label="normal"). ts 오름차순, id는 ``t00001`` 형식."""
    if days <= 0:
        raise ValueError("days는 1 이상이어야 해요.")
    rng = np.random.default_rng(seed)
    hours = np.arange(*persona.active_hours)
    hour_p = _hour_profile(persona.active_hours)
    occasional = _OCCASIONAL_MERCHANTS  # 한 번 간 가게에 다시 갈 수도 있다(현실적인 반복)
    rows: list[_Row] = []

    def day_hour() -> int:
        """활동 시간 안의 시각 하나."""
        return int(rng.choice(hours, p=hour_p))

    for d in range(days):
        day = start + timedelta(days=d)

        # 월 1회 입금
        if day.day == _day_in_month(day, persona.income_day):
            amount = persona.monthly_income
            if persona.income_jitter > 0:
                amount = int(amount * (1 + rng.uniform(-persona.income_jitter, persona.income_jitter)))
            rows.append(_Row(
                ts=_at(day, int(rng.integers(9, 11)), rng), amount=_round(amount, 1_000),
                direction=Direction.IN, channel=Channel.INCOME,
                counterparty=persona.income_source[0], counterparty_id=persona.income_source[1],
            ))

        # 월 1회 통신요금(본인 회선 1개)
        if day.day == _day_in_month(day, persona.bill_day):
            amount = persona.telecom_bill + int(rng.integers(-300, 301)) * 10
            rows.append(_Row(
                ts=_at(day, int(rng.integers(10, 12)), rng), amount=max(amount, 1_000),
                direction=Direction.OUT, channel=Channel.TELECOM_BILL,
                counterparty=persona.telecom_carrier[0], counterparty_id=persona.telecom_carrier[1],
                line_id=persona.telecom_line,
            ))

        # 카드결제: 단골 위주, 가끔 처음 가는 가게 소액
        for _ in range(int(rng.poisson(persona.card_count_per_week / 7))):
            hour = day_hour()
            amount = _card_amount(rng, persona.daily_card_mean)
            if rng.random() < persona.new_merchant_share:
                name, mid = occasional[int(rng.integers(len(occasional)))]
                amount = min(amount, 30_000)
            else:
                name, mid = _pick_known(rng, persona.known_merchants)
            rows.append(_Row(_at(day, hour, rng), amount, Direction.OUT, Channel.CARD, name, mid))

        # 밤 카드결제(23~01시) 잡음: 첫 번째 단골 가게
        if rng.random() < persona.night_card_per_month / 30:
            hour = int(rng.choice([23, 0, 1]))
            name, mid = persona.known_merchants[0]
            rows.append(_Row(_at(day, hour, rng), _card_amount(rng, persona.daily_card_mean),
                             Direction.OUT, Channel.CARD, name, mid))

        # 처음 가는 가게 조금 큰 결제(옷·신발 등) 잡음
        if rng.random() < persona.big_new_merchant_per_month / 30:
            name, mid = occasional[int(rng.integers(len(occasional)))]
            hour = day_hour()
            rows.append(_Row(_at(day, hour, rng), int(rng.integers(50, 151)) * 1_000,
                             Direction.OUT, Channel.CARD, name, mid))

        # 알려진 상대 송금
        if rng.random() < persona.transfers_per_month / 30:
            name, acct = _pick_known(rng, persona.known_payees)
            hour = day_hour()
            rows.append(_Row(_at(day, hour, rng), _transfer_amount(rng, persona.transfer_mean),
                             Direction.OUT, Channel.TRANSFER, name, acct))

        # 드문 밤 송금(알려진 상대, 23~00시) 잡음
        if rng.random() < persona.night_transfer_per_month / 30:
            name, acct = _pick_known(rng, persona.known_payees)
            hour = int(rng.choice([23, 0]))
            rows.append(_Row(_at(day, hour, rng), _transfer_amount(rng, persona.transfer_mean),
                             Direction.OUT, Channel.TRANSFER, name, acct))

        # 드문 새 상대 1회 소액 송금(중고거래·회비 등) 잡음
        if rng.random() < persona.new_payee_per_month / 30:
            acct = f"900-8{int(rng.integers(0, 1000)):03d}-{int(rng.integers(0, 1_000_000)):06d}"
            name = _NEW_PAYEE_NAMES[int(rng.integers(len(_NEW_PAYEE_NAMES)))]
            hour = day_hour()
            rows.append(_Row(_at(day, hour, rng), int(rng.integers(1, 6)) * 10_000,
                             Direction.OUT, Channel.TRANSFER, name, acct))

        # 휴대폰 소액결제(본인 회선)
        if rng.random() < persona.micropay_per_month / 30:
            name, cid = _NORMAL_MICROPAY[int(rng.integers(len(_NORMAL_MICROPAY)))]
            hour = day_hour()
            rows.append(_Row(_at(day, hour, rng), int(rng.integers(10, 151)) * 100,
                             Direction.OUT, Channel.MICROPAY, name, cid, persona.telecom_line))

        # 현금 인출
        if rng.random() < persona.atm_per_month / 30:
            hour = day_hour()
            amount = int(rng.choice([10_000, 20_000, 30_000, 50_000, 100_000]))
            rows.append(_Row(_at(day, hour, rng), amount, Direction.OUT, Channel.ATM, "ATM", "ATM"))

    order = sorted(range(len(rows)), key=lambda i: (rows[i].ts, i))
    return [_to_txn(rows[i], f"t{n:05d}", NORMAL_LABEL) for n, i in enumerate(order, start=1)]


# ---------------------------------------------------------------------------
# 시나리오 주입
# ---------------------------------------------------------------------------

@dataclass
class _Context:
    """시나리오 설계에 쓰는 개인 기준값(시작일 이전 거래만)과 이미 쓰인 식별값."""

    at: date
    history_start: date
    used_ids: set[str]            # 이력 전체(과거·미래)의 거래 id
    used_counterparties: set[str]  # 이력 전체의 counterparty_id
    used_names: set[str]          # 이력 전체의 counterparty 이름
    used_lines: set[str]          # 이력 전체의 line_id
    main_line: str                # 본인 회선(가장 많이 청구된 회선)
    card_p95: float               # 시작일 이전 카드결제 금액 p95
    transfer_7d_baseline: float   # 시작일 이전 평소 7일 송금 합계(평균)

    @staticmethod
    def build(history: Sequence[Transaction], at: date) -> "_Context":
        cutoff = datetime.combine(at, time(0, 0))
        before = [t for t in history if t.ts < cutoff]
        first = min((t.ts.date() for t in history), default=at)

        card = [t.amount for t in before if t.channel == Channel.CARD and t.direction == Direction.OUT]
        p95 = float(np.percentile(card, 95)) if card else 0.0

        transfer_sum = sum(t.amount for t in before
                           if t.channel == Channel.TRANSFER and t.direction == Direction.OUT)
        weeks = max(1.0, (at - first).days / 7)

        lines: dict[str, int] = {}
        for t in history:
            if t.channel == Channel.TELECOM_BILL and t.line_id:
                lines[t.line_id] = lines.get(t.line_id, 0) + 1
        if not lines:
            for t in history:
                if t.channel == Channel.MICROPAY and t.line_id:
                    lines[t.line_id] = lines.get(t.line_id, 0) + 1
        main_line = max(sorted(lines), key=lambda k: lines[k]) if lines else "010-****-0000"

        return _Context(
            at=at,
            history_start=first,
            used_ids={t.id for t in history},
            used_counterparties={t.counterparty_id for t in history if t.counterparty_id},
            used_names={t.counterparty for t in history if t.counterparty},
            used_lines={t.line_id for t in history if t.line_id},
            main_line=main_line,
            card_p95=p95,
            transfer_7d_baseline=transfer_sum / weeks,
        )

    def new_payee(self, rng: np.random.Generator) -> tuple[str, str]:
        """이력 전체에 없는 송금 상대(이름과 계좌 모두 처음 보는 값)."""
        names = [n for n in _NEW_PAYEE_NAMES if n not in self.used_names]
        if names:
            name = names[int(rng.integers(len(names)))]
        else:  # 이름 풀이 모자라면 번호를 붙인다
            k = 1
            while f"새 상대 {k}" in self.used_names:
                k += 1
            name = f"새 상대 {k}"
        while True:
            acct = f"900-7{int(rng.integers(0, 1000)):03d}-{int(rng.integers(0, 1_000_000)):06d}"
            if acct not in self.used_counterparties:
                break
        self.used_names.add(name)
        self.used_counterparties.add(acct)
        return name, acct

    def new_merchants(self, rng: np.random.Generator, n: int) -> list[tuple[str, str]]:
        """이력 전체에 없는 가맹점 n곳."""
        pool = [m for m in _HIGH_VALUE_MERCHANTS
                if m[1] not in self.used_counterparties and m[0] not in self.used_names]
        picked: list[tuple[str, str]] = []
        for i in rng.permutation(len(pool))[:n]:
            picked.append(pool[int(i)])
        k = 1
        while len(picked) < n:  # 풀이 모자라면 번호를 붙여 새로 만든다
            cand = (f"처음 보는 가게 {k}", f"M-99{k:02d}")
            if cand[1] not in self.used_counterparties and cand[0] not in self.used_names:
                picked.append(cand)
            k += 1
        self.used_counterparties.update(m[1] for m in picked)
        self.used_names.update(m[0] for m in picked)
        return picked

    def new_lines(self, rng: np.random.Generator, n: int) -> list[str]:
        """이력 전체에 없는 회선 n개(마스킹 형식)."""
        out: list[str] = []
        while len(out) < n:
            line = f"010-****-{int(rng.integers(0, 10_000)):04d}"
            if line not in self.used_lines:
                self.used_lines.add(line)
                out.append(line)
        return out


def _scn_night_repeat(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """3~5일에 걸쳐 00~04시에 처음 보는 상대에게 이체 4~6건(각 10만~50만 원)."""
    n = int(rng.integers(4, 7))
    span = int(rng.integers(3, 6))
    k = min(n, span)  # 이체가 있는 날 수(첫날·마지막 날 포함)
    middle = rng.choice(np.arange(1, span - 1), size=k - 2, replace=False).tolist()
    active = sorted({0, span - 1, *[int(x) for x in middle]})
    offsets = active + [int(x) for x in rng.choice(active, size=n - len(active))]
    name, acct = ctx.new_payee(rng)
    rows = []
    for off in sorted(offsets):
        day = ctx.at + timedelta(days=off)
        rows.append(_Row(_at(day, int(rng.integers(0, 5)), rng), int(rng.integers(10, 51)) * 10_000,
                         Direction.OUT, Channel.TRANSFER, name, acct))
    return rows


def _scn_payee_surge(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """새 상대 1명에게 7일 안에 4~7건, 합계는 평소 7일 송금 합계의 9~12배(최소 30만 원).

    SPEC 기준은 5배 이상이다. 시나리오 거래 자체가 뒤 거래의 '평소' 기준에 섞여도
    5배를 넘도록 여유를 둔다.
    """
    n = int(rng.integers(4, 8))
    total = max(ctx.transfer_7d_baseline * rng.uniform(9.0, 12.0), int(rng.integers(30, 61)) * 10_000)
    weights = rng.dirichlet(np.full(n, 2.0))
    amounts = [max(10_000, _ceil(total * w, 10_000)) for w in weights]
    offsets = _offsets(rng, n, span=7)
    name, acct = ctx.new_payee(rng)
    return [
        _Row(_at(ctx.at + timedelta(days=off), int(rng.integers(9, 21)), rng), amt,
             Direction.OUT, Channel.TRANSFER, name, acct)
        for off, amt in zip(offsets, amounts)
    ]


def _scn_micropay_surge(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """7일 안에 휴대폰 소액결제 8~15건(각 1만~10만 원), 본인 회선."""
    n = int(rng.integers(8, 16))
    offsets = _offsets(rng, n, span=7)
    rows = []
    for off in offsets:
        name, cid = _SCENARIO_MICROPAY[int(rng.integers(len(_SCENARIO_MICROPAY)))]
        rows.append(_Row(_at(ctx.at + timedelta(days=off), int(rng.integers(9, 23)), rng),
                         int(rng.integers(10, 101)) * 1_000,
                         Direction.OUT, Channel.MICROPAY, name, cid, ctx.main_line))
    return rows


def _scn_new_merchant_high(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """처음 보는 가맹점 2~4곳에서 고액 결제. 금액은 max(개인 p95×3, 10만 원)의 1.2~2.5배."""
    n = int(rng.integers(2, 5))
    floor = max(ctx.card_p95 * 3.0, 100_000.0)
    offsets = _offsets(rng, n, span=6)
    rows = []
    for off, (name, mid) in zip(offsets, ctx.new_merchants(rng, n)):
        amount = _ceil(floor * rng.uniform(1.2, 2.5), 1_000)
        rows.append(_Row(_at(ctx.at + timedelta(days=off), int(rng.integers(10, 21)), rng),
                         amount, Direction.OUT, Channel.CARD, name, mid))
    return rows


def _scn_multi_line(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """14일 안에 서로 다른 새 회선 2~3개의 통신요금 청구(명의도용 개통 재현)."""
    n = int(rng.integers(2, 4))
    offsets = sorted([0, *[int(x) + 1 for x in rng.choice(13, size=n - 1, replace=False)]])
    rows = []
    for off, line in zip(offsets, ctx.new_lines(rng, n)):
        name, cid = _CARRIERS[int(rng.integers(len(_CARRIERS)))]
        rows.append(_Row(_at(ctx.at + timedelta(days=off), int(rng.integers(9, 19)), rng),
                         int(rng.integers(3_500, 9_900)) * 10,
                         Direction.OUT, Channel.TELECOM_BILL, name, cid, line))
    return rows


_BUILDERS: dict[SignalCode, Callable[[np.random.Generator, _Context], list[_Row]]] = {
    SignalCode.NIGHT_REPEAT_TRANSFER: _scn_night_repeat,
    SignalCode.PAYEE_SURGE: _scn_payee_surge,
    SignalCode.MICROPAY_SURGE: _scn_micropay_surge,
    SignalCode.NEW_MERCHANT_HIGH_VALUE: _scn_new_merchant_high,
    SignalCode.MULTI_LINE_TELECOM: _scn_multi_line,
}


# ---- 경계 변형(subtle): SPEC §3 [추가 r4] 사전 등록 정의 ----

def _amount_between(rng: np.random.Generator, lo: float, hi: float, unit: int) -> int:
    """[lo, hi] 안의 금액 하나(unit 단위). 그 구간에 unit 단위 값이 없으면 원 단위."""
    value = _round(float(rng.uniform(lo, hi)), unit)
    lo_u, hi_u = _ceil(lo, unit), int(math.floor(hi / unit)) * unit
    if lo_u <= hi_u:
        return min(max(value, lo_u), hi_u)
    lo_w, hi_w = int(math.ceil(lo)), int(math.floor(hi))
    return lo_w if lo_w <= hi_w else int(round(lo))


def _subtle_night_repeat(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """7일 안 00~04시에 처음 보는 상대(한 사람)에게 이체 2건, 각 30만~80만 원."""
    offsets = _offsets(rng, 2, span=7)
    name, acct = ctx.new_payee(rng)
    return [
        _Row(_at(ctx.at + timedelta(days=off), int(rng.integers(0, 5)), rng),
             int(rng.integers(30, 81)) * 10_000, Direction.OUT, Channel.TRANSFER, name, acct)
        for off in offsets
    ]


def _subtle_payee_surge(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """새 상대 1명에게 7일 안 2건. 합계 = 평소 7일 송금 합계 × 2.0~2.9 (평소 0이면 20만~29만 원)."""
    base = ctx.transfer_7d_baseline
    if base > 0:
        total = _amount_between(rng, 2.0 * base, 2.9 * base, 1_000)
    else:
        total = int(rng.integers(20, 30)) * 10_000
    first = _round(total * float(rng.uniform(0.3, 0.7)), 1_000)
    if total >= 2_000:
        first = min(max(first, 1_000), total - 1_000)
    else:
        first = total // 2
    offsets = _offsets(rng, 2, span=7)
    name, acct = ctx.new_payee(rng)
    return [
        _Row(_at(ctx.at + timedelta(days=off), int(rng.integers(9, 21)), rng), amt,
             Direction.OUT, Channel.TRANSFER, name, acct)
        for off, amt in zip(offsets, (first, total - first))
    ]


def _subtle_micropay_surge(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """7일 안 본인 회선 휴대폰 소액결제 4건, 각 5만~10만 원."""
    rows = []
    for off in _offsets(rng, 4, span=7):
        name, cid = _SCENARIO_MICROPAY[int(rng.integers(len(_SCENARIO_MICROPAY)))]
        rows.append(_Row(_at(ctx.at + timedelta(days=off), int(rng.integers(9, 23)), rng),
                         int(rng.integers(50, 101)) * 1_000,
                         Direction.OUT, Channel.MICROPAY, name, cid, ctx.main_line))
    return rows


def _subtle_new_merchant_high(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """처음 보는 가맹점 1곳 결제 1건. 금액 = max(개인 카드 p95 × 2.0~2.9, 10만 원)."""
    (name, mid), = ctx.new_merchants(rng, 1)
    p95 = ctx.card_p95
    scaled = _amount_between(rng, 2.0 * p95, 2.9 * p95, 100) if p95 > 0 else 0
    amount = max(scaled, 100_000)
    return [_Row(_at(ctx.at, int(rng.integers(10, 21)), rng), amount,
                 Direction.OUT, Channel.CARD, name, mid)]


def _subtle_multi_line(rng: np.random.Generator, ctx: _Context) -> list[_Row]:
    """처음 보는 회선 1개의 통신요금 청구 1건(시작일)."""
    (line,) = ctx.new_lines(rng, 1)
    name, cid = _CARRIERS[int(rng.integers(len(_CARRIERS)))]
    return [_Row(_at(ctx.at, int(rng.integers(9, 19)), rng), int(rng.integers(3_500, 9_900)) * 10,
                 Direction.OUT, Channel.TELECOM_BILL, name, cid, line)]


_SUBTLE_BUILDERS: dict[SignalCode, Callable[[np.random.Generator, _Context], list[_Row]]] = {
    SignalCode.NIGHT_REPEAT_TRANSFER: _subtle_night_repeat,
    SignalCode.PAYEE_SURGE: _subtle_payee_surge,
    SignalCode.MICROPAY_SURGE: _subtle_micropay_surge,
    SignalCode.NEW_MERCHANT_HIGH_VALUE: _subtle_new_merchant_high,
    SignalCode.MULTI_LINE_TELECOM: _subtle_multi_line,
}


def inject_scenario(history: Sequence[Transaction], code: SignalCode | str, at: date,
                    seed: int, intensity: str = "standard") -> list[Transaction]:
    """시나리오 거래를 더한 새 리스트(ts 오름차순). 원본은 바꾸지 않는다.

    주입 거래는 ``at`` 날짜 0시 이후에 놓이고 label=code.value이다(강도와 관계없이 같은 라벨).
    개인 기준값(카드 p95, 평소 7일 송금)은 ``at`` 이전 거래로 계산한다.
    intensity: "standard"(기본, 룰 기준을 넉넉히 넘음) 또는 "subtle"(경계 변형, SPEC §3 [추가 r4]).
    """
    code = SignalCode(code)
    builders = _SUBTLE_BUILDERS if check_intensity(intensity) == "subtle" else _BUILDERS
    rng = np.random.default_rng(seed)
    ctx = _Context.build(history, at)
    rows = sorted(builders[code](rng, ctx), key=lambda r: r.ts)
    injected: list[Transaction] = []
    for k, row in enumerate(rows, start=1):
        base = f"s-{code.value}-{at:%Y%m%d}-{k:02d}"
        tid, n = base, 2
        while tid in ctx.used_ids:
            tid, n = f"{base}-{n}", n + 1
        ctx.used_ids.add(tid)
        injected.append(_to_txn(row, tid, code.value))
    return sorted([*history, *injected], key=lambda t: t.ts)


def make_dataset(persona_key: str, seed: int, days: int = 120,
                 scenarios: Sequence[SignalCode | str] | None = None,
                 *, start: date = DEFAULT_START, intensity: str = "standard") -> list[Transaction]:
    """정상 이력 + 시나리오(각 1회, 마지막 30일 안). ts 오름차순, id 고유.

    ``scenarios``가 None이거나 비어 있으면 정상 거래만 돌려준다(모두 넣으려면 ALL_SCENARIOS).
    같은 seed면 정상 부분은 시나리오 유무·강도와 관계없이 똑같다(정상 전용 대조군용).
    시나리오 위치·내용은 (seed, 인물, 시나리오 종류)로 정한 하위 seed를 따르므로 목록 순서와 무관하다.
    intensity: "standard"(기본) 또는 "subtle"(경계 변형, SPEC §3 [추가 r4]).
    """
    spans = SUBTLE_SPAN_DAYS if check_intensity(intensity) == "subtle" else SCENARIO_SPAN_DAYS
    if persona_key not in PERSONAS:
        raise ValueError(f"알 수 없는 인물 설정이에요: {persona_key} (가능: {', '.join(PERSONAS)})")
    if seed < 0:
        raise ValueError("seed는 0 이상의 정수여야 해요.")
    txns = generate_history(PERSONAS[persona_key], start, days, seed)
    codes = list(dict.fromkeys(SignalCode(c) for c in (scenarios or [])))
    if not codes:
        return txns
    if days <= SCENARIO_WINDOW_DAYS:
        raise ValueError(f"시나리오를 넣으려면 days가 {SCENARIO_WINDOW_DAYS}보다 커야 해요.")

    salt = zlib.crc32(persona_key.encode("utf-8"))  # 인물마다 다른 시나리오가 나오게
    plan: list[tuple[int, int, SignalCode]] = []
    for code in codes:
        idx = list(SignalCode).index(code)
        place_rng = np.random.default_rng([seed, salt, 1_000 + idx])
        lo = days - SCENARIO_WINDOW_DAYS
        hi = days - spans[code]
        plan.append((int(place_rng.integers(lo, hi + 1)), idx, code))
    # 시간순으로 넣어야 뒤 시나리오의 기준값에 앞 시나리오 거래가 반영된다.
    for offset, idx, code in sorted(plan):
        txns = inject_scenario(txns, code, start + timedelta(days=offset),
                               seed=_derive_seed(seed, salt, idx), intensity=intensity)
    return txns


# ---------------------------------------------------------------------------
# 표준 CSV
# ---------------------------------------------------------------------------

def to_csv(txns: Iterable[Transaction], path: str | Path) -> Path:
    """SafePause 표준 CSV로 저장(UTF-8 BOM: 엑셀에서 한글이 깨지지 않게)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(STANDARD_COLUMNS)
        for t in txns:
            d = t.to_dict()
            writer.writerow(["" if d.get(c) is None else d[c] for c in STANDARD_COLUMNS])
    return path


def from_csv(path: str | Path) -> list[Transaction]:
    """SafePause 표준 CSV를 읽는다. 형식이 다르면 ValueError."""
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_STANDARD_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"SafePause 표준 CSV가 아니에요. 없는 열: {', '.join(missing)}")
        out = []
        for line_no, row in enumerate(reader, start=2):
            if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
                continue
            try:
                out.append(txn_from_standard_row(row))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{line_no}번째 줄을 읽지 못했어요: {exc}") from exc
    return out


class DateRangeError(ValueError):
    """날짜가 받을 수 있는 범위(MIN_YEAR~MAX_YEAR) 밖일 때."""


class AmountError(ValueError):
    """금액이 반올림해서 0원 이하일 때(거래로 받지 않는다)."""


def round_amount(number: float) -> int:
    """금액을 원 단위로 반올림한다. 0.5는 절댓값이 커지는 쪽(2.5→3, -2.5→-3).

    표준 CSV(txn_from_standard_row)와 한국어 머리글 CSV(loader)가 같은 규칙을 쓴다.
    Python의 round()는 2.5→2(짝수 쪽)라 쓰지 않는다.
    """
    value = math.floor(abs(number) + 0.5)
    return int(-value if number < 0 else value)


def check_year(ts: datetime) -> datetime:
    """연도가 MIN_YEAR~MAX_YEAR 안이면 그대로, 아니면 DateRangeError(날짜 계산 넘침 방지)."""
    if not MIN_YEAR <= ts.year <= MAX_YEAR:
        raise DateRangeError(f"{MIN_YEAR}~{MAX_YEAR}년 밖의 날짜예요: {ts.year}년")
    return ts


# ISO 8601 일시: 날짜(YYYY-MM-DD, YYYYMMDD) [T 또는 공백] 시각(HH:MM[:SS], HHMM[SS]) [소수 초] [시간대]
_ISO_TS_RE = re.compile(
    r"^(\d{4})-?(\d{2})-?(\d{2})"
    r"(?:[T ](\d{2}):?(\d{2})(?::?(\d{2})(?:[.,](\d+))?)?"
    r"(Z|[+-]\d{2}(?::?\d{2})?)?)?$",
    re.IGNORECASE,
)


def normalize_iso_ts(text: str) -> str:
    """ISO 8601 일시를 Python 3.10의 ``datetime.fromisoformat``도 읽는 모양으로 맞춘다.

    3.10은 isoformat() 출력 모양만 읽는다(소수 초 3·6자리, 시간대 '+HH:MM'). 3.11부터는
    '+0900', '.5', '20260901T100000'도 읽으므로, 같은 파일이 Python 버전에 따라 다르게 읽히지
    않게 여기서 '+09:00', '.500000', '2026-09-01T10:00:00'으로 바꾼다. 모양이 다르면 그대로 둔다.
    """
    s = text.strip()
    m = _ISO_TS_RE.match(s)
    if not m:
        return s
    year, month, day, hour, minute, second, fraction, zone = m.groups()
    out = f"{year}-{month}-{day}"
    if hour is None:
        return out
    out += f"T{hour}:{minute}:{second or '00'}"
    if fraction:
        out += "." + (fraction + "000000")[:6]
    if zone:
        if zone.upper() == "Z":
            out += "+00:00"
        else:
            digits = zone[1:].replace(":", "")
            out += f"{zone[0]}{digits[:2]}:{digits[2:4] or '00'}"
    return out


def parse_standard_ts(text: str) -> datetime:
    """표준 CSV의 ts(ISO 형식) → 시간대 없는(naive) 이 컴퓨터 시각.

    models.py 계약상 시각은 모두 naive 로컬 시각이다. '+09:00'·'Z' 같은 시간대 표기가 있으면
    이 컴퓨터 시각으로 바꾼 뒤 시간대를 뗀다(서버의 보낼 시각 처리와 같은 규칙).
    Python 3.10에서도 3.12와 똑같이 읽히도록 먼저 normalize_iso_ts로 모양을 맞춘다
    ('Z'→'+00:00', '+0900'→'+09:00', 소수 초는 6자리로).
    """
    ts = check_year(datetime.fromisoformat(normalize_iso_ts(text)))
    if ts.tzinfo is not None:
        ts = ts.astimezone().replace(tzinfo=None)
    return check_year(ts.replace(microsecond=0))


def txn_from_standard_row(row: dict[str, str | None]) -> Transaction:
    """표준 CSV 한 행(dict) → Transaction. 금액의 쉼표는 허용한다.

    금액은 원 단위로 반올림(round_amount)하고, 0원 이하(음수 포함)면 AmountError(ValueError).
    """
    def get(key: str) -> str:
        return (row.get(key) or "").strip()

    amount_text = get("amount").replace(",", "")
    if not amount_text:
        raise ValueError("amount가 비어 있어요")
    number = float(amount_text)
    if not math.isfinite(number) or abs(number) >= AMOUNT_LIMIT:
        raise ValueError(f"amount를 금액으로 읽을 수 없어요: {amount_text[:20]}")
    amount = round_amount(number)
    if amount <= 0:
        raise AmountError(f"amount가 0원 이하예요: {amount_text[:20]}")
    label = get("label") or None
    return Transaction(
        id=get("id"),
        ts=parse_standard_ts(get("ts")),
        amount=amount,
        direction=Direction(get("direction")),
        channel=Channel(get("channel")),
        counterparty=get("counterparty"),
        counterparty_id=get("counterparty_id"),
        line_id=get("line_id"),
        memo=get("memo"),
        label=label,
    )


# ---------------------------------------------------------------------------
# 내부 도우미
# ---------------------------------------------------------------------------

def _derive_seed(seed: int, salt: int, idx: int) -> int:
    """(seed, 인물, 시나리오)마다 고정된 하위 seed."""
    return int(np.random.SeedSequence([seed, salt, 7, idx]).generate_state(1)[0])


def _to_txn(row: _Row, tid: str, label: str) -> Transaction:
    return Transaction(
        id=tid, ts=row.ts, amount=int(row.amount), direction=row.direction, channel=row.channel,
        counterparty=row.counterparty, counterparty_id=row.counterparty_id, line_id=row.line_id,
        memo=_MEMO.get(row.channel, ""), label=label,
    )


def _day_in_month(day: date, wanted: int) -> int:
    """wanted일이 그 달에 없으면 말일."""
    return min(wanted, calendar.monthrange(day.year, day.month)[1])


def _hour_profile(active_hours: tuple[int, int]) -> np.ndarray:
    """활동 시간 안의 시각 분포(점심·저녁에 조금 더 몰림)."""
    start, end = active_hours
    if not 0 <= start < end <= 24:
        raise ValueError("active_hours는 0 ≤ 시작 < 끝 ≤ 24 이어야 해요.")
    hours = np.arange(start, end)
    w = np.ones(len(hours))
    w[(hours >= 12) & (hours < 14)] += 1.0
    w[(hours >= 18) & (hours < 21)] += 1.0
    return w / w.sum()


def _at(day: date, hour: int, rng: np.random.Generator) -> datetime:
    return datetime.combine(day, time(hour, int(rng.integers(0, 60)), int(rng.integers(0, 60))))


def _pick_known(rng: np.random.Generator, items: Sequence[tuple[str, str]]) -> tuple[str, str]:
    """앞쪽 항목을 더 자주 고른다(단골·가까운 사람)."""
    w = 1.0 / np.arange(1, len(items) + 1)
    return items[int(rng.choice(len(items), p=w / w.sum()))]


def _card_amount(rng: np.random.Generator, mean: int) -> int:
    sigma = 0.55
    mu = math.log(mean) - sigma**2 / 2
    return max(1_000, _round(float(rng.lognormal(mu, sigma)), 100))


def _transfer_amount(rng: np.random.Generator, mean: int) -> int:
    sigma = 0.5
    mu = math.log(mean) - sigma**2 / 2
    return max(5_000, _round(float(rng.lognormal(mu, sigma)), 5_000))


def _offsets(rng: np.random.Generator, n: int, span: int) -> list[int]:
    """0일째(시작일)를 포함한 n개의 날짜 오프셋(0..span-1, 중복 허용, 오름차순)."""
    rest = rng.integers(0, span, size=n - 1).tolist()
    return sorted([0, *[int(x) for x in rest]])


def _round(x: float, unit: int) -> int:
    return int(round(x / unit)) * unit


def _ceil(x: float, unit: int) -> int:
    return int(math.ceil(x / unit)) * unit
