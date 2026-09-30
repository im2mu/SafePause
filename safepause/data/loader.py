"""거래내역 CSV 가져오기.

- SafePause 표준 CSV(열: id,ts,amount,direction,channel,...)면 그대로 읽는다.
- 그 밖의 CSV는 한국어 머리글(열 이름)을 보고 자동으로 짝을 짓는다. 특정 금융기관 양식을
  지원한다는 뜻이 아니다(실제 양식으로 시험한 적 없음). 머리글을 모르면 ``mapping``으로 지정한다.
- 인코딩은 utf-8-sig → cp949 순서로 시도한다.
- 거래 종류(channel)·회선·상대 식별값은 글자를 보고 추정하며, 추정했다는 사실을 리포트
  ``warnings``에 남긴다.

``mapping`` 형식(값은 파일의 열 이름. counterparty는 여러 열을 리스트로 줄 수 있음)::

    {
      "datetime": "거래일시",          # 날짜+시각이 한 열에 있을 때
      "date": "거래일자", "time": "거래시간",  # 따로 있을 때(time은 없어도 됨)
      "out_amount": "출금액", "in_amount": "입금액",  # 출금/입금 두 열
      "amount": "금액", "kind": "구분",  # 금액 한 열 + 입출금 구분 열
      "default_direction": "out",      # 구분 열이 없고 금액이 모두 양수일 때 방향
      "counterparty": ["내용"], "memo": "적요", "merchant": "가맹점명",
      "counterparty_id": "상대계좌번호", "line": "전화번호"
    }
"""
from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from datetime import datetime, time
from pathlib import Path
from typing import Any

from safepause.data.synth import (
    AMOUNT_LIMIT,
    MAX_YEAR,
    MIN_YEAR,
    REQUIRED_STANDARD_COLUMNS,
    DateRangeError,
    txn_from_standard_row,
)
from safepause.models import Channel, Direction, Transaction

ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp949")
HEADER_SCAN_ROWS = 30          # 머리글을 찾을 때 훑어보는 앞쪽 행 수
DEFAULT_TIME = time(12, 0)     # 시각이 없을 때 쓰는 값
MAX_REPORTED_SKIPS = 20
_RANGE_REASON = f"날짜가 {MIN_YEAR}~{MAX_YEAR}년 밖"
_BOM = chr(0xFEFF)          # UTF-8 BOM 글자

COLUMN_KEYS: tuple[str, ...] = (
    "datetime", "date", "time", "out_amount", "in_amount", "amount", "kind",
    "counterparty", "counterparty_id", "memo", "merchant", "line",
)
_OPTION_KEYS: tuple[str, ...] = ("default_direction",)

# 자동 매핑 후보(앞에 있을수록 우선). 정규화된 머리글(공백·괄호 제거)과 비교한다.
_AUTO: dict[str, tuple[str, ...]] = {
    "datetime": ("거래일시", "일시", "날짜"),
    "date": ("거래일자",),
    "time": ("거래시간", "시간", "시각"),
    "out_amount": ("출금액", "출금금액"),
    "in_amount": ("입금액", "입금금액"),
    "amount": ("금액", "거래금액"),
    "kind": ("구분", "입출금구분", "거래구분"),
    "counterparty": ("받는분", "보낸분", "거래처", "가맹점명", "내용", "적요"),
    "memo": ("메모", "비고", "적요"),
    "merchant": ("가맹점명",),
    "counterparty_id": ("상대계좌번호", "상대계좌", "계좌번호", "가맹점번호"),
    "line": ("회선", "회선번호", "전화번호", "휴대폰번호"),
}

_CHANNEL_KO = {
    Channel.TRANSFER: "이체", Channel.CARD: "카드", Channel.MICROPAY: "소액결제",
    Channel.TELECOM_BILL: "통신요금", Channel.ATM: "현금 인출", Channel.INCOME: "입금",
    Channel.OTHER: "기타",
}

