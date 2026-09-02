"""Guardrails service using NeMo Guardrails."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx

# Optional NeMo import - deterministic Persian rails (actions.py) work without it.
# On hosts where nemoguardrails is installed (py<=3.13 / H200), full Colang rails load.
try:
    from nemoguardrails import RailsConfig
    from nemoguardrails.integrations.langchain.runnable import RunnableRails
    NEMO_AVAILABLE = True
except ImportError:
    RailsConfig = None
    RunnableRails = None
    NEMO_AVAILABLE = False

from .config import get_settings, load_nemo_config
from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChoice,
    RailCheckRequest,
    RailCheckResponse,
    HealthResponse,
    ReadyResponse,
)
from .actions import (
    normalize_persian,
    check_input_persian,
    check_output_persian,
)

log = logging.getLogger(__name__)

# Global state
_rails_app = None
_nemo_config_loaded: bool = False
_upstream_reachable: bool = False


async def check_upstream_health() -> bool:
    """Check if upstream Gemma manager is reachable."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0, pool=5.0),
            trust_env=False,
        ) as client:
            response = await client.get(settings.upstream_health_url)
            return response.status_code == 200
    except Exception as e:
        log.warning("Upstream health check failed: %s", e)
        return False


async def initialize_rails() -> None:
    """Initialize NeMo Guardrails application (or deterministic-only fallback)."""
    global _rails_app, _nemo_config_loaded, _upstream_reachable

    settings = get_settings()

    if NEMO_AVAILABLE:
        try:
            # Load NeMo configuration
            config_dict = load_nemo_config()
            rails_config = RailsConfig.from_content(
                yaml_content=config_dict.get("models", []),
                colang_content=config_dict.get("rails_colang", ""),
            )
            _rails_app = RunnableRails(config=rails_config)
            _nemo_config_loaded = True
            log.info("NeMo Guardrails configuration loaded successfully")
        except Exception as e:
            log.error("Failed to load NeMo Guardrails config: %s", e)
            _nemo_config_loaded = False
    else:
        log.warning(
            "nemoguardrails not installed - running deterministic Persian rails only "
            "(kb/*.json via actions.py). Install nemoguardrails for full Colang flows."
        )
        _nemo_config_loaded = True  # service is functional with deterministic rails

    # Check upstream
    _upstream_reachable = await check_upstream_health()
    if _upstream_reachable:
        log.info("Upstream Gemma manager is reachable")
    else:
        log.warning("Upstream Gemma manager is NOT reachable")


def get_rails_app():
    """Get the initialized Rails app (None in deterministic-only mode)."""
    return _rails_app


async def check_rails(request: RailCheckRequest) -> RailCheckResponse:
    """Run Persian deterministic rails first, then NeMo."""
    settings = get_settings()

    # ---- 1. Persian deterministic rails (no LLM, fail fast) ----
    if request.stage == "input":
        blocked, category, reason = check_input_persian(request.text)
        if blocked:
            # Map to Persian refusal
            msg_map = {
                "prompt_injection": "درخواست شما به عنوان تلاش برای دور زدن دستورات شناسایی شد.",
                "jailbreak": "درخواست شما به عنوان تلاش برای دور زدن محدودیت‌ها شناسایی شد.",
                "hate": "محتوای شما حاوی زبان آزاردهنده است و قابل پردازش نیست.",
                "offense": "محتوای شما حاوی الفاظ نامناسب است.",
                "out_of_scope": "این دستیار فقط در حوزه اعتبارسنجی و گزارش اعتباری (ICS) پاسخ می‌دهد.",
            }
            return RailCheckResponse(
                allowed=False,
                action="refuse",
                categories=[category],
                reason=msg_map.get(category, "درخواست شما مسدود شد.") + f" ({reason})",
                policy_version=settings.policy_version,
                request_id=request.request_id,
            )
    else:
        blocked, category, reason = check_output_persian(request.text)
        if blocked:
            return RailCheckResponse(
                allowed=False,
                action="refuse",
                categories=[category],
                reason="پاسخ حاوی محتوای نامناسب است." + f" ({reason})",
                policy_version=settings.policy_version,
                request_id=request.request_id,
            )

    # ---- 2. NeMo rails (Colang) - only when nemoguardrails is installed ----
    rails = get_rails_app()
    if rails is None:
        # Deterministic-only mode: Persian checks passed -> allow
        return RailCheckResponse(
            allowed=True,
            action="allow",
            categories=[],
            reason=None,
            policy_version=settings.policy_version,
            request_id=request.request_id,
        )

    # Prepare messages for NeMo
    messages = [{"role": "user", "content": request.text}]

    try:
        if request.stage == "input":
            # Run input rails
            result = await rails.generate_async(messages=messages)
            # Check if any input rail triggered a refusal
            # NeMo returns the bot response; if it's a refusal, it's blocked
            bot_response = result.get("content", "") if isinstance(result, dict) else str(result)

            # Check for refusal indicators
            is_refusal = any(
                phrase in bot_response.lower()
                for phrase in [
                    "cannot",
                    "not allowed",
                    "refuse",
                    "blocked",
                    "violation",
                ]
            )

            if is_refusal:
                return RailCheckResponse(
                    allowed=False,
                    action="refuse",
                    categories=["policy_violation"],
                    reason=bot_response,
                    policy_version=settings.policy_version,
                    request_id=request.request_id,
                )
            return RailCheckResponse(
                allowed=True,
                action="allow",
                categories=[],
                reason=None,
                policy_version=settings.policy_version,
                request_id=request.request_id,
            )

        else:  # output stage
            # Run output rails
            result = await rails.generate_async(messages=messages)
            bot_response = result.get("content", "") if isinstance(result, dict) else str(result)

            is_refusal = any(
                phrase in bot_response.lower()
                for phrase in [
                    "cannot",
                    "not allowed",
                    "refuse",
                    "blocked",
                    "violation",
                ]
            )

            if is_refusal:
                return RailCheckResponse(
                    allowed=False,
                    action="refuse",
                    categories=["output_violation"],
                    reason=bot_response,
                    policy_version=settings.policy_version,
                    request_id=request.request_id,
                )
            return RailCheckResponse(
                allowed=True,
                action="allow",
                categories=[],
                reason=None,
                policy_version=settings.policy_version,
                request_id=request.request_id,
            )

    except Exception as e:
        log.error("Rail check failed: %s", e)
        # Fail closed on policy engine errors
        return RailCheckResponse(
            allowed=False,
            action="refuse",
            categories=["engine_error"],
            reason=f"Policy engine error: {str(e)}",
            policy_version=settings.policy_version,
            request_id=request.request_id,
        )


