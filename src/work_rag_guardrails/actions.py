"""Persian-aware deterministic guardrail actions — loaded from kb/*.json.

All checks use Persian normalization (ZWNJ, Arabic char variants) matching kb-manager.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Tuple, List, Dict

# ---- Persian normalization (same as kb_manager/web/routes/search.py:31) ----
_PERSIAN_CHAR_MAP = {
    "\u064a": "\u06cc",  # ي -> ی
    "\u0649": "\u06cc",  # ى -> ی
    "\u0643": "\u06a9",  # ك -> ک
    "\u0629": "\u0647",  # ة -> ه
    "\u0671": "\u0627",  # ٱ -> ا
    "\u0623": "\u0627",  # أ -> ا
    "\u0625": "\u0627",  # إ -> ا
    "\u200c": "",  # ZWNJ -> empty (parsitext: fix misplaced ZWNJ, handle می‌خواهم == میخواهم)
    "\u0660": "0", "\u0661": "1", "\u0662": "2", "\u0663": "3", "\u0664": "4",
    "\u0665": "5", "\u0666": "6", "\u0667": "7", "\u0668": "8", "\u0669": "9",
    "\u06f0": "0", "\u06f1": "1", "\u06f2": "2", "\u06f3": "3", "\u06f4": "4",
    "\u06f5": "5", "\u06f6": "6", "\u06f7": "7", "\u06f8": "8", "\u06f9": "9",
}
_PERSIAN_TABLE = str.maketrans(_PERSIAN_CHAR_MAP)
# zero-width joiner/non-joiner, tatweel, diacritics
_INVISIBLE_RE = re.compile(r"[\u200d\u0640\u064b-\u065f\u0670]")

def normalize_persian(text: str) -> str:
    """Lower + translate Arabic variants + strip diacritics + collapse spaces."""
    text = text.translate(_PERSIAN_TABLE)
    text = _INVISIBLE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()

def _kb_path(name: str) -> Path:
    # kb/ is sibling of src/work_rag_guardrails, or config/../../kb
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "kb" / name,
        Path(__file__).resolve().parent / "kb" / name,
        Path.cwd() / "kb" / name,
        Path.cwd() / "components" / "guardrails" / "kb" / name,
    ]
    for p in candidates:
        if p.exists():
            return p
    # fallback to repo root kb
    return Path(__file__).resolve().parents[4] / "components" / "guardrails" / "kb" / name

@lru_cache(maxsize=1)
def load_swear() -> List[str]:
    try:
        p = _kb_path("persian_swear.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        return [normalize_persian(w) for w in data]
    except Exception:
        return []

@lru_cache(maxsize=1)
def load_hurtlex() -> List[str]:
    try:
        p = _kb_path("hurtlex_fa_conservative.json")
        data = json.loads(p.read_text(encoding="utf-8"))
        return [normalize_persian(w) for w in data]
    except Exception:
        return []

@lru_cache(maxsize=1)
def load_injection_patterns() -> List[Dict]:
    try:
        p = _kb_path("prompt_injection_fa.json")
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []

@lru_cache(maxsize=1)
def load_out_of_scope() -> Dict:
    try:
        p = _kb_path("out_of_scope.json")
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"allowed_keywords": [], "out_of_scope_categories": []}

# ---- Deterministic checks ----

_PERSIAN_INJECTION_REGEXES = [
    re.compile(r"(دستورات|پرامپت).*(قبلی|سیستم).*(نادیده|فراموش)"),
    re.compile(r"(نقش|شخصیت).*(جدید|دان|DAN)"),
    re.compile(r"(نشان بده|فاش کن).*(پرامپت|کلید|توکن)"),
    re.compile(r"تمام دستورات.*فراموش کن"),
    re.compile(r"هوش مصنوعی بدون.*محدودیت"),
]

def check_prompt_injection_fa(text: str) -> Tuple[bool, str]:
    """Return (blocked, reason). Checks kb/prompt_injection_fa.json + spec regexes + English fallback."""
    norm = normalize_persian(text)
    for entry in load_injection_patterns():
        pat = normalize_persian(entry["pattern"])
        if pat and pat in norm:
            return True, f"injection:{entry['id']}"
    for rx in _PERSIAN_INJECTION_REGEXES:
        if rx.search(norm):
            return True, f"injection:regex:{rx.pattern[:20]}"
    # regex fallbacks for obfuscation (base64-like, hex)
    if re.search(r"[A-Za-z0-9+/]{40,}={0,2}", text) and "base64" in norm:
        return True, "injection:encoding-base64"
    return False, ""

def check_jailbreak_fa(text: str) -> Tuple[bool, str]:
    norm = normalize_persian(text)
    triggers = ["jailbreak", "جلبریک", "حالت توسعه دهنده", "developer mode", "sudo mode", "بدون سانسور", "بدون محدودیت", "نقش جدید", "unrestricted"]
    # Phrase triggers: substring search
    for t in triggers:
        if normalize_persian(t) in norm:
            return True, f"jailbreak:{t}"
    # Short/substring-sensitive triggers: word-boundary only
    # "دان" (DAN) should not match "دانش" / "بدانید" — require word boundary or phrase "نقش دان"
    if re.search(r"\bدان\b", norm):
        return True, "jailbreak:دان"
    if re.search(r"نقش\s+دان", norm):
        return True, "jailbreak:نقش دان"
    return False, ""

def check_profanity_fa(text: str) -> Tuple[bool, str]:
    norm = normalize_persian(text)
    # word-boundary check
    for w in load_swear():
        if w and re.search(rf"\b{re.escape(w)}\b", norm):
            return True, f"profanity:{w[:20]}"
    return False, ""

def check_hurtlex_fa(text: str) -> Tuple[bool, str]:
    norm = normalize_persian(text)
    for w in load_hurtlex():
        if w and len(w) > 2 and re.search(rf"\b{re.escape(w)}\b", norm):
            return True, f"hate:{w[:20]}"
    return False, ""

def check_out_of_scope(text: str) -> Tuple[bool, str]:
    cfg = load_out_of_scope()
    norm = normalize_persian(text)
    allowed = [normalize_persian(k) for k in cfg.get("allowed_keywords", [])]
    # if any allowed keyword present, it's in-scope
    if any(k in norm for k in allowed if len(k) > 2):
        return False, ""
    for cat in cfg.get("out_of_scope_categories", []):
        for kw in cat.get("keywords", []):
            if normalize_persian(kw) in norm:
                return True, f"out_of_scope:{cat['id']}"
    # heuristic: very short generic chat like "سلام" without credit terms -> not out-of-scope, allow
    if len(norm.split()) <= 3:
        return False, ""
    return False, ""

def check_input_persian(text: str) -> Tuple[bool, str, str]:
    """Run all input checks in order. Returns (blocked, category, reason)."""
    for fn, cat in [
        (check_prompt_injection_fa, "prompt_injection"),
        (check_jailbreak_fa, "jailbreak"),
        (check_hurtlex_fa, "hate"),
        (check_profanity_fa, "offense"),
        (check_out_of_scope, "out_of_scope"),
    ]:
        blocked, reason = fn(text)
        if blocked:
            return True, cat, reason
    return False, "", ""

# ---- PII validators (parsitext Rust -> Python port) ----

def _validate_national_id(code: str) -> bool:
    """Iranian National ID 10-digit checksum."""
    if not re.fullmatch(r"\d{10}", code) or len(set(code)) == 1:
        return False
    check = int(code[9])
    s = sum(int(code[i]) * (10 - i) for i in range(9))
    r = s % 11
    return (r < 2 and check == r) or (r >= 2 and check == 11 - r)

def _validate_sheba(sheba: str) -> bool:
    """IR-IBAN Sheba: IR + 24 digits, mod-97 == 1."""
    sheba = sheba.replace(" ", "").upper()
    if not re.fullmatch(r"IR\d{24}", sheba):
        return False
    # move IR + 2 check digits to end, convert letters
    rearranged = sheba[4:] + sheba[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(numeric) % 97 == 1
    except Exception:
        return False

def check_pii_ir(text: str) -> Tuple[bool, str]:
    """Detect Iranian PII: national_id, Sheba, mobile/landline."""
    # normalize digits (Persian/Arabic -> Latin already done)
    if re.search(r"\b\d{10}\b", text):
        for m in re.finditer(r"\b\d{10}\b", text):
            if _validate_national_id(m.group()):
                return True, f"pii:national_id:{m.group()[:4]}****"
    if re.search(r"\bIR\d{24}\b", text.upper()):
        for m in re.finditer(r"\bIR\d{24}\b", text.upper()):
            if _validate_sheba(m.group()):
                return True, f"pii:sheba:{m.group()[:6]}****"
    if re.search(r"\b09\d{9}\b", text):
        return True, "pii:phone"
    if re.search(r"\b0\d{2,3}-?\d{7,8}\b", text):
        # landline 11 digits with 0 prefix - heuristic
        for m in re.finditer(r"\b0\d{10}\b", text):
            return True, "pii:landline"
    return False, ""

def check_output_persian(text: str) -> Tuple[bool, str, str]:
    for fn, cat in [
        (check_profanity_fa, "profanity"),
        (check_hurtlex_fa, "hate"),
        (check_pii_ir, "pii"),
    ]:
        blocked, reason = fn(text)
        if blocked:
            return True, cat, reason
    # secret markers
    lower = text.lower()
    for m in ["sk-", "api_key", "database_url", "Bearer "]:
        if m.lower() in lower:
            return True, "secret", f"secret:{m}"
    return False, "", ""
