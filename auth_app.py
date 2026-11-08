import logging
import os

from dotenv import load_dotenv
from starlette.applications import Starlette

load_dotenv()
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import feedback
import google_oidc


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


async def _json_body(request: Request) -> dict | JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Expected a JSON body."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Expected a JSON object."}, status_code=400)
    return body


def _error(exc: auth.AuthError) -> JSONResponse:
    return JSONResponse({"error": exc.message}, status_code=exc.status_code)


async def signup(request: Request) -> JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        result = auth.signup(str(body.get("email") or ""), str(body.get("password") or ""))
    except auth.AuthError as exc:
        return _error(exc)
    return JSONResponse(result, status_code=201)


async def login(request: Request) -> JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        result = auth.login(str(body.get("email") or ""), str(body.get("password") or ""))
    except auth.AuthError as exc:
        return _error(exc)
    return JSONResponse({"ok": True, **result})


async def logout(request: Request) -> JSONResponse:
    auth.logout(_bearer(request))
    return JSONResponse({"ok": True})


async def me(request: Request) -> JSONResponse:
    try:
        user = auth.current_user(_bearer(request))
    except auth.AuthError as exc:
        return _error(exc)
    return JSONResponse(user)


async def google_status(_request: Request) -> JSONResponse:
    return JSONResponse({"enabled": google_oidc.google_enabled()})


async def google_start(request: Request):
    return await google_oidc.start(request)


async def google_callback(request: Request) -> JSONResponse:
    return await google_oidc.finish(request)


async def post_feedback(request: Request) -> JSONResponse:
    try:
        auth.current_user(_bearer(request))
    except auth.AuthError as exc:
        return _error(exc)
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    reaction = body.get("reaction")
    trace_id = body.get("trace_id")
    if reaction is not None and not isinstance(reaction, str):
        return JSONResponse(
            {"error": "reaction must be liked or disliked."},
            status_code=400,
        )
    if trace_id is not None and not isinstance(trace_id, str):
        trace_id = ""
    try:
        result = feedback.handle_feedback(
            trace_id if isinstance(trace_id, str) else None,
            reaction if isinstance(reaction, str) else None,
        )
    except feedback.FeedbackError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)
    if result is None:
        return JSONResponse({"ok": True, "logged": False})
    return JSONResponse({"ok": True, "logged": True})


async def verify(request: Request) -> JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        result = auth.verify_email_token(str(body.get("token") or ""))
    except auth.AuthError as exc:
        return _error(exc)
    return JSONResponse({"ok": True, **result})


app = Starlette(
    routes=[
        Route("/auth/signup", signup, methods=["POST"]),
        Route("/auth/login", login, methods=["POST"]),
        Route("/auth/logout", logout, methods=["POST"]),
        Route("/auth/me", me, methods=["GET"]),
        Route("/auth/verify", verify, methods=["POST"]),
        Route("/auth/google", google_status, methods=["GET"]),
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["POST"]),
        Route("/feedback", post_feedback, methods=["POST"]),
    ]
)


class _RedactAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage().lower()
        except Exception:
            return True
        if any(
            marker in message
            for marker in ("code=", "id_token", "client_secret", "access_token")
        ):
            record.msg = "redacted"
            record.args = ()
        return True


def _configure_logging() -> None:
    logger = logging.getLogger("gsb.auth")
    logger.setLevel(logging.INFO)
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    redact = _RedactAccessLog()
    for name in ("uvicorn.access", "uvicorn.error"):
        access_logger = logging.getLogger(name)
        if not any(isinstance(item, _RedactAccessLog) for item in access_logger.filters):
            access_logger.addFilter(redact)


def main() -> None:
    import uvicorn

    _configure_logging()
    uvicorn.run(
        app,
        host=os.getenv("AUTH_HOST", "127.0.0.1"),
        port=int(os.getenv("AUTH_PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
