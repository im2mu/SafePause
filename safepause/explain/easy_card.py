"""쉬운 말 카드(안전 정지 화면) 만들기. SPEC §6, 제안서 S20/S21/S38.

위험 판단(RiskAssessment)을 당사자가 바로 이해할 수 있는 짧은 카드로 바꾼다.
- 짧은 문장, 한 줄에 한 문장, 어려운 말 금지
- 금액은 "30만 원", 시각은 "새벽 2시"처럼
- 카드는 막지 않고 묻는다: 최종 결정은 당사자가 한다
- 룰 근거의 건수·합계는 평가 대상 거래를 포함한다. 보내기 전 카드는 '이번이 N번째',
  '이번 돈까지 모두'처럼 말하고, 이미 끝난 거래의 기록 카드(past=True)는 제목과 줄을 모두
  과거형으로 말한다('요즘' 같은 지금 기준 말 대신 '그때')
- 이력이 짧아 처음인지 알 수 없다는 근거(newness_unknown)가 있으면 '처음·새로'라고 말하지 않는다
- 질문·선택지는 거래 방법에 맞춘다(이체: 보내다, 결제·요금: 내다, 현금: 찾다)
- AI 단독 '다른 시간' 카드의 심야 그림(moon)은 근거에 담긴 심야 여부(이상탐지 시각 이유의
  detail.is_night: 엔진 설정 기준)를 먼저 쓰고, 없으면 넘겨받은 설정(settings, 기본 Settings())으로 정한다
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Callable, Iterable, Optional

from safepause.config import Settings
from safepause.models import (
    LEVEL_ORDER,
    AlertCard,
    Channel,
    Decision,
    Reason,
    RiskAssessment,
    RiskLevel,
    SignalCode,
    SignalHit,
    Transaction,
)

# ---- 쉬운 정보 원칙 -------------------------------------------------------

MAX_TITLE_LEN = 15
MAX_LINE_LEN = 30
MAX_LINES = 4
FORBIDDEN_WORDS: tuple[str, ...] = (
    "이상거래", "패턴", "탐지", "알고리즘", "모니터링", "이례", "임계", "통계",
)


@dataclass(frozen=True)
class ChannelWords:
    """거래 방법에 맞는 말(보내다/내다/찾다)."""

    question: str      # 카드 질문
    go: str            # 그래도 할래요
    stop: str          # 안 할래요
    done: str          # 했어요
    not_done: str      # 안 했어요(결과: 안 할래요)
    before: str        # '…기 전에'
    self_do: str = ""  # 결과: 그래도 할래요. SafePause는 돈을 옮기지 않아 본인이 직접 하도록 안내(v0.3 돈 보내기)


WORDS_SEND = ChannelWords("이 돈을 정말 보내는 것이 맞나요?", "그래도 보낼래요", "안 보낼래요",
                          "보냈어요", "보내지 않았어요", "보내기", "내 은행 앱에서 보내 주세요")
WORDS_PAY = ChannelWords("이 돈을 정말 내는 것이 맞나요?", "그래도 낼래요", "안 낼래요",
                         "결제했어요", "결제하지 않았어요", "결제하기", "결제는 직접 해 주세요")
WORDS_BILL = ChannelWords("이 요금을 정말 내는 것이 맞나요?", "그래도 낼래요", "안 낼래요",
                          "냈어요", "내지 않았어요", "내기", "요금은 직접 내 주세요")
WORDS_CASH = ChannelWords("이 돈을 정말 찾는 것이 맞나요?", "그래도 찾을래요", "안 찾을래요",
                          "찾았어요", "찾지 않았어요", "찾기", "돈은 직접 찾아 주세요")
WORDS_OTHER = ChannelWords("이 돈을 정말 내는 것이 맞나요?", "그래도 낼래요", "안 낼래요",
                           "냈어요", "내지 않았어요", "내기", "돈은 직접 내 주세요")
_CHANNEL_WORDS: dict[Channel, ChannelWords] = {
    Channel.TRANSFER: WORDS_SEND,
    Channel.CARD: WORDS_PAY,
    Channel.MICROPAY: WORDS_PAY,
    Channel.TELECOM_BILL: WORDS_BILL,
    Channel.ATM: WORDS_CASH,
}

ASK_HELPER_LABEL = "조력자에게 물어볼래요"
COMMON_QUESTION = WORDS_SEND.question          # 계좌 이체 카드의 질문(SPEC §6 기본 문장)
PAST_QUESTION = "그때 걱정했던 거래예요."      # ④ 기록 카드: 이미 끝난 거래라 묻지 않는다
CHOICES: tuple[tuple[Decision, str], ...] = (   # 계좌 이체 카드의 선택지
    (Decision.SEND, WORDS_SEND.go),
    (Decision.CANCEL, WORDS_SEND.stop),
    (Decision.ASK_HELPER, ASK_HELPER_LABEL),
)


def channel_words(channel: Channel | str) -> ChannelWords:
    """거래 방법에 맞는 동사 묶음. 모르는 값이면 '내다'."""
    try:
        ch = Channel(channel)
    except ValueError:
        return WORDS_OTHER
    return _CHANNEL_WORDS.get(ch, WORDS_OTHER)


def card_question(channel: Channel | str = Channel.TRANSFER, past: bool = False) -> str:
    return PAST_QUESTION if past else channel_words(channel).question


def card_choices(channel: Channel | str = Channel.TRANSFER, past: bool = False) -> list[dict[str, str]]:
    """안전 정지 카드의 선택지 3개. 기록 카드(past)는 고를 것이 없어 빈 목록."""
    if past:
        return []
    w = channel_words(channel)
    return [{"decision": Decision.SEND.value, "label": w.go},
            {"decision": Decision.CANCEL.value, "label": w.stop},
            {"decision": Decision.ASK_HELPER.value, "label": ASK_HELPER_LABEL}]

# static/icons/<id>.svg 로 제공되는 그림 id (SPEC §10)
PICTOGRAMS: frozenset[str] = frozenset({
    "moon", "money", "question", "phone", "store", "person",
    "warning", "check", "stop", "helper", "ear",
})

# 여러 시그널이 동시에 걸렸을 때 대표 시그널을 고르는 고정 순서(같은 등급일 때)
SIGNAL_ORDER: tuple[SignalCode, ...] = tuple(SignalCode)

# 이상탐지 특징 이름 → 카드 종류
ANOMALY_FEATURE_GROUPS: dict[str, str] = {
    "log_amount": "amount",
    "amount_vs_p95": "amount",
    "hour_sin": "time",
    "hour_cos": "time",
    "is_night": "time",
    "new_counterparty": "new_counterparty",
    "cp_count_7d": "same_counterparty",
    "cp_sum_7d_ratio": "same_counterparty",
    "channel_count_7d_ratio": "channel_burst",
    "new_line": "new_line",
}


# ---- 금액·시각 포맷 -------------------------------------------------------

def _round_div(n: int, unit: int) -> int:
    """n / unit 을 반올림(0.5는 올림)."""
    return (n + unit // 2) // unit


def format_won(amount: int) -> str:
    """금액을 읽기 쉬운 한국어로 바꾼다.

    - 1천 원 미만: 그대로 (예: "800원")
    - 1억 원 미만: 천 원 단위 반올림 (예: 300000 → "30만 원", 125400 → "12만 5천 원")
    - 1조 원 미만: 만 원 단위 반올림 (예: "1억 2,000만 원")
    - 그 이상: 억 원 단위 반올림
    """
    n = int(amount)
    if n < 0:
        raise ValueError("금액은 0 이상이어야 해요.")
    if n < 1_000:
        return f"{n}원"
    if n < 100_000_000 - 500:
        man, cheon = divmod(_round_div(n, 1_000), 10)
        parts = []
        if man:
            parts.append(f"{man:,}만")
        if cheon:
            parts.append(f"{cheon}천")
        return " ".join(parts) + " 원"
    if n < 1_000_000_000_000 - 5_000:
        eok, man = divmod(_round_div(n, 10_000), 10_000)
        return f"{eok:,}억 {man:,}만 원" if man else f"{eok:,}억 원"
    jo, eok = divmod(_round_div(n, 100_000_000), 10_000)
    return f"{jo:,}조 {eok:,}억 원" if eok else f"{jo:,}조 원"


def format_time_kr(ts: datetime | time, with_minutes: bool = True) -> str:
    """시각을 "새벽 2시", "오후 3시 20분"처럼 바꾼다."""
    hour, minute = ts.hour, ts.minute
    if hour == 0:
        text = "밤 12시"
    elif hour < 6:
        text = f"새벽 {hour}시"
    elif hour < 9:
        text = f"아침 {hour}시"
    elif hour < 12:
        text = f"오전 {hour}시"
    elif hour == 12:
        text = "낮 12시"
    elif hour < 18:
        text = f"오후 {hour - 12}시"
    elif hour < 21:
        text = f"저녁 {hour - 12}시"
    else:
        text = f"밤 {hour - 12}시"
    if with_minutes and minute:
        text += f" {minute}분"
    return text


# ---- 가독성 검사 ----------------------------------------------------------

_SENTENCE_END = re.compile(r"[.?!](?=\s|$)")
_RAW_BIG_NUMBER = re.compile(r"\d{5,}")      # 30만 원 대신 300000원 같은 표기
_CLOCK_FORMAT = re.compile(r"\d{1,2}:\d{2}")  # 새벽 2시 대신 02:00 같은 표기


def _sentence_count(text: str) -> int:
    parts = [p for p in _SENTENCE_END.split(text) if p.strip()]
    return len(parts)


def _text_issues(label: str, text: str, max_len: int) -> list[str]:
    """한 덩어리 글의 위반 사항. 메시지는 "위치: 문제 - 원문" 형식."""
    issues: list[str] = []
    stripped = text.strip()
    if not stripped:
        return [f"{label}: 비어 있음"]
    if len(stripped) > max_len:
        issues.append(f"{label}: {max_len}자 초과({len(stripped)}자) - {stripped}")
    compact = re.sub(r"\s+", "", stripped)
    for word in FORBIDDEN_WORDS:
        if word in stripped or word in compact:
            issues.append(f"{label}: 어려운 말 '{word}' - {stripped}")
    if _sentence_count(stripped) > 1:
        issues.append(f"{label}: 한 줄에 문장 여러 개 - {stripped}")
    no_comma = re.sub(r"(?<=\d),(?=\d)", "", stripped)
    if _RAW_BIG_NUMBER.search(no_comma):
        issues.append(f"{label}: 긴 숫자(만 원 단위로 쓸 것) - {stripped}")
    if _CLOCK_FORMAT.search(stripped):
        issues.append(f"{label}: 시각은 '새벽 2시'처럼 쓸 것 - {stripped}")
    return issues


def readability_issues(card: AlertCard) -> list[str]:
    """쉬운 정보 원칙 위반 목록. 빈 목록이면 통과."""
    issues: list[str] = []
    issues += _text_issues("제목", card.title, MAX_TITLE_LEN)
    if not card.lines:
        issues.append("내용: 줄 없음")
    if len(card.lines) > MAX_LINES:
        issues.append(f"내용: {MAX_LINES}줄 초과({len(card.lines)}줄)")
    for i, line in enumerate(card.lines, start=1):
        issues += _text_issues(f"{i}번째 줄", line, MAX_LINE_LEN)
    issues += _text_issues("질문", card.question, MAX_LINE_LEN)
    for choice in card.choices:
        issues += _text_issues("선택지", choice.get("label", ""), MAX_LINE_LEN)
    return issues


# ---- 카드 조립 ------------------------------------------------------------

def make_speak_text(title: str, lines: Iterable[str], question: str) -> str:
    """음성 읽기용 한 문단: 제목 + 내용 + 질문."""
    parts: list[str] = []
    for piece in (title, *lines, question):
        piece = piece.strip()
        if not piece:
            continue
        if piece[-1] not in ".?!":
            piece += "."
        parts.append(piece)
    return " ".join(parts)


def build_card(txn_id: str, level: RiskLevel, title: str, lines: list[str],
               pictograms: list[str], source: str = "template", *,
               channel: Channel | str = Channel.TRANSFER, past: bool = False) -> AlertCard:
    """질문·선택지·음성 문장을 붙여 카드를 만든다(질문·선택지는 거래 방법에 맞춘다)."""
    unknown = [p for p in pictograms if p not in PICTOGRAMS]
    if unknown:
        raise ValueError(f"없는 그림 id: {unknown}")
    question = card_question(channel, past)
    return AlertCard(
        txn_id=txn_id,
        level=level,
        title=title,
        lines=list(lines),
        pictograms=list(pictograms),
        question=question,
        choices=card_choices(channel, past),
        speak_text=make_speak_text(title, lines, question),
        source=source,
    )


# ---- 문구 도우미 ----------------------------------------------------------

def _has_final_consonant(word: str) -> bool:
    last = word[-1]
    return 0xAC00 <= ord(last) <= 0xD7A3 and (ord(last) - 0xAC00) % 28 != 0


def _topic(word: str) -> str:
    """은/는 조사."""
    return word + ("은" if _has_final_consonant(word) else "는")


def _short_name(name: str, max_len: int = 8) -> Optional[str]:
    """카드에 넣어도 되는 짧은 이름이면 돌려주고, 아니면 None."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name or len(name) > max_len:
        return None
    last = name[-1]
    if not (0xAC00 <= ord(last) <= 0xD7A3):  # 조사를 정확히 붙일 수 있는 한글 끝말만
        return None
    if re.search(r"\d", name):
        return None
    compact = name.replace(" ", "")
    if any(w in compact for w in FORBIDDEN_WORDS):
        return None
    return name


