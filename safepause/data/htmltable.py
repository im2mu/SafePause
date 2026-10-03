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
  colspan·rowspan 상한.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Optional

MAX_CHARS = 30_000_000
MAX_ROWS = 100_000
MAX_COLS = 256
MAX_SPAN = 1000
MAX_CELLS = 3_000_000     # 모든 표의 칸 수 합계(colspan으로 늘어난 칸 포함, xlsx와 같은 상한)
MAX_TABLES = 10_000

TOO_BIG = "웹 페이지(HTML) 모양의 파일이 너무 커요. 기간을 나눠 내려받아 올려 주세요."
TOO_MANY_ROWS = f"표의 줄이 너무 많아요({MAX_ROWS:,}줄까지). 기간을 나눠 내려받아 올려 주세요."
TOO_MANY_CELLS = f"표의 칸이 너무 많아요({MAX_CELLS:,}칸까지). 기간을 나눠 내려받아 올려 주세요."

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
    parser.feed(text)
    parser.finish()
    return [t.rows for t in parser.tables]


__all__ = ["HtmlTableError", "MAX_CHARS", "MAX_COLS", "MAX_ROWS", "html_tables"]
