"""Observability — Phase 4.
Every request exposes: request_id, triggered_rules, risk_scores, final_decision
"""
from __future__ import annotations

import time
import logging
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from .risk.scorer import RiskDecision, RiskScores

log = logging.getLogger(__name__)

class Observability:
    """Logs and enriches every guardrail decision."""

    @staticmethod
    def log_request(
        request_id: str,
        text: str,
        stage: str,
        triggered_rules: List[str],
        risk_scores: RiskScores,
        final_decision: str,
        latency_ms: float,
        category: str = "",
    ) -> Dict[str, Any]:
        """Log structured observability and return dict for response headers."""
        payload = {
            "request_id": request_id,
            "stage": stage,
            "category": category,
            "triggered_rules": triggered_rules,
            "risk_scores": asdict(risk_scores) if hasattr(risk_scores, '__dict__') else risk_scores,
            "final_decision": final_decision,
            "latency_ms": round(latency_ms, 2),
            "text_preview": text[:100],
        }
        # Structured log for Loki/Prometheus
        log.info(f"observability request_id={request_id} stage={stage} decision={final_decision} rules={triggered_rules} scores={payload['risk_scores']} latency={latency_ms:.1f}ms")
        return payload

    @staticmethod
    def enrich_response(
        response: Dict[str, Any],
        observability: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add observability to response (for API)."""
        response["_observability"] = observability
        return response

