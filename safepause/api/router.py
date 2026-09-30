"""(메서드, 경로) → Service 호출. 안드로이드 앱(Pyodide 브리지)이 FastAPI 없이 같은 API를 쓰게 한다.

PC판 FastAPI 라우트(safepause.server.app)와 같은 경로·같은 입력 검사(schemas)·같은 한국어 오류 문구를 쓴다.
tests/test_api_router.py가 두 쪽의 응답이 같은지 비교한다.
"""
from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ValidationError

from safepause.api.schemas import (
    CardsQuery,
    ConsentIn,
    DecideIn,
    EvalIn,
    HelperList,
    PendingIn,
    SampleIn,
    TxnQuery,
    validation_detail,
)
from safepause.api.service import Service, ServiceError
from safepause.store import StoreError

INTERNAL_ERROR = "처리하다 문제가 생겼어요. 다시 해 주세요."

Handler = Callable[[Service, dict[str, str], Any, Optional[bytes]], Any]


def _model(cls: type[BaseModel], body: Any) -> Any:
    return cls.model_validate(body if body is not None else {})


def _eval_run(s: Service, q: dict[str, str], body: Any, raw: Optional[bytes]) -> Any:
    return s.eval_run(EvalIn.model_validate(body) if body is not None else None)


def _upload(s: Service, q: dict[str, str], body: Any, raw: Optional[bytes]) -> Any:
    mapping = ""
    if isinstance(body, dict) and isinstance(body.get("mapping"), str):
        mapping = body["mapping"]
    return s.upload(raw, mapping)


def _transactions(s: Service, q: dict[str, str], body: Any, raw: Optional[bytes]) -> Any:
    query = TxnQuery.model_validate(q)
    return s.transactions(query.level, query.limit, query.offset)


def _cards(s: Service, q: dict[str, str], body: Any, raw: Optional[bytes]) -> Any:
    return s.cards(CardsQuery.model_validate(q).limit)


ROUTES: dict[tuple[str, str], Handler] = {
    ("GET", "/api/health"): lambda s, q, b, r: s.health(),
    ("GET", "/api/consent"): lambda s, q, b, r: s.get_consent(),
    ("PUT", "/api/consent"): lambda s, q, b, r: s.put_consent(_model(ConsentIn, b)),
    ("GET", "/api/helpers"): lambda s, q, b, r: s.get_helpers(),
    ("PUT", "/api/helpers"): lambda s, q, b, r: s.put_helpers(HelperList.validate_python(b if b is not None else [])),
    ("GET", "/api/data/summary"): lambda s, q, b, r: s.data_summary(),
    ("POST", "/api/data/sample"): lambda s, q, b, r: s.data_sample(_model(SampleIn, b)),
    ("POST", "/api/data/upload"): _upload,
    ("GET", "/api/transactions"): _transactions,
    ("GET", "/api/payees"): lambda s, q, b, r: s.payees(),
    ("POST", "/api/safepause/check"): lambda s, q, b, r: s.check(_model(PendingIn, b)),
    ("POST", "/api/safepause/decide"): lambda s, q, b, r: s.decide(_model(DecideIn, b)),
    ("GET", "/api/cards"): _cards,
    ("GET", "/api/notices"): lambda s, q, b, r: s.notices(),
    ("GET", "/api/decisions"): lambda s, q, b, r: s.decisions(),
    ("POST", "/api/eval/run"): _eval_run,
    ("POST", "/api/eval/file"): lambda s, q, b, r: s.eval_file(),
    ("GET", "/api/export/results"): lambda s, q, b, r: s.export_results_csv(),
    ("GET", "/api/export/validation"): lambda s, q, b, r: s.export_validation(),
    ("POST", "/api/wipe"): lambda s, q, b, r: s.wipe(),
}


def dispatch(service: Service, method: str, path: str, body: Any = None,
             raw: Optional[bytes] = None) -> tuple[int, Any]:
    """요청 하나를 처리해 (상태 코드, JSON으로 보낼 값)을 돌려준다. 예외를 밖으로 내보내지 않는다."""
    parts = urlsplit(path)
    route = ROUTES.get((method.upper(), parts.path))
    if route is None:
        known = any(p == parts.path for (_, p) in ROUTES)
        return (405, {"detail": "이 방법으로는 쓸 수 없어요."}) if known else (404, {"detail": "없는 기능이에요."})
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    try:
        return 200, route(service, query, body, raw)
    except ValidationError as exc:
        detail, errors = validation_detail(exc.errors())
        return 422, {"detail": detail, "errors": errors}
    except ServiceError as exc:
        payload: dict[str, Any] = {"detail": exc.detail}
        if exc.errors:
            payload["errors"] = exc.errors
        return exc.status, payload
    except StoreError as exc:
        return 500, {"detail": str(exc)}
    except Exception:  # 마지막 안전망: 사용자에게는 쉬운 말, 개발자에게는 로그
        traceback.print_exc()
        return 500, {"detail": INTERNAL_ERROR}


__all__ = ["INTERNAL_ERROR", "ROUTES", "dispatch"]
