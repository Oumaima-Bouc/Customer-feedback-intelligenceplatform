"""
LoRA-aware model loader.

Supports:
  - Full HuggingFace models (AutoModelForSequenceClassification)
  - LoRA adapters (PEFT) — auto-detected via adapter_config.json

Ported from the production pipeline.py inference code.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import torch
from safetensors.torch import load_file
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from peft import PeftModel

logger = logging.getLogger(__name__)


class ModelBundle:
    """
    Encapsulates a tokenizer + model pair.
    Auto-detects LoRA adapters vs full models at load time.
    """

    def __init__(self, path: str, device: torch.device) -> None:
        logger.info("Loading model: %s", path)

        model_path = Path(path)

        if not model_path.exists():
            raise ValueError(f"Model path does not exist: {model_path}")

        is_lora = (model_path / "adapter_config.json").exists()

        if is_lora:
            self._load_lora(model_path, device)
        else:
            self._load_full(model_path, device)

        self.device = device
        self.id2label: dict[int, str] = self.model.config.id2label

        logger.info("Model ready | labels=%s", list(self.id2label.values()))

    # ------------------------------------------------------------------
    def _load_lora(self, path: Path, device: torch.device) -> None:
        """Load a LoRA adapter on top of its base model."""
        logger.info("LoRA adapter detected at %s", path)

        with open(path / "adapter_config.json") as f:
            cfg = json.load(f)

        base_model_name = cfg["base_model_name_or_path"]
        logger.info("Base model: %s", base_model_name)

        # Infer num_labels from the classifier head in safetensors weights
        weights = load_file(str(path / "adapter_model.safetensors"))

        num_labels: Optional[int] = None
        for k, v in weights.items():
            if "classifier" in k and "weight" in k:
                num_labels = v.shape[0]
                break

        if num_labels is None:
            raise ValueError(
                f"Cannot infer num_labels from adapter weights at {path}"
            )

        logger.info("num_labels = %d", num_labels)

        self.tokenizer = AutoTokenizer.from_pretrained(path)

        base_model = AutoModelForSequenceClassification.from_pretrained(
            base_model_name,
            num_labels=num_labels,
        )

        self.model = (
            PeftModel.from_pretrained(base_model, path)
            .to(device)
            .eval()
        )

    # ------------------------------------------------------------------
    def _load_full(self, path: Path, device: torch.device) -> None:
        """Load a standard full HuggingFace model."""
        logger.info("Full model detected at %s", path)

        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = (
            AutoModelForSequenceClassification
            .from_pretrained(path)
            .to(device)
            .eval()
        )


class ModelRegistry:
    """Singleton cache — each model path is loaded at most once."""

    _cache: dict[str, ModelBundle] = {}

    @classmethod
    def get(cls, path: str, device: torch.device) -> ModelBundle:
        if path not in cls._cache:
            cls._cache[path] = ModelBundle(path, device)
        return cls._cache[path]

    @classmethod
    def clear(cls) -> None:
        cls._cache.clear()


def classify_batch(
    texts: list[str],
    bundle: ModelBundle,
    batch_size: int,
) -> tuple[list[str], list[float]]:
    """
    Run batch inference using raw logits (no HF pipeline API).
    Returns (labels, confidences).

    Ported from pipeline.py _classify().
    """
    labels: list[str] = []
    confidences: list[float] = []

    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]

            enc = bundle.tokenizer(
                chunk,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(bundle.device)

            logits = bundle.model(**enc).logits
            probs = torch.softmax(logits, dim=-1)
            pred_ids = logits.argmax(-1).tolist()
            pred_confs = probs.max(dim=-1).values.tolist()

            for pid, conf in zip(pred_ids, pred_confs):
                labels.append(bundle.id2label[pid])
                confidences.append(round(conf, 4))

    return labels, confidences