# 거래 종류 추정 규칙(SPEC §4). 카드 낱말 규칙은 가맹점명 열이 없는 파일을 위한 보완이다.
_MICROPAY_RE = re.compile(r"소액결제|휴대폰결제")
_TELECOM_RE = re.compile(
    r"통신|(?<![A-Za-z])(?:SKT|KT|LG\s?U\+)(?![A-Za-z])|(?<!전기|수도|가스|난방|버스|택시|주차)요금",
    re.IGNORECASE,
)
_ATM_RE = re.compile(r"ATM|현금", re.IGNORECASE)
_CARD_RE = re.compile(r"체크카드|신용카드|카드결제|카드승인")
_PHONE_RE = re.compile(r"(01[016789])[-\s.]?(\d{3,4}|\*{3,4})[-\s.]?(\d{4})")
# 회선 열이 없을 때 통신요금의 회선을 가르는 통신사 이름(글자 전체 대신 이것만 쓴다)
_CARRIER_RE = re.compile(
    r"(?<![A-Za-z])(?:(?P<skt>SKT|SK\s?텔레콤)|(?P<lgu>LG\s?U\+|LG\s?유플러스|엘지\s?유플러스)|(?P<kt>KT))(?![A-Za-z])",
    re.IGNORECASE,
)
_CARRIER_NAMES = {"skt": "SKT", "lgu": "LG U+", "kt": "KT"}
# 통신사 이름이 없을 때 적요에서 빼는 달마다 바뀌는 글자(예: '9월', '2026년', '10/25')
_BILL_PERIOD_RE = re.compile(r"\d+\s*(?:년|월|일|회차)?|[/.\-]")

_IN_WORDS = ("입금", "입")
_OUT_WORDS = ("출금", "지급", "출", "결제", "이체", "인출", "송금")


class LoaderError(ValueError):
    """거래내역을 읽을 수 없을 때(한국어 안내 포함)."""


_MAPPING_HINT = (
    '열 이름을 mapping으로 알려 주세요. 예: {"datetime": "거래일시", "out_amount": "출금액", '
    '"in_amount": "입금액", "counterparty": "내용", "memo": "적요"}'
)


def load_csv(path_or_text: str | Path | bytes,
             mapping: dict[str, Any] | None = None) -> tuple[list[Transaction], dict[str, Any]]:
    """거래내역 CSV를 읽어 (거래 목록(시간순), 리포트)를 돌려준다.

    ``path_or_text``: 파일 경로(str/Path), CSV 글(str, 줄바꿈 포함), 또는 파일 내용(bytes).
    리포트: ``{"rows", "loaded", "skipped", "format", "encoding", "header_row", "mapping",
    "warnings", "skipped_rows"}``.
    """
    text, encoding = _read_text(path_or_text)
    table = _parse_table(text)
    if not table:
        raise LoaderError("파일이 비어 있어요.")
    if mapping is not None:
        _validate_mapping(mapping)

    header_idx, fmt = _find_header(table, mapping)
    header = [_clean_header(h) for h in table[header_idx]]
    body = [(header_idx + 2 + k, row) for k, row in enumerate(table[header_idx + 1:])]
    body = [(n, row) for n, row in body if any(c.strip() for c in row)]  # 빈 줄 제외

    if fmt == "standard":
        txns, skipped, warnings, used = _load_standard(header, body)
    else:
        cols = _resolve_columns(header, mapping)
        txns, skipped, warnings = _load_mapped(header, body, cols, mapping or {})
        used = {k: v for k, v in cols.items() if v}
        if mapping and mapping.get("default_direction"):
            used["default_direction"] = str(mapping["default_direction"])

    if _is_newest_first(txns):
        # 최신순 파일: 같은 시각(날짜만 있는 파일은 모두 낮 12시) 거래도 오래된 것이 먼저 오게 뒤집은 뒤 정렬
        txns = txns[::-1]
        warnings.append("최근 거래가 위에 있는 파일이라 아래 줄부터 시간 순서대로 다시 정렬했어요. "
                        "같은 시각의 거래도 아래 줄을 먼저 일어난 것으로 봤어요.")
    ordered = sorted(txns, key=lambda t: t.ts)   # 안정 정렬: 같은 시각은 위 순서 유지
    if [t.id for t in ordered] != [t.id for t in txns]:
        warnings.append("거래를 시간 순서대로 다시 정렬했어요.")
    if fmt != "standard":  # 가져온 거래 id는 시간순 번호
        for k, t in enumerate(ordered, start=1):
            t.id = f"imp-{k:05d}"
    if header_idx > 0:
        warnings.append(f"{header_idx + 1}번째 줄을 머리글로 보고, 그 위 {header_idx}줄은 건너뛰었어요.")
    if skipped:
        shown = ", ".join(f"{n}번째 줄({why})" for n, why in skipped[:MAX_REPORTED_SKIPS])
        more = f" 외 {len(skipped) - MAX_REPORTED_SKIPS}줄" if len(skipped) > MAX_REPORTED_SKIPS else ""
        warnings.append(f"읽지 못한 {len(skipped)}줄을 건너뛰었어요: {shown}{more}")

    report: dict[str, Any] = {
        "rows": len(body),
        "loaded": len(ordered),
        "skipped": len(skipped),
        "format": fmt,
        "encoding": encoding,
        "header_row": header_idx + 1,
        "mapping": used,
        "warnings": warnings,
        "skipped_rows": [n for n, _ in skipped[:MAX_REPORTED_SKIPS]],
    }
    return ordered, report


