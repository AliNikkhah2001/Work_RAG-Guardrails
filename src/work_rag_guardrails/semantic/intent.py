"""Intent classifier interface — Phase 5.

For prompt injection / jailbreak intent detection.
Candidates: protectai/deberta-v3-base-prompt-injection-v2, deepset/deberta-v3-base-injection
Do not download yet.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

class IntentClassifier:
    """Intent classifier for injection/jailbreak."""

    MODEL_CANDIDATES = [
        "protectai/deberta-v3-base-prompt-injection-v2",
        "deepset/deberta-v3-base-injection",
        "laiyer/custom-prompt-injection",  # multilingual
    ]

    def __init__(self, model_name: Optional[str] = None, threshold: float = 0.85):
        self.model_name = model_name or self.MODEL_CANDIDATES[0]
        self.threshold = threshold
        self._pipeline = None
        log.info(f"IntentClassifier {self.model_name} lazy")

    def load(self):
        if self._pipeline is not None:
            return self._pipeline
        try:
            from transformers import pipeline
            self._pipeline = pipeline("text-classification", model=self.model_name)
        except Exception as e:
            log.warning(f"Failed to load intent model: {e}")
        return self._pipeline

    def score(self, text: str) -> float:
        if self._pipeline is None:
            return 0.0
        try:
            result = self._pipeline(text[:512])[0]
            return float(result["score"])
        except Exception:
            return 0.0

def score_text(text: str) -> float:
    return 0.0
