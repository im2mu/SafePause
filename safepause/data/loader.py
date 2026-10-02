"""거래내역 CSV·엑셀(.xlsx) 가져오기.

- SafePause 표준 CSV(열: id,ts,amount,direction,channel,...)면 그대로 읽는다.
- 그 밖의 CSV는 한국어 머리글(열 이름)을 보고 자동으로 짝을 짓는다. 특정 금융기관 양식을
  지원한다는 뜻이 아니다(실제 양식으로 시험한 적 없음). 머리글을 모르면 ``mapping``으로 지정한다.
- 인코딩: 파일 앞이 FF FE / FE FF(BOM)면 UTF-16, 아니면 utf-8-sig → cp949 순서로 시도한다.
  엑셀(.xlsx)은 첫 시트를 CSV 글로 바꿔 같은 방법으로 읽는다(data.xlsx, 표준 라이브러리만, v0.3 수정 AUG-02).
  옛 엑셀(.xls)·PDF·사진·HTML 파일은 앞 바이트(또는 글)로 알아보고 맞는 안내를 한다.
- 구분자: 쉼표·탭·세미콜론·세로줄(|)을 하나씩 써 보고, 머리글을 찾은 구분자를 쓴다.
- 거래 종류(channel)·상대 식별값은 글자를 보고 추정하며, 추정했다는 사실을 리포트
  ``warnings``에 남긴다. 회선 번호(전화번호)를 알 수 없는 통신요금은 회선을 비워 둔다.
- 합계·소계 줄, 취소 거래('취소' 글자·출금 칸 음수)는 건너뛰고 ``warnings``에 남긴다.
  모든 줄을 건너뛰면 건너뛴 이유(최대 3가지)를 담은 LoaderError를 낸다.

``mapping`` 형식(값은 파일의 열 이름. counterparty는 여러 열을 리스트로 줄 수 있음)::

    {
      "datetime": "거래일시",          # 날짜+시각이 한 열에 있을 때
      "date": "거래일자", "time": "거래시간",  # 따로 있을 때(time은 없어도 됨)
      "out_amount": "출금액", "in_amount": "입금액",  # 출금/입금 두 열
      "amount": "금액", "kind": "구분",  # 금액 한 열 + 입출금 구분 열
      "default_direction": "out",      # 구분 열이 없고 금액이 모두 양수일 때 방향
      "date_format": "%m/%d/%Y",       # 날짜 모양이 다를 때(strptime 형식, 칸 전체와 맞아야 함)
      "counterparty": ["내용"], "memo": "적요", "merchant": "가맹점명",
      "counterparty_id": "상대계좌번호", "line": "전화번호"
    }

열 이름 없이 ``{"date_format": ...}``·``{"default_direction": ...}``만 주면 열은 자동으로 찾고
그 설정만 쓴다.
"""
from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from safepause.data.synth import (
    AMOUNT_LIMIT,
    MAX_YEAR,
    MIN_YEAR,
    REQUIRED_STANDARD_COLUMNS,
    AmountError,
    DateRangeError,
    round_amount,
    txn_from_standard_row,
)
from safepause.data.xlsx import XlsxError, is_zip, xlsx_to_csv_text
from safepause.models import Channel, Direction, Transaction

ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp949")
DELIMITERS: tuple[str, ...] = (",", "\t", ";", "|")   # 머리글을 찾을 때 써 보는 순서
HEADER_SCAN_ROWS = 30          # 머리글을 찾을 때 훑어보는 앞쪽 행 수
DEFAULT_TIME = time(12, 0)     # 시각이 없을 때 쓰는 값
MAX_REPORTED_SKIPS = 20
MAX_ERROR_REASONS = 3          # 모두 건너뛰었을 때 오류 문구에 담는 이유 수
_RANGE_REASON = f"날짜가 {MIN_YEAR}~{MAX_YEAR}년 밖"
_BOM = chr(0xFEFF)          # UTF-8 BOM 글자

# 건너뛴 이유(리포트 warnings·오류 문구에 그대로 나간다)
_R_DATE = "날짜를 읽지 못함"
_R_AMOUNT = "금액을 읽지 못함"
_R_NO_AMOUNT = "금액이 비었거나 0원"
_R_BOTH = "입금·출금이 함께 있음"
_R_KIND = "입금·출금 구분을 읽지 못함"
_R_TOTAL = "합계·소계 줄"
_R_CANCEL = "취소 거래"
_R_NEGATIVE = "취소로 보이는 음수 금액"
_R_NONPOSITIVE = "금액이 0원 이하"
_R_FORMAT = "형식 오류"

COLUMN_KEYS: tuple[str, ...] = (
    "datetime", "date", "time", "out_amount", "in_amount", "amount", "kind",
    "counterparty", "counterparty_id", "memo", "merchant", "line",
)
_OPTION_KEYS: tuple[str, ...] = ("default_direction", "date_format")

