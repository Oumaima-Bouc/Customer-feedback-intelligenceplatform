"""
Layer 2 — TF-IDF statistical word discovery (Strategy pattern).

Discovers emerging terms not in the curated dictionary by computing
TF-IDF scores across the day's comment corpus. Language-agnostic.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Optional

from src.app.domain.ports import WordExtractionStrategyPort
from src.app.infrastructure.word_cloud.tokenizer import tokenize

logger = logging.getLogger(__name__)


class TfIdfExtractor(WordExtractionStrategyPort):
    """
    Extracts top-N terms by TF-IDF score from a corpus of comments.
    Excludes any words already present in a curated set (to avoid duplicates).
    """

    def __init__(
        self,
        top_n: int = 50,
        min_frequency: int = 3,
        curated_words: Optional[set[str]] = None,
    ) -> None:
        self._top_n = top_n
        self._min_freq = min_frequency
        self._curated = curated_words or set()

    def extract(self, texts: list[str]) -> dict[str, dict]:
        """
        Compute TF-IDF and return top-N discovered terms.

        Returns:
            {word: {"frequency": int, "category": None, "source": "discovered"}}
        """
        if not texts:
            return {}

        # Tokenize all documents
        doc_tokens: list[list[str]] = [tokenize(t) for t in texts]
        num_docs = len(doc_tokens)

        if num_docs == 0:
            return {}

        # Document frequency: in how many documents does each term appear?
        doc_freq: Counter[str] = Counter()
        for tokens in doc_tokens:
            unique_tokens = set(tokens)
            for tok in unique_tokens:
                doc_freq[tok] += 1

        # Term frequency across entire corpus
        term_freq: Counter[str] = Counter()
        for tokens in doc_tokens:
            term_freq.update(tokens)

        # Compute TF-IDF score per term
        tfidf_scores: dict[str, float] = {}
        for term, tf in term_freq.items():
            # Skip terms below minimum frequency
            if tf < self._min_freq:
                continue
            # Skip curated words (already handled by Layer 1)
            if term in self._curated:
                continue

            df = doc_freq.get(term, 1)
            idf = math.log(num_docs / df) + 1.0  # smoothed IDF
            tfidf_scores[term] = tf * idf

        # Rank and take top N
        ranked = sorted(tfidf_scores.items(), key=lambda x: x[1], reverse=True)
        top_terms = ranked[: self._top_n]

        result: dict[str, dict] = {}
        for word, _score in top_terms:
            result[word] = {
                "frequency": term_freq[word],
                "category": None,
                "source": "discovered",
            }

        logger.info(
            "word_cloud.tfidf_extracted",
            extra={
                "corpus_size": num_docs,
                "unique_terms": len(term_freq),
                "discovered_terms": len(result),
            },
        )
        return result