# 사람이 아닌 받는 곳(모임 회비·가게 등)으로 보는 끝말. 이런 이름에는 '에게' 대신 '에'를 붙인다.
_PLACE_ENDINGS: tuple[str, ...] = (
    "회비", "월세", "관리비", "요금", "보험", "적금", "센터", "회사", "은행", "모임", "협회", "재단",
    "교회", "성당", "학교", "학원", "병원", "약국", "가게", "상가", "마트", "식당", "매장", "몰", "점",
)


def _is_place(name: str) -> bool:
    """받는 쪽이 사람보다 모임·가게·요금 같은 '곳'으로 보이면 True(가린 이름 '김*호'는 사람)."""
    compact = re.sub(r"\s+", "", name or "")
    if not compact or "*" in compact or compact.endswith(("님", "씨")):
        return False
    return compact.endswith(_PLACE_ENDINGS)


def _with_to(name: str) -> str:
    """이름 + '에게'(사람) 또는 '에'(모임·가게 등). '에게'·'에'는 받침과 관계없다."""
    return f"{name}에" if _is_place(name) else f"{name}에게"


def to_whom(name: str, fallback: str = "이 사람") -> str:
    """카드용 받는 쪽 표현: '엄마에게', '모임 회비에', 이름이 길거나 숫자가 있으면 '이 사람에게'."""
    short = _short_name(name)
    return _with_to(short) if short else f"{fallback}에게"