# ---------------------------------------------------------------------------
# 읽기·머리글
# ---------------------------------------------------------------------------

def _read_text(src: str | Path | bytes) -> tuple[str, str]:
    """(글, 인코딩 이름). 줄바꿈이 있는 str은 CSV 글 자체로 본다."""
    if isinstance(src, (bytes, bytearray)):
        data = bytes(src)
    elif isinstance(src, str) and ("\n" in src or "\r" in src):
        return src.lstrip(_BOM), "text"
    else:
        path = Path(src)
        if not path.is_file():
            raise LoaderError(f"파일을 찾을 수 없어요: {path}")
        data = path.read_bytes()
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise LoaderError("글자 인코딩을 알 수 없어요. UTF-8 또는 CP949(EUC-KR)로 저장해 주세요.")


def _parse_table(text: str) -> list[list[str]]:
    lines = [ln for ln in text.splitlines() if ln.strip()][:5]
    sample = "\n".join(lines)
    delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    try:
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    except csv.Error as exc:  # 한 칸이 너무 길거나(13만 자 초과) 따옴표가 깨진 파일
        raise LoaderError("CSV 모양을 읽지 못했어요. 한 칸의 글이 너무 길거나 따옴표가 잘못됐을 수 있어요. "
                          "은행 등에서 내려받은 CSV 파일이 맞는지 확인해 주세요.") from exc


def _clean_header(name: str) -> str:
    """'출금액(원)', ' 거래 일시 ' → '출금액', '거래일시'."""
    name = name.replace(_BOM, "")
    name = re.sub(r"[\(\[].*?[\)\]]", "", name)
    return re.sub(r"\s+", "", name)


def _find_header(table: list[list[str]], mapping: dict[str, Any] | None) -> tuple[int, str]:
    for idx, row in enumerate(table[:HEADER_SCAN_ROWS]):
        cells = {_clean_header(c) for c in row if c.strip()}
        if not cells:
            continue
        if mapping is not None:
            wanted = {_clean_header(c) for c in _mapping_columns(mapping)}
            if wanted and wanted <= cells:
                return idx, "mapped"
            continue
        if all(c in cells for c in REQUIRED_STANDARD_COLUMNS):
            return idx, "standard"
        has_time = any(c in cells for c in _AUTO["datetime"] + _AUTO["date"])
        has_pair = any(c in cells for c in _AUTO["out_amount"]) and any(c in cells for c in _AUTO["in_amount"])
        has_amount = any(c in cells for c in _AUTO["amount"])
        if has_time and (has_pair or has_amount):
            return idx, "mapped"
    if mapping is not None:
        missing = sorted({_clean_header(c) for c in _mapping_columns(mapping)}
                         - {_clean_header(c) for row in table[:HEADER_SCAN_ROWS] for c in row})
        raise LoaderError(f"mapping에 적은 열을 파일에서 찾지 못했어요: {', '.join(missing) or '(머리글 줄 없음)'}")
    raise LoaderError("머리글(열 이름)을 알아보지 못했어요. " + _MAPPING_HINT)


