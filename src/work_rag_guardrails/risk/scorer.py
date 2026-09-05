"""Risk scoring layer — Phase 3.

Policy:
- PII: high confidence block (validated IDs, checksums)
- Secrets: high confidence block (regex with high entropy)
- Injection: high confidence block (exact pattern + regex)
- Toxicity/hate: threshold based (semantic scores if available, else deterministic)
- Unknown: allow but log

This layer does NOT directly block on semantic classifier outputs alone;
it combines deterministic and semantic into a risk score and applies thresholds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

log = logging.getLogger(__name__)

@dataclass
class RiskScores:
    """Risk scores per category (0.0 to 1.0)."""
    pii: float = 0.0
    secret: float = 0.0
    injection: float = 0.0
    toxicity: float = 0.0
    hate: float = 0.0
    profanity: float = 0.0
    overall: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RiskDecision:
    """Final decision from risk scoring."""
    action: str  # "block" or "allow"
    reason: str
    scores: RiskScores
    triggered_rules: List[str]
    confidence: float

class RiskScorer:
    """Risk scoring with threshold policy.

    Thresholds:
    - pii >= 0.9, secret >= 0.9, injection >= 0.85 → block
    - toxicity/hate >= 0.8 → block, 0.5-0.8 → allow but log (flag for review)
    - unknown → allow but log
    """

    # Thresholds
    PII_THRESHOLD = 0.90
    SECRET_THRESHOLD = 0.90
    INJECTION_THRESHOLD = 0.85
    TOXICITY_BLOCK_THRESHOLD = 0.80
    TOXICITY_FLAG_THRESHOLD = 0.50
    HATE_BLOCK_THRESHOLD = 0.80
    HATE_FLAG_THRESHOLD = 0.50

    def score(
        self,
        deterministic: Dict[str, Any],
        semantic: Optional[Dict[str, float]] = None,
    ) -> RiskDecision:
        """
        deterministic: dict from check_input/output_persian, e.g.
            {"blocked": True, "category": "pii", "reason": "pii:national_id:..."}
        semantic: optional dict with keys like "toxicity", "hate", "intent" scores 0-1
        """
        semantic = semantic or {}
        scores = RiskScores()
        triggered = []
        # Map deterministic to scores
        cat = deterministic.get("category", "")
        reason = deterministic.get("reason", "")
        blocked = deterministic.get("blocked", False)

        # PII — high confidence block (validated checksum)
        if cat == "pii":
            # PII validator already does checksum, so if blocked, it's high confidence
            scores.pii = 0.95 if blocked else 0.0
            if blocked:
                triggered.append(f"pii:{reason}")
        # Secret — high confidence block
        elif cat == "secret":
            scores.secret = 0.95 if blocked else 0.0
            if blocked:
                triggered.append(f"secret:{reason}")
        # Injection — high confidence block
        elif cat in ("prompt_injection", "jailbreak"):
            # Check if it's an exact pattern vs regex
            scores.injection = 0.90 if blocked else 0.0
            if blocked:
                triggered.append(f"injection:{reason}")
        # Toxicity/hate — threshold based, combine deterministic and semantic
        elif cat in ("hate", "profanity", "offense"):
            # Deterministic gives binary 0 or 1, map to 0.85 if blocked
            det_score = 0.85 if blocked else 0.0
            # Semantic scores if available
            sem_tox = semantic.get("toxicity", 0.0)
            sem_hate = semantic.get("hate", 0.0)
            # Take max of deterministic and semantic, but don't directly block on semantic alone
            # Pair with allowlist already handled in deterministic
            scores.toxicity = max(det_score if cat in ("profanity", "offense") else 0.0, sem_tox)
            scores.hate = max(det_score if cat == "hate" else 0.0, sem_hate)
            if cat == "hate":
                scores.hate = max(det_score, sem_hate)
                triggered.append(f"hate:{reason} (det:{det_score:.2f} sem:{sem_hate:.2f})")
            else:
                scores.toxicity = max(det_score, sem_tox)
                triggered.append(f"toxicity:{reason} (det:{det_score:.2f} sem:{sem_tox:.2f})")
            # Also include semantic details
            scores.details["semantic"] = semantic
        elif blocked:
            # Unknown category but blocked — treat as low confidence
            scores.overall = 0.60
            triggered.append(f"unknown:{reason}")

        # Compute overall as max of all
        scores.overall = max(scores.pii, scores.secret, scores.injection, scores.toxicity, scores.hate, scores.overall)

        # Decision policy
        if scores.pii >= self.PII_THRESHOLD:
            return RiskDecision(action="block", reason=f"pii high confidence ({scores.pii:.2f}): {reason}", scores=scores, triggered_rules=triggered, confidence=scores.pii)
        if scores.secret >= self.SECRET_THRESHOLD:
            return RiskDecision(action="block", reason=f"secret high confidence ({scores.secret:.2f}): {reason}", scores=scores, triggered_rules=triggered, confidence=scores.secret)
        if scores.injection >= self.INJECTION_THRESHOLD:
            return RiskDecision(action="block", reason=f"injection high confidence ({scores.injection:.2f}): {reason}", scores=scores, triggered_rules=triggered, confidence=scores.injection)
        if scores.hate >= self.HATE_BLOCK_THRESHOLD or scores.toxicity >= self.TOXICITY_BLOCK_THRESHOLD:
            # Block only if high confidence; semantic alone with 0.6 would not block without deterministic
            # But if semantic is high and deterministic was allowlisted, we still respect allowlist (deterministic would have been 0)
            # So this will only block if either deterministic or semantic is high
            # For allowlisted benign (deterministic 0), semantic would need to be >0.8 to block, which is rare for "حذف"
            return RiskDecision(action="block", reason=f"toxicity/hate high ({max(scores.hate, scores.toxicity):.2f}): {reason}", scores=scores, triggered_rules=triggered, confidence=max(scores.hate, scores.toxicity))
        if scores.hate >= self.HATE_FLAG_THRESHOLD or scores.toxicity >= self.TOXICITY_FLAG_THRESHOLD:
            # Allow but log for review
            log.info(f"Risk flag (allow but log): hate={scores.hate:.2f} toxicity={scores.toxicity:.2f} reason={reason}")
            return RiskDecision(action="allow", reason=f"flagged for review (hate {scores.hate:.2f}, toxicity {scores.toxicity:.2f}): {reason}", scores=scores, triggered_rules=triggered, confidence=max(scores.hate, scores.toxicity))

        # Unknown or low risk — allow but log
        if blocked:
            # This was blocked deterministically but with low score (e.g., out_of_scope)
            # For MVP, we allow out_of_scope but log
            if cat == "out_of_scope":
                return RiskDecision(action="allow", reason=f"out_of_scope allow but log: {reason}", scores=scores, triggered_rules=triggered, confidence=0.6)
            # Otherwise, if deterministic blocked but score is low, we still block? For now, respect deterministic for non-toxicity
            # But to avoid increasing FP, we log and allow for low-confidence toxicity
            log.info(f"Low confidence block, allowing but logging: {cat} {reason}")
            return RiskDecision(action="allow", reason=f"allow but log low confidence {cat}: {reason}", scores=scores, triggered_rules=triggered, confidence=scores.overall)

        return RiskDecision(action="allow", reason="allow", scores=scores, triggered_rules=triggered, confidence=0.0)

    def evaluate_sample(self, text: str, deterministic_result: Dict[str, Any], semantic_scores: Optional[Dict[str, float]] = None) -> RiskDecision:
        """Convenience for evaluation runner."""
        return self.score(deterministic_result, semantic_scores)

