"""Guard event log: terminated samples + aggregates for the dashboard.

JSONL at /tmp/guard_events.jsonl (GUARD_EVENTS_FILE override). PII digit runs
are masked before logging. Nothing here stores raw secrets.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)

_EVENTS_FILE = Path(os.getenv("GUARD_EVENTS_FILE", "/tmp/guard_events.jsonl"))
_MASKED = "[masked-pii]"


def mask_text(text: str) -> str:
    t = re.sub(r"\b\d{10}\b", _MASKED, text)          # national id / phones
    t = re.sub(r"\bIR\d{24}\b", _MASKED, text.upper() if False else t)
    t = re.sub(r"\b09\d{9}\b", _MASKED, t)
    t = re.sub(r"\b0\d{10}\b", _MASKED, t)
    t = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", _MASKED, t)
    t = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer " + _MASKED, t)
    return t


def log_event(stage: str, text: str, verdict: Dict[str, Any],
              request_id: str = "", source: str = "rails") -> None:
    """Append one decision event (called for blocks AND shadow allows)."""
    try:
        rec = {
            "ts": int(time.time()),
            "stage": stage,
            "source": source,
            "request_id": request_id,
            "allowed": bool(verdict.get("allowed")),
            "category": verdict.get("category", ""),
            "reason": str(verdict.get("reason", ""))[:200],
            "signals": [
                {"detector": s.get("detector"), "category": s.get("category"),
                 "matched": str(s.get("matched", ""))[:60]}
                for s in (verdict.get("details", {}) or {}).get("signals", [])
            ],
            "text": mask_text(text)[:2000],
        }
        with _EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log.error("event log failed: %s", e)


def read_events(limit: int = 500) -> List[Dict[str, Any]]:
    if not _EVENTS_FILE.exists():
        return []
    try:
        lines = _EVENTS_FILE.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


def stats() -> Dict[str, Any]:
    evs = read_events(limit=5000)
    total = len(evs)
    blocked = [e for e in evs if not e.get("allowed")]
    return {
        "total": total,
        "blocked": len(blocked),
        "allowed": total - len(blocked),
        "block_rate": round(len(blocked) / total, 4) if total else 0.0,
        "by_category": dict(Counter(e.get("category", "?") for e in blocked)),
        "by_stage": dict(Counter(f"{e.get('stage')}:{'block' if not e.get('allowed') else 'allow'}" for e in evs)),
        "by_detector": dict(Counter(
            s.get("detector", "?") for e in blocked for s in e.get("signals", []))),
    }
