import re
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.auth.routes import router as auth_router


app = FastAPI()
app.include_router(auth_router, prefix="/api/v1")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID")
    if (
        request_id is None
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id) is None
    ):
        request_id = f"req_{uuid4().hex}"
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    fields: dict[str, list[str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "request_id": request.state.request_id,
        },
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    code = detail.get("code")
    if not isinstance(code, str):
        code = "request_error"
    message = detail.get("message")
    if not isinstance(message, str):
        message = "The request could not be completed."
    return _error_response(
        request,
        exc.status_code,
        code,
        message,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    fields: dict[str, list[str]] = {}
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"][1:])
        if location:
            fields.setdefault(location, []).append("Invalid value.")
    return _error_response(
        request,
        422,
        "validation_error",
        "The request could not be completed.",
        fields,
    )