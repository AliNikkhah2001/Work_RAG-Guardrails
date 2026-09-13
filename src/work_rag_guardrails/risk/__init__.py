"""Risk scoring layer — Phase 3.
Does not directly block semantic outputs; uses thresholds.
"""
from .scorer import RiskScorer, RiskScores, RiskDecision
__all__ = ["RiskScorer", "RiskScores", "RiskDecision"]
