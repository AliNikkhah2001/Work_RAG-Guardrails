"""Regression tests for HurtLex allowlist — Phase 3-4.
Benign credit terms must remain allowed; true hate/profanity/PII/secret must still be blocked.
"""
from __future__ import annotations

import pytest

from work_rag_guardrails.actions import (
    check_hurtlex_fa,
    check_hurtlex_fa_strict,
    check_input_persian,
    check_output_persian,
    normalize_persian,
)


class TestHurtlexAllowlistBenign:
    """Benign Persian credit terms that were false positives before allowlist."""

    def test_failing_generated_sentence_allowed(self):
        """Exact raw Gemma output for failing query must be allowed (was blocked by حذف)."""
        text = "با توجه به متن ارائه شده، در صورتی که سوابق مالی مستقل کافی در سیستم اعتبارسنجی وجود نداشته باشد، امکان اخذ گزارش اعتبارسنجی وجود ندارد [1]، [2]، [3]. اطلاعات بیشتری در مورد نحوه دریافت گزارش در متن موجود نیست."
        blocked, reason = check_hurtlex_fa(text)
        assert blocked is False, f"Benign sentence blocked as {reason}"
        blocked_out, cat, reason2 = check_output_persian(text)
        assert blocked_out is False, f"Output blocked as {cat}:{reason2}"
        blocked_in, cat_in, reason_in = check_input_persian(text)
        # Input check also should not block benign financial sentence (allowlist applied)
        assert blocked_in is False, f"Input blocked as {cat_in}:{reason_in}"

    def test_bakhshi_benign_allowed(self):
        """بخشی in benign context must be allowed (documented false positive)."""
        text = "بخشی از اطلاعات اعتباری شما در سامانه ثبت شده است"
        blocked, reason = check_hurtlex_fa(text)
        assert blocked is False, f"بخشی blocked as {reason}"
        blocked_out, _, _ = check_output_persian(text)
        assert blocked_out is False

    def test_hazf_benign_allowed(self):
        """حذف in credit context must be allowed."""
        text = "درخواست حذف سابقه منفی قدیمی از گزارش اعتباری شرکت را ثبت کنید"
        blocked, reason = check_hurtlex_fa(text)
        assert blocked is False, f"حذف blocked as {reason}"

    def test_tamin_mali_allowed(self):
        text = "تامین مالی از طریق تسهیلات بانکی"
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is False

    def test_eshteghal_allowed(self):
        text = "اشتغال و سابقه بیمه در امتیاز اعتباری موثر است"
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is False

    def test_post_allowed(self):
        text = "پست سازمانی و سمت شغلی در فرم ثبت نام"
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is False

    def test_masraf_allowed(self):
        text = "گزارش‌های مصرف را به‌صورت خودکار در سیستم ذخیره کنید"
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is False

    def test_hadaf_allowed(self):
        text = "هدف از دریافت تسهیلات اعتباری"
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is False

    def test_normalized_hazf_with_zwnj_allowed(self):
        """ZWNJ handling: حذف with ZWNJ should also be allowlisted after normalization."""
        text = "درخواست حذف\u200cسابقه"  # ZWNJ between
        norm = normalize_persian(text)
        assert "حذف" in norm
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is False

    def test_nadorost_allowed(self):
        """نادرست in credit correction context must be allowed (Phase 5 failure)."""
        text = "برای پیگیری اصلاح اطلاعات نادرست در گزارش اعتباری، می‌توانید از طریق CRM اقدام کنید"
        blocked, reason = check_hurtlex_fa(text)
        assert blocked is False, f"نادرست blocked as {reason}"
        blocked_out, _, _ = check_output_persian(text)
        assert blocked_out is False


class TestHurtlexStrictStillBlocked:
    """Genuine hate/profanity/PII/secret must still be blocked."""

    def test_explicit_hate_still_blocked(self):
        """Explicit slur not in allowlist must still be blocked."""
        # "حرامزاده" is in hurtlex_fa_conservative.json and not allowlisted
        text = "این فرد حرامزاده است"
        blocked, reason = check_hurtlex_fa(text)
        assert blocked is True, "Explicit hate should be blocked"
        assert "hate:" in reason
        # Strict version also blocks
        blocked_s, _ = check_hurtlex_fa_strict(text)
        assert blocked_s is True

    def test_ahmagh_still_blocked(self):
        """احمق is in hurtlex and not allowlisted."""
        text = "تو احمق هستی"
        blocked, _ = check_hurtlex_fa(text)
        assert blocked is True

    def test_profanity_still_blocked(self):
        """Profanity from persian_swear.json must remain blocked (strict, no allowlist)."""
        text = "این آشغال است"  # آشغال is in persian_swear.json
        blocked, cat, reason = check_output_persian(text)
        # check_output_persian checks profanity first
        assert blocked is True
        assert cat == "profanity"

    def test_profanity_input_still_blocked(self):
        text = "تو اسکل هستی"  # اسکل in swear
        blocked, cat, _ = check_input_persian(text)
        assert blocked is True

    def test_pii_still_blocked(self):
        """National ID with valid checksum must be blocked."""
        # Valid Iranian National ID example: 1234567890 is invalid checksum, use known valid 0011223344? Let's use a valid one: 1234567891 is valid? We'll generate one
        # Use 0071234567 is not valid, so use 1234567891 which passes checksum? Let's test: 1*10+2*9+3*8+4*7+5*6+6*5+7*4+8*3+9*2= 10+18+24+28+30+30+28+24+18=210, 210%11=1, check=1 => 1234567891 should be valid
        text = "کد ملی من 1234567891 است"
        blocked, cat, reason = check_output_persian(text)
        assert blocked is True
        assert cat == "pii"

    def test_secret_still_blocked(self):
        text = "Here is your API key: sk-abc123def456"
        blocked, cat, _ = check_output_persian(text)
        assert blocked is True
        assert cat == "secret"

    def test_allowlist_does_not_disable_hate_rail(self):
        """Allowlist must not disable entire hate rail — non-allowlisted hate still blocked."""
        # Pick a hate word that is not in allowlist, e.g., "خائن"
        text = "این شخص خائن است"
        blocked, reason = check_hurtlex_fa(text)
        # خائن is in hurtlex, not in allowlist, should be blocked
        assert blocked is True, f"Non-allowlisted hate should be blocked, got {reason}"

    def test_strict_vs_allowlist_difference(self):
        """Demonstrate that allowlist only affects output/benign, strict still flags حذف."""
        text = "حذف"
        blocked_strict, _ = check_hurtlex_fa_strict(text)
        assert blocked_strict is True, "Strict should flag حذف"
        blocked_allow, _ = check_hurtlex_fa(text)
        assert blocked_allow is False, "Allowlisted version should NOT flag حذف"