# 자동 매핑 후보(앞에 있을수록 우선). 정규화된 머리글(공백·괄호 제거: '출금(원)'→'출금')과 비교한다.
_AUTO: dict[str, tuple[str, ...]] = {
    "datetime": ("거래일시", "일시", "날짜", "이용일시", "승인일시", "거래날짜"),
    "date": ("거래일자", "이용일자", "승인일자", "거래일", "이용일", "일자"),
    "time": ("거래시간", "시간", "시각", "이용시간", "승인시간", "거래시각"),
    "out_amount": ("출금액", "출금금액", "출금", "지급액", "지급금액", "지급", "찾으신금액", "인출금액"),
    "in_amount": ("입금액", "입금금액", "입금", "맡기신금액"),
    "amount": ("금액", "거래금액", "이용금액", "승인금액"),
    "kind": ("구분", "입출금구분", "거래구분"),
    # 상대 이름. '보낸분/받는분'처럼 '/'가 든 머리글은 나눠서 비교한다.
    # 적요(모바일이체·체크카드 같은 거래 종류 글자)는 상대로 쓰지 않는다(mapping으로 지정하면 씀).
    "counterparty": ("받는분", "보낸분", "받는사람", "보낸사람", "수취인", "수취인명", "상대방", "상대방명",
                     "거래처", "거래처명", "가맹점명", "가맹점", "이용가맹점", "내용", "거래내용", "기재내용"),
    "memo": ("메모", "비고", "적요"),
    "merchant": ("가맹점명", "가맹점", "이용가맹점"),
    "counterparty_id": ("상대계좌번호", "상대계좌", "계좌번호", "가맹점번호"),
    "line": ("회선", "회선번호", "전화번호", "휴대폰번호"),
}
# 카드 이용내역의 금액 열: 구분 열이 없으면 모두 쓴 돈(출금)으로 본다(음수는 취소로 보고 건너뜀)
_CARD_AMOUNT_COLUMNS: tuple[str, ...] = ("이용금액", "승인금액")

_CHANNEL_KO = {
    Channel.TRANSFER: "이체", Channel.CARD: "카드", Channel.MICROPAY: "소액결제",
    Channel.TELECOM_BILL: "통신요금", Channel.ATM: "현금 인출", Channel.INCOME: "입금",
    Channel.OTHER: "기타",
}

# 거래 종류 추정 규칙(SPEC §4). 카드 낱말 규칙은 가맹점명 열이 없는 파일을 위한 보완이다.
_MICROPAY_RE = re.compile(r"소액결제|휴대폰결제")
# 통신요금: 통신사 이름(알뜰폰 브랜드, 'OO통신'·'OO텔레콤' 회사 이름 포함)이나 통신·휴대폰·인터넷 요금 낱말일 때만.
# 'KT&G'(케이티앤지), '통신판매', '정보통신'·'전자통신' 회사, 통행요금·택배요금·렌탈요금은 통신요금이 아니다.
_TELECOM_RE = re.compile(
    r"(?:통신|휴대폰|핸드폰|휴대전화|전화|인터넷)\s*(?:요금|사용료)|통신비|알뜰폰"
    r"|(?<![A-Za-z])(?:SKT|KT(?!\s*&)|LG\s?U\+|LGU\+)(?![A-Za-z])"
    r"|SK\s?텔레콤|SK\s?브로드밴드|SK\s?텔링크|에스케이\s?텔레콤|케이티(?!\s*앤\s*지)"
    r"|LG\s?유플러스|엘지\s?유플러스|유플러스|U\+\s?(?:알뜰)?모바일"
    r"|헬로모바일|세븐모바일|리브\s?모바일|리브엠|토스\s?모바일|이야기\s?모바일"
    r"|[가-힣A-Za-z]+(?<!정보)(?<!전자)(?:통신|텔레콤)(?![가-힣])",
    re.IGNORECASE,
)
_ATM_RE = re.compile(r"ATM|현금(?!영수증)", re.IGNORECASE)
_CARD_RE = re.compile(r"체크카드|신용카드|카드결제|카드승인")
# 휴대폰 번호: 010-1234-5678, 010-****-5678, +82 10-1234-5678, 82-10-1234-5678, +82(0)10…
_PHONE_RE = re.compile(
    r"(?:(?<!\d)\+?82[-\s.]?(?:\(0\)[-\s.]?|0)?|0)(1[016789])[-\s.]?(\d{3,4}|\*{3,4})[-\s.]?(\d{4})"
)
_TOTAL_WORDS: tuple[str, ...] = ("합계", "소계")
_RANGE_MARKS: tuple[str, ...] = ("~", "～", "〜")

_IN_WORDS = ("입금", "입")
_OUT_WORDS = ("출금", "지급", "출", "결제", "이체", "인출", "송금")


class LoaderError(ValueError):
    """거래내역을 읽을 수 없을 때(한국어 안내 포함)."""


_MAPPING_HINT = (
    '열 이름을 mapping으로 알려 주세요. 예: {"datetime": "거래일시", "out_amount": "출금액", '
    '"in_amount": "입금액", "counterparty": "내용", "memo": "적요"}'
)
_DATE_FORMAT_HINT = ' 날짜 모양이 다르면 mapping에 날짜 모양을 적어 주세요. 예: {"date_format": "%m/%d/%Y"}'
_KIND_HINT = 'mapping에 "kind"(구분 열) 또는 "default_direction"("out"/"in")을 지정해 주세요.'
_COUNTERPARTY_HINT = ' 받는 사람 이름이 든 열이 있으면 mapping의 "counterparty"로 알려 주세요.'
_LINE_HINT = ' 전화번호가 든 열이 있으면 mapping의 "line"으로 알려 주세요.'
# 화면(파일 올리기)은 열 이름을 직접 알려 주지 않는다(v0.3에서 뺌): mapping 안내를 쉬운 말로 바꾸거나 뺀다.
# CLI·API에서 mapping을 쓰는 사람에게는 원래 안내가 그대로 간다.
_PLAIN_HINTS: tuple[tuple[str, str], ...] = (
    (_MAPPING_HINT, "은행 앱이나 인터넷뱅킹에서 내려받은 거래내역 파일인지 확인해 주세요."),
    (_DATE_FORMAT_HINT, " 은행에서 내려받은 그대로의 파일인지 확인해 주세요."),
    (_KIND_HINT, "입금과 출금이 나뉜 거래내역 파일을 올려 주세요."),
    (_COUNTERPARTY_HINT, ""),
    (_LINE_HINT, ""),
)