def _as_count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (list, tuple, set, frozenset)):
        value = len(value)
    if isinstance(value, (int, float)) and value >= 1:
        return int(round(value))
    return None


def _pick_count(detail: dict[str, Any], keys: tuple[str, ...], hit: Optional[SignalHit]) -> Optional[int]:
    """근거 dict에서 건수를 찾는다. 없으면 관련 거래 수로 대신한다."""
    for key in keys:
        count = _as_count(detail.get(key))
        if count is not None:
            return count
    if hit is not None and hit.related_txn_ids:
        return len(hit.related_txn_ids)
    return None


def _pick_amount(detail: dict[str, Any], keys: tuple[str, ...]) -> Optional[int]:
    for key in keys:
        value = detail.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            return int(round(value))
    return None


# 근거 dict 키 후보 (룰 모듈이 쓰는 이름이 달라도 동작하도록 여러 이름을 본다)
_COUNT_KEYS = ("count_7d", "count", "night_count_7d", "cp_count_7d", "micropay_count_7d",
               "transfer_count_7d", "n_7d", "n")
_SUM_KEYS = ("sum_7d", "cp_sum_7d", "total_7d", "amount_sum_7d", "total", "sum")
_LINE_COUNT_KEYS = ("distinct_lines_30d", "lines_30d", "line_count_30d", "distinct_lines",
                    "new_lines", "new_line_count", "count_30d", "count")
