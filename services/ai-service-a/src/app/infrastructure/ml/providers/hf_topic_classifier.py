"""
HFTopicClassifier — LoRA-aware HuggingFace adapter implementing TopicClassifierPort.

Uses direct AutoModel + PEFT loading (not the HF pipeline API) to support:
  - Full HuggingFace models
  - LoRA adapters (auto-detected via adapter_config.json)

Inference: raw tokenizer → model forward pass → logits.argmax → id2label.
Ported from the production pipeline.py.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import torch
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.app.domain.ports import ClassificationResult, TopicClassifierPort
from src.app.infrastructure.config.settings import TopicModelSettings
from src.app.infrastructure.ml.model_loader import ModelBundle, ModelRegistry, classify_batch

logger = logging.getLogger(__name__)


class HFTopicClassifier(TopicClassifierPort):
    """
    LoRA-aware topic classifier.
    Thread-safe for read access after load(); loading is NOT thread-safe.
    """

    def __init__(self, settings: TopicModelSettings) -> None:
        self._settings = settings
        self._bundle: Optional[ModelBundle] = None
        self._model_version: Optional[str] = None
        self._circuit_open: bool = False
        self._circuit_failure_count: int = 0
        self._circuit_last_failure_time: float = 0.0
        self._circuit_threshold: int = 5
        self._circuit_reset_seconds: float = 60.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Call once at bootstrap. Handles LoRA detection automatically."""
        device = torch.device(self._settings.device)
        self._bundle = ModelRegistry.get(self._settings.name, device)

        try:
            self._model_version = self._bundle.model.config._name_or_path
        except AttributeError:
            self._model_version = self._settings.name

        logger.info(
            "topic_model_loaded",
            extra={
                "model_version": self._model_version,
                "labels": list(self._bundle.id2label.values()),
            },
        )

    def warmup(self) -> None:
        if self._bundle is None:
            self.load()
        logger.info("topic_model_warmup_start")
        assert self._bundle is not None
        classify_batch(["warmup"], self._bundle, batch_size=1)
        logger.info("topic_model_warmup_complete")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def classify_batch(self, texts: list[str]) -> list[ClassificationResult]:
        if not texts:
            return []

        if self._is_circuit_open():
            logger.warning("topic_circuit_breaker_open_returning_fallbacks")
            return self._fallback_results(len(texts))

        try:
            return self._classify_with_retry(texts)
        except Exception as exc:
            self._record_failure()
            logger.error(
                "topic_classify_batch_failed",
                exc_info=exc,
                extra={"batch_size": len(texts)},
            )
            return self._fallback_results(len(texts))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _classify_with_retry(self, texts: list[str]) -> list[ClassificationResult]:
        for attempt in Retrying(
            retry=retry_if_exception_type(RuntimeError),
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=2, max=30),
            reraise=True,
        ):
            with attempt:
                return self._run_inference(texts)

    def _run_inference(self, texts: list[str]) -> list[ClassificationResult]:
        if self._bundle is None:
            raise RuntimeError("Topic model not loaded. Call load() first.")

        labels, confidences = classify_batch(
            texts, self._bundle, self._settings.batch_size
        )

        results: list[ClassificationResult] = []
        for label, conf in zip(labels, confidences):
            # Enforce min confidence threshold
            if conf < self._settings.confidence_min:
                label = self._settings.output_label_fallback

            results.append(
                ClassificationResult(
                    label=label,
                    confidence=conf,
                    model_version=self._model_version,
                )
            )

        self._reset_circuit()
        return results

    def _fallback_results(self, count: int) -> list[ClassificationResult]:
        return [
            ClassificationResult(
                label=self._settings.output_label_fallback,
                confidence=0.0,
                model_version=self._model_version,
            )
            for _ in range(count)
        ]

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------
    def _is_circuit_open(self) -> bool:
        if not self._circuit_open:
            return False
        elapsed = time.monotonic() - self._circuit_last_failure_time
        if elapsed > self._circuit_reset_seconds:
            logger.info("topic_circuit_breaker_half_open")
            self._circuit_open = False
            self._circuit_failure_count = 0
            return False
        return True

    def _record_failure(self) -> None:
        self._circuit_failure_count += 1
        self._circuit_last_failure_time = time.monotonic()
        if self._circuit_failure_count >= self._circuit_threshold:
            if not self._circuit_open:
                logger.error(
                    "topic_circuit_breaker_opened",
                    extra={"failure_count": self._circuit_failure_count},
                )
            self._circuit_open = True

    def _reset_circuit(self) -> None:
        self._circuit_failure_count = 0
        self._circuit_open = False
