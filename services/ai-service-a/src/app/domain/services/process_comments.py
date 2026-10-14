"""
ProcessCommentsService — core domain service.

CLUSTER-FIRST ARCHITECTURE:
  Stage 1: Cluster ALL comments semantically (on normalized text)
  Stage 2: Merge similar clusters (embedding-based, strict)
  Stage 3: Sentiment classification per cluster (on raw text)
  Stage 4: LLM topic labeling per cluster (with fallback to old classifier)
  Stage 5: Assemble enriched output + topic summary

Depends only on domain ports — no infrastructure imports.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from src.app.domain.ports import (
    ClassificationResult,
    ClusterInfo,
    ClusterResult,
    SentimentClassifierPort,
    TopicClassifierPort,
    TopicClusteringPort,
    TopicLabelingPort,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CommentInput:
    comment_id: str
    raw_text: str
    normalized_text: str
    source: Optional[str]
    created_at: str


@dataclass(frozen=True)
class CommentOutput:
    comment_id: str
    topic: str
    sentiment: str
    cluster_id: Optional[int] = None
    topic_label: Optional[str] = None
    fallback_used: bool = False
    topic_confidence: Optional[float] = None
    sentiment_confidence: Optional[float] = None
    model_version: Optional[str] = None


@dataclass(frozen=True)
class TopicSummary:
    """Per-topic sentiment distribution."""
    topic: str
    total_comments: int
    sentiment_distribution: dict[str, float]


@dataclass
class ProcessResult:
    """Complete pipeline output: per-comment enrichment + aggregated summary."""
    enriched_comments: list[CommentOutput]
    topic_summary: list[TopicSummary]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ProcessCommentsService:
    """
    Stateless domain service implementing the CLUSTER-FIRST pipeline:
      Stage 1: cluster ALL comments (normalized text)
      Stage 2: merge similar clusters (embedding-based, strict)
      Stage 3: sentiment classification per cluster (raw text)
      Stage 4: LLM topic labeling per cluster (fallback: old topic classifier)
      Stage 5: assemble enriched_comments + topic_summary
    """

    def __init__(
        self,
        sentiment_classifier: SentimentClassifierPort,
        topic_clustering: TopicClusteringPort,
        topic_labeler: TopicLabelingPort,
        topic_classifier_fallback: TopicClassifierPort,
        sentiment_fallback: str = "neutral",
        topic_fallback: str = "other",
    ) -> None:
        self._sentiment_clf = sentiment_classifier
        self._clustering = topic_clustering
        self._labeler = topic_labeler
        self._topic_clf_fallback = topic_classifier_fallback
        self._sentiment_fallback = sentiment_fallback
        self._topic_fallback = topic_fallback

    # ------------------------------------------------------------------
    def process_comments(self, items: list[CommentInput]) -> ProcessResult:
        """
        Main entry point — cluster-first pipeline.

        Returns ProcessResult containing:
          - enriched_comments: one CommentOutput per input, original order preserved
          - topic_summary: per-topic sentiment distribution (percentages)
        """
        if not items:
            return ProcessResult(enriched_comments=[], topic_summary=[])

        normalized_texts = [c.normalized_text for c in items]
        raw_texts = [c.raw_text for c in items]

        # --- Stage 1: Cluster ALL comments on normalized text ---
        try:
            cluster_result: ClusterResult = self._clustering.cluster(normalized_texts)
        except Exception as exc:
            logger.error("clustering_failed", exc_info=exc)
            cluster_result = ClusterResult(
                clusters=[ClusterInfo(
                    cluster_id=0,
                    comment_indices=list(range(len(items))),
                    representative_indices=list(range(min(len(items), 15))),
                    size=len(items),
                )],
                labels=[0] * len(items),
            )

        logger.info(
            "clustering_stage_done",
            extra={"n_clusters": len(cluster_result.clusters), "n_comments": len(items)},
        )

        # --- Stage 2: Merge similar clusters (embedding-based, strict) ---
        try:
            cluster_result = self._clustering.merge_similar_clusters(cluster_result)
        except Exception as exc:
            logger.error("cluster_merge_failed", exc_info=exc)

        logger.info(
            "merge_stage_done",
            extra={"n_clusters_after_merge": len(cluster_result.clusters)},
        )

        # --- Stage 3: Sentiment classification per cluster (on raw text) ---
        # comment_enrichment[original_idx] = (cluster_id, sentiment_label, sentiment_confidence)
        comment_enrichment: dict[int, tuple[int, str, float]] = {}

        for ci in cluster_result.clusters:
            cluster_raw = [raw_texts[idx] for idx in ci.comment_indices if idx < len(raw_texts)]
            sentiment_results = self._safe_classify_sentiments(cluster_raw)

            for local_idx, global_idx in enumerate(ci.comment_indices):
                if global_idx < len(items) and local_idx < len(sentiment_results):
                    sent = sentiment_results[local_idx]
                    comment_enrichment[global_idx] = (
                        ci.cluster_id, sent.label, sent.confidence,
                    )

        logger.info(
            "sentiment_per_cluster_done",
            extra={"n_enriched": len(comment_enrichment)},
        )

        # --- Stage 4: LLM topic labeling per cluster ---
        llm_available = self._check_llm_available()

        cluster_reps: dict[int, list[str]] = {}
        for ci in cluster_result.clusters:
            rep_texts = [
                normalized_texts[ri] for ri in ci.representative_indices
                if ri < len(normalized_texts)
            ]
            if not rep_texts:
                rep_texts = [normalized_texts[ci.comment_indices[0]]]
            cluster_reps[ci.cluster_id] = rep_texts

        labels_map, used_fallback = self._label_clusters(cluster_reps, llm_available)

        # --- Stage 4.5: LLM-based topic merge (deduplicate near-identical labels) ---
        if llm_available and not used_fallback and len(cluster_result.clusters) >= 2:
            try:
                merge_input = []
                for ci in cluster_result.clusters:
                    rep_texts = [
                        normalized_texts[ri] for ri in ci.representative_indices
                        if ri < len(normalized_texts)
                    ][:5]
                    merge_input.append({
                        "cluster_id": ci.cluster_id,
                        "topic_label": labels_map.get(ci.cluster_id, ""),
                        "size": ci.size,
                        "representatives": rep_texts,
                        "comment_indices": ci.comment_indices,
                    })

                merged_clusters = self._labeler.merge_clusters(merge_input)

                if len(merged_clusters) < len(cluster_result.clusters):
                    # Rebuild labels_map and cluster_result from merged output
                    new_labels_map: dict[int, str] = {}
                    new_cluster_infos: list[ClusterInfo] = []

                    for mc in merged_clusters:
                        new_cid = mc["cluster_id"]
                        new_labels_map[new_cid] = mc.get("topic_label", labels_map.get(new_cid, ""))
                        new_cluster_infos.append(ClusterInfo(
                            cluster_id=new_cid,
                            comment_indices=mc.get("comment_indices", []),
                            representative_indices=mc.get("comment_indices", [])[:15],
                            size=mc.get("size", 0),
                        ))

                    # Rebuild comment_enrichment with new cluster IDs
                    idx_to_new_cid: dict[int, int] = {}
                    for nci in new_cluster_infos:
                        for idx in nci.comment_indices:
                            idx_to_new_cid[idx] = nci.cluster_id

                    for i in list(comment_enrichment.keys()):
                        old_cid, sent, conf = comment_enrichment[i]
                        new_cid = idx_to_new_cid.get(i, old_cid)
                        comment_enrichment[i] = (new_cid, sent, conf)

                    labels_map = new_labels_map
                    cluster_result = ClusterResult(
                        clusters=new_cluster_infos,
                        labels=[idx_to_new_cid.get(i, 0) for i in range(len(items))],
                    )

                    logger.info(
                        "llm_topic_merge_done",
                        extra={"merged_from": len(merge_input), "merged_to": len(merged_clusters)},
                    )
            except Exception as exc:
                logger.warning("llm_topic_merge_failed", exc_info=exc)

        # --- Stage 5: Assemble output ---
        enriched: list[CommentOutput] = []
        topic_sentiments: dict[str, list[str]] = defaultdict(list)

        for i, item in enumerate(items):
            cluster_id, sentiment_label, sentiment_conf = comment_enrichment.get(
                i, (0, self._sentiment_fallback, 0.0),
            )
            topic = labels_map.get(cluster_id, self._topic_fallback)

            enriched.append(
                CommentOutput(
                    comment_id=item.comment_id,
                    topic=topic,
                    sentiment=sentiment_label,
                    cluster_id=cluster_id,
                    topic_label=topic,
                    fallback_used=used_fallback,
                    topic_confidence=None,
                    sentiment_confidence=round(sentiment_conf, 4),
                    model_version=None,
                )
            )

            topic_sentiments[topic].append(sentiment_label)

        # Build topic_summary
        summary: list[TopicSummary] = []
        for topic, sents in topic_sentiments.items():
            total = len(sents)
            counts: dict[str, int] = defaultdict(int)
            for s in sents:
                counts[s.lower()] += 1

            summary.append(
                TopicSummary(
                    topic=topic,
                    total_comments=total,
                    sentiment_distribution={
                        k: round(v / total * 100, 2) for k, v in counts.items()
                    },
                )
            )

        return ProcessResult(enriched_comments=enriched, topic_summary=summary)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _check_llm_available(self) -> bool:
        try:
            available = self._labeler.is_available()
            if not available:
                logger.warning("llm_unavailable_will_use_fallback_topic_classifier")
            return available
        except Exception:
            logger.warning("llm_availability_check_error_will_use_fallback")
            return False

    def _label_clusters(
        self,
        cluster_reps: dict[int, list[str]],
        llm_available: bool,
    ) -> tuple[dict[int, str], bool]:
        """
        Try LLM labeling; on failure fall back to old topic classifier.
        Returns (labels_map, used_fallback).
        """
        if llm_available:
            try:
                labels_map = self._labeler.label_clusters(cluster_reps)
                return labels_map, False
            except Exception as exc:
                logger.error("llm_labeling_failed_using_fallback", exc_info=exc)

        # Fallback: use legacy topic classifier on representative texts
        return self._fallback_classify_clusters(cluster_reps), True

    def _fallback_classify_clusters(
        self, cluster_reps: dict[int, list[str]]
    ) -> dict[int, str]:
        """Use old topic classifier on cluster representatives to get a label."""
        labels: dict[int, str] = {}
        for cid, reps in cluster_reps.items():
            try:
                results = self._topic_clf_fallback.classify_batch(reps)
                # Majority vote among representative classifications
                label_counts: dict[str, int] = defaultdict(int)
                for r in results:
                    label_counts[r.label] += 1
                best_label = max(label_counts, key=label_counts.get)
                labels[cid] = best_label
            except Exception:
                labels[cid] = self._topic_fallback
        return labels

    def _safe_classify_sentiments(
        self, texts: list[str]
    ) -> list[ClassificationResult]:
        try:
            results = self._sentiment_clf.classify_batch(texts)
            if len(results) != len(texts):
                raise ValueError(
                    f"Sentiment classifier returned {len(results)} results for {len(texts)} inputs"
                )
            return results
        except Exception as exc:
            logger.error("sentiment_batch_classification_failed", exc_info=exc)
            return [
                ClassificationResult(
                    label=self._sentiment_fallback, confidence=0.0
                )
                for _ in texts
            ]