_SLOW_DOWN = "천천히 한 번 더 생각해요."
_WINDOW = "7일 동안"   # 최근 창(window_short_days) 표현. '이번 주'는 기록 카드에서 틀린 말이 된다
_RECENT = "요즘"       # 보내기 전 카드의 '지금 기준' 말
_THEN = "그때"         # 기록 카드(past)에서 _RECENT 대신 쓰는 말


@dataclass
class _Parts:
    title: str
    lines: list[str]
    pictograms: list[str]


@dataclass(frozen=True)
class _Ctx:
    """템플릿 입력.

    룰 근거의 건수·합계는 대상 거래를 포함한다. past=False(보내기 전 안전 정지)면 대상은 아직
    이뤄지지 않았고, past=True(④ 기록 카드)면 이미 이뤄진 거래다. 문장은 이 차이에 맞춘다.
    """

    txn: Transaction
    detail: dict[str, Any]
    hit: Optional[SignalHit]
    past: bool
    settings: Optional[Settings] = None   # 근거에 심야 여부가 없을 때 쓸 판단 설정(없으면 기본값)

    def count(self, keys: tuple[str, ...] = _COUNT_KEYS) -> Optional[int]:
        """최근 7일 건수(대상 거래 포함)."""
        return _pick_count(self.detail, keys, self.hit)

    def completed(self, n: Optional[int]) -> Optional[int]:
        """이미 이뤄진 건수: 보내기 전이면 대상을 빼고, 기록 카드면 대상을 포함한다."""
        if n is None:
            return None
        return n if self.past else max(n - 1, 0)

    def tail(self) -> list[str]:
        """마무리 권유 줄. 이미 끝난 거래(기록 카드)에는 붙이지 않는다."""
        return [] if self.past else [_SLOW_DOWN]

    @property
    def when(self) -> str:
        """'요즘'(보내기 전) / '그때'(기록 카드)."""
        return _THEN if self.past else _RECENT

    def pick(self, now: str, then: str) -> str:
        """보내기 전 문장(now)과 기록 카드 문장(then) 가운데 하나."""
        return then if self.past else now

    @property
    def newness_unknown(self) -> bool:
        """이력이 짧아 처음인지 알 수 없음(룰 근거). 이때는 '처음·새로'라고 말하지 않는다."""
        return bool(self.detail.get("newness_unknown"))


def _count_line(ctx: _Ctx, n: int, done_verb: str) -> str:
    """'7일 동안 이번이 3번째예요.'(보내기 전) / '7일 동안 3번 보냈어요.'(기록)."""
    if ctx.past:
        return f"{_WINDOW} {n}번 {done_verb}."
    return f"{_WINDOW} 이번이 {n}번째예요."


def _sum_line(ctx: _Ctx, n: Optional[int], total: int) -> str:
    """합계 줄(대상 포함 합계). 1건뿐이면 이번 돈 하나라고 말한다."""
    won = format_won(total)   # 늘 '원'으로 끝난다(받침 있음 → '이었어요')
    if n is not None and n <= 1:
        return f"그 돈은 {won}이었어요." if ctx.past else f"이번 돈은 {won}이에요."
    return f"{_WINDOW} 모두 {won}이었어요." if ctx.past else f"이번 돈까지 모두 {won}이에요."