def plain_message(text: str) -> str:
    """열 이름을 직접 알려 주지 않는 화면용 안내: mapping 안내를 쉬운 말로 바꾸거나 뺀다."""
    out = str(text)
    for hint, plain in _PLAIN_HINTS:
        out = out.replace(hint, plain)
    return out
_SAVE_AS_CSV = ("엑셀에서 [다른 이름으로 저장]을 누르고 파일 형식을 [CSV UTF-8(쉼표로 분리)]로 골라 저장한 뒤 "
                "그 파일을 올려 주세요.")
_EXPORT_HINT = "은행 앱이나 인터넷뱅킹에서 거래내역을 엑셀(.xlsx)이나 CSV 파일로 내려받아 올려 주세요."
_IMAGE_MESSAGE = "사진(이미지) 파일은 읽지 못해요. " + _EXPORT_HINT
# 파일 앞 바이트 → 안내(CSV·엑셀(.xlsx)이 아닌 파일). zip(PK)은 _read_text가 엑셀로 읽어 본다
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (bytes.fromhex("D0CF11E0A1B11AE1"), "옛 엑셀 파일(.xls) 같은 문서 파일은 바로 읽지 못해요. " + _SAVE_AS_CSV),
    (b"%PDF", "PDF 파일은 읽지 못해요. " + _EXPORT_HINT),
    (b"\x89PNG\r\n\x1a\n", _IMAGE_MESSAGE),
    (b"\xff\xd8\xff", _IMAGE_MESSAGE),        # JPEG
    (b"GIF8", _IMAGE_MESSAGE),
)
_MARKUP_MESSAGE = ("웹 페이지(HTML) 모양의 파일이라 바로 읽지 못해요. 이 파일을 엑셀에서 연 뒤 "
                   "[다른 이름으로 저장]에서 [CSV UTF-8(쉼표로 분리)]로 저장해 올려 주세요.")
_MARKUP_TAGS: tuple[str, ...] = ("<html", "<table", "<!doctype", "<?xml", "<head", "<body", "<meta")


def load_csv(path_or_text: str | Path | bytes,
             mapping: dict[str, Any] | None = None) -> tuple[list[Transaction], dict[str, Any]]:
    """거래내역 CSV를 읽어 (거래 목록(시간순), 리포트)를 돌려준다.

    ``path_or_text``: 파일 경로(str/Path), CSV 글(str, 줄바꿈 포함), 또는 파일 내용(bytes).
    리포트: ``{"rows", "loaded", "skipped", "format", "encoding", "header_row", "mapping",
    "warnings", "skipped_rows", "delimiter"}``. 읽은 거래가 하나도 없으면 LoaderError.
    """
    text, encoding = _read_text(path_or_text)
    if not text.strip(" \t\r\n,;|" + _BOM):
        raise LoaderError("파일이 비어 있어요.")
    if mapping is not None:
        _validate_mapping(mapping)
    col_mapping = _column_mapping(mapping)
    options = {k: mapping[k] for k in _OPTION_KEYS if mapping and mapping.get(k)}

    delimiter, header_idx, fmt = _detect_layout(text, col_mapping)
    table = _parse_table(text, delimiter)
    header = [_clean_header(h) for h in table[header_idx]]
    body = [(header_idx + 2 + k, row) for k, row in enumerate(table[header_idx + 1:])]
    body = [(n, row) for n, row in body if any(c.strip() for c in row)]  # 빈 줄 제외

    if fmt == "standard":
        txns, skipped, warnings, used = _load_standard(header, body)
    else:
        cols = _resolve_columns(header, col_mapping)
        txns, skipped, warnings = _load_mapped(header, body, cols, options)
        used = {k: v for k, v in cols.items() if v}
        used.update({k: str(v) for k, v in options.items()})

    if not txns:
        raise LoaderError(_nothing_loaded_message(len(body), skipped))
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
        warnings.append(f"거래로 읽지 않은 {len(skipped)}줄을 건너뛰었어요: {shown}{more}")

    report: dict[str, Any] = {
        "rows": len(body),
        "loaded": len(ordered),
        "skipped": len(skipped),
        "format": fmt,
        "encoding": encoding,
        "delimiter": delimiter,
        "header_row": header_idx + 1,
        "mapping": used,
        "warnings": warnings,
        "skipped_rows": [n for n, _ in skipped[:MAX_REPORTED_SKIPS]],
    }
    return ordered, report


def _nothing_loaded_message(n_rows: int, skipped: list[tuple[int, str]]) -> str:
    """읽은 거래가 없을 때의 안내. 건너뛴 이유를 많은 순서로 최대 3가지 담는다."""
    if not n_rows:
        return "머리글 아래에 거래 줄이 없어요. 거래내역이 든 파일인지 확인해 주세요."
    reasons = Counter(why for _, why in skipped).most_common(MAX_ERROR_REASONS)
    shown = ", ".join(f"{why} {n}줄" for why, n in reasons)
    message = f"읽을 수 있는 거래가 없어요. {n_rows}줄을 모두 건너뛰었어요. 건너뛴 이유: {shown}."
    if reasons and reasons[0][0] == _R_DATE:
        message += _DATE_FORMAT_HINT
    return message