def _validate_mapping(mapping: dict[str, Any]) -> None:
    unknown = [str(k) for k in mapping if k not in COLUMN_KEYS and k not in _OPTION_KEYS]
    if unknown:
        raise LoaderError(f"mapping에 알 수 없는 항목이 있어요: {', '.join(unknown)}. "
                          f"쓸 수 있는 항목: {', '.join(COLUMN_KEYS + _OPTION_KEYS)}")
    for key in COLUMN_KEYS:
        value = mapping.get(key)
        if value is None or isinstance(value, str):
            continue
        # 상대(counterparty)만 여러 열을 리스트로 줄 수 있다
        if key == "counterparty" and isinstance(value, list) and all(isinstance(v, str) for v in value):
            continue
        raise LoaderError(f"mapping의 '{key}' 값은 열 이름(글자)이어야 해요."
                          + (' 여러 열은 ["열1", "열2"]처럼 써요.' if key == "counterparty" else ""))
    direction = mapping.get("default_direction")
    if direction is not None and not isinstance(direction, str):
        raise LoaderError('default_direction은 "out" 또는 "in"이어야 해요.')
    has_time = mapping.get("datetime") or mapping.get("date")
    has_amount = (mapping.get("out_amount") and mapping.get("in_amount")) or mapping.get("amount")
    if not has_time or not has_amount:
        raise LoaderError("mapping에는 일시(datetime 또는 date)와 금액(out_amount+in_amount 또는 amount)이 "
                          "꼭 있어야 해요. " + _MAPPING_HINT)
    direction = mapping.get("default_direction")
    if direction and str(direction) not in ("out", "in"):
        raise LoaderError('default_direction은 "out" 또는 "in"이어야 해요.')