# ---- 시그널별 템플릿 (제안서 S19 5종) --------------------------------------

def _tpl_night(ctx: _Ctx) -> _Parts:
    n = ctx.count()
    done = ctx.completed(n)
    if done is not None and done >= 2:
        title, first = "밤에 돈을 자주 보냈어요", f"{ctx.when} 밤늦게 돈을 여러 번 보냈어요."
    elif n is not None and n >= 2:  # 보내기 전이고 앞서 1번 보냄
        title, first = "밤에 또 돈을 보내요", "요즘 밤늦게 돈을 보낸 적이 있어요."
    elif ctx.past:
        title, first = "밤늦게 돈을 보냈어요", "밤늦게 돈이 나갔어요."
    else:
        title, first = "밤늦게 돈을 보내요", "밤늦게 돈이 나가요."
    lines = [first]
    if n is not None and n >= 2:
        lines.append(_count_line(ctx, n, "보냈어요"))
    lines.append("누가 시켰나요?")
    return _Parts(title, lines, ["moon", "money", "question"])


def _tpl_payee(ctx: _Ctx) -> _Parts:
    name = _short_name(ctx.txn.counterparty)
    one = "곳" if name and _is_place(name) else "사람"
    who = to_whom(ctx.txn.counterparty)            # '엄마에게' / '모임 회비에' / '이 사람에게'
    n = ctx.count()
    done = ctx.completed(n)
    others = (n - 1) if n else 0                   # 대상 말고 7일 안에 보낸 건수
    first_seen_known = "first_seen_days_ago" in ctx.detail
    never_before = first_seen_known and ctx.detail.get("first_seen_days_ago") is None
    # 이력이 짧아 새 상대인지 알 수 없으면 '처음·새로'라고 말하지 않는다
    unknown = ctx.newness_unknown
    if done is not None and done >= 2:
        title = "한 곳에 많이 보냈어요" if one == "곳" else "한 사람에게 많이 보냈어요"
        first = f"{who} 돈을 자주 보냈어요."
    elif never_before and others == 0 and not unknown:
        title = ctx.pick(f"처음 보내는 {one}이에요", f"처음 보낸 {one}이었어요")
        first = f"{who} 처음 보낸 돈이었어요." if ctx.past else f"{who} 처음 보내는 돈이에요."
    elif not unknown and (others >= 1 or (first_seen_known and not never_before)):
        # 룰 조건상 첫 거래가 30일 안인 상대
        title = ctx.pick(f"요즘 새로 보내는 {one}이에요", f"새로 보내던 {one}이었어요")
        first = f"{who} 보내기 시작한 지 얼마 안 됐어요."
    else:
        title = ctx.pick("보내는 돈을 확인해요", "다시 볼 송금이었어요")
        first = f"{who} 보낸 돈이었어요." if ctx.past else f"{who} 보내는 돈이에요."
    lines = [first]
    if n is not None and n >= 2:
        lines.append(_count_line(ctx, n, "보냈어요"))
    total = _pick_amount(ctx.detail, _SUM_KEYS)
    if total:
        lines.append(_sum_line(ctx, n, total))
    lines.append("누가 보내라고 했나요?")
    return _Parts(title, lines, ["person", "money", "question"])


def _tpl_micropay(ctx: _Ctx) -> _Parts:
    n = ctx.count()
    done = ctx.completed(n)
    if done is not None and done >= 2:
        title = ctx.pick("휴대폰 결제가 많아요", "휴대폰 결제가 많았어요")
        first = f"{ctx.when} 휴대폰으로 결제를 많이 했어요."
    else:
        title = ctx.pick("휴대폰 결제를 확인해요", "다시 볼 휴대폰 결제였어요")
        first = "휴대폰으로 결제했어요." if ctx.past else "휴대폰으로 결제해요."
    lines = [first]
    if n is not None and n >= 2:
        lines.append(_count_line(ctx, n, "결제했어요"))
    total = _pick_amount(ctx.detail, _SUM_KEYS)
    if total:
        lines.append(_sum_line(ctx, n, total))
    lines.append("누가 결제해 달라고 했나요?")
    return _Parts(title, lines, ["phone", "money", "question"])


