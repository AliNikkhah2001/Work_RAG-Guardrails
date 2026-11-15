"""Regression: plural «سوابق» and negative-record queries stay in-domain."""
from __future__ import annotations

from work_rag_guardrails.judge import _has_ics_product_keyword
from work_rag_guardrails.policies import load_active_policy
from work_rag_guardrails.signals import needs_domain_check


def test_suabeg_plural_needs_domain_check_allowed():
    policy = load_active_policy()
    q = "چگونه سوابق منفی را رفع کنم؟"
    assert needs_domain_check(q, policy) is False


def test_suabeg_negative_removal_phrase_in_domain_allowlist():
    q = "سوابق منفی چگونه حذف می‌شود؟"
    assert _has_ics_product_keyword(q) is True