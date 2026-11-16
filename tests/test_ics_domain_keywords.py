"""Regression: ICS domain_keywords and allowlist overrides for credit leaf terms."""
from __future__ import annotations

from work_rag_guardrails.actions import check_out_of_scope
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


def test_safteh_questions_skip_domain_pre_check():
    policy = load_active_policy()
    for q in ("سفته", "سفته چیست؟", "آیا سابقه سفته ثبت می‌شود؟"):
        assert needs_domain_check(q, policy) is False


def test_safteh_phrases_in_ics_domain_allowlist():
    for q in ("سفته چیست؟", "آیا سابقه سفته ثبت می‌شود؟"):
        assert _has_ics_product_keyword(q) is True


def test_safteh_not_flagged_out_of_scope_by_kb():
    for q in ("سفته", "سفته چیست؟", "آیا سابقه سفته ثبت می‌شود؟"):
        blocked, _ = check_out_of_scope(q)
        assert blocked is False


def test_off_domain_cooking_still_needs_review():
    policy = load_active_policy()
    assert needs_domain_check("طرز تهیه قرمه‌سبزی چیست؟", policy) is True