def _tpl_new_merchant(ctx: _Ctx) -> _Parts:
    store = _short_name(ctx.txn.counterparty)
    won = format_won(ctx.txn.amount)
    if ctx.newness_unknown:
        # 이력이 짧아 처음 가는 가게인지 알 수 없음: '처음·새'라고 말하지 않는다
        where = f"{store}에서" if store else "가게에서"
        first = ctx.pick(f"{where} 결제해요.", f"{where} 결제했어요.")
        title = ctx.pick("가게에 큰 돈을 내요", "가게에 큰 돈을 냈어요")
    elif ctx.past:
        first = f"{_topic(store)} 처음 간 가게였어요." if store else "처음 간 가게였어요."
        title = "새 가게에 큰 돈을 냈어요"
    else:
        first = f"{_topic(store)} 처음 가는 가게예요." if store else "처음 가는 가게예요."
        title = "새 가게에 큰 돈을 내요"
    second = ctx.pick(f"이번 결제는 {won}이에요.", f"그때 결제는 {won}이었어요.")
    p95 = ctx.detail.get("card_p95")
    # 평소 카드 결제 기준이 없으면(p95=0) '평소보다'라고 말하지 않는다
    no_usual = isinstance(p95, (int, float)) and p95 <= 0
    if ctx.past:
        third = "큰 돈이었어요." if no_usual else "평소보다 훨씬 큰 돈이었어요."
    else:
        third = "큰 돈이에요." if no_usual else "평소보다 훨씬 큰 돈이에요."
    return _Parts(title, [first, second, third, "누가 사 달라고 했나요?"],
                  ["store", "money", "question"])


def _tpl_multi_line(ctx: _Ctx) -> _Parts:
    n = _pick_count(ctx.detail, _LINE_COUNT_KEYS, ctx.hit)
    many = f"한 달 동안 요금이 {n}개 나왔어요." if n and n >= 2 else "휴대폰 요금이 여러 개 나왔어요."
    if ctx.newness_unknown:
        # 이력이 짧아 새로 생긴 회선인지 알 수 없음: '처음 보는'이라고 말하지 않는다
        lines = [many, "모두 내가 쓰는 휴대폰이 맞나요?"]
    else:
        lines = ["처음 보는 휴대폰 요금이 나왔어요."]
        if n and n >= 2:
            lines.append(many)
        lines.append("내가 만든 휴대폰이 맞나요?")   # 기록 카드에서도 질문으로 둔다(지금도 확인할 일)
    title = ctx.pick("휴대폰 요금이 여러 개예요", "휴대폰 요금이 여러 개였어요")
    return _Parts(title, lines, ["phone", "warning", "question"])


_SIGNAL_TEMPLATES: dict[SignalCode, Callable[[_Ctx], _Parts]] = {
    SignalCode.NIGHT_REPEAT_TRANSFER: _tpl_night,
    SignalCode.PAYEE_SURGE: _tpl_payee,
    SignalCode.MICROPAY_SURGE: _tpl_micropay,
    SignalCode.NEW_MERCHANT_HIGH_VALUE: _tpl_new_merchant,
    SignalCode.MULTI_LINE_TELECOM: _tpl_multi_line,
}


# ---- 이상탐지(개인 기준과 다름) 사유별 템플릿 -------------------------------

def _feature_value(reason: Optional[Reason]) -> Optional[float]:
    if reason is None or not isinstance(reason.detail, dict):
        return None
    value = reason.detail.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _is_night_for_card(ctx: _Ctx, reason: Optional[Reason]) -> bool:
    """심야 그림을 쓸지. 근거의 심야 여부(detail.is_night, is_night 특징 값)가 있으면 그것을,
    없으면 넘겨받은 설정(없으면 기본 Settings())으로 정한다."""
    detail = reason.detail if reason is not None and isinstance(reason.detail, dict) else {}
    flag = detail.get("is_night")
    if isinstance(flag, bool):
        return flag
    if detail.get("feature") == "is_night":
        value = _feature_value(reason)
        if value is not None:
            return value >= 0.5
    return (ctx.settings or Settings()).is_night(ctx.txn.ts.hour)


