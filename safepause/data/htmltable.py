"""확장자만 .xls인 웹 페이지(HTML 표) 파일에서 표를 꺼낸다. 표준 라이브러리(html.parser)만 쓴다(앱의 Pyodide에서도 동작).

일부 은행·카드사의 '엑셀 저장' 파일은 진짜 엑셀이 아니라 HTML 표에 .xls 이름을 붙인 것이다(공개 코드로 확인한 곳:
기업은행 거래내역조회, 현대카드 이용내역. 출처는 tests/test_loader_bank_formats.py 머리말).
data.loader가 표마다 머리글(날짜·금액 열)을 찾아 보고 처음 찾은 표를 CSV 글로 바꿔 읽는다.

- 문서 안의 모든 표(<table>)를 시작 순서대로 줄(<tr>)·칸(<td>·<th>) 목록으로 바꾼다. 표 안의 표는 따로 센다
  (바깥 칸에는 안쪽 표의 글을 넣지 않는다).
- 칸 글: 태그를 빼고 공백(줄바꿈·&nbsp; 포함)을 한 칸으로 줄인다. <br>·<p>·<div>는 공백 하나(날짜<br>시각 → '날짜 시각').
- colspan: 오른쪽 칸을 빈 칸으로 채운다. rowspan: 아래 줄 같은 자리에 같은 글을 채운다(여러 거래에 걸친 날짜 칸).
- <script>·<style> 안 글은 버린다. 닫는 태그가 빠진 칸·줄은 다음 칸·줄이 시작될 때 닫는다.
- 안전: 글 길이 상한(3천만 자), 모든 표의 줄 수 합계(10만 줄)·칸 수 합계(300만 칸) 상한, 한 줄 256칸, 표 1만 개,
  colspan·rowspan 상한, 닫히지 않은 구문을 다시 훑는 양의 상한.
  옛 html.parser(이 저장소 시험 환경 Python 3.12.10에서 확인)는 끝에서 닫히지 않은 구문('<!--', '<a ', '</' 등)을
  하나씩 글로 넘기며 매번 글 끝까지 다시 훑는다(CVE-2025-6069. 앱의 Pyodide Python 3.14.2 판은 한 번만 훑음).
  그런 구문이 수만 개면 수십 초~수 분 걸리므로(60KB짜리 '<a '×2만 = 90초, 퍼징으로 찾음) 닫히지 않은 구문을 만난
  횟수와 그때 훑은 양을 센다. 양 = 훑은 글자 수 × 무게. 시작 태그는 html.parser의 속성 정규식이 실제로 닿은 곳까지
  (같은 정규식을 한 번 더 맞춰 잰다) × 200, 나머지(주석·끝 태그·선언, 글 끝까지 글자 찾기)는 글 끝까지 × 10
  (이 PC에서 잰 글자당 시간 ns 차이). FREE_RESCANS번을 넘고 양이 MAX_RESCAN_COST를 넘으면 '태그가 깨진 파일'로
  안내한다(어느 기계에서나 같은 결과가 나오게 시간이 아니라 양으로 센다. 이 PC에서 1초 안쪽).
  정상 파일은 닫히지 않은 구문이 없거나 한두 개라 걸리지 않는다(결과는 그대로).
  html.parser가 깨진 선언('<![', '<!DOCTYPE x [' 등)에서 내는 AssertionError도 같은 안내로 바꾼다.
"""
from __future__ import annotations

import html.parser as _html_parser
from html.parser import HTMLParser
from typing import Optional

MAX_CHARS = 30_000_000
MAX_ROWS = 100_000
MAX_COLS = 256
MAX_SPAN = 1000
MAX_CELLS = 3_000_000     # 모든 표의 칸 수 합계(colspan으로 늘어난 칸 포함, xlsx와 같은 상한)
MAX_TABLES = 10_000
MAX_RESCAN_COST = 250_000_000    # 닫히지 않은 구문 때문에 다시 훑는 양의 합계 상한(글자 수 × 무게)
FREE_RESCANS = 3                 # 이 횟수까지는 양과 관계없이 그대로 읽는다(정상 파일의 끝이 잘린 경우 등)
_TAG_WEIGHT, _FIND_WEIGHT = 200, 10  # 시작 태그(정규식으로 속성 훑기) / 나머지(주석·끝 태그 등, 글자 찾기)
# 시작 태그가 어디까지 훑였는지 잴 때 쓰는 html.parser의 정규식(없는 판이면 글 끝까지로 본다)
_START_TAG_SCAN = getattr(_html_parser, "locatestarttagend_tolerant", None)

