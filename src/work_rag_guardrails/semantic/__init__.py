"""Semantic classifier interface — Phase 5.
Allows adding HF models later without downloading now.
"""
from .toxicity import ToxicityClassifier
from .hate import HateClassifier
from .intent import IntentClassifier

__all__ = ["ToxicityClassifier", "HateClassifier", "IntentClassifier"]

def get_toxicity_score(text: str) -> float:
    """Placeholder — returns 0.0 until model is loaded."""
    return 0.0
