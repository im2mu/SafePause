"""explain/llm_adapter.py 테스트. 실제 네트워크 대신 urllib.request.build_opener 를 바꿔 끼운다."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Optional

import pytest

from safepause.explain import llm_adapter
from safepause.explain.easy_card import build_card, readability_issues
from safepause.explain.llm_adapter import (
    LocalLLMRewriter,
    number_tokens,
    parse_lines,
    same_numbers,
    validate_loopback_endpoint,
)
from safepause.models import AlertCard, RiskLevel

ORIGINAL_LINES = ["요즘 밤늦게 돈을 여러 번 보냈어요.", "이번 주에만 4번이에요.", "모두 30만 원이에요."]


def make_card() -> AlertCard:
    return build_card("t1", RiskLevel.HIGH, "밤에 돈을 자주 보냈어요", list(ORIGINAL_LINES),
                      ["moon", "money", "question"])


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class FakeOpener:
    """build_opener 가 돌려주는 가짜. 요청을 기록하고 정해진 응답이나 예외를 낸다."""

    def __init__(self, handlers: tuple[Any, ...], reply: Optional[bytes], error: Optional[BaseException]):
        self.handlers = handlers
        self.reply = reply
        self.error = error
        self.requests: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, timeout: float = 0.0) -> FakeResponse:
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        assert self.reply is not None
        return FakeResponse(self.reply)


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch):
    """fake_server(lines=...|reply=...|error=...) 로 응답을 정하고 생성된 opener 목록을 돌려받는다."""
    openers: list[FakeOpener] = []

    def configure(lines: Optional[list[str]] = None, reply: Optional[bytes] = None,
                  error: Optional[BaseException] = None) -> list[FakeOpener]:
        if lines is not None:
            reply = json.dumps({"model": "m", "response": json.dumps({"lines": lines}, ensure_ascii=False),
                                "done": True}, ensure_ascii=False).encode("utf-8")

        def fake_build_opener(*handlers: Any) -> FakeOpener:
            opener = FakeOpener(handlers, reply, error)
            openers.append(opener)
            return opener

        monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
        return openers

    return configure


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("네트워크 호출이 있으면 안 돼요")

    monkeypatch.setattr(urllib.request, "build_opener", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)


# ---- 기본값·주소 검사 ----------------------------------------------------

def test_disabled_by_default_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_network(monkeypatch)
    rewriter = LocalLLMRewriter()
    assert rewriter.enabled is False
    assert rewriter.endpoint == "http://127.0.0.1:11434"
    card = make_card()
    assert rewriter.rewrite(card) is card
    assert card.source == "template"


def test_enabled_without_model_makes_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    forbid_network(monkeypatch)
    rewriter = LocalLLMRewriter(enabled=True, model="")
    card = make_card()
    assert rewriter.rewrite(card) is card
    assert rewriter.last_error


@pytest.mark.parametrize("endpoint", [
    "http://example.com:11434",
    "https://api.example.org",
    "http://192.168.0.10:11434",
    "http://10.0.0.1",
    "http://0.0.0.0:11434",
    "http://127.0.0.1@evil.example.com",
    "http://user:pw@127.0.0.1:11434",
    "http://localhost.evil.example.com",
    "http://127.1:11434",
    "ftp://127.0.0.1",
    "127.0.0.1:11434",
    "",
    "http://127.0.0.1:99999",
])
def test_non_loopback_endpoint_raises(endpoint: str) -> None:
    with pytest.raises(ValueError):
        LocalLLMRewriter(endpoint=endpoint)


@pytest.mark.parametrize("endpoint, expected", [
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://localhost:8080/", "http://localhost:8080"),
    ("http://LOCALHOST:8080", "http://LOCALHOST:8080"),
    ("http://[::1]:11434", "http://[::1]:11434"),
    ("http://127.0.0.2:1", "http://127.0.0.2:1"),
])
def test_loopback_endpoints_allowed(endpoint: str, expected: str) -> None:
    assert validate_loopback_endpoint(endpoint) == expected
    LocalLLMRewriter(endpoint=endpoint)


# ---- 서버 없음·실패 -------------------------------------------------------

@pytest.mark.parametrize("error", [
    urllib.error.URLError(ConnectionRefusedError(10061, "refused")),
    TimeoutError("timed out"),
    ConnectionResetError("reset"),
    urllib.error.HTTPError("http://127.0.0.1:11434/api/generate", 500, "err", {}, None),  # type: ignore[arg-type]
])
def test_server_unavailable_returns_original(fake_server, error: BaseException) -> None:
    fake_server(error=error)
    rewriter = LocalLLMRewriter(enabled=True, model="local-model")
    card = make_card()
    assert rewriter.rewrite(card) is card
    assert rewriter.last_error


@pytest.mark.parametrize("reply", [
    b"not json",
    json.dumps({"response": "그냥 글이에요"}).encode(),
    json.dumps({"response": json.dumps({"lines": []})}).encode(),
    json.dumps({"response": json.dumps({"lines": [1, 2, 3]})}).encode(),
    json.dumps({"no_response": True}).encode(),
    b"\xff\xfe broken",
])
def test_malformed_reply_returns_original(fake_server, reply: bytes) -> None:
    fake_server(reply=reply)
    card = make_card()
    assert LocalLLMRewriter(enabled=True, model="m").rewrite(card) is card


def test_oversized_reply_returns_original(fake_server) -> None:
    fake_server(reply=b"x" * (llm_adapter.MAX_RESPONSE_BYTES + 10))
    card = make_card()
    assert LocalLLMRewriter(enabled=True, model="m").rewrite(card) is card


# ---- 성공·검증 ------------------------------------------------------------

def test_successful_rewrite_changes_lines_only(fake_server, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:8080")
    new_lines = ["요즘 밤에 돈을 자주 보냈어요.", "이번 주에 4번 보냈어요.", "다 합쳐 30만 원이에요."]
    openers = fake_server(lines=new_lines)
    rewriter = LocalLLMRewriter(enabled=True, model="local-model", timeout=3.0, seed=7)
    card = make_card()
    result = rewriter.rewrite(card)

    assert result is not card
    assert result.source == "llm"
    assert result.lines == new_lines
    assert result.title == card.title and result.question == card.question
    assert result.choices == card.choices and result.pictograms == card.pictograms
    assert all(line in result.speak_text for line in new_lines)
    assert readability_issues(result) == []
    assert card.lines == ORIGINAL_LINES and card.source == "template"  # 원본은 그대로

    # 요청 내용: loopback 주소, POST, 프록시 끔, 리다이렉트 막음
    (opener,) = openers
    (request, timeout), = opener.requests
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    assert request.get_method() == "POST"
    assert timeout == 3.0
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "local-model" and body["stream"] is False
    assert body["options"] == {"temperature": 0, "seed": 7}
    assert "이번 주에만 4번이에요." in body["prompt"]
    proxy_handlers = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxy_handlers and proxy_handlers[0].proxies == {}
    assert any(isinstance(h, llm_adapter._NoRedirectHandler) for h in opener.handlers)


def test_changed_numbers_return_original(fake_server) -> None:
    fake_server(lines=["요즘 밤늦게 돈을 여러 번 보냈어요.", "이번 주에만 5번이에요.", "모두 30만 원이에요."])
    card = make_card()
    rewriter = LocalLLMRewriter(enabled=True, model="m")
    assert rewriter.rewrite(card) is card
    assert "숫자" in (rewriter.last_error or "")


def test_numbers_written_as_words_return_original(fake_server) -> None:
    fake_server(lines=["요즘 밤늦게 돈을 여러 번 보냈어요.", "이번 주에만 네 번이에요.", "모두 30만 원이에요."])
    card = make_card()
    assert LocalLLMRewriter(enabled=True, model="m").rewrite(card) is card


@pytest.mark.parametrize("bad_lines", [
    ["요즘 밤늦게 이상거래가 있었어요.", "이번 주에만 4번이에요.", "모두 30만 원이에요."],
    ["요즘 밤늦게 돈을 여러 번 보냈는데 이것은 아주 위험할 수도 있어요.", "이번 주에만 4번이에요.",
     "모두 30만 원이에요."],
    ["요즘 밤늦게 보냈어요. 여러 번 보냈어요.", "이번 주에만 4번이에요.", "모두 30만 원이에요."],
])
def test_readability_violation_returns_original(fake_server, bad_lines: list[str]) -> None:
    fake_server(lines=bad_lines)
    card = make_card()
    rewriter = LocalLLMRewriter(enabled=True, model="m")
    assert rewriter.rewrite(card) is card
    assert "쉬운 글" in (rewriter.last_error or "")


def test_line_count_change_returns_original(fake_server) -> None:
    fake_server(lines=["밤에 4번, 30만 원을 보냈어요."])
    card = make_card()
    assert LocalLLMRewriter(enabled=True, model="m").rewrite(card) is card


def test_identical_lines_keep_template_source(fake_server) -> None:
    fake_server(lines=list(ORIGINAL_LINES))
    card = make_card()
    result = LocalLLMRewriter(enabled=True, model="m").rewrite(card)
    assert result is card and result.source == "template"


def test_source_is_llm_only_when_rewritten(fake_server) -> None:
    # 원본 카드가 무엇이든 다듬은 경우에만 source="llm"
    fake_server(lines=["요즘 밤에 돈을 자주 보냈어요.", "이번 주에만 4번이에요.", "모두 30만 원이에요."])
    card = replace(make_card(), source="template")
    assert LocalLLMRewriter(enabled=True, model="m").rewrite(card).source == "llm"


def test_no_redirect_handler_refuses() -> None:
    handler = llm_adapter._NoRedirectHandler()
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate")
    assert handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example.com/") is None


# ---- 도우미 함수 ----------------------------------------------------------

def test_number_tokens_and_same_numbers() -> None:
    assert number_tokens(["12만 5천 원이에요.", "새벽 2시예요.", "4번이에요."]) == sorted(["12만", "5천", "2시", "4번"])
    assert number_tokens(["1,234만 원"]) == ["1234만"]
    assert same_numbers(["이번 주에만 4번이에요.", "모두 30만 원이에요."], ["모두 30만 원이에요.", "4번 보냈어요."])
    assert not same_numbers(["4번, 30만 원"], ["30번, 4만 원"])
    assert not same_numbers(["4번이에요."], ["네 번이에요."])
    assert not same_numbers(["30만 원"], ["30만 원", "1번"])


def test_parse_lines_variants() -> None:
    assert parse_lines('{"lines": ["가요.", "와요."]}') == ["가요.", "와요."]
    assert parse_lines('다듬었어요:\n{"lines": ["1. 가요.", "- 와요."]}\n끝') == ["가요.", "와요."]
    assert parse_lines("") is None
    assert parse_lines('{"lines": ["가요.", ""]}') is None
    assert parse_lines('["가요."]') is None