TOO_BIG = "웹 페이지(HTML) 모양의 파일이 너무 커요. 기간을 나눠 내려받아 올려 주세요."
TOO_MANY_ROWS = f"표의 줄이 너무 많아요({MAX_ROWS:,}줄까지). 기간을 나눠 내려받아 올려 주세요."
TOO_MANY_CELLS = f"표의 칸이 너무 많아요({MAX_CELLS:,}칸까지). 기간을 나눠 내려받아 올려 주세요."
BROKEN = ("웹 페이지(HTML) 모양의 파일인데 태그가 깨져 있어 읽지 못했어요. 이 파일을 엑셀에서 연 뒤 "
          "[다른 이름으로 저장]에서 [CSV UTF-8(쉼표로 분리)]로 저장해 올려 주세요.")

_CELL_TAGS = ("td", "th")
_BREAK_TAGS = ("br", "p", "div", "li")
_SKIP_TAGS = ("script", "style")   # 칸 밖 글(제목 등)은 원래 버리므로 이 둘만 따로 센다


class HtmlTableError(ValueError):
    """HTML 표를 읽을 수 없을 때(한국어 안내)."""


class _Table:
    __slots__ = ("rows", "row", "cell", "span", "pending")

    def __init__(self) -> None:
        self.rows: list[list[str]] = []
        self.row: Optional[list[tuple[str, int, int]]] = None   # 지금 줄의 (글, colspan, rowspan)
        self.cell: Optional[list[str]] = None                   # 지금 칸의 글 조각
        self.span = (1, 1)
        self.pending: dict[int, tuple[str, int]] = {}           # 위 줄 rowspan이 채울 칸: 열 → (글, 남은 줄 수)