def _tpl_anomaly(group: str, ctx: _Ctx, reason: Optional[Reason] = None) -> _Parts:
    txn, past = ctx.txn, ctx.past
    transfer = txn.channel == Channel.TRANSFER
    won = format_won(txn.amount)
    if group == "amount":
        return _Parts(ctx.pick("평소보다 큰 돈이에요", "평소보다 큰 돈이었어요"), [
            f"그 돈은 {won}이었어요." if past else f"이번 돈은 {won}이에요.",
            "평소에 쓰는 돈보다 많았어요." if past else "평소에 쓰는 돈보다 많아요.",
            *ctx.tail(),
        ], ["money", "warning", "question"])
    if group == "time":
        icon = "moon" if _is_night_for_card(ctx, reason) else "warning"
        when = format_time_kr(txn.ts)
        return _Parts(ctx.pick("평소와 다른 시간이에요", "평소와 다른 시간이었어요"), [
            f"{when}에 돈이 나갔어요." if past else f"{when}에 돈이 나가요.",
            "평소에는 이 시간에 잘 안 썼어요." if past else "평소에는 이 시간에 잘 안 써요.",
            *ctx.tail(),
        ], [icon, "money", "question"])
    if group == "new_counterparty":
        if transfer:
            name = _short_name(txn.counterparty)
            place = bool(name and _is_place(name))
            who = to_whom(txn.counterparty)
            one = "곳" if place else "사람"
            return _Parts(ctx.pick(f"처음 보는 {one}이에요", f"처음 보는 {one}이었어요"), [
                f"{who} 처음 돈을 보냈어요." if past else f"{who} 처음 돈을 보내요.",
                "잘 아는 곳인가요?" if place else "잘 아는 사람인가요?",
                *ctx.tail(),
            ], ["person", "question"])
        return _Parts(ctx.pick("처음 보는 곳이에요", "처음 보는 곳이었어요"), [
            "처음 돈을 낸 곳이었어요." if past else "처음 돈을 내는 곳이에요.",
            "잘 아는 곳인가요?",
            *ctx.tail(),
        ], ["store", "question"])
    if group == "same_counterparty":
        feature = str(reason.detail.get("feature", "")) if reason and isinstance(reason.detail, dict) else ""
        value = _feature_value(reason)
        n = int(round(value)) if feature == "cp_count_7d" and value is not None and value >= 2 else None
        if transfer:
            who = to_whom(txn.counterparty, fallback="같은 사람")
            if n is not None:
                return _Parts("같은 사람에게 또 보냈어요" if past else "같은 사람에게 또 보내요", [
                    f"{who} 또 돈을 보냈어요." if past else f"{who} 또 돈을 보내요.",
                    _count_line(ctx, n, "보냈어요"),
                    "누가 시켰나요?",
                ], ["person", "money", "question"])
            return _Parts("평소보다 많이 보냈어요" if past else "평소보다 많이 보내요", [
                f"{who} 보낸 돈이 평소보다 많았어요." if past else f"{who} 보내는 돈이 평소보다 많아요.",
                "누가 시켰나요?",
            ], ["person", "money", "question"])
        if n is not None:
            return _Parts("같은 곳에 또 썼어요" if past else "같은 곳에 또 써요", [
                "같은 곳에 또 돈을 냈어요." if past else "같은 곳에 또 돈을 내요.",
                _count_line(ctx, n, "냈어요"),
                "누가 시켰나요?",
            ], ["store", "money", "question"])
        return _Parts("평소보다 많이 썼어요" if past else "평소보다 많이 써요", [
            "같은 곳에 낸 돈이 평소보다 많았어요." if past else "같은 곳에 내는 돈이 평소보다 많아요.",
            "누가 시켰나요?",
        ], ["store", "money", "question"])
    if group == "channel_burst":
        title = ("평소보다 자주 보냈어요" if past else "평소보다 자주 보내요") if transfer else \
                ("평소보다 자주 썼어요" if past else "평소보다 자주 써요")
        if past:
            first = f"{ctx.when} 이 방법으로 돈을 {'보낸' if transfer else '쓴'} 일이 평소보다 많았어요."
        else:
            first = f"{ctx.when} 이 방법으로 돈을 {'보내는' if transfer else '쓰는'} 일이 평소보다 많아요."
        return _Parts(title, [first, *ctx.tail()], ["money", "warning", "question"])
    if group == "new_line":
        if txn.channel == Channel.MICROPAY:
            first = "처음 보는 휴대폰 번호로 결제했어요." if past else "처음 보는 휴대폰 번호로 결제해요."
        else:
            first = "처음 보는 휴대폰 요금이었어요." if past else "처음 보는 휴대폰 요금이에요."
        return _Parts(ctx.pick("처음 보는 휴대폰이에요", "처음 보는 휴대폰이었어요"),
                      [first, "내가 만든 휴대폰이 맞나요?"],
                      ["phone", "warning", "question"])
    return _generic_parts(ctx)


def _generic_parts(ctx: Optional[_Ctx] = None) -> _Parts:
    past = bool(ctx and ctx.past)
    return _Parts("다시 볼 거래였어요" if past else "한 번 더 확인해요",
                  ["평소와 조금 달랐어요."] if past else ["평소와 조금 달라요.", _SLOW_DOWN],
                  ["warning", "question"])


# ---- 공개 함수 ------------------------------------------------------------

def _primary_hit(hits: list[SignalHit]) -> SignalHit:
    """가장 높은 등급, 같으면 SIGNAL_ORDER 앞의 시그널."""
    return min(hits, key=lambda h: (-LEVEL_ORDER[h.severity], SIGNAL_ORDER.index(h.code)))


def _detail_for(hit: SignalHit, reasons: list[Reason]) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for reason in reasons:
        if reason.code == hit.code.value and isinstance(reason.detail, dict):
            detail.update(reason.detail)
    detail.update(hit.evidence or {})
    return detail


def _anomaly_reason(reasons: list[Reason]) -> Optional[tuple[str, Reason]]:
    """첫 이상탐지 사유의 (카드 종류, 사유)."""
    for reason in reasons:
        if reason.code.startswith("anomaly:"):
            feature = reason.code.split(":", 1)[1]
            return ANOMALY_FEATURE_GROUPS.get(feature, "generic"), reason
    return None


