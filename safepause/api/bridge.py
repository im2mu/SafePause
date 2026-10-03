"""안드로이드 앱(Pyodide) 진입점. 웹 워커(engine/worker.mjs)가 부른다.

    init("/spdata/store")                    # 저장 폴더(IndexedDB에 연결된 폴더)
    warm()                                   # AI 패키지를 실은 뒤: 엔진 모듈을 미리 import
    warm_more()                              # 요청이 없는 동안: 첫 학습이 쓰는 큰 모듈을 하나씩 미리 import
    handle(method, path, body_json, raw)     # → '{"status": 200, "body": {...}}'

PC판과 같은 서비스·라우터를 쓰므로 같은 요청에 같은 응답을 준다. 인터넷을 쓰지 않는다.
"""
from __future__ import annotations

import importlib
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


# 첫 분석(학습)이 처음 부를 때 불러오는 큰 모듈. 앱 안에서는 모두 약 3초 걸려(scipy.stats 약 1.3초) 워커가 요청이 없는
# 동안 하나씩 미리 불러 둔다(warm_more). 어차피 첫 학습 때 같은 순서로 불러오는 모듈이라 결과는 바뀌지 않는다
IDLE_MODULES: tuple[str, ...] = (
    "scipy.sparse", "scipy.special", "scipy.stats", "sklearn", "sklearn.ensemble",
    "safepause.data.sources", "safepause.data.loader",
)
_idle_next = 0


def warm_more() -> bool:
    """IDLE_MODULES에서 다음 모듈 하나를 불러온다. 더 남았으면 True. 불러오지 못하면 예외(워커가 그만둔다)."""
    global _idle_next
    if _idle_next >= len(IDLE_MODULES):
        return False
    name = IDLE_MODULES[_idle_next]
    _idle_next += 1
    importlib.import_module(name)
    return _idle_next < len(IDLE_MODULES)


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
    except (ValueError, RecursionError):   # JSONDecodeError도 ValueError. 4300자리 넘는 정수도 여기서 400
        return json.dumps({"status": 400, "body": {"detail": "요청 형식이 잘못됐어요."}}, ensure_ascii=False)
    try:
        status, payload = dispatch(_service, method, path, body, _to_bytes(raw))
        return json.dumps({"status": status, "body": payload}, ensure_ascii=False, allow_nan=False)
    except Exception:   # dispatch는 예외를 내지 않지만, 직렬화 등 마지막 안전망
        return json.dumps({"status": 500, "body": {"detail": INTERNAL_ERROR}}, ensure_ascii=False)


__all__ = ["handle", "init", "warm", "warm_more"]