# ---------------------------------------------------------------------------
# 읽기·머리글
# ---------------------------------------------------------------------------

def _read_text(src: str | Path | bytes) -> tuple[str, str]:
    """(글, 인코딩 이름). 줄바꿈이 있는 str은 CSV 글 자체로 본다."""
    if isinstance(src, (bytes, bytearray)):
        data = bytes(src)
    elif isinstance(src, str) and ("\n" in src or "\r" in src):
        text = src.lstrip(_BOM)
        _check_markup(text)
        return text, "text"
    else:
        path = Path(src)
        if not path.is_file():
            raise LoaderError(f"파일을 찾을 수 없어요: {path}")
        data = path.read_bytes()
    if is_zip(data):   # 엑셀(.xlsx): 첫 시트를 CSV 글로 바꾼다. 엑셀이 아닌 zip·손상·너무 큰 파일은 안내
        try:
            return xlsx_to_csv_text(data), "xlsx"
        except XlsxError as exc:
            raise LoaderError(str(exc)) from exc
    for magic, message in _SIGNATURES:
        if data.startswith(magic):
            raise LoaderError(message)
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):   # UTF-16 BOM(엑셀 '유니코드 텍스트' 저장)
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise LoaderError("UTF-16 글자를 읽지 못했어요. " + _SAVE_AS_CSV) from exc
        _check_markup(text)
        return text, "utf-16"
    for enc in ENCODINGS:
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        _check_markup(text)
        return text, enc
    raise LoaderError("글자 인코딩을 알 수 없어요. UTF-8 또는 CP949(EUC-KR)로 저장해 주세요. "
                      "엑셀이라면 파일 형식을 [CSV UTF-8(쉼표로 분리)]로 골라 저장하면 돼요.")


def _check_markup(text: str) -> None:
    """HTML·XML 파일(은행 '엑셀 저장'이 HTML 표인 경우 등)이면 안내와 함께 LoaderError."""
    head = text.lstrip(_BOM + " \t\r\n")[:2048].lower()
    if head.startswith("<") and any(tag in head for tag in _MARKUP_TAGS):
        raise LoaderError(_MARKUP_MESSAGE)


_CSV_BROKEN = ("CSV 모양을 읽지 못했어요. 한 칸의 글이 너무 길거나 따옴표가 잘못됐을 수 있어요. "
               "은행 등에서 내려받은 CSV 파일이 맞는지 확인해 주세요.")


def _parse_table(text: str, delimiter: str) -> list[list[str]]:
    try:
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    except csv.Error as exc:  # 한 칸이 너무 길거나(13만 자 초과) 따옴표가 깨진 파일
        raise LoaderError(_CSV_BROKEN) from exc


def _head_rows(text: str, delimiter: str) -> tuple[list[list[str]], bool]:
    """앞 HEADER_SCAN_ROWS줄(머리글 찾기용). 중간에 CSV 모양이 깨지면 그 앞까지와 True."""
    rows: list[list[str]] = []
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delimiter):
            rows.append(row)
            if len(rows) >= HEADER_SCAN_ROWS:
                break
    except csv.Error:
        return rows, True
    return rows, False


def _detect_layout(text: str, col_mapping: dict[str, Any] | None) -> tuple[str, int, str]:
    """(구분자, 머리글 줄 번호(0부터), 형식). 구분자마다 머리글을 찾아 보고, 찾은 것 중 칸이 가장 많은 것."""
    found: list[tuple[int, int, str, int, str]] = []
    heads: dict[str, list[list[str]]] = {}
    broken = 0
    for order, delimiter in enumerate(DELIMITERS):
        head, is_broken = _head_rows(text, delimiter)
        broken += is_broken and not head
        heads[delimiter] = head
        hit = _find_header(head, col_mapping)
        if hit is not None:
            idx, fmt = hit
            width = sum(1 for c in head[idx] if c.strip())
            found.append((-width, order, delimiter, idx, fmt))
    if found:
        _, _, delimiter, idx, fmt = min(found)
        return delimiter, idx, fmt
    if broken == len(DELIMITERS):
        raise LoaderError(_CSV_BROKEN)
    if col_mapping is not None:
        wanted = {_clean_header(c) for c in _mapping_columns(col_mapping)}
        missing = min((sorted(wanted - {_clean_header(c) for row in head for c in row}) for head in heads.values()),
                      key=len)
        raise LoaderError(f"mapping에 적은 열을 파일에서 찾지 못했어요: {', '.join(missing) or '(머리글 줄 없음)'}")
    raise LoaderError(_header_error(heads.values()))


def _header_error(heads) -> str:
    """머리글을 못 찾았을 때 무엇(날짜 열·금액 열)이 없는지 알려 준다."""
    best = (0, 0, False, False)
    for head in heads:
        for row in head:
            cells = {_clean_header(c) for c in row if c.strip()}
            has_time, has_amount = _header_kinds(cells)
            known = sum(1 for c in cells if any(c in names for names in _AUTO.values()))
            best = max(best, (has_time + has_amount, known, has_time, has_amount))
    _, _, has_time, has_amount = best
    if has_amount and not has_time:
        what = "날짜 열(예: 거래일시·거래일자·이용일시)"
    elif has_time and not has_amount:
        what = "금액 열(예: 출금액과 입금액, 또는 금액·이용금액)"
    else:
        what = "날짜 열과 금액 열"
    return f"머리글(열 이름)에서 {what}을 찾지 못했어요. " + _MAPPING_HINT


