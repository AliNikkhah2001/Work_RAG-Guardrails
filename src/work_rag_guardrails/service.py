"""Guardrails service using NeMo Guardrails (deterministic fallback)."""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
import re
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

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
from .dashboard import register as register_dashboard

log = logging.getLogger(__name__)

try:
    import nemoguardrails  # noqa: F401
    NEMO_AVAILABLE = True
except ImportError:
    NEMO_AVAILABLE = False

# Global state
_rails_app = None
_nemo_config_loaded: bool = False
_upstream_reachable: bool = False

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Lifespan: initialize rails on startup, cleanup on shutdown."""
    global _rails_app, _nemo_config_loaded, _upstream_reachable
    try:
        await initialize_rails()
    except Exception as e:
        log.error("Failed to initialize rails in lifespan: %s", e)
    yield


# Create the FastAPI app once at module level so uvicorn --factory works.
app = FastAPI(title="Work RAG Guardrails", version="mvp-1", lifespan=lifespan)


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
    """Initialize NeMo Guardrails application (best-effort; deterministic fallback)."""
    global _rails_app, _nemo_config_loaded, _upstream_reachable

    settings = get_settings()

    if NEMO_AVAILABLE:
        try:
            import yaml
            from nemoguardrails import RailsConfig
            from nemoguardrails.integrations.langchain.runnable import RunnableRails

            config_dict = load_nemo_config()
            yaml_content = yaml.safe_dump({"models": config_dict.get("models", [])}) if isinstance(config_dict.get("models"), list) else config_dict.get("models", "")
            rails_config = RailsConfig.from_content(
                yaml_content=yaml_content,
                colang_content=config_dict.get("rails_colang", ""),
            )
            _rails_app = RunnableRails(config=rails_config)
            _nemo_config_loaded = True
            log.info("NeMo Guardrails configuration loaded successfully")
        except Exception as e:
            log.warning(
                "NeMo Guardrails unavailable (%s) - running deterministic rails only", e
            )
            _rails_app = None
            _nemo_config_loaded = True
    else:
        log.warning(
            "nemoguardrails not installed - running deterministic rails only"
        )
        _nemo_config_loaded = True

    _upstream_reachable = await check_upstream_health()
    if _upstream_reachable:
        log.info("Upstream Gemma manager is reachable")
    else:
        log.warning("Upstream Gemma manager is NOT reachable")


def get_rails_app():
    """Get the initialized Rails app."""
    return _rails_app


def create_app():
    """Create and return the FastAPI app (rails init via lifespan)."""
    register_dashboard(app)
    return app


# ---- Routes ----

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@app.get("/ready", response_model=ReadyResponse)
async def ready():
    settings = get_settings()
    return ReadyResponse(
        status="ready" if _nemo_config_loaded else "not_ready",
        nemo_config_loaded=_nemo_config_loaded,
        upstream_reachable=_upstream_reachable,
        policy_version=settings.policy_version,
    )


@app.post("/v1/rails/check", response_model=RailCheckResponse)
async def check_rails(request: RailCheckRequest):
    """Signals → judge adjudication (NeMo second opinion), fail closed."""
    from .judge import adjudicate
    from . import events

    settings = get_settings()
    verdict = await adjudicate(request.text, stage=request.stage)
    events.log_event(request.stage, request.text, verdict,
                     request_id=request.request_id)

    if verdict["allowed"]:
        return RailCheckResponse(
            allowed=True, action="allow", categories=[],
            reason=None, policy_version=settings.policy_version,
            request_id=request.request_id,
        )
    category = verdict.get("category", "")
    if settings.guard_response_mode.strip().lower() == "verbose":
        msg_map = {
            "prompt_injection": "درخواست شما به عنوان تلاش برای دور زدن دستورات شناسایی شد.",
            "jailbreak": "درخواست شما به عنوان تلاش برای دور زدن محدودیت‌ها شناسایی شد.",
            "hate": "محتوای شما حاوی زبان آزاردهنده است و قابل پردازش نیست.",
            "offense": "محتوای شما حاوی الفاظ نامناسب است.",
            "out_of_scope": "این دستیار فقط در حوزه اعتبارسنجی و گزارش اعتباری (ICS) پاسخ می‌دهد.",
            "profanity": "محتوای شما حاوی الفاظ نامناسب است.",
            "pii": "محتوای شما حاوی اطلاعات شخصی است.",
            "secret": "نمی‌توانم این اطلاعات را ارائه دهم.",
            "policy": "درخواست شما با سیاست‌های دستیار مغایرت دارد.",
            "nemo": "درخواست شما توسط بازبینی امنیتی مسدود شد.",
        }
        base = msg_map.get(category, "درخواست شما مسدود شد.")
        if request.stage == "output" and category in ("hate", "offense", "profanity"):
            base = "پاسخ حاوی محتوای نامناسب است."
        return RailCheckResponse(
            allowed=False, action="refuse", categories=[category or "policy"],
            reason=base + f" ({verdict.get('reason', '')})",
            policy_version=settings.policy_version,
            request_id=request.request_id,
        )
    premade = (settings.refusal_message
               or "متأسفم، نمی‌توانم به این درخواست پاسخ دهم.")
    return RailCheckResponse(
        allowed=False, action="refuse", categories=["policy_violation"],
        reason=premade, policy_version=settings.policy_version,
        request_id=request.request_id,
    )


_CLEAN_PATTERNS = [
    (re.compile(r"<unused\d+>"), ""),
    (re.compile(r"<\|?tool_call\|?>"), ""),
    (re.compile(r"<\|?tool_response\|?>"), ""),
    (re.compile(r"tool_response\|>"), ""),
    (re.compile(r"tool_call\|>"), ""),
    (re.compile(r"\[multimodal\]"), ""),
    (re.compile(r"<\|channel>thought.*?<channel\|>", re.DOTALL), ""),
    (re.compile(r"<\|think\|>"), ""),
    (re.compile(r"<\|turn>.*?<turn\|>", re.DOTALL), ""),
    (re.compile(r"<bos>"), ""),
    (re.compile(r"<eos>"), ""),
    (re.compile(r"<\|?tool\|?>"), ""),
    (re.compile(r'<\|?\"|\|>'), ""),
    (re.compile(r"<\|?[^>]*\|>"), ""),
    (re.compile(r"[ \t]+"), " "),
    (re.compile(r"\n[ \t]*\n[ \t]*\n+"), "\n\n"),
    (re.compile(r"(?<!\n)\n(?!\n)"), " "),
]


def _clean_gemma_output(text: str) -> str:
    """Remove Gemma control/tool tokens that leak from llama.cpp."""
    if not text:
        return text
    for pat, repl in _CLEAN_PATTERNS:
        text = pat.sub(repl, text)
    return text.strip()


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
                "chat_template_kwargs": {"enable_thinking": False},
            },
            headers={"Authorization": f"Bearer {settings.resolved_api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        return _clean_gemma_output(raw)


async def guarded_completion(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Run guarded chat completion via Guardrails -> upstream Gemma."""
    rails = get_rails_app()
    settings = get_settings()

    user_messages = [m for m in request.messages if m.get("role") == "user"]
    if not user_messages:
        raise ValueError("No user message in request")

    last_user_msg = user_messages[-1]["content"]
    input_text = last_user_msg
    if "Question:" in last_user_msg:
        input_text = last_user_msg.split("Question:")[-1].strip()
        if not input_text:
            input_text = last_user_msg
    elif "سوال:" in last_user_msg:
        input_text = last_user_msg.split("سوال:")[-1].strip() or last_user_msg

    # Input rail check (signals → judge, fail closed)
    input_check = await check_rails(
        RailCheckRequest(stage="input", text=input_text)
    )
    if not input_check.allowed:
        refusal_msg = input_check.reason or "I cannot process that request."
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

    # Call upstream Gemma via NeMo (which handles output rails), or direct
    try:
        upstream_messages = [
            {"role": m["role"], "content": m["content"]} for m in request.messages
        ]

        if rails is not None:
            result = await rails.generate_async(messages=upstream_messages)
            bot_response = result.get("content", "") if isinstance(result, dict) else str(result)
        else:
            bot_response = await _call_upstream(upstream_messages, request)

        if not bot_response or not bot_response.strip():
            bot_response = "متأسفم، مدل پاسخ مناسبی تولید نکرد. بر اساس منابع بازیابی‌شده، لطفاً سوال را واضح‌تر بپرسید."

        # Output rail check (signals → judge, fail closed)
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

        from .actions import check_pii_ir
        from . import events as _events
        try:
            pii_blocked, _ = check_pii_ir(bot_response)
            if pii_blocked:
                bot_response = _events.mask_text(bot_response)
                log.info("output PII masked (request_id=%s)",
                         getattr(request, "request_id", ""))
        except Exception:
            pass

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

    except Exception as e:
        log.exception("Upstream error")
        return ChatCompletionResponse(
            model=request.model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message={
                        "role": "assistant",
                        "content": f"Upstream error: {str(e)[:200]}",
                    },
                    finish_reason="error",
                )
            ],
        )


