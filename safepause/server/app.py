"""SafePause 로컬 웹 서버(FastAPI) — PC판. SPEC §10, 제안서 S20~S23·S35·S37·S38.

업무 로직은 safepause.api.service(프레임워크 없음)에 있고, 이 모듈은 HTTP 틀만 맡는다.
안드로이드 앱은 같은 서비스를 Pyodide 브리지(safepause.api.bridge)로 부른다.

보안 원칙
- 127.0.0.1 전용: Host 머리글이 loopback 이름이 아니면 거절한다(DNS 리바인딩 방지).
  바인드 주소는 CLI(``python -m safepause serve``)가 127.0.0.1로 고정한다.
- 세션 토큰(v0.2): serve가 켤 때마다 새 토큰을 만들고, 브라우저를 ``/#k=<토큰>``으로 연다. 화면은 모든
  /api 요청(GET 포함)에 ``X-SafePause: <토큰>``을 붙인다. 토큰이 틀리면 403. 같은 PC의 다른 프로그램·다른
  사용자 계정이 로컬 서버로 동의를 켜거나 거래를 읽거나 지우는 일을 막는다(v0.1은 고정값 "1"이라 막지 못했음).
  create_app(token=None)이면 v0.1처럼 상태를 바꾸는 요청에 "1"만 요구한다(테스트용).
- Origin 머리글이 있으면 같은 출처여야 한다('null' 출처도 거절).
- 요청 본문 한도: 파일 올리기 5MB(+여유), 그 밖의 요청 64KB. 길이를 모르는 본문(chunked)은 받지 않는다.
- 처리하지 못한 예외도 한국어 JSON(500)으로 돌려준다(스택은 서버 창에만).
"""
from __future__ import annotations

import hmac
import logging
import re
from collections.abc import Callable, Iterable
from datetime import datetime
from email import policy as _email_policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from safepause import __version__, config
from safepause.api.constants import MAX_UPLOAD_BYTES, NO_FILE, TOO_BIG
from safepause.api.router import INTERNAL_ERROR
from safepause.api.schemas import ConsentIn, DecideIn, EvalIn, HelperIn, PendingIn, SampleIn, validation_detail
from safepause.api.service import (   # noqa: F401  (v0.1 이름: 테스트·도구가 여기서 가져간다)
    EvalUnavailable,
    Evaluator,
    Service,
    ServiceError,
    _mask_contact,
    _plain,
    _recent_high,
    train_count,
)
from safepause.config import Settings
from safepause.store import StoreError

log = logging.getLogger("safepause.server")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATIC_DIR = WEB_DIR   # v0.1 이름
ALLOWED_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
CLIENT_HEADER = "x-safepause"          # 세션 토큰(또는 토큰 없는 모드에서 "1")
UPLOAD_OVERHEAD_BYTES = 64 * 1024      # multipart 머리글 등 파일 밖 여유분
MAX_JSON_BYTES = 64 * 1024             # 파일 올리기가 아닌 요청 본문 한도
UPLOAD_PATH = "/api/data/upload"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
        "connect-src 'self'; font-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'")


# Host 머리글은 '이름[:포트]' 모양만 받는다('127.0.0.1/x'처럼 경로가 섞인 값은 거절).
# v0.2 2차 검증: 옛 starlette(0.36)는 request.url을 Host 문자열로 만들어, 경로가 섞인 Host로 /api 판단을 속일 수 있었다.
_HOST_RE = re.compile(r"^(?P<host>127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?$", re.IGNORECASE)


def _host_of(value: str) -> str:
    """'127.0.0.1:8765', '[::1]:8765' → 호스트 이름. 모양이 다르면 빈 글."""
    m = _HOST_RE.match((value or "").strip())
    if not m:
        return ""
    return m.group("host").strip("[]").lower()


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def _secure(response: Response, *, api: bool) -> Response:
    """보안 머리글을 붙인다(정상 응답·오류 응답 모두)."""
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    if api:
        response.headers["Cache-Control"] = "no-store"
    else:   # 화면 파일: 늘 다시 확인(새 버전으로 바꾼 뒤 옛 파일이 남지 않게)
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _json(status: int, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail, **extra})