def _clean_header(name: str) -> str:
    """'출금액(원)', ' 거래 일시 ' → '출금액', '거래일시'."""
    name = name.replace(_BOM, "")
    name = re.sub(r"[\(\[].*?[\)\]]", "", name)
    return re.sub(r"\s+", "", name)


def _header_parts(name: str) -> set[str]:
    """'보낸분/받는분' → {'보낸분/받는분', '보낸분', '받는분'}."""
    return {name, *(p for p in name.split("/") if p)}


def _header_kinds(cells: set[str]) -> tuple[bool, bool]:
    """(날짜 열이 있는지, 금액 열(출금+입금 또는 금액)이 있는지)."""
    has_time = any(c in cells for c in _AUTO["datetime"] + _AUTO["date"])
    has_pair = any(c in cells for c in _AUTO["out_amount"]) and any(c in cells for c in _AUTO["in_amount"])
    has_amount = any(c in cells for c in _AUTO["amount"])
    return has_time, has_pair or has_amount


def _find_header(table: list[list[str]], col_mapping: dict[str, Any] | None) -> tuple[int, str] | None:
    wanted = {_clean_header(c) for c in _mapping_columns(col_mapping)} if col_mapping is not None else None
    for idx, row in enumerate(table[:HEADER_SCAN_ROWS]):
        cells = {_clean_header(c) for c in row if c.strip()}
        if not cells:
            continue
        if wanted is not None:
            if wanted and wanted <= cells:
                return idx, "mapped"
            continue
        if all(c in cells for c in REQUIRED_STANDARD_COLUMNS):
            return idx, "standard"
        has_time, has_amount = _header_kinds(cells)
        if has_time and has_amount:
            return idx, "mapped"
    return None


def _column_mapping(mapping: dict[str, Any] | None) -> dict[str, Any] | None:
    """열 이름이 하나라도 있는 mapping이면 그대로, 설정(date_format 등)만 있으면 None(열은 자동)."""
    if mapping and any(mapping.get(k) for k in COLUMN_KEYS):
        return mapping
    return None


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
    _validate_date_format(mapping.get("date_format"))
    if any(mapping.get(k) for k in COLUMN_KEYS):   # 설정만 있는 mapping은 열을 자동으로 찾는다
        has_time = mapping.get("datetime") or mapping.get("date")
        has_amount = (mapping.get("out_amount") and mapping.get("in_amount")) or mapping.get("amount")
        if not has_time or not has_amount:
            raise LoaderError("mapping에는 일시(datetime 또는 date)와 금액(out_amount+in_amount 또는 amount)이 "
                              "꼭 있어야 해요. " + _MAPPING_HINT)
    if direction and str(direction) not in ("out", "in"):
        raise LoaderError('default_direction은 "out" 또는 "in"이어야 해요.')


def _validate_date_format(fmt: Any) -> None:
    if fmt is None:
        return
    bad = LoaderError('date_format은 "%m/%d/%Y"(월/일/연)처럼 날짜 모양을 적은 글자여야 해요. '
                      '%Y=연(4자리), %y=연(2자리), %m=월, %d=일, %H=시, %M=분, %S=초')
    if not isinstance(fmt, str) or "%" not in fmt:
        raise bad
    try:   # 모양이 잘못된 형식(%Q 등)은 여기서 걸러진다
        datetime.strptime(datetime(2026, 9, 1, 13, 5, 7).strftime(fmt), fmt)
    except ValueError as exc:
        raise bad from exc


