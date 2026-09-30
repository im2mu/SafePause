"""선택 기능: 같은 PC에서 돌아가는 로컬 sLLM으로 카드 문장 다듬기. SPEC §6, 제안서 S35.

- 기본은 꺼짐(enabled=False). 꺼져 있으면 어떤 통신도 하지 않는다.
- 주소는 loopback(127.0.0.1, localhost, ::1)만 허용한다. 다른 호스트면 ValueError.
- 프록시 환경변수를 무시하고, 다른 주소로의 리다이렉트도 따라가지 않는다.
- 서버가 없거나 응답이 이상하면 원본 카드를 그대로 돌려준다.
- 다듬은 문장이 쉬운 정보 원칙을 어기거나 숫자가 바뀌면 원본을 돌려준다.

요청 형식은 Ollama 호환 `/api/generate`(stream=false, 응답의 "response" 필드)를 쓴다.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import replace
from typing import Any, Iterable, Optional

from safepause.explain.easy_card import (
    FORBIDDEN_WORDS,
    MAX_LINE_LEN,
    make_speak_text,
    readability_issues,
)
from safepause.models import AlertCard

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_API_PATH = "/api/generate"
MAX_RESPONSE_BYTES = 64 * 1024


# ---- 주소 검사 ------------------------------------------------------------

def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_loopback_endpoint(endpoint: str) -> str:
    """loopback 주소만 허용하고 정리된 주소를 돌려준다. 아니면 ValueError."""
    parts = urllib.parse.urlsplit((endpoint or "").strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"로컬 sLLM 주소는 http(s)만 쓸 수 있어요: {endpoint!r}")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"로컬 sLLM 주소에 사용자 정보를 넣을 수 없어요: {endpoint!r}")
    host = parts.hostname or ""
    if not _is_loopback_host(host):
        raise ValueError(
            f"로컬 sLLM은 이 PC(127.0.0.1 또는 localhost)에서만 쓸 수 있어요: {endpoint!r}"
        )
    try:
        parts.port  # 잘못된 포트면 ValueError
    except ValueError as exc:
        raise ValueError(f"로컬 sLLM 주소의 포트가 잘못됐어요: {endpoint!r}") from exc
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


# ---- 숫자 보존 검사 -------------------------------------------------------

# 숫자 뒤 단위어. 긴 것부터 맞춘다('3번째'가 '3번'으로 잘리지 않게: "이번이 3번째예요" ≠ "3번 보냈어요").
_UNIT_WORDS: tuple[str, ...] = tuple(sorted((
    "번째", "가지", "개월", "시간", "주일",
    "번", "째", "만", "천", "백", "억", "조", "원", "일", "주", "달", "년", "월",
    "시", "분", "초", "개", "건", "명", "곳", "살", "회", "배", "%",
), key=len, reverse=True))
# 시각 앞의 때 말. '새벽 2시'를 '오후 2시'로 바꾸면 뜻이 달라지므로 '시'와 한 토큰으로 본다.
_DAY_PARTS: tuple[str, ...] = ("새벽", "아침", "오전", "낮", "오후", "저녁", "밤")
_NUMBER_TOKEN = re.compile(
    r"(?:(?P<part>" + "|".join(_DAY_PARTS) + r")\s*)?"
    r"(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>" + "|".join(re.escape(u) for u in _UNIT_WORDS) + r")?"
)


def _line_tokens(line: str) -> list[str]:
    text = re.sub(r"(?<=\d),(?=\d)", "", line)
    tokens: list[str] = []
    for m in _NUMBER_TOKEN.finditer(text):
        unit = m.group("unit") or ""
        part = m.group("part") if unit == "시" and m.group("part") else ""
        tokens.append(f"{part}{m.group('num')}{unit}")
    return tokens


def number_tokens(lines: Iterable[str]) -> list[str]:
    """숫자와 뒤의 단위어 전체(예: "4번", "3번째", "30만", "5천", "새벽2시")를 모아 정렬해 돌려준다."""
    tokens: list[str] = []
    for line in lines:
        tokens += _line_tokens(line)
    return sorted(tokens)


def same_numbers(before: Iterable[str], after: Iterable[str]) -> bool:
    """줄마다 숫자·단위어가 그대로인지. 줄 수가 다르거나 숫자가 다른 줄로 옮겨 가도 False."""
    b, a = list(before), list(after)
    if len(b) != len(a):
        return False
    return all(Counter(_line_tokens(x)) == Counter(_line_tokens(y)) for x, y in zip(b, a))


# ---- 프롬프트·응답 --------------------------------------------------------

def build_prompt(card: AlertCard) -> str:
    """sLLM에 줄 지시문. 줄 수·숫자 유지와 금지어를 명시한다."""
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(card.lines, start=1))
    return (
        "너는 발달장애인을 위한 쉬운 글 도우미야.\n"
        "아래 문장을 더 쉽고 짧은 한국어로 다듬어 줘.\n"
        "규칙:\n"
        f"- 줄 수는 그대로 {len(card.lines)}줄.\n"
        f"- 한 줄에 한 문장, {MAX_LINE_LEN}자 이내.\n"
        "- 숫자와 단위(예: 30만 원, 4번, 새벽 2시)는 그대로 둬.\n"
        "- 새로운 사실을 더하지 마.\n"
        f"- 다음 말은 쓰지 마: {', '.join(FORBIDDEN_WORDS)}.\n"
        '- 결과는 JSON 하나로만 답해: {"lines": ["...", "..."]}\n'
        "문장:\n"
        f"{numbered}\n"
    )


_LIST_PREFIX = re.compile(r"^\s*(?:\d+[.)]\s+|[-*•]\s*)")


def parse_lines(text: str) -> Optional[list[str]]:
    """sLLM 응답 글에서 {"lines": [...]} 를 꺼낸다. 형식이 틀리면 None."""
    candidates = [text]
    match = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        lines = data.get("lines") if isinstance(data, dict) else None
        if isinstance(lines, list) and lines and all(isinstance(x, str) for x in lines):
            cleaned = [_LIST_PREFIX.sub("", x).strip() for x in lines]
            if all(cleaned):
                return cleaned
    return None


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다(다른 호스트로 새지 않게)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


# ---- 본체 -----------------------------------------------------------------

class LocalLLMRewriter:
    """로컬 sLLM으로 카드의 lines만 다듬는다. 실패하면 언제나 원본을 돌려준다."""

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, model: str = "", enabled: bool = False,
                 timeout: float = 5.0, seed: int = 0, api_path: str = DEFAULT_API_PATH) -> None:
        self._endpoint = validate_loopback_endpoint(endpoint)
        self.model = model
        self.enabled = enabled
        self.timeout = float(timeout)
        self.seed = int(seed)
        self.api_path = "/" + api_path.lstrip("/")
        self.last_error: Optional[str] = None

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def url(self) -> str:
        return self._endpoint + self.api_path

    def rewrite(self, card: AlertCard) -> AlertCard:
        """lines를 다듬은 새 카드. 조건을 못 지키면 원본 카드 그대로."""
        self.last_error = None
        if not self.enabled:
            return card
        if not self.model:
            self.last_error = "모델 이름이 비어 있어요."
            return card
        try:
            reply = self._generate(build_prompt(card))
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            self.last_error = f"로컬 sLLM 연결 실패: {exc}"
            return card
        new_lines = parse_lines(reply)
        if new_lines is None:
            self.last_error = "응답 형식이 맞지 않아요."
            return card
        return self._accept_or_original(card, new_lines)

    # 검증을 통과할 때만 바꾼다
    def _accept_or_original(self, card: AlertCard, new_lines: list[str]) -> AlertCard:
        if new_lines == card.lines:
            return card
        if len(new_lines) != len(card.lines):
            self.last_error = "줄 수가 달라졌어요."
            return card
        if not same_numbers(card.lines, new_lines):
            self.last_error = "숫자가 달라졌어요."
            return card
        candidate = replace(
            card,
            lines=new_lines,
            speak_text=make_speak_text(card.title, new_lines, card.question),
            source="llm",
        )
        issues = readability_issues(candidate)
        if issues:
            self.last_error = "쉬운 글 규칙 위반: " + "; ".join(issues)
            return card
        return candidate

    def _generate(self, prompt: str) -> str:
        url = self.url
        validate_loopback_endpoint(url)  # 방어적 재확인
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "seed": self.seed},
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        # 빈 ProxyHandler: HTTP(S)_PROXY 환경변수를 무시해 외부로 새지 않게 한다
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())
        with opener.open(request, timeout=self.timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("응답이 너무 커요.")
        data: Any = json.loads(raw.decode("utf-8"))
        text = data.get("response") if isinstance(data, dict) else None
        if not isinstance(text, str):
            raise ValueError("응답에 response 글이 없어요.")
        return text


__all__ = [
    "DEFAULT_ENDPOINT", "LocalLLMRewriter", "build_prompt", "number_tokens",
    "parse_lines", "same_numbers", "validate_loopback_endpoint",
]
