"""Toxicity classifier interface — Phase 5.

Interface for HF models like:
- GhadeerALbadani/mmbert-Multilingual_detection_of_hate_speech (F1 0.94 Persian)
- HamidRezaei/Persian-Offensive-Language-Detection
- textdetox/bert-multilingual-toxicity-classifier

Do not download large models yet — interface only.
"""
from __future__ import annotations

from typing import Dict, Any, Optional
import logging

log = logging.getLogger(__name__)

class ToxicityClassifier:
    """HF toxicity classifier wrapper."""

    MODEL_CANDIDATES = [
        "GhadeerALbadani/mmbert-Multilingual_detection_of_hate_speech",  # F1 0.94 Persian, 21 langs
        "HamidRezaei/Persian-Offensive-Language-Detection",  # ParsBERT, 33k tweets
        "textdetox/bert-multilingual-toxicity-classifier",  # 15 langs, 2025
        "HooshvareLab/bert-base-parsbert-uncased",  # base, fine-tune on PHATE
    ]

    def __init__(self, model_name: Optional[str] = None, device: str = "cpu", threshold: float = 0.8):
        self.model_name = model_name or self.MODEL_CANDIDATES[0]
        self.device = device
        self.threshold = threshold
        self._pipeline = None
        log.info(f"ToxicityClassifier initialized with {self.model_name} (lazy, not downloaded)")

    def load(self):
        """Load HF pipeline — call explicitly, not on import."""
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline
            self._pipeline = pipeline("text-classification", model=self.model_name, device=self.device)
            log.info(f"Loaded toxicity model {self.model_name}")
        except Exception as e:
            log.warning(f"Failed to load {self.model_name}: {e} — returning 0.0")
            self._pipeline = None
        return self._pipeline

    def score(self, text: str) -> float:
        """Return toxicity score 0.0-1.0. 0.0 if model not loaded."""
        if self._pipeline is None:
            # Lazy: try to load, but if not available, return 0.0
            # For MVP, we don't download, so return 0.0 and rely on deterministic
            return 0.0
        try:
            result = self._pipeline(text[:512])[0]
            # Map label to score: assume label "toxic" or "hate" is positive
            if result["label"].lower() in ("toxic", "hate", "offensive", "label_1"):
                return float(result["score"])
            # If label is "non-toxic", invert
            return 1.0 - float(result["score"]) if "non" in result["label"].lower() else float(result["score"])
        except Exception as e:
            log.warning(f"Toxicity score failed: {e}")
            return 0.0

    def is_toxic(self, text: str) -> bool:
        return self.score(text) >= self.threshold

# Singleton for easy import
_default_toxicity = None

def get_toxicity_classifier() -> ToxicityClassifier:
    global _default_toxicity
    if _default_toxicity is None:
        _default_toxicity = ToxicityClassifier()
    return _default_toxicity

def score_text(text: str) -> float:
    """Convenience: score without loading model (returns 0.0 until Phase 6)."""
    return 0.0