def _mapping_columns(mapping: dict[str, Any] | None) -> list[str]:
    out: list[str] = []
    for key in COLUMN_KEYS:
        value = (mapping or {}).get(key)
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
    # 상대: 후보 순서대로, '/'가 든 머리글은 나눠 비교. 메모 열(적요 등)은 상대로 쓰지 않는다.
    cps: list[str] = []
    for alias in _AUTO["counterparty"]:
        for name in header:
            if name and name not in cps and name != cols["memo"] and alias in _header_parts(name):
                cps.append(name)
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
        except AmountError:
            skipped.append((line_no, _R_NONPOSITIVE))
            continue
        except (KeyError, ValueError, OverflowError):
            skipped.append((line_no, _R_FORMAT))
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
                 cols: dict[str, Any], options: dict[str, Any]):
    index = {h: i for i, h in reversed(list(enumerate(header)))}  # 같은 이름이면 앞 열

    def cell(row: list[str], col: str | None) -> str:
        if not col or col not in index:
            return ""
        i = index[col]
        return row[i].strip() if i < len(row) else ""

    def column_values(col: str | None) -> list[int]:
        return [v for v in (_parse_amount(cell(r, col)) for _, r in body) if v]

    negative_style: dict[str | None, bool] = {}

    def sign_convention(col: str | None) -> bool:
        """이 열의 0 아닌 금액이 모두 음수면 '음수로 적는 파일'로 보고 음수를 취소로 보지 않는다.

        음수가 처음 나올 때 한 번만 열 전체를 본다(음수가 없는 보통 파일은 더 읽지 않는다)."""
        if col not in negative_style:
            values = column_values(col)
            negative_style[col] = bool(values) and all(v < 0 for v in values)
        return negative_style[col]

    default_direction = options.get("default_direction")
    date_format = options.get("date_format")
    pair = bool(cols.get("out_amount") and cols.get("in_amount"))
    amount_col = cols.get("amount")
    signed = card = False
    if not pair and amount_col and not cols.get("kind") and not default_direction:
        if amount_col in _CARD_AMOUNT_COLUMNS:
            card = True
        else:
            signed = any(v < 0 for v in column_values(amount_col))
            if not signed:
                raise LoaderError("금액 열만 있고 입금·출금을 나누는 구분 열이 없어요. " + _KIND_HINT)
    fixed_direction = Direction(str(default_direction)) if default_direction else Direction.OUT

    def row_amount(row: list[str]) -> tuple[Direction | None, int, str]:
        if pair:
            out_v = _parse_amount(cell(row, cols["out_amount"]))
            in_v = _parse_amount(cell(row, cols["in_amount"]))
            unreadable = out_v is None or in_v is None
            out_v, in_v = out_v or 0, in_v or 0
            # 출금·입금 칸의 음수는 취소(되돌림)로 보고 방향을 뒤집지 않는다(안전한 쪽: 건너뜀)
            if ((out_v < 0 and not sign_convention(cols["out_amount"]))
                    or (in_v < 0 and not sign_convention(cols["in_amount"]))):
                return None, 0, _R_NEGATIVE
            out_v, in_v = abs(out_v), abs(in_v)
            if out_v and in_v:
                return None, 0, _R_BOTH
            if out_v:
                return Direction.OUT, out_v, ""
            if in_v:
                return Direction.IN, in_v, ""
            return None, 0, _R_AMOUNT if unreadable else _R_NO_AMOUNT
        value = _parse_amount(cell(row, amount_col))
        if value is None:
            return None, 0, _R_AMOUNT
        if value == 0:
            return None, 0, _R_NO_AMOUNT
        if cols.get("kind"):
            direction = _parse_kind(cell(row, cols["kind"]))
            if direction is None:
                return None, 0, _R_KIND
            return direction, abs(value), ""
        if signed:
            return (Direction.OUT if value < 0 else Direction.IN), abs(value), ""
        if value < 0 and not sign_convention(amount_col):   # 방향을 정해 둔 파일(카드 이용내역 등)의 음수 = 취소
            return None, 0, _R_NEGATIVE
        return fixed_direction, abs(value), ""

    text_cols = list(dict.fromkeys(
        [*(cols.get("counterparty") or []), cols.get("memo"), cols.get("merchant")]
    ))
    text_cols = [c for c in text_cols if c]
    date_cols = [c for c in (cols.get("datetime"), cols.get("time")) if c]
    time_width = _time_digit_width([cell(r, cols["time"]) for _, r in body]) if cols.get("time") else 6

    txns: list[Transaction] = []
    skipped: list[tuple[int, str]] = []
    channel_count: Counter[Channel] = Counter()
    no_time = bad_time = 0
    tel_without_line = 0
    card_by_word = 0
    totals = cancels = 0

    for line_no, row in body:
        row_text = "\n".join(row)   # 칸 사이에 줄바꿈을 넣어 낱말이 두 칸에 걸쳐 맞지 않게
        if (any(w in row_text for w in _TOTAL_WORDS)
                or any(m in cell(row, c) for c in date_cols for m in _RANGE_MARKS)):
            skipped.append((line_no, _R_TOTAL))
            totals += 1
            continue
        if "취소" in row_text:
            skipped.append((line_no, _R_CANCEL))
            cancels += 1
            continue
        ts, time_state = _row_datetime(row, cols, cell, date_format, time_width)
        if ts is None:
            skipped.append((line_no, _R_DATE))
            continue
        if not MIN_YEAR <= ts.year <= MAX_YEAR:   # 0001-01-01 같은 빈 날짜 대용값
            skipped.append((line_no, _RANGE_REASON))
            continue
        direction, amount, why = row_amount(row)
        if direction is None:
            skipped.append((line_no, why))
            if why == _R_NEGATIVE:
                cancels += 1
            continue
        no_time += time_state == "missing"
        bad_time += time_state == "unreadable"

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
            # 회선은 회선 열이나 글 속 전화번호로만 정한다. 이름(통신사 등)으로 만든 회선은
            # 서로 다른 회선인지 알 수 없어 '휴대폰 요금이 여러 개' 판단을 틀리게 하므로 비워 둔다.
            line_id = _mask_phone(cell(row, cols.get("line"))) or _find_phone(text)
            if not line_id and channel == Channel.TELECOM_BILL:
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
        warnings.append(f"가맹점명 열이 없어 체크카드 같은 글자로 카드결제 {card_by_word}건을 추정했어요.")
    if txns and not cols.get("counterparty"):
        warnings.append("받는 사람 열을 찾지 못해 한 사람에게 송금 집중은 판단하기 어려워요." + _COUNTERPARTY_HINT)
    elif txns and not cols.get("counterparty_id"):
        warnings.append("상대 계좌 열이 없어, 이름이 같으면 같은 상대로 봤어요(추정).")
    if tel_without_line:
        warnings.append(f"통신요금 {tel_without_line}건은 회선(전화번호) 정보가 없어 휴대폰 요금 여러 회선 "
                        "판단에서 뺐어요." + _LINE_HINT)
    if no_time:
        warnings.append(f"시각이 없는 거래 {no_time}건은 낮 12시로 두었어요. 밤 시간 판단이 정확하지 않을 수 있어요.")
    if bad_time:
        warnings.append(f"시각을 읽지 못한 {bad_time}건은 낮 12시로 두었어요. 밤 시간 판단이 정확하지 않을 수 있어요.")
    if signed:
        warnings.append("구분 열이 없어 금액 부호로 입금·출금을 나눴어요(음수=출금, 양수=입금, 추정).")
    if card and txns:
        warnings.append(f"{amount_col} 열을 카드 이용내역으로 보고, 금액을 모두 쓴 돈(출금)으로 봤어요(추정).")
    if totals:
        warnings.append(f"합계·소계 줄 {totals}개는 거래가 아니라서 뺐어요.")
    if cancels:
        warnings.append(f"취소로 보이는 {cancels}줄(취소라는 글자나 음수 금액)은 건너뛰었어요. "
                        "원래 거래는 그대로 두었어요.")
    return txns, skipped, warnings


