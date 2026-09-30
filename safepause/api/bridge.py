"""안드로이드 앱(Pyodide) 진입점. 웹 워커(engine/worker.mjs)가 부른다.

    init("/spdata/store")                    # 저장 폴더(IndexedDB에 연결된 폴더)
    warm()                                   # AI 패키지를 실은 뒤: 엔진 모듈을 미리 import
    handle(method, path, body_json, raw)     # → '{"status": 200, "body": {...}}'

PC판과 같은 서비스·라우터를 쓰므로 같은 요청에 같은 응답을 준다. 인터넷을 쓰지 않는다.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from safepause.api.router import INTERNAL_ERROR, dispatch
from safepause.api.service import Service

_service: Optional[Service] = None


def init(home: str) -> None:
    global _service
    _service = Service(home)


def warm() -> None:
    """numpy·scikit-learn을 실은 뒤 탐지 엔진 모듈을 미리 불러 둔다(첫 분석 대기 줄이기)."""
    import safepause.data.synth  # noqa: F401
    import safepause.detect.engine  # noqa: F401


def _is_nullish(value: Any) -> bool:
    """None 또는 자바스크립트 null(Pyodide 0.25+는 JS null을 None이 아닌 pyodide.ffi.jsnull로 넘긴다)."""
    if value is None:
        return True
    try:
        from pyodide.ffi import jsnull  # type: ignore[import-not-found]
    except ImportError:
        return False
    return value is jsnull


def _to_bytes(raw: Any) -> Optional[bytes]:
    if _is_nullish(raw):
        return None
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw)
    to_bytes = getattr(raw, "to_bytes", None)   # Pyodide JsProxy(Uint8Array)
    if callable(to_bytes):
        return bytes(to_bytes())
    return bytes(raw)


def handle(method: str, path: str, body_json: str = "null", raw: Any = None) -> str:
    if _service is None:
        return json.dumps({"status": 503, "body": {"detail": "엔진이 아직 준비되지 않았어요."}}, ensure_ascii=False)
    try:
        body = json.loads(body_json) if body_json else None
    except (json.JSONDecodeError, RecursionError):
        return json.dumps({"status": 400, "body": {"detail": "요청 형식이 잘못됐어요."}}, ensure_ascii=False)
    try:
        status, payload = dispatch(_service, method, path, body, _to_bytes(raw))
        return json.dumps({"status": status, "body": payload}, ensure_ascii=False, allow_nan=False)
    except Exception:   # dispatch는 예외를 내지 않지만, 직렬화 등 마지막 안전망
        return json.dumps({"status": 500, "body": {"detail": INTERNAL_ERROR}}, ensure_ascii=False)


__all__ = ["handle", "init", "warm"]