async def guarded_completion_stream(request: ChatCompletionRequest):
    """Streaming version — input rail checked, then real upstream tokens yielded as SSE."""
    # Extract user message for input rail (same as guarded_completion)
    user_messages = [m for m in request.messages if m.get("role") == "user"]
    if not user_messages:
        raise ValueError("No user message")
    last_user_msg = user_messages[-1]["content"]
    input_text = last_user_msg
    if "Question:" in last_user_msg:
        input_text = last_user_msg.split("Question:")[-1].strip() or last_user_msg
    elif "سوال:" in last_user_msg:
        input_text = last_user_msg.split("سوال:")[-1].strip() or last_user_msg

    input_check = await check_rails(RailCheckRequest(stage="input", text=input_text))
    if not input_check.allowed:
        # Stream refusal as single chunk
        refusal = input_check.reason or "I cannot comply."
        yield f"data: {json.dumps({'choices':[{'delta':{'content': refusal},'finish_reason':'content_filter'}]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    upstream_messages = [{"role": m["role"], "content": m["content"]} for m in request.messages]
    # If NeMo rails loaded, we can't true-stream through NeMo (generate_async is buffered)
    # So in NEMO mode we fall back to buffered then chunk; else real stream
    rails = get_rails_app()
    if rails is not None:
        # Buffered fallback: call non-streaming then yield chunks without artificial delay
        # Still faster than fake streaming with sleep, but not token-by-token from LLM
        result = await rails.generate_async(messages=upstream_messages)
        bot_response = result.get("content", "") if isinstance(result, dict) else str(result)
        bot_response = _clean_gemma_output(bot_response)
        # Output rail check after full
        output_check = await check_rails(RailCheckRequest(stage="output", text=bot_response))
        if not output_check.allowed:
            bot_response = output_check.reason or "I cannot provide that response."
            yield f"data: {json.dumps({'choices':[{'delta':{'content': bot_response},'finish_reason':'content_filter'}]}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        # Yield without sleep — real generation already done, just chunk
        for tok in bot_response.split(" "):
            yield f"data: {json.dumps({'choices':[{'delta':{'content': tok+' '}}]}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Deterministic mode: real upstream streaming (no added latency)
    async for content in _call_upstream_stream(upstream_messages, request):
        # Optionally light clean per token
        # we don't sleep — tokens arrive as fast as LLM generates (~30-50ms)
        yield f"data: {json.dumps({'choices':[{'delta':{'content': content}}]}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """OpenAI-compatible chat completion with input/output guardrails."""
    if request.stream:
        return StreamingResponse(
            guarded_completion_stream(request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return await guarded_completion(request)


async def _call_upstream_stream(messages: list, request: ChatCompletionRequest):
    """Yield raw content deltas from upstream with stream=true (real streaming, no added latency).

    Upstream llama-server :18000 currently returns JSON even with stream:true (no SSE),
    so we handle both: if SSE, stream deltas; if JSON, chunk the full content without sleep.
    """
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.upstream_read_timeout,
                              connect=settings.upstream_connect_timeout,
                              read=settings.upstream_read_timeout,
                              write=settings.upstream_read_timeout,
                              pool=settings.upstream_connect_timeout),
        trust_env=False,
    ) as client:
        async with client.stream(
            "POST",
            settings.upstream_chat_url,
            json={
                "model": request.model,
                "messages": messages,
                "max_tokens": request.max_tokens or 4000,
                "temperature": request.temperature,
                "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            },
            headers={"Authorization": f"Bearer {settings.resolved_api_key}"},
        ) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            # Fallback: upstream returned buffered JSON (no SSE)
            if "application/json" in ctype:
                try:
                    body = await resp.aread()
                    data = json.loads(body)
                    raw = data["choices"][0]["message"]["content"]
                    raw = _clean_gemma_output(raw)
                    # Chunk without artificial delay — still counts as streaming from guardrails perspective
                    for tok in raw.split(" "):
                        if tok:
                            yield tok + " "
                    return
                except Exception as e:
                    log.warning("Fallback JSON parse failed: %s", e)
                    return
            # Real SSE path
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content
                    if choices[0].get("finish_reason"):
                        break
                except Exception:
                    continue


@app.post("/v1/chat/completions/stream")
async def chat_completions_stream(request: ChatCompletionRequest):
    """Streamed guarded completion."""
    from fastapi.responses import StreamingResponse

    rails = get_rails_app()
    settings = get_settings()

    user_messages = [m for m in request.messages if m.get("role") == "user"]
    if not user_messages:
        raise ValueError("No user message in request")

    last_user_msg = user_messages[-1]["content"]
    input_text = last_user_msg
    if "Question:" in last_user_msg:
        input_text = last_user_msg.split("Question:")[-1].strip()
        if not input_text:
            input_text = last_user_msg
    elif "سوال:" in last_user_msg:
        input_text = last_user_msg.split("سوال:")[-1].strip() or last_user_msg

    # Input rail check (signals → judge, fail closed)
    input_check = await check_rails(
        RailCheckRequest(stage="input", text=input_text)
    )
    if not input_check.allowed:
        refusal_msg = input_check.reason or "I cannot process that request."
        async def refusal_stream():
            yield refusal_msg
        return StreamingResponse(refusal_stream(), media_type="text/plain")

    async def content_stream():
        try:
            upstream_messages = [
                {"role": m["role"], "content": m["content"]} for m in request.messages
            ]

            if rails is not None:
                result = await rails.generate_async(messages=upstream_messages)
                bot_response = result.get("content", "") if isinstance(result, dict) else str(result)
                yield bot_response
            else:
                async for chunk in _call_upstream_stream(upstream_messages, request):
                    yield chunk

        except httpx.TimeoutException:
            log.error("Upstream timeout")
            yield "The model request timed out. Please try again."
        except Exception as e:
            log.exception("Upstream error")
            yield f"Upstream error: {str(e)[:200]}"

    return StreamingResponse(content_stream(), media_type="text/plain")


def main():
    """Entry point for running the service directly."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.guardrails_host,
        port=settings.guardrails_port,
    )