def _row_datetime(row, cols, cell, date_format: str | None,
                  time_width: int) -> tuple[datetime | None, str]:
    """(일시, 시각 상태). 상태: 'ok'(시각 있음), 'missing'(시각 없음), 'unreadable'(시각 칸을 못 읽음).

    시각이 없거나 못 읽으면 DEFAULT_TIME(낮 12시)."""
    raw = cell(row, cols.get("datetime"))
    if date_format:
        parsed, had_time = _parse_with_format(raw, date_format)
    else:
        parsed, had_time = _parse_datetime(raw)
    if parsed is None:
        return None, "missing"
    if had_time:
        return parsed, "ok"
    time_text = cell(row, cols.get("time")) if cols.get("time") else ""
    if not time_text:
        return datetime.combine(parsed.date(), DEFAULT_TIME), "missing"
    t = _parse_time(time_text, time_width)
    if t is None:
        return datetime.combine(parsed.date(), DEFAULT_TIME), "unreadable"
    return datetime.combine(parsed.date(), t), "ok"


# ---------------------------------------------------------------------------
# 값 해석
# ---------------------------------------------------------------------------

_AMPM = r"오전|오후|AM|PM|A\.M\.|P\.M\."
# 시각: [오전/오후/AM/PM] H:MM[:SS][.소수] [AM/PM/오전/오후]. '13시 5분 7초'도 읽는다.
_TIME_PART = (
    rf"(?:(?P<lead>{_AMPM})\s*)?(?P<h>\d{{1,2}})\s*[:시]\s*(?P<m>\d{{1,2}})\s*분?"
    rf"(?:\s*:?\s*(?P<s>\d{{1,2}})\s*초?)?(?:\.\d{{1,6}})?(?:\s*(?P<trail>{_AMPM}))?"
)
# 날짜[(요일)] [T 또는 공백 시각] [시간대]. 칸 전체가 맞아야 한다(꼬리 글자가 있으면 못 읽음).
_DT_RE = re.compile(
    r"(?P<y>\d{4})\s*[-./년]\s*(?P<mo>\d{1,2})\s*[-./월]\s*(?P<d>\d{1,2})\s*(?:일|\.)?"
    r"(?:\s*\(\s*[월화수목금토일]\s*\))?"
    rf"(?:(?:\s*T\s*|\s+){_TIME_PART}(?:\s*(?P<zone>Z|[+-]\d{{2}}:?\d{{2}}))?)?",
    re.IGNORECASE,
)
_TIME_RE = re.compile(_TIME_PART, re.IGNORECASE)
_FORMAT_TIME_CODES: tuple[str, ...] = ("%H", "%I", "%M", "%X", "%c")


def _hour24(hour: int, lead: str | None, trail: str | None) -> int | None:
    """오전/오후·AM/PM을 24시간제로. 모순(오전 13시, 앞뒤 표기 둘 다)이면 None."""
    if lead and trail:
        return None
    marker = (lead or trail or "").upper().replace(".", "")
    if not marker:
        return hour
    if marker in ("PM", "오후"):
        return hour + 12 if hour < 12 else hour
    if hour > 12:
        return None
    return 0 if hour == 12 else hour


def _parse_datetime(text: str) -> tuple[datetime | None, bool]:
    """(일시, 시각 포함 여부). 못 읽으면 (None, False). 칸 전체가 날짜 모양이어야 한다."""
    s = text.strip()
    if not s:
        return None, False
    try:
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d"), False
        m = re.fullmatch(r"(\d{8})\s*(\d{6}|\d{4})|(\d{8})\s+(\d{5})", s)
        if m:
            day, clock = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4).zfill(6))
            fmt = "%Y%m%d%H%M%S" if len(clock) == 6 else "%Y%m%d%H%M"
            return datetime.strptime(day + clock, fmt), True
        m = _DT_RE.fullmatch(s)
        if not m:
            return None, False
        y, mo, d = int(m["y"]), int(m["mo"]), int(m["d"])
        if m["h"] is None:
            return datetime(y, mo, d), False
        hour = _hour24(int(m["h"]), m["lead"], m["trail"])
        if hour is None:
            return None, False
        ts = datetime(y, mo, d, hour, int(m["m"]), int(m["s"] or 0))
        if m["zone"]:   # 시간대가 있으면 표준 CSV와 같이 이 컴퓨터 시각으로 바꾼 뒤 뗀다
            ts = ts.replace(tzinfo=_zone(m["zone"])).astimezone().replace(tzinfo=None)
        return ts, True
    except (ValueError, OverflowError):
        return None, False


