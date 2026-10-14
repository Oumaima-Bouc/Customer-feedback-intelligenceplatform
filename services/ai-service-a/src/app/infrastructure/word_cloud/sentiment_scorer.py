"""
Sentiment scorer — computes per-word sentiment breakdown.

Given merged word frequencies and the original (text, sentiment) pairs,
calculates what percentage of each word's occurrences fall in
positive / neutral / negative comments.

Uses variant-to-canonical mapping so curated canonical names
(e.g. "espace_client") are matched via their actual variant forms
(e.g. "فضاء الزبون", "espace client") in the comment text.
"""
from __future__ import annotations

from typing import Optional

from src.app.domain.ports import WordCloudEntry
from src.app.infrastructure.word_cloud.tokenizer import tokenize


def score_words_by_sentiment(
    merged_words: dict[str, dict],
    texts: list[str],
    sentiments: list[str],
    variant_to_canonical: Optional[dict[str, str]] = None,
) -> list[WordCloudEntry]:
    """
    For each word in merged_words, count how many times it appears in
    positive / neutral / negative comments, then compute percentages.

    Args:
        merged_words: {word: {"frequency": int, "category": str|None, "source": str}}
        texts: list of comment texts (aligned with sentiments)
        sentiments: list of sentiment labels (aligned with texts)
        variant_to_canonical: {variant_lower: canonical_word} from DictionaryMatcher

    Returns:
        List of WordCloudEntry with sentiment percentages filled in.
    """
    if not merged_words or not texts:
        return []

    word_set = set(merged_words.keys())

    # Build reverse lookup: canonical -> set of variant forms (for curated words)
    canonical_to_variants: dict[str, set[str]] = {w: set() for w in word_set}
    if variant_to_canonical:
        for variant, canonical in variant_to_canonical.items():
            if canonical in canonical_to_variants:
                canonical_to_variants[canonical].add(variant)

    # Per-word sentiment counters
    word_sentiment: dict[str, dict[str, int]] = {
        w: {"positive": 0, "neutral": 0, "negative": 0}
        for w in word_set
    }

    for text, sentiment in zip(texts, sentiments):
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = "neutral"

        tokens = set(tokenize(text))
        text_lower = text.lower()

        for word in word_set:
            matched = False

            # Direct token match (works for discovered words and single-token curated)
            if word in tokens:
                matched = True

            # Variant-based matching for curated canonical words
            if not matched and canonical_to_variants[word]:
                for variant in canonical_to_variants[word]:
                    if " " in variant:
                        # Multi-word variant: substring match in original text
                        if variant in text_lower:
                            matched = True
                            break
                    else:
                        # Single-word variant: token match
                        if variant in tokens:
                            matched = True
                            break

            # Fallback: multi-word canonical in text (for discovered words with spaces)
            if not matched and " " in word and word in text_lower:
                matched = True

            if matched:
                word_sentiment[word][sentiment] += 1

    entries: list[WordCloudEntry] = []
    for word, info in merged_words.items():
        freq = info["frequency"]
        if freq <= 0:
            continue

        counts = word_sentiment[word]
        total_sentiment = counts["positive"] + counts["neutral"] + counts["negative"]

        if total_sentiment == 0:
            pos_pct = neu_pct = neg_pct = 0.0
        else:
            pos_pct = round(counts["positive"] / total_sentiment, 4)
            neu_pct = round(counts["neutral"] / total_sentiment, 4)
            neg_pct = round(counts["negative"] / total_sentiment, 4)

        entries.append(
            WordCloudEntry(
                word=word,
                frequency=freq,
                positive_pct=pos_pct,
                neutral_pct=neu_pct,
                negative_pct=neg_pct,
                source=info["source"],
                category=info.get("category"),
            )
        )

    # Sort by frequency descending
    entries.sort(key=lambda e: e.frequency, reverse=True)
    return entries
