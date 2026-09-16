"""Versioned business-policy loader (policies/*.yaml + active pin).

Only the pinned version is enforced. Prompt templates use {{text}} and
{{signals}} placeholders rendered per decision.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def _policies_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "policies",
        Path(__file__).resolve().parent / "policies",
        Path.cwd() / "policies",
        Path.cwd() / "components" / "guardrails" / "policies",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        pass
    # Minimal YAML subset fallback (no pyyaml): top-level scalars + categories
    # with prompt/refusal/examples — good enough for our schema.
    data: Dict[str, Any] = {}
    cats: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    key: Optional[str] = None
    buf: List[str] = []
    in_literal = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if line.startswith("  - id: "):
            if cur:
                if key and buf:
                    cur[key] = "\n".join(buf)
                cats.append(cur)
            cur, key, buf, in_literal = {"id": line.split(":", 1)[1].strip()}, None, [], False
            continue
        if cur is None:
            if ":" in line and not line.startswith(" "):
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip()
            continue
        m = __import__("re").match(r"    (\w+):\s*(\|-\s*)?$", line)
        if m:
            if key and buf and cur is not None:
                cur[key] = "\n".join(buf)
            key, buf = m.group(1), []
            in_literal = bool(m.group(2))
            continue
        if key and (line.startswith("      ") or (in_literal and line.strip() == "")):
            buf.append(line[6:] if line.startswith("      ") else "")
            continue
        if line.startswith("      - "):
            ex_key = key or "examples"
            cur.setdefault(ex_key, [])
            buf.append(line.strip())
    if cur:
        if key and buf:
            cur[key] = "\n".join(buf)
        cats.append(cur)
    data["categories"] = cats
    return data


@lru_cache(maxsize=1)
def load_active_policy() -> Dict[str, Any]:
    """Load the pinned policy file. Returns {} when absent (judge falls back)."""
    d = _policies_dir()
    active = (d / "active.yaml").read_text(encoding="utf-8") if (d / "active.yaml").exists() else ""
    pin = ""
    for line in active.splitlines():
        if line.strip().startswith("active:"):
            pin = line.split(":", 1)[1].strip()
    if not pin:
        log.warning("policies/active.yaml missing pin — business judge disabled")
        return {}
    path = d / pin
    if not path.exists():
        log.warning("pinned policy %s missing — business judge disabled", pin)
        return {}
    data = _load_yaml(path)
    data["_file"] = pin
    log.info("active policy: %s v%s (%d categories)",
             data.get("id"), data.get("version"), len(data.get("categories", [])))
    return data


def render(template: str, text: str, signals: List[Dict[str, Any]]) -> str:
    """Render {{text}} / {{signals}} placeholders."""
    if signals:
        sig_txt = "; ".join(
            f"{s.get('detector')}:{s.get('matched')} (ctx: {(s.get('context') or '')[:80]})"
            for s in signals
        )
    else:
        sig_txt = "none — no deterministic detector fired"
    return template.replace("{{text}}", text).replace("{{signals}}", sig_txt)


def categories_for_stage(policy: Dict[str, Any], stage: str) -> List[Dict[str, Any]]:
    stages = policy.get("stage", ["input", "output"])
    if stage not in stages:
        return []
    return [c for c in policy.get("categories", []) if isinstance(c, dict)]