def _zone(text: str) -> timezone:
    if text.upper() == "Z":
        return timezone.utc
    digits = text[1:].replace(":", "")
    minutes = int(digits[:2]) * 60 + int(digits[2:4])
    return timezone((-1 if text[0] == "-" else 1) * timedelta(minutes=minutes))


def _parse_with_format(text: str, fmt: str) -> tuple[datetime | None, bool]:
    """mapping의 date_format으로 읽는다(칸 전체가 맞아야 함). (일시, 형식에 시각이 있는지)."""
    s = text.strip()
    if not s:
        return None, False
    try:
        return datetime.strptime(s, fmt), any(code in fmt for code in _FORMAT_TIME_CODES)
    except ValueError:
        return None, False


def _time_digit_width(values: list[str]) -> int:
    """숫자만 있는 시각 열의 자릿수. 5~6자리가 하나라도 있으면 HHMMSS(6), 아니면 HHMM(4).

    엑셀이 숫자로 바꾸며 앞 0을 지운 시각(09:10:30 → 91030, 00:05:00 → 500)을 되살릴 때 쓴다.
    """
    lengths = [len(v) for v in (x.strip() for x in values) if re.fullmatch(r"[0-9]{1,6}", v)]
    return 6 if any(n >= 5 for n in lengths) else 4


def _parse_time(text: str, width: int = 6) -> time | None:
    s = text.strip()
    if not s:
        return None
    m = _TIME_RE.fullmatch(s)
    if m:
        hour = _hour24(int(m["h"]), m["lead"], m["trail"])
        minute, second = m["m"], m["s"]
    elif re.fullmatch(r"[0-9]{1,6}", s) and len(s) <= width:
        digits = s.zfill(width)   # 엑셀 숫자형 시각: 91030 → 091030
        hour, minute, second = int(digits[0:2]), digits[2:4], (digits[4:6] or None)
    else:
        return None
    if hour is None:
        return None
    try:
        return time(hour, int(minute), int(second or 0))
    except ValueError:
        return None


# 금액 앞뒤의 통화 표기(₩, 전각 ￦, CP949 파일의 '\', KRW, 원)
_CURRENCY_RE = re.compile(r"KRW|원|[₩￦\\]", re.IGNORECASE)
_MINUS_SIGNS = "\u2212\u2012\u2013\u2014\ufe63\uff0d"   # U+2212 빼기 기호, 대시류, 전각 빼기
_INVISIBLE = "\u200b\u200c\u200d\u2060" + _BOM   # 폭 없는 글자


_SPACE_RE = re.compile(r"\s+")   # 모든 유니코드 공백(NBSP·전각 공백 포함)
# 폭 없는 글자와 쉼표(전각 쉼표 포함)는 지우고, 여러 빼기 기호는 '-'로 바꾸는 표
_AMOUNT_TABLE = str.maketrans({**{c: None for c in _INVISIBLE + "," + chr(0xFF0C)},
                               **{c: "-" for c in _MINUS_SIGNS}})
_MAX_PLAIN_DIGITS = len(str(int(AMOUNT_LIMIT))) - 1   # 이 자릿수 이하의 숫자만이면 AMOUNT_LIMIT 미만


def _parse_amount(text: str) -> int | None:
    """금액 글 → 정수(원 단위 반올림). 비었거나 '-'면 0, 못 읽으면 None.

    '1,234원', '₩ 5,000', '￦5,000', 'KRW 5,000', '-3,000', '(3,000)', '5,000-', '−5,000', '△5,000'
    (괄호·끝 '-'·U+2212·'△'는 음수). 모든 유니코드 공백(NBSP 등)은 지운다.
    """
    if text.isascii() and text.isdecimal() and len(text) <= _MAX_PLAIN_DIGITS:   # 흔한 모양은 바로
        return int(text)
    s = _CURRENCY_RE.sub("", _SPACE_RE.sub("", text).translate(_AMOUNT_TABLE))
    if s in ("", "-"):
        return 0
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.startswith("△"):
        negative, s = True, s[1:]
    if s.endswith("-") and len(s) > 1:
        negative, s = True, s[:-1]
    s = s.lstrip("+")
    try:
        number = float(s)
    except ValueError:
        return None
    if not math.isfinite(number) or abs(number) >= AMOUNT_LIMIT:  # "1e400", "nan" 등
        return None
    value = round_amount(number)
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


def _name_key(name: str) -> str:
    """상대 식별값이 없을 때 이름을 식별값으로 쓴다(공백 정리)."""
    return re.sub(r"\s+", " ", name).strip()


def _find_phone(text: str) -> str:
    """글 속 휴대폰 번호를 가운데를 가린 모양(010-****-1234)으로. +82·82로 시작하면 0으로 바꾼다."""
    m = _PHONE_RE.search(text)
    return f"0{m.group(1)}-****-{m.group(3)}" if m else ""


def _mask_phone(text: str) -> str:
    """전화번호는 가운데를 가려 저장한다(010-****-1234). 번호 모양이 아니면 그대로."""
    if not text:
        return ""
    return _find_phone(text) or text.strip()


__all__ = ["load_csv", "LoaderError", "COLUMN_KEYS", "ENCODINGS", "DELIMITERS"]
