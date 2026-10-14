"""
SocialTextNormalizer — implements NormalizerPort.

Rules (from architecture spec):
- Normalize in memory ONLY — never written to DB
- Preserve emojis
- Remove URLs, repeated noise, control characters
- Remove unsafe prompt-like artifacts (separate from input_sanitizer: this strips; sanitizer rejects)
- Keep raw_text unchanged in the database
- Unicode NFKC normalization (optional, per config)
- HTML stripping (optional)
- Configurable mention/hashtag removal
"""
from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache

from src.app.domain.ports import NormalizerPort
from src.app.infrastructure.config.settings import NormalizationSettings


# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for performance)
# ---------------------------------------------------------------------------
_URL_PATTERN = re.compile(
    r"https?://\S+|www\.\S+",
    re.IGNORECASE,
)
_MENTION_PATTERN = re.compile(r"@\w{1,50}")
_HASHTAG_PATTERN = re.compile(r"#\w{1,100}")
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_TAG_PATTERN = re.compile(r"<[^>]{0,200}>")
_WHITESPACE_COLLAPSE_PATTERN = re.compile(r"[ \t]{2,}")
_REPEATED_PUNCT_PATTERN = re.compile(r"([!?.،؟]){3,}")
_PROMPT_ARTIFACT_PATTERN = re.compile(
    r"(?i)(system\s*:\s*|user\s*:\s*|assistant\s*:\s*|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>|<\|im_start\|>|<\|im_end\|>)"
)


class SocialTextNormalizer(NormalizerPort):

    def __init__(self, settings: NormalizationSettings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    def normalize(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return ""

        s = text

        # 1. Unicode NFKC (before anything else — collapses lookalike chars)
        if self._settings.unicode_nfkc:
            s = unicodedata.normalize("NFKC", s)

        # 2. HTML entity decode then strip tags
        if self._settings.strip_html:
            s = html.unescape(s)
            s = _HTML_TAG_PATTERN.sub(" ", s)

        # 3. Remove control characters (preserves \n \r \t)
        if self._settings.remove_control_chars:
            s = _CONTROL_CHAR_PATTERN.sub("", s)

        # 4. Strip prompt injection artifacts (defensive layer)
        s = _PROMPT_ARTIFACT_PATTERN.sub(" ", s)

        # 5. URLs
        if self._settings.remove_urls:
            s = _URL_PATTERN.sub(" ", s)

        # 6. @mentions
        if self._settings.remove_mentions:
            s = _MENTION_PATTERN.sub(" ", s)

        # 7. #hashtags
        if self._settings.remove_hashtags:
            s = _HASHTAG_PATTERN.sub(" ", s)

        # 8. Collapse repeated punctuation (e.g. "!!!!!!!" → "!")
        s = _REPEATED_PUNCT_PATTERN.sub(r"\1", s)

        # 9. Collapse whitespace (preserve newlines for structure)
        if self._settings.collapse_whitespace:
            s = _WHITESPACE_COLLAPSE_PATTERN.sub(" ", s)
            s = s.strip()

        # 10. Enforce max length LAST (after all transforms)
        if len(s) > self._settings.max_text_length:
            s = s[: self._settings.max_text_length]

        return s

    def normalize_batch(self, texts: list[str]) -> list[str]:
        return [self.normalize(t) for t in texts]
