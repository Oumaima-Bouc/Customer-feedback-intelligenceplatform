"""
Domain ports — pure interfaces and DTOs.

No infrastructure dependencies. All adapters in the infrastructure layer
implement these ports, enabling strategy-pattern swaps (HF / ONNX / mock)
without touching domain or application logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# DTOs (Value Objects)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CommentRecord:
    """Row fetched from the comments table."""
    comment_id: str
    text_content: str
    created_at: datetime
    source: Optional[str] = None


@dataclass(frozen=True)
class EnrichmentUpdate:
    """Payload written back to the comments table."""
    comment_id: str
    topic: str
    sentiment: str
    cluster_id: Optional[int] = None
    topic_label: Optional[str] = None
    fallback_used: bool = False


@dataclass(frozen=True)
class CheckpointValue:
    """Keyset-pagination resume state."""
    key: str
    last_comment_id: str
    last_run_at: Optional[datetime] = None
    last_window_start: Optional[datetime] = None
    last_window_end: Optional[datetime] = None


@dataclass(frozen=True)
class ClassificationResult:
    """Output of any classifier adapter."""
    label: str
    confidence: float
    model_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Repository Ports
# ---------------------------------------------------------------------------
class CommentRepositoryPort(ABC):

    @abstractmethod
    def fetch_batch(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        last_comment_id: str,
        batch_size: int,
        process_only_unclassified: bool,
        ignore_date_window: bool = False,
    ) -> list[CommentRecord]:
        ...

    @abstractmethod
    def update_enrichment_batch(self, updates: list[EnrichmentUpdate]) -> int:
        ...


class CheckpointRepositoryPort(ABC):

    @abstractmethod
    def load(self, key: str) -> Optional[CheckpointValue]:
        ...

    @abstractmethod
    def save(self, checkpoint: CheckpointValue) -> None:
        ...


# ---------------------------------------------------------------------------
# Topic Tracking Port
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TopicDailyRecord:
    """One row in topic_daily_tracking — per-topic per-day aggregate."""
    run_date: datetime
    topic: str
    comment_count: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class TopicTrackingRepositoryPort(ABC):

    @abstractmethod
    def upsert_daily_tracking(self, records: list[TopicDailyRecord]) -> None:
        """Insert or update topic tracking rows for a given run date."""
        ...


# ---------------------------------------------------------------------------
# Classifier Ports
# ---------------------------------------------------------------------------
class TopicClassifierPort(ABC):
    """Legacy topic classifier — used as FALLBACK when LLM labeling fails."""

    @abstractmethod
    def classify_batch(self, texts: list[str]) -> list[ClassificationResult]:
        ...


class SentimentClassifierPort(ABC):

    @abstractmethod
    def classify_batch(self, texts: list[str]) -> list[ClassificationResult]:
        ...


# ---------------------------------------------------------------------------
# Topic Clustering DTOs
# ---------------------------------------------------------------------------
@dataclass
class ClusterInfo:
    """A single cluster with its comments and representatives."""
    cluster_id: int
    comment_indices: list[int]       # indices into the original comment list
    representative_indices: list[int]  # indices of representative comments
    topic_label: str = ""           # filled by LLM labeler or fallback
    size: int = 0


@dataclass
class ClusterResult:
    """Output of the clustering stage for the full comment batch."""
    clusters: list[ClusterInfo]
    labels: list[int]   # cluster_id per comment (aligned with input)


# ---------------------------------------------------------------------------
# Topic Clustering Port
# ---------------------------------------------------------------------------
class TopicClusteringPort(ABC):
    """Embeds, reduces, clusters comments, and merges similar clusters."""

    @abstractmethod
    def cluster(
        self,
        texts: list[str],
        *,
        n_clusters: Optional[int] = None,
    ) -> ClusterResult:
        ...

    @abstractmethod
    def merge_similar_clusters(
        self,
        cluster_result: ClusterResult,
    ) -> ClusterResult:
        """Merge clusters whose centroids are above the similarity threshold."""
        ...


# ---------------------------------------------------------------------------
# Topic Labeling Port (LLM-based)
# ---------------------------------------------------------------------------
class TopicLabelingPort(ABC):
    """Labels clusters using an LLM API, then optionally merges similar ones."""

    @abstractmethod
    def label_clusters(
        self,
        cluster_representatives: dict[int, list[str]],
    ) -> dict[int, str]:
        """Returns {cluster_id: topic_label}."""
        ...

    @abstractmethod
    def merge_clusters(
        self,
        clusters: list[dict],
    ) -> list[dict]:
        """Merge similar clusters. Returns updated cluster list."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM API is reachable."""
        ...


# ---------------------------------------------------------------------------
# Normalizer Port
# ---------------------------------------------------------------------------
class NormalizerPort(ABC):

    @abstractmethod
    def normalize(self, text: str) -> str:
        ...

    @abstractmethod
    def normalize_batch(self, texts: list[str]) -> list[str]:
        ...


# ---------------------------------------------------------------------------
# Word Cloud DTOs & Ports
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WordCloudEntry:
    """Single word in the word cloud snapshot."""
    word: str
    frequency: int
    positive_pct: float
    neutral_pct: float
    negative_pct: float
    source: str             # 'curated' | 'discovered'
    category: Optional[str] = None


class WordCloudRepositoryPort(ABC):
    """Persists and reads the word cloud snapshot."""

    @abstractmethod
    def replace_snapshot(self, entries: list[WordCloudEntry]) -> None:
        """Atomically replaces the entire snapshot (TRUNCATE + INSERT)."""
        ...

    @abstractmethod
    def fetch_snapshot(self) -> list[WordCloudEntry]:
        """Returns all entries ordered by frequency DESC."""
        ...


class WordExtractionStrategyPort(ABC):
    """Strategy interface for word extraction (dictionary or TF-IDF)."""

    @abstractmethod
    def extract(
        self,
        texts: list[str],
    ) -> dict[str, dict]:
        """
        Returns {word: {"frequency": int, "category": str|None, "source": str}}.
        """
        ...