def compose_parts(assessment: RiskAssessment, txn: Transaction,
                  past: bool = False, settings: Optional[Settings] = None
                  ) -> tuple[str, list[str], list[str]]:
    """(제목, 줄, 그림) 을 고른다. 룰 시그널이 있으면 그것이 우선이다.

    settings: 근거에 심야 여부가 없을 때 심야 그림을 정하는 판단 설정(없으면 기본 Settings()).
    """
    hits = [h for h in assessment.rule_hits if h.code in _SIGNAL_TEMPLATES]
    if hits:
        hit = _primary_hit(hits)
        ctx = _Ctx(txn, _detail_for(hit, assessment.reasons), hit, past, settings)
        parts = _SIGNAL_TEMPLATES[hit.code](ctx)
        others = len({h.code for h in hits}) - 1
        if others > 0 and len(parts.lines) < MAX_LINES:
            # 질문 줄 앞에 넣어 질문이 마지막에 오게 한다
            more = "있었어요" if past else "있어요"
            parts.lines.insert(len(parts.lines) - 1, f"걱정되는 점이 {others}가지 더 {more}.")
    else:
        ctx = _Ctx(txn, {}, None, past, settings)
        found = _anomaly_reason(assessment.reasons)
        parts = _tpl_anomaly(found[0], ctx, found[1]) if found else _generic_parts(ctx)
    return parts.title, parts.lines[:MAX_LINES], parts.pictograms


def render_card(assessment: RiskAssessment, txn: Transaction, *,
                past: bool = False, settings: Optional[Settings] = None) -> Optional[AlertCard]:
    """위험 판단을 쉬운 말 카드로. 위험 없음(NONE)이면 None.

    past=False: 보내기 전 안전 정지 카드(질문 + 선택지 3개, 거래 방법에 맞는 말).
    past=True: 이미 끝난 거래의 기록 카드(④ 알림 카드). 묻지 않고 선택지도 없다.
    settings: 판단에 쓴 설정. 근거에 심야 여부가 없을 때 심야 그림(moon)을 정하는 데 쓴다.
    """
    if assessment.level == RiskLevel.NONE:
        return None
    title, lines, pictograms = compose_parts(assessment, txn, past, settings)
    return build_card(assessment.txn_id or txn.id, assessment.level, title, lines, pictograms,
                      channel=txn.channel, past=past)


NO_HELPER_TO_ASK = "물어볼 조력자가 없어요"
NO_HELPER_HINT = "조력자 화면에서 조력자를 정할 수 있어요."


def practice_result(decision: Decision | str, txn: Transaction,
                    asked_count: Optional[int] = None) -> tuple[str, list[str]]:
    """보내기 전 확인 결과 화면의 (제목, 줄). 거래 방법에 맞는 동사·조사를 쓴다.

    SafePause는 돈을 옮기지 않는다. 그래서 그래도 할래요를 고르면 했다고 말하지 않고, 본인이 직접 하도록
    안내한다(계좌 이체: 내 은행 앱에서 보내 주세요). 연습이라는 말은 쓰지 않는다(v0.3, 이름은 호환용으로 그대로).
    asked_count: '조력자에게 물어볼래요'로 실제 물어본 조력자 수. 0이면 물어봤다고 말하지 않는다.
    """
    d = Decision(decision)
    w = channel_words(txn.channel)
    won = format_won(txn.amount)
    name = re.sub(r"\s+", " ", txn.counterparty or "").strip()
    if txn.channel == Channel.TRANSFER:
        target = f"{_with_to(name)} " if name else ""
    elif txn.channel == Channel.CARD:
        target = f"{name}에서 " if name else "가게에서 "
    elif txn.channel == Channel.MICROPAY:
        target = "휴대폰으로 "
    elif txn.channel == Channel.TELECOM_BILL:
        target = "휴대폰 요금 "
    elif txn.channel == Channel.ATM:
        target = "현금 "
    else:
        target = f"{name}에 " if name else ""
    if d == Decision.SEND:
        return w.self_do, [f"{target}{won}을 {w.before} 전에 확인했어요."]
    if d == Decision.CANCEL:
        return w.not_done, [f"{target}{won}을 {w.not_done}."]
    if asked_count is not None and asked_count <= 0:
        return NO_HELPER_TO_ASK, [f"{target}{won}을 아직 {w.not_done}.", NO_HELPER_HINT]
    return "조력자에게 물어봐요", [f"{target}{won}을 {w.before} 전에 조력자에게 물어봐요.",
                                   f"아직 {w.not_done}."]


__all__ = [
    "ANOMALY_FEATURE_GROUPS", "ASK_HELPER_LABEL", "CHOICES", "COMMON_QUESTION", "ChannelWords",
    "FORBIDDEN_WORDS", "MAX_LINES", "MAX_LINE_LEN", "MAX_TITLE_LEN", "NO_HELPER_HINT", "NO_HELPER_TO_ASK",
    "PAST_QUESTION", "PICTOGRAMS",
    "SIGNAL_ORDER", "build_card", "card_choices", "card_question", "channel_words", "compose_parts",
    "format_time_kr", "format_won", "make_speak_text", "practice_result", "readability_issues",
    "render_card", "to_whom",
]
