import asyncio
import os
import re
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from src.agent.config import get_agent_runtime_settings
from src.agentcard.routes import router as agentcard_router
from src.agentcard.receipts import run_agentcard_worker
from src.agent.routes import router as agent_router
from src.agent.worker import run_agent_worker
from src.approvals.routes import router as approvals_router
from src.auth.routes import router as auth_router
from src.catalog.routes import router as catalog_router
from src.conversations.routes import router as conversations_router
from src.dashboard.routes import router as dashboard_router
from src.integrations.routes import router as integrations_router
from src.orders.routes import router as orders_router
from src.owner_assistant.routes import router as owner_assistant_router
from src.owner_assistant.routes import service_router as internal_owner_assistant_router
from src.realtime.routes import router as realtime_router
from src.search.routes import router as search_router
from src.settings.routes import router as settings_router
from src.supabase.client import get_supabase_settings
from src.webhooks.routes import router as webhooks_router
from src.widget.routes import router as widget_router
from src.workspace.routes import router as workspace_router


logger = logging.getLogger(__name__)
load_dotenv(Path(__file__).with_name(".env"))
is_production = os.getenv("APP_ENV", "development").lower() == "production"


class CheckoutTokenAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        if (
            isinstance(arguments, tuple)
            and len(arguments) >= 3
            and isinstance(arguments[2], str)
        ):
            sanitized_path = re.sub(
                r"(?<=/agentcard/checkout/)[A-Za-z0-9_-]{32,64}",
                "[REDACTED]",
                arguments[2],
            )
            record.args = (*arguments[:2], sanitized_path, *arguments[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(CheckoutTokenAccessLogFilter())


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_tasks = []
    runtime_settings = get_agent_runtime_settings()
    if runtime_settings.strands_agent_enabled:
        if runtime_settings.openrouter_api_key is None:
            logger.error(
                "Strands worker is enabled but OPENROUTER_API_KEY is not configured."
            )
        elif get_supabase_settings().supabase_secret_key is None:
            logger.error(
                "Strands worker is enabled but SUPABASE_SECRET_KEY is not configured."
            )
        else:
            worker_tasks.append(
                asyncio.create_task(run_agent_worker(), name="strands-agent-worker")
            )
    if get_supabase_settings().supabase_secret_key is not None:
        worker_tasks.append(
            asyncio.create_task(
                run_agentcard_worker(),
                name="agentcard-receipt-worker",
            )
        )
    try:
        yield
    finally:
        for worker_task in worker_tasks:
            worker_task.cancel()
        for worker_task in worker_tasks:
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    openapi_url=None if is_production else "/api/v1/openapi.json",
    docs_url=None if is_production else "/api/v1/docs",
    redoc_url=None,
    lifespan=lifespan,
)


class WidgetCORSMiddleware(CORSMiddleware):
    def __init__(self, app, standard_origins, **kwargs):
        self.standard_origins = set(standard_origins)
        super().__init__(app, **kwargs)

    async def __call__(self, scope, receive, send):
        origin = next(
            (
                value.decode()
                for name, value in scope.get("headers", [])
                if name.lower() == b"origin"
            ),
            None,
        )
        if (
            scope["type"] == "http"
            and scope["path"].startswith("/api/v1/public/widgets/")
            and origin not in self.standard_origins
        ):
            await super().__call__(scope, receive, send)
            return
        await self.app(scope, receive, send)


allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_WEB_ORIGINS",
        "https://reactant-theta.vercel.app,http://localhost:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "If-Match",
        "Idempotency-Key",
        "X-Request-ID",
    ],
    expose_headers=["ETag", "X-Request-ID"],
)
app.add_middleware(
    WidgetCORSMiddleware,
    standard_origins=allowed_origins,
    allow_origins=[],
    allow_origin_regex=r"https?://[^/]+",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

for router in (
    auth_router,
    workspace_router,
    settings_router,
    dashboard_router,
    catalog_router,
    integrations_router,
    agent_router,
    conversations_router,
    owner_assistant_router,
    approvals_router,
    orders_router,
    agentcard_router,
    search_router,
    realtime_router,
    widget_router,
):
    app.include_router(router, prefix="/api/v1")
app.include_router(internal_owner_assistant_router, prefix="/internal/v1")
app.include_router(webhooks_router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    started_at = time.perf_counter()
    request_id = request.headers.get("X-Request-ID")
    if (
        request_id is None
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request_id) is None
    ):
        request_id = f"req_{uuid4().hex}"
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        re.sub(
            r"(?<=/agentcard/checkout/)[A-Za-z0-9_-]{32,64}",
            "[REDACTED]",
            request.url.path,
        ),
        response.status_code,
        round((time.perf_counter() - started_at) * 1000),
    )
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


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled request failure request_id=%s exception_type=%s",
        request.state.request_id,
        type(exc).__name__,
    )
    return _error_response(
        request,
        500,
        "internal_error",
        "The request could not be completed.",
    )