def _mapping_columns(mapping: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in COLUMN_KEYS:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            out.append(value)
        elif isinstance(value, (list, tuple)):
            out.extend(str(v) for v in value if v)
    return out


def _resolve_columns(header: list[str], mapping: dict[str, Any] | None) -> dict[str, Any]:
    """정식 항목 → 열 이름(counterparty는 열 이름 리스트)."""
    present = set(header)
    cols: dict[str, Any] = {}
    if mapping is not None:
        for key in COLUMN_KEYS:
            value = mapping.get(key)
            if isinstance(value, (list, tuple)):
                cols[key] = [_clean_header(str(v)) for v in value if v] or None
            else:
                cols[key] = _clean_header(value) if value else None
        if isinstance(cols.get("counterparty"), str):
            cols["counterparty"] = [cols["counterparty"]]
        if not cols["datetime"]:
            cols["datetime"], cols["date"] = cols["date"], None
        return cols

    def first(key: str) -> str | None:
        return next((c for c in _AUTO[key] if c in present), None)

    for key in ("datetime", "date", "time", "out_amount", "in_amount", "amount", "kind",
                "memo", "merchant", "counterparty_id", "line"):
        cols[key] = first(key)
    # 일시 열은 하나만 쓴다. 그 열에 시각이 없으면 시각 열(있으면)로 채운다.
    cols["datetime"] = cols["datetime"] or cols["date"]
    cols["date"] = None
    if cols["out_amount"] and cols["in_amount"]:
        cols["amount"] = cols["kind"] = None
    else:
        cols["out_amount"] = cols["in_amount"] = None
    # 상대: 메모로 쓰는 열은 다른 후보가 없을 때만 마지막에 쓴다(예: 적요는 메모, 내용은 상대).
    cps = [c for c in _AUTO["counterparty"] if c in present and c != cols["memo"]]
    if cols["memo"] and cols["memo"] in _AUTO["counterparty"]:
        cps.append(cols["memo"])
    cols["counterparty"] = cps or None
    return cols


# ---------------------------------------------------------------------------
# 표준 CSV
# ---------------------------------------------------------------------------

def _load_standard(header: list[str], body: list[tuple[int, list[str]]]):
    txns: list[Transaction] = []
    skipped: list[tuple[int, str]] = []
    seen: set[str] = set()
    dup = 0
    for line_no, row in body:
        record = {h: (row[i] if i < len(row) else "") for i, h in enumerate(header)}
        try:
            t = txn_from_standard_row(record)
        except DateRangeError:
            skipped.append((line_no, _RANGE_REASON))
            continue
        except (KeyError, ValueError, OverflowError):
            skipped.append((line_no, "형식 오류"))
            continue
        if not t.id or t.id in seen:
            base, k = t.id or "row", 2
            while f"{base}-{k}" in seen:
                k += 1
            t.id = f"{base}-{k}"
            dup += 1
        seen.add(t.id)
        txns.append(t)
    warnings: list[str] = []
    if dup:
        warnings.append(f"id가 비었거나 겹치는 거래 {dup}건에 새 id를 붙였어요.")
    return txns, skipped, warnings, {c: c for c in header if c}


# ---------------------------------------------------------------------------
# 한국어 머리글 CSV
# ---------------------------------------------------------------------------

def _load_mapped(header: list[str], body: list[tuple[int, list[str]]],
                 cols: dict[str, Any], mapping: dict[str, Any]):
    index = {h: i for i, h in reversed(list(enumerate(header)))}  # 같은 이름이면 앞 열

    def cell(row: list[str], col: str | None) -> str:
        if not col or col not in index:
            return ""
        i = index[col]
        return row[i].strip() if i < len(row) else ""

    signed = False
    if cols.get("amount") and not cols.get("kind") and not mapping.get("default_direction"):
        signed = any((_parse_amount(cell(r, cols["amount"])) or 0) < 0 for _, r in body)
        if not signed:
            raise LoaderError("금액 열만 있고 입금·출금을 나누는 '구분' 열이 없어요. "
                              'mapping에 "kind"(구분 열) 또는 "default_direction"("out"/"in")을 지정해 주세요.')

    text_cols = list(dict.fromkeys(
        [*(cols.get("counterparty") or []), cols.get("memo"), cols.get("merchant")]
    ))
    text_cols = [c for c in text_cols if c]

    txns: list[Transaction] = []
    skipped: list[tuple[int, str]] = []
    channel_count: Counter[Channel] = Counter()
    no_time = 0
    tel_without_line = 0
    card_by_word = 0

    for line_no, row in body:
        ts, had_time = _row_datetime(row, cols, cell)
        if ts is None:
            skipped.append((line_no, "날짜"))
            continue
        if not MIN_YEAR <= ts.year <= MAX_YEAR:   # 0001-01-01 같은 빈 날짜 대용값
            skipped.append((line_no, _RANGE_REASON))
            continue
        direction, amount, why = _row_amount(row, cols, cell, mapping, signed)
        if direction is None:
            skipped.append((line_no, why))
            continue
        if not had_time:
            no_time += 1

        counterparty = next((v for v in (cell(row, c) for c in cols.get("counterparty") or []) if v), "")
        memo = cell(row, cols.get("memo"))
        if memo == counterparty:
            memo = ""
        text = " ".join(v for v in (cell(row, c) for c in text_cols) if v)
        has_merchant = bool(cell(row, cols.get("merchant")))
        channel = _infer_channel(direction, text, has_merchant)
        if channel == Channel.CARD and not has_merchant:
            card_by_word += 1

        counterparty_id = cell(row, cols.get("counterparty_id")) or _name_key(counterparty)
        line_id = ""
        if channel in (Channel.TELECOM_BILL, Channel.MICROPAY):
            line_id = _mask_phone(cell(row, cols.get("line"))) or _find_phone(text)
            if not line_id and channel == Channel.TELECOM_BILL:
                line_id = f"통신사:{_carrier_key(text) or _name_key(_BILL_PERIOD_RE.sub(' ', counterparty)) or '알수없음'}"
                tel_without_line += 1

        channel_count[channel] += 1
        txns.append(Transaction(
            id=f"row-{line_no}", ts=ts, amount=amount, direction=direction, channel=channel,
            counterparty=counterparty, counterparty_id=counterparty_id, line_id=line_id,
            memo=memo, label=None,
        ))

    warnings: list[str] = []
    if txns:
        summary = ", ".join(f"{_CHANNEL_KO[c]} {n}건" for c, n in channel_count.most_common())
        warnings.append("거래 종류(카드·이체·소액결제 등)는 적요·내용 글자를 보고 추정했어요. "
                        f"틀릴 수 있어요. 추정 결과: {summary}")
    if card_by_word:
        warnings.append(f"가맹점명 열이 없어 '체크카드' 같은 글자로 카드결제 {card_by_word}건을 추정했어요.")
    if txns and not cols.get("counterparty_id"):
        warnings.append("상대 계좌 열이 없어, 이름이 같으면 같은 상대로 봤어요(추정).")
    if tel_without_line:
        warnings.append(f"통신요금 {tel_without_line}건은 회선 정보가 없어, 통신사 이름으로 회선을 구분했어요(추정).")
    if no_time:
        warnings.append(f"시각이 없는 거래 {no_time}건은 낮 12시로 두었어요. 밤 시간 판단이 정확하지 않을 수 있어요.")
    if signed:
        warnings.append("'구분' 열이 없어 금액 부호로 입금·출금을 나눴어요(음수=출금, 양수=입금, 추정).")
    return txns, skipped, warnings


def _row_datetime(row, cols, cell) -> tuple[datetime | None, bool]:
    """(일시, 시각이 실제로 있었는지). 시각이 없으면 DEFAULT_TIME."""
    parsed, had_time = _parse_datetime(cell(row, cols.get("datetime")))
    if parsed is None or had_time:
        return parsed, had_time
    t = _parse_time(cell(row, cols.get("time"))) if cols.get("time") else None
    if t is None:
        return datetime.combine(parsed.date(), DEFAULT_TIME), False
    return datetime.combine(parsed.date(), t), True


def _row_amount(row, cols, cell, mapping, signed) -> tuple[Direction | None, int, str]:
    if cols.get("out_amount") and cols.get("in_amount"):
        out_v = _parse_amount(cell(row, cols["out_amount"]))
        in_v = _parse_amount(cell(row, cols["in_amount"]))
        out_v, in_v = abs(out_v or 0), abs(in_v or 0)
        if out_v and in_v:
            return None, 0, "입금·출금이 함께 있음"
        if out_v:
            return Direction.OUT, out_v, ""
        if in_v:
            return Direction.IN, in_v, ""
        return None, 0, "금액"
    value = _parse_amount(cell(row, cols.get("amount")))
    if not value:
        return None, 0, "금액"
    if cols.get("kind"):
        direction = _parse_kind(cell(row, cols["kind"]))
        if direction is None:
            return None, 0, "구분"
        return direction, abs(value), ""
    if signed:
        return (Direction.OUT if value < 0 else Direction.IN), abs(value), ""
    return Direction(str(mapping["default_direction"])), abs(value), ""


# ---------------------------------------------------------------------------
# 값 해석
# ---------------------------------------------------------------------------

_DT_RE = re.compile(
    r"^\s*(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?:\s*일|\.)?"
    r"(?:[\sT]+(오전|오후)?\s*(\d{1,2})\s*[:시]\s*(\d{1,2})\s*분?(?:\s*:?\s*(\d{1,2})\s*초?)?)?"
)


def _parse_datetime(text: str) -> tuple[datetime | None, bool]:
    """(일시, 시각 포함 여부). 못 읽으면 (None, False)."""
    s = text.strip()
    if not s:
        return None, False
    digits = re.sub(r"\D", "", s)
    try:
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d"), False
        if re.fullmatch(r"\d{8}\s*\d{4,6}", s) and len(digits) in (12, 14):
            fmt = "%Y%m%d%H%M%S" if len(digits) == 14 else "%Y%m%d%H%M"
            return datetime.strptime(digits, fmt), True
        m = _DT_RE.match(s)
        if not m:
            return None, False
        y, mo, d, ampm, hh, mm, ss = m.groups()
        if hh is None:
            return datetime(int(y), int(mo), int(d)), False
        hour = int(hh)
        if ampm == "오후" and hour < 12:
            hour += 12
        elif ampm == "오전" and hour == 12:
            hour = 0
        return datetime(int(y), int(mo), int(d), hour, int(mm), int(ss or 0)), True
    except ValueError:
        return None, False


def _parse_time(text: str) -> time | None:
    s = text.strip()
    if not s:
        return None
    m = re.fullmatch(r"(오전|오후)?\s*(\d{1,2})\s*[:시]\s*(\d{1,2})\s*분?(?:\s*:?\s*(\d{1,2})\s*초?)?", s)
    if m:
        ampm, hh, mm, ss = m.groups()
    elif re.fullmatch(r"\d{4}|\d{6}", s):
        hh, mm, ss, ampm = s[0:2], s[2:4], (s[4:6] or None), None
    else:
        return None
    hour = int(hh)
    if ampm == "오후" and hour < 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0
    try:
        return time(hour, int(mm), int(ss or 0))
    except ValueError:
        return None


def _parse_amount(text: str) -> int | None:
    """'1,234원', '₩ 5,000', '-3,000', '(3,000)' → 정수. 비었거나 '-'면 0, 못 읽으면 None."""
    s = text.strip().replace(",", "").replace("원", "").replace("₩", "").replace(" ", "")
    if s in ("", "-"):
        return 0
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").lstrip("+")
    try:
        number = float(s)
    except ValueError:
        return None
    if not math.isfinite(number) or abs(number) >= AMOUNT_LIMIT:  # "1e400", "nan" 등
        return None
    value = int(round(number))
    return -abs(value) if negative else value


def _parse_kind(text: str) -> Direction | None:
    s = text.replace(" ", "")
    if not s:
        return None
    if any(w in s for w in _IN_WORDS) and "출" not in s:
        return Direction.IN
    if any(w in s for w in _OUT_WORDS):
        return Direction.OUT
    return None


def _infer_channel(direction: Direction, text: str, has_merchant: bool) -> Channel:
    """SPEC §4 추정 규칙."""
    if direction == Direction.IN:
        return Channel.INCOME  # 급여·수당 등 모든 입금
    if _MICROPAY_RE.search(text):
        return Channel.MICROPAY
    if _TELECOM_RE.search(text):
        return Channel.TELECOM_BILL
    if _ATM_RE.search(text):
        return Channel.ATM
    if has_merchant or _CARD_RE.search(text):
        return Channel.CARD
    return Channel.TRANSFER


def _is_newest_first(txns: list[Transaction]) -> bool:
    """파일이 최신순(내림차순)인지. 이웃한 행의 시각이 내려가는 쌍이 올라가는 쌍보다 많으면 참.

    같으면 첫 행이 마지막 행보다 늦은지로 정한다(날짜만 있어 같은 시각이 많은 파일).
    """
    down = sum(1 for a, b in zip(txns, txns[1:]) if a.ts > b.ts)
    up = sum(1 for a, b in zip(txns, txns[1:]) if a.ts < b.ts)
    if down != up:
        return down > up
    return len(txns) > 1 and txns[0].ts > txns[-1].ts


def _carrier_key(text: str) -> str:
    """글에서 통신사 이름(SKT·KT·LG U+)을 찾는다. 없으면 빈 글."""
    m = _CARRIER_RE.search(text)
    if not m:
        return ""
    return next(_CARRIER_NAMES[k] for k, v in m.groupdict().items() if v)


def _name_key(name: str) -> str:
    """상대 식별값이 없을 때 이름을 식별값으로 쓴다(공백 정리)."""
    return re.sub(r"\s+", " ", name).strip()


def _find_phone(text: str) -> str:
    m = _PHONE_RE.search(text)
    return f"{m.group(1)}-****-{m.group(3)}" if m else ""


def _mask_phone(text: str) -> str:
    """전화번호는 가운데를 가려 저장한다(010-****-1234). 번호 모양이 아니면 그대로."""
    if not text:
        return ""
    return _find_phone(text) or text.strip()


__all__ = ["load_csv", "LoaderError", "COLUMN_KEYS", "ENCODINGS"]