def _span(value: Optional[str]) -> int:
    if value is None:   # 흔한 경우(속성 없음)
        return 1
    try:
        return max(1, min(MAX_SPAN, int(str(value or "1").strip() or 1)))
    except ValueError:
        return 1


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.stack: list[_Table] = []
        self.skip = 0
        self.n_rows = 0
        self.n_cells = 0
        self.unclosed = 0    # 닫히지 않은 구문을 만난 횟수
        self.rescan = 0      # 그때마다 글 끝까지 훑은 양(글자 수 × 무게) 합계
        self._parsing = 0    # 구문 해석 함수 안쪽 호출(예: 선언 → 주석)은 한 번만 센다

    # -- 닫히지 않은 구문 다시 훑기 세기 ----------------------------------------------
    def _call(self, parse, i: int, *args, **kwargs) -> tuple[int, bool]:
        """(해석 결과, 바깥 호출에서 닫히지 않음을 만났는지)."""
        self._parsing += 1
        try:
            k = parse(i, *args, **kwargs)
        finally:
            self._parsing -= 1
        return k, k < 0 and not self._parsing

    def _charge(self, cost: int) -> None:
        self.unclosed += 1
        self.rescan += cost
        if self.unclosed > FREE_RESCANS and self.rescan > MAX_RESCAN_COST:
            raise HtmlTableError(BROKEN)

    def parse_starttag(self, i, *args, **kwargs):
        # 시작 태그 해석은 다른 구문 해석 함수를 부르지 않고 가장 자주 불리므로 _call 없이 바로 센다
        k = super().parse_starttag(i, *args, **kwargs)
        if k < 0 and not self._parsing:
            m = _START_TAG_SCAN.match(self.rawdata, i) if _START_TAG_SCAN is not None else None
            self._charge(((m.end() if m else len(self.rawdata)) - i) * _TAG_WEIGHT)
        return k

    def _parse_to_end(self, parse, i: int, *args, **kwargs) -> int:
        k, unclosed = self._call(parse, i, *args, **kwargs)
        if unclosed:   # 닫는 표시를 글 끝까지 찾았다
            self._charge((len(self.rawdata) - i) * _FIND_WEIGHT)
        return k

    def parse_endtag(self, i, *args, **kwargs):
        return self._parse_to_end(super().parse_endtag, i, *args, **kwargs)

    def parse_comment(self, i, *args, **kwargs):
        return self._parse_to_end(super().parse_comment, i, *args, **kwargs)

    def parse_pi(self, i, *args, **kwargs):
        return self._parse_to_end(super().parse_pi, i, *args, **kwargs)

    def parse_html_declaration(self, i, *args, **kwargs):
        return self._parse_to_end(super().parse_html_declaration, i, *args, **kwargs)

    # -- 칸·줄 닫기 ------------------------------------------------------------
    def _end_cell(self, t: _Table) -> None:
        if t.cell is None:
            return
        text = " ".join("".join(t.cell).split())
        if t.row is None:
            t.row = []
        t.row.append((text, *t.span))
        t.cell = None

    def _end_row(self, t: _Table) -> None:
        self._end_cell(t)
        if t.row is None:
            return
        cells, t.row = t.row, None
        out: list[str] = []

        def carry() -> None:   # 위 줄 rowspan이 이 자리를 차지하면 그 글을 채운다
            while len(out) in t.pending and len(out) < MAX_COLS:
                col = len(out)
                text, left = t.pending[col]
                out.append(text)
                if left <= 1:
                    del t.pending[col]
                else:
                    t.pending[col] = (text, left - 1)

        for text, colspan, rowspan in cells:
            for k in range(colspan):
                carry()
                if len(out) >= MAX_COLS:
                    break
                value = text if k == 0 else ""
                if rowspan > 1:
                    t.pending[len(out)] = (value, rowspan - 1)
                out.append(value)
        for col in sorted(c for c in t.pending if c >= len(out)):   # 줄 끝 뒤쪽 rowspan 칸
            if col >= MAX_COLS:
                break
            out.extend([""] * (col - len(out)))
            carry()
        self.n_rows += 1
        self.n_cells += len(out)
        if self.n_rows > MAX_ROWS:
            raise HtmlTableError(TOO_MANY_ROWS)
        if self.n_cells > MAX_CELLS:
            raise HtmlTableError(TOO_MANY_CELLS)
        t.rows.append(out)

    # -- 태그 -----------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if tag == "table":
            if len(self.tables) >= MAX_TABLES:
                raise HtmlTableError(TOO_BIG)
            t = _Table()
            self.tables.append(t)
            self.stack.append(t)
            return
        t = self.stack[-1] if self.stack else None
        if t is None:
            return
        if tag == "tr":
            self._end_row(t)
            t.row = []
        elif tag in _CELL_TAGS:
            self._end_cell(t)
            if t.row is None:
                t.row = []
            values = dict(attrs)
            t.span = (_span(values.get("colspan")), _span(values.get("rowspan")))
            t.cell = []
        elif tag in _BREAK_TAGS and t.cell is not None:
            t.cell.append(" ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:   # <script/> 같은 빈 태그는 건너뛸 글이 없다
            return
        self.handle_starttag(tag, attrs)
        if tag == "table":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        t = self.stack[-1] if self.stack else None
        if t is None:
            return
        if tag == "table":
            self._end_row(t)
            self.stack.pop()
        elif tag == "tr":
            self._end_row(t)
        elif tag in _CELL_TAGS:
            self._end_cell(t)

    def handle_data(self, data: str) -> None:
        if self.skip or not self.stack:
            return
        t = self.stack[-1]
        if t.cell is not None:
            t.cell.append(data)

    def finish(self) -> None:
        self.close()
        while self.stack:
            self._end_row(self.stack.pop())


def html_tables(text: str) -> list[list[list[str]]]:
    """HTML 글 → 표 목록(표마다 줄 목록, 줄마다 칸 글 목록). 표 시작 순서대로."""
    if len(text) > MAX_CHARS:
        raise HtmlTableError(TOO_BIG)
    parser = _Collector()
    try:
        parser.feed(text)
        parser.finish()
    except AssertionError as exc:   # html.parser가 깨진 선언('<![<![' 등)에서 내는 오류(퍼징으로 찾음)
        raise HtmlTableError(BROKEN) from exc
    return [t.rows for t in parser.tables]


__all__ = ["HtmlTableError", "MAX_CHARS", "MAX_COLS", "MAX_ROWS", "html_tables"]
