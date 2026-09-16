"""Deterministic detectors as EVIDENCE signals (no hard blocks here).

Each signal: {detector, category, matched, context}. The judge decides;
only the `secret` class keeps a hard block (service.py).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .actions import (
    normalize_persian,
    check_prompt_injection_fa,
    check_jailbreak_fa,
    check_hurtlex_fa,
    check_profanity_fa,
    check_pii_ir,
    check_out_of_scope,
)


def _ctx(text: str, match: str, width: int = 60) -> str:
    i = text.find(match)
    if i < 0:
        return text[: 2 * width]
    return text[max(0, i - width): i + len(match) + width]


def collect_signals(text: str, stage: str = "input") -> List[Dict[str, Any]]:
    """Run all deterministic detectors, return evidence list (possibly empty)."""
    norm = normalize_persian(text)
    signals: List[Dict[str, Any]] = []

    def add(detector: str, category: str, fn) -> None:
        try:
            blocked, reason = fn(text)
        except Exception:
            return
        if blocked:
            matched = reason.split(":", 1)[-1][:60] if ":" in reason else reason[:60]
            signals.append({
                "detector": detector,
                "category": category,
                "matched": matched or reason[:60],
                "context": _ctx(norm, matched) if matched else norm[:120],
            })

    add("injection", "prompt_injection", check_prompt_injection_fa)
    add("jailbreak", "jailbreak", check_jailbreak_fa)
    add("hurtlex", "hate", check_hurtlex_fa)
    add("profanity", "offense", check_profanity_fa)
    if stage == "input":
        # out_of_scope is a weak signal (keyword gate), judge weighs it
        try:
            blocked, reason = check_out_of_scope(text)
            if blocked:
                signals.append({"detector": "scope", "category": "out_of_scope",
                                "matched": reason[:60], "context": norm[:120]})
        except Exception:
            pass
    else:
        add("pii", "pii", check_pii_ir)
    return signals


def needs_domain_check(text: str, policy=None) -> bool:
    """Fast no-LLM domain pre-check: long text with zero in-domain keywords
    (policy `domain_keywords`) earns an out_of_domain SIGNAL forcing review."""
    from .actions import normalize_persian as _norm
    if policy is None:
        try:
            from .policies import load_active_policy as _load
            policy = _load()
        except Exception:
            return False
    kws = [k for k in (policy.get("domain_keywords") or []) if isinstance(k, str)]
    if not kws:
        return False
    norm = _norm(text)
    if len(norm.split()) <= 4:
        return False
    return not any(_norm(k) in norm for k in kws if len(_norm(k)) > 1)
