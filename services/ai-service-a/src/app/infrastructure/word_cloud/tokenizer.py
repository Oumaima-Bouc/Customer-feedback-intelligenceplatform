"""
Word cloud tokenizer — splits comment text into meaningful tokens.

Handles the multilingual corpus (French, Arabic, Darija, Franco-Arab)
by applying Unicode-aware splitting and a combined stopword list.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# ---------------------------------------------------------------------------
# Stopwords — French + Arabic + common Darija function words
# ---------------------------------------------------------------------------
_FRENCH_STOPWORDS = frozenset(
    "le la les de du des un une et est en au aux ce que qui ne pas "
    "se sa son ses sur par pour dans il elle ils elles je tu nous vous "
    "on avec tout mais ou bien aussi plus très même ca cette ces si "
    "comme leur leurs nos vos mon ma mes lui où quand donc "
    "sont été fait faire dit été y a d l n s c j m t qu".split()
)

_ARABIC_STOPWORDS = frozenset(
    "في من على هذا هذه التي الذي إلى أن كان ما هو هي لا "
    "عن بين كل ذلك لم يا ان او قد تم بعد حتى ثم اي هل "
    "منذ لكن عند عندما ليس ولا فقط كما لقد بل ايضا "
    "مع هنا هناك كيف ماذا لماذا اذا".split()
)

_DARIJA_STOPWORDS = frozenset(
    "هاد ديال كاين راه راهي لي اللي تاع نتاع خلاص باش "
    "كي واش علاه فين وين شحال قداش كيفاش ماشي هادي هادا "
    "عندي عندك عنده عندها ولكن بصح غير حتى واحد".split()
)

STOPWORDS = _FRENCH_STOPWORDS | _ARABIC_STOPWORDS | _DARIJA_STOPWORDS

# Match word-like tokens: Arabic script sequences OR Latin+digit sequences
_TOKEN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]+|[a-zA-Z0-9àâäéèêëïîôùûüçœæ]+", re.UNICODE)

# Minimum token length (characters) to keep
_MIN_TOKEN_LEN = 2


def tokenize(text: str) -> list[str]:
    """
    Tokenize a single comment into lowercase tokens,
    filtering stopwords and short tokens.
    """
    text = unicodedata.normalize("NFKC", text)
    raw_tokens = _TOKEN_RE.findall(text.lower())
    return [
        tok for tok in raw_tokens
        if len(tok) >= _MIN_TOKEN_LEN and tok not in STOPWORDS
    ]


def tokenize_batch(texts: Iterable[str]) -> list[list[str]]:
    """Tokenize multiple texts."""
    return [tokenize(t) for t in texts]
