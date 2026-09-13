"""Hate classifier interface — Phase 5.

For Persian hate detection, same candidates as toxicity but with hate-specific tuning.
Do not download yet.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

class HateClassifier:
    """Hate classifier wrapper."""

    MODEL_CANDIDATES = [
        "GhadeerALbadani/mmbert-Multilingual_detection_of_hate_speech",  # best for Persian hate
        "HamidRezaei/Persian-Offensive-Language-Detection",
    ]

    def __init__(self, model_name: Optional[str] = None, threshold: float = 0.8):
        self.model_name = model_name or self.MODEL_CANDIDATES[0]
        self.threshold = threshold
        self._pipeline = None
        log.info(f"HateClassifier {self.model_name} lazy")

    def load(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline
            self._pipeline = pipeline("text-classification", model=self.model_name)
        except Exception as e:
            log.warning(f"Failed to load hate model: {e}")
        return self._pipeline

    def score(self, text: str) -> float:
        if self._pipeline is None:
            return 0.0
        try:
            result = self._pipeline(text[:512])[0]
            return float(result["score"]) if "hate" in result["label"].lower() else 0.0
        except Exception:
            return 0.0

def score_text(text: str) -> float:
    return 0.0