async def _read_body_limited(request: Request, limit: int) -> bytes:
    """요청 본문을 메모리로 읽는다. 받는 동안 크기를 세어 limit를 넘으면 바로 413."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ServiceError(413, TOO_BIG)
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_form(content_type: str, body: bytes) -> dict[str, bytes]:
    """multipart/form-data 본문을 메모리에서 나눈다({칸 이름: 내용}). 임시 파일을 쓰지 않는다."""
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type:
        raise ServiceError(400, NO_FILE)
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "replace")
    message = BytesParser(policy=_email_policy.HTTP).parsebytes(head + body)
    if not message.is_multipart():
        raise ServiceError(400, NO_FILE)
    fields: dict[str, bytes] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or name in fields:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            fields[name] = payload
    return fields


# ---- 앱 팩토리 ------------------------------------------------------------

def create_app(home: Path | str | None = None, *, settings: Settings | None = None,
               seed: int = 0, evaluator: Optional[Evaluator] = None,
               allowed_hosts: Iterable[str] = ALLOWED_HOSTS,
               now: Callable[[], datetime] = datetime.now,
               token: Optional[str] = None) -> FastAPI:
    """SafePause FastAPI 앱을 만든다.

    home: 저장 폴더(없으면 config.data_dir()). evaluator: 성능 평가 함수(테스트용). now: 기록 시각(테스트용).
    token: 세션 토큰. 주면 모든 /api 요청에 X-SafePause: <토큰>이 있어야 한다(serve는 늘 준다).
    """
    root = Path(home) if home is not None else config.data_dir()
    service = Service(root, settings or Settings(), seed, evaluator, now)
    hosts = frozenset(h.lower() for h in allowed_hosts)
    token_bytes = token.encode("utf-8") if token else None

    # docs_url/redoc_url은 외부 CDN을 쓰므로 끈다(오프라인 원칙).
    app = FastAPI(title="SafePause", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.safepause = service

    def _token_ok(value: Optional[str]) -> bool:
        if token_bytes is None:
            return value == "1"
        return value is not None and hmac.compare_digest(value.encode("utf-8"), token_bytes)

    # ---- 보안 머리글·요청 확인 ----
    @app.middleware("http")
    async def _guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        host = _host_of(request.headers.get("host", ""))
        if host not in hosts:
            return _json(400, "이 주소로는 열 수 없어요. http://127.0.0.1 주소로 열어 주세요.")
        path = request.scope.get("path", "")   # 실제 라우팅에 쓰는 경로(Host 문자열과 무관)
        is_api = path.startswith("/api")
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            # Origin이 있으면 같은 출처여야 한다. 'null'(파일·샌드박스 등 출처를 숨긴 요청)도 거절한다
            if origin is not None and (origin.strip().lower() == "null" or
                                       urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()):
                return _json(403, "다른 사이트에서 보낸 요청은 받지 않아요.")
        if is_api and (request.method not in _SAFE_METHODS or token_bytes is not None):
            if not _token_ok(request.headers.get(CLIENT_HEADER)):
                return _json(403, "SafePause 화면에서 보낸 요청이 아니에요. SafePause 프로그램이 연 창에서 다시 해 주세요.")
        if request.method not in _SAFE_METHODS:
            # 본문을 읽기 전에 크기를 본다. 길이를 미리 알 수 없는 요청(chunked)은 받지 않는다.
            length = request.headers.get("content-length")
            if "transfer-encoding" in request.headers or (length is None and path == UPLOAD_PATH):
                return _json(411, "파일 크기를 알 수 없어요. SafePause 화면에서 다시 올려 주세요.")
            if length is not None:
                try:
                    size = int(length)
                except ValueError:
                    return _json(400, "요청 크기 값이 잘못됐어요.")
                limit = MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD_BYTES if path == UPLOAD_PATH else MAX_JSON_BYTES
                if size > limit:
                    return _json(413, TOO_BIG if path == UPLOAD_PATH else "요청이 너무 커요.")
        response: Response = await call_next(request)
        return _secure(response, api=is_api)

    # ---- 오류 처리(한국어) ----
    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        extra = {"errors": exc.errors} if exc.errors else {}
        return _json(exc.status, exc.detail, **extra)

    @app.exception_handler(StoreError)
    async def _store_error(request: Request, exc: StoreError) -> JSONResponse:
        return _json(500, str(exc))

    # 프레임워크가 내는 영어 오류(본문 해석 실패·없는 주소·허용 안 된 방법)도 쉬운 한국어로(안드로이드 router와 같은 문구)
    _HTTP_KO = {400: "보낸 내용을 읽지 못했어요. 다시 해 주세요.", 404: "없는 기능이에요.", 405: "이 방법으로는 쓸 수 없어요."}

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) and re.search(r"[가-힣]", exc.detail) else _HTTP_KO.get(exc.status_code, INTERNAL_ERROR)
        response = _json(exc.status_code, detail)
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail, errors = validation_detail(list(exc.errors()))
        return _json(422, detail, errors=errors)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("처리하지 못한 오류: %s %s", request.method, request.scope.get("path", ""))
        # 이 처리기는 가장 바깥에서 불려 _guard의 머리글이 붙지 않는다: 여기서 직접 붙인다
        return _secure(_json(500, INTERNAL_ERROR), api=True)

    # ---- 상태 ----
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return service.health()

    # ---- 동의(S18/S37) ----
    @app.get("/api/consent")
    def get_consent() -> dict[str, Any]:
        return service.get_consent()

    @app.put("/api/consent")
    def put_consent(body: ConsentIn) -> dict[str, Any]:
        return service.put_consent(body)

    # ---- 신뢰 조력자(S22/S37) ----
    @app.get("/api/helpers")
    def get_helpers() -> list[dict[str, Any]]:
        return service.get_helpers()

    @app.put("/api/helpers")
    def put_helpers(helpers: list[HelperIn]) -> list[dict[str, Any]]:
        return service.put_helpers(helpers)

    # ---- 데이터 ----
    @app.get("/api/data/summary")
    def data_summary() -> dict[str, Any]:
        return service.data_summary()

    @app.post("/api/data/sample")
    def data_sample(body: SampleIn) -> dict[str, Any]:
        return service.data_sample(body)

    def _upload_finish(generation: int, content_type: str, body: bytes) -> dict[str, Any]:
        fields = _parse_form(content_type, body)
        mapping = fields.get("mapping", b"").decode("utf-8", "replace")
        return service.upload_finish(generation, fields.get("file"), mapping)

    @app.post(UPLOAD_PATH)
    async def data_upload(request: Request) -> dict[str, Any]:
        """거래내역 CSV 올리기(multipart: file, 선택 mapping). 파일은 메모리에서만 읽는다."""
        generation = await run_in_threadpool(service.upload_begin)
        body = await _read_body_limited(request, MAX_UPLOAD_BYTES + UPLOAD_OVERHEAD_BYTES)
        return await run_in_threadpool(_upload_finish, generation, request.headers.get("content-type", ""), body)

    # ---- 내 거래 + 평가 ----
    @app.get("/api/transactions")
    def transactions(level: Literal["all", "caution", "high"] = "all",
                     limit: int = Query(0, ge=0, le=100_000),
                     offset: int = Query(0, ge=0, le=10_000_000)) -> dict[str, Any]:
        return service.transactions(level, limit, offset)

    @app.get("/api/payees")
    def payees() -> dict[str, Any]:
        return service.payees()

    # ---- 안전 정지(S20/S21) ----
    @app.post("/api/safepause/check")
    def safepause_check(body: PendingIn) -> dict[str, Any]:
        return service.check(body)

    @app.post("/api/safepause/decide")
    def safepause_decide(body: DecideIn) -> dict[str, Any]:
        return service.decide(body)

    # ---- 기록 ----
    @app.get("/api/cards")
    def cards(limit: int = Query(20, ge=1, le=500)) -> dict[str, Any]:
        return service.cards(limit)

    @app.get("/api/notices")
    def notices() -> dict[str, Any]:
        return service.notices()

    @app.get("/api/decisions")
    def decisions() -> dict[str, Any]:
        return service.decisions()

    # ---- 성능 확인 ----
    @app.post("/api/eval/run")
    def eval_run(body: Optional[EvalIn] = None) -> dict[str, Any]:
        return service.eval_run(body)

    @app.post("/api/eval/file")
    def eval_file() -> dict[str, Any]:
        return service.eval_file()

    # ---- 내보내기(선택 사항: 샘플 결과물·현장 검증 요약) ----
    @app.get("/api/export/results")
    def export_results() -> dict[str, Any]:
        return service.export_results_csv()

    @app.get("/api/export/validation")
    def export_validation() -> dict[str, Any]:
        return service.export_validation()

    # ---- 즉시 철회: 모두 지우기 ----
    @app.post("/api/wipe")
    def wipe() -> dict[str, Any]:
        return service.wipe()

    # ---- 화면(안드로이드 앱과 같은 파일) ----
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app


__all__ = ["ALLOWED_HOSTS", "CLIENT_HEADER", "EvalUnavailable", "WEB_DIR", "create_app"]
