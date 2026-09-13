"""Pydantic models for Guardrails API."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Literal, Any
from uuid import UUID, uuid4


class RailCheckRequest(BaseModel):
    """Request for input/output rail check."""

    stage: Literal["input", "output"] = Field(
        ...,
        description="Which rail stage to check: 'input' (before retrieval/generation) or 'output' (after generation)",
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Text to check against rails",
    )
    request_id: Optional[str] = Field(
        default_factory=lambda: str(uuid4()),
        description="Request ID for tracing",
    )


class RailCheckResponse(BaseModel):
    """Response from rail check."""

    allowed: bool = Field(..., description="Whether the text passes the rails")
    action: Literal["allow", "refuse"] = Field(
        ..., description="Action to take: 'allow' or 'refuse'"
    )
    categories: list[str] = Field(
        default_factory=list, description="Categories of violations if any"
    )
    reason: Optional[str] = Field(
        default=None, description="Human-readable reason for refusal"
    )
    policy_version: str = Field(
        default="mvp-1", description="Policy version used for this check"
    )
    request_id: str = Field(..., description="Request ID for tracing")


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str = Field(..., description="Model identifier")
    messages: list[dict[str, str]] = Field(..., min_length=1)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)
    temperature: Optional[float] = Field(default=0.0, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=0.95, ge=0.0, le=1.0)
    stream: bool = Field(default=False)
    session_id: Optional[str] = Field(default=None)


class ChatCompletionChoice(BaseModel):
    """Single choice in chat completion response."""

    index: int
    message: dict[str, str]
    finish_reason: Literal["stop", "length", "content_filter"]


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex[:29]}")
    object: Literal["chat.completion"] = "chat.completion"
    model: str
    choices: list[ChatCompletionChoice]
    usage: Optional[dict[str, int]] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    """Readiness check response."""

    status: Literal["ready", "not_ready"]
    nemo_config_loaded: bool
    upstream_reachable: bool
    policy_version: str = "mvp-1"