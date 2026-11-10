"""Load canned refusals + judge prompts from KB registry (or vendored YAML)."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

log = logging.getLogger(__name__)

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_AT: float = 0.0
_TTL_S = 60.0
_FALLBACK_DIR = Path(__file__).resolve().parent / "fallback_packs"
_FALLBACK_CANNED = _FALLBACK_DIR / "canned.yaml"
_FALLBACK_PROMPTS = _FALLBACK_DIR / "prompts_guardrails.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        log.error("Missing vendored pack: %s", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.exception("Failed loading %s: %s", path, exc)
        return {}


def _fallback_payload() -> dict[str, Any]:
    canned = _load_yaml(_FALLBACK_CANNED)
    prompts = _load_yaml(_FALLBACK_PROMPTS)
    return {
        "pins": {
            "canned": str(canned.get("version") or "fallback-yaml"),
            "prompts_guardrails": str(prompts.get("version") or "fallback-yaml"),
        },
        "canned": canned,
        "prompts_guardrails": {
            "prompts": dict(prompts.get("prompts") or {}),
            "version": prompts.get("version") or "fallback-yaml",
        },
        "source": "fallback-yaml",
    }


def refresh_registry(force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_AT
    with _LOCK:
        if (
            not force
            and _CACHE is not None
            and (time.monotonic() - _CACHE_AT) < _TTL_S
        ):
            return _CACHE
    kb_base = (os.getenv("KB_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    url = kb_base + "/registry/api/active"
    try:
        with httpx.Client(timeout=8.0, trust_env=False) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            data["source"] = "kb-registry"
            canned = data.get("canned") or {}
            prompts = (data.get("prompts_guardrails") or {}).get("prompts") or {}
            # Incomplete older pins → merge vendored packs so we never ship
            # empty refusals/prompts while KB is mid-upgrade.
            if not canned.get("guardrails_refusals"):
                fb = _fallback_payload()
                canned = {**fb["canned"], **canned}
                canned["guardrails_refusals"] = dict(
                    (fb["canned"].get("guardrails_refusals") or {})
                )
                data["canned"] = canned
                data["source"] = "kb-registry+fallback-canned"
            if not prompts:
                fb = _fallback_payload()
                data["prompts_guardrails"] = fb["prompts_guardrails"]
                data["source"] = str(data.get("source") or "kb-registry") + "+fallback-prompts"
            if not (canned.get("guardrails_refusals") or canned.get("refusals")):
                raise RuntimeError("KB registry canned pack missing refusals")
            with _LOCK:
                _CACHE = data
                _CACHE_AT = time.monotonic()
            log.info(
                "Loaded guardrails content registry (source=%s, canned=%s)",
                data.get("source"),
                (data.get("pins") or {}).get("canned"),
            )
            return data
    except Exception as exc:
        log.warning("KB registry unavailable for guardrails (%s); using vendored YAML", exc)
        payload = _fallback_payload()
        with _LOCK:
            if _CACHE is not None and _CACHE.get("source") == "kb-registry":
                return _CACHE
            _CACHE = payload
            _CACHE_AT = time.monotonic()
            return _CACHE


def get_registry_payload() -> dict[str, Any]:
    return refresh_registry(force=False)


def canned() -> dict[str, Any]:
    return dict(get_registry_payload().get("canned") or {})


def guardrails_refusal(category: str, *, stage: str = "input") -> str:
    """User-facing refusal for a guardrails category."""
    pack = canned()
    refusals = dict(pack.get("guardrails_refusals") or {})
    cat = (category or "").strip().replace("-", "_")
    aliases = {
        "out_of_domain": "out_of_scope",
        "off_domain": "out_of_scope",
        "irrelevant": "out_of_scope",
        "irrelevant_to_corpus": "out_of_scope",
    }
    cat = aliases.get(cat, cat)
    if stage == "output" and cat in {"hate", "offense", "profanity"}:
        return str(
            refusals.get("output_inappropriate")
            or refusals.get("output_inappropriate_short")
            or refusals.get("default")
            or ""
        )
    return str(
        refusals.get(cat)
        or refusals.get("default")
        or (pack.get("refusals") or {}).get("blocked_default")
        or ""
    )


def message(key: str, default: str = "") -> str:
    refusals = dict((canned().get("refusals") or {}))
    guard = dict((canned().get("guardrails_refusals") or {}))
    msgs = dict((canned().get("messages") or {}))
    return str(refusals.get(key) or guard.get(key) or msgs.get(key) or default)


def require_prompt(name: str, **fmt: Any) -> str:
    prompts = (
        (get_registry_payload().get("prompts_guardrails") or {}).get("prompts") or {}
    )
    text = prompts.get(name)
    if not text or not str(text).strip():
        # fallback yaml may be nested under prompts only when source=fallback
        raise RuntimeError(f"Guardrails prompt {name!r} missing from registry")
    if not fmt:
        return str(text)
    try:
        return str(text).format(**fmt)
    except Exception as exc:
        log.warning("guardrails prompt %r format failed (%s)", name, exc)
        return str(text)