async def _call_upstream(messages: list, request: ChatCompletionRequest) -> str:
    """Direct OpenAI-compatible call to the upstream Gemma manager."""
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_read_timeout,
                              connect=settings.upstream_connect_timeout,
                              read=settings.upstream_read_timeout,
                              write=settings.upstream_read_timeout,
                              pool=settings.upstream_connect_timeout),
        trust_env=False,
    ) as client:
        resp = await client.post(
            settings.upstream_chat_url,
            json={
                "model": request.model,
                "messages": messages,
                "max_tokens": request.max_tokens or 4000,
                "temperature": request.temperature,
            },
            headers={"Authorization": f"Bearer {settings.upstream_llm_api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


async def guarded_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Run guarded chat completion via NeMo Guardrails -> upstream Gemma."""
    rails = get_rails_app()
    settings = get_settings()

    # Extract user message (last user message in conversation)
    user_messages = [m for m in request.messages if m.get("role") == "user"]
    if not user_messages:
        raise ValueError("No user message in request")

    last_user_msg = user_messages[-1]["content"]

    # 1. Input rail check
    input_check = await check_rails(
        RailCheckRequest(stage="input", text=last_user_msg)
    )
    if not input_check.allowed:
        # Return refusal response
        refusal_msg = input_check.reason or "I cannot comply with that request."
        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message={"role": "assistant", "content": refusal_msg},
                    finish_reason="content_filter",
                )
            ],
        )

    # 2. Call upstream Gemma via NeMo (which handles output rails), or direct in
    # deterministic-only mode (nemoguardrails not installed on this host).
    try:
        # Prepare messages for upstream
        upstream_messages = [
            {"role": m["role"], "content": m["content"]} for m in request.messages
        ]

        if rails is not None:
            # Call NeMo which will run output rails after generation
            result = await rails.generate_async(messages=upstream_messages)
            bot_response = result.get("content", "") if isinstance(result, dict) else str(result)
        else:
            # Direct upstream call - output checked by check_output_persian below
            bot_response = await _call_upstream(upstream_messages, request)

        # 3. Output rail check
        output_check = await check_rails(
            RailCheckRequest(stage="output", text=bot_response)
        )
        if not output_check.allowed:
            refusal_msg = output_check.reason or "I cannot provide that response."
            return ChatCompletionResponse(
                model=request.model,
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message={"role": "assistant", "content": refusal_msg},
                        finish_reason="content_filter",
                    )
                ],
            )

        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message={"role": "assistant", "content": bot_response},
                    finish_reason="stop",
                )
            ],
        )

    except httpx.TimeoutException:
        log.error("Upstream timeout")
        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message={
                        "role": "assistant",
                        "content": "The model request timed out. Please try again.",
                    },
                    finish_reason="length",
                )
            ],
        )
    except httpx.ConnectError:
        log.error("Upstream connection failed")
        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message={
                        "role": "assistant",
                        "content": "Unable to reach the model service. Please try again later.",
                    },
                    finish_reason="length",
                )
            ],
        )
    except Exception as e:
        log.error("Guarded completion failed: %s", e)
        # Fail closed - don't expose internal errors
        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message={
                        "role": "assistant",
                        "content": "An error occurred while processing your request.",
                    },
                    finish_reason="length",
                )
            ],
        )


@asynccontextmanager
async def lifespan(app):
    """Application lifespan handler."""
    log.info("Starting Guardrails service...")
    await initialize_rails()
    yield
    log.info("Shutting down Guardrails service...")


def create_app():
    """Create FastAPI application."""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(
        title="Work RAG Guardrails",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=ReadyResponse)
    async def ready():
        global _upstream_reachable
        _upstream_reachable = await check_upstream_health()
        return ReadyResponse(
            status="ready" if _nemo_config_loaded and _upstream_reachable else "not_ready",
            nemo_config_loaded=_nemo_config_loaded,
            upstream_reachable=_upstream_reachable,
        )

    @app.post("/v1/rails/check", response_model=RailCheckResponse)
    async def rails_check(request: RailCheckRequest):
        if not _nemo_config_loaded:
            raise HTTPException(status_code=503, detail="NeMo configuration not loaded")
        return await check_rails(request)

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    async def chat_completions(request: ChatCompletionRequest):
        if not _nemo_config_loaded:
            raise HTTPException(status_code=503, detail="NeMo configuration not loaded")
        if not _upstream_reachable:
            raise HTTPException(status_code=503, detail="Upstream model not reachable")
        return await guarded_completion(request)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


def main():
    """Entry point for running the service."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "work_rag_guardrails.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=settings.guardrails_port,
        log_level="info",
    )