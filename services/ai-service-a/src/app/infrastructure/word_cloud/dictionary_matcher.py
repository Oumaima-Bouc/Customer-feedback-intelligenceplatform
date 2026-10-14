"""
Layer 1 — Curated dictionary matcher (Strategy pattern).

Loads the domain keyword dictionary from YAML and counts occurrences
of curated words (including all variant forms) in tokenized comments.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.app.domain.ports import WordExtractionStrategyPort
from src.app.infrastructure.word_cloud.tokenizer import tokenize

logger = logging.getLogger(__name__)


class DictionaryMatcher(WordExtractionStrategyPort):
    """
    Matches tokens against a curated YAML dictionary.
    Each dictionary entry has a canonical word and variant forms;
    all variants map to the same canonical word for counting.
    """

    def __init__(self, dictionary_path: Path) -> None:
        self._variant_to_canonical: dict[str, str] = {}
        self._canonical_to_category: dict[str, str] = {}
        self._load_dictionary(dictionary_path)

    def _load_dictionary(self, path: Path) -> None:
        """Parse words.yaml and build variant → canonical lookup tables."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning("word_cloud.dictionary_not_found", extra={"path": str(path)})
            return
        except Exception as exc:
            logger.error("word_cloud.dictionary_load_error", extra={"error": str(exc)})
            return

        categories: dict[str, list[dict[str, Any]]] = data.get("categories", {})

        for category_name, entries in categories.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                canonical = entry.get("word", "").strip().lower()
                if not canonical:
                    continue
                self._canonical_to_category[canonical] = category_name

                for variant in entry.get("variants", []):
                    normalized = variant.strip().lower()
                    if normalized:
                        self._variant_to_canonical[normalized] = canonical

        logger.info(
            "word_cloud.dictionary_loaded",
            extra={
                "canonical_words": len(self._canonical_to_category),
                "total_variants": len(self._variant_to_canonical),
            },
        )

    def extract(self, texts: list[str]) -> dict[str, dict]:
        """
        Count curated word occurrences across all texts.

        Returns:
            {canonical_word: {"frequency": int, "category": str, "source": "curated"}}
        """
        counts: dict[str, int] = {}

        for text in texts:
            tokens = tokenize(text)
            matched_in_text: set[str] = set()

            # Single-token matching
            for tok in tokens:
                canonical = self._variant_to_canonical.get(tok)
                if canonical and canonical not in matched_in_text:
                    counts[canonical] = counts.get(canonical, 0) + 1
                    matched_in_text.add(canonical)

            # Multi-token (bigram) matching for compound variants
            text_lower = text.lower()
            for variant, canonical in self._variant_to_canonical.items():
                if " " in variant and canonical not in matched_in_text:
                    if variant in text_lower:
                        counts[canonical] = counts.get(canonical, 0) + 1
                        matched_in_text.add(canonical)

        result: dict[str, dict] = {}
        for word, freq in counts.items():
            result[word] = {
                "frequency": freq,
                "category": self._canonical_to_category.get(word),
                "source": "curated",
            }
        return result
