"""
TopicClusteringAdapter — implements TopicClusteringPort.

Wraps the standalone topic clustering pipeline logic:
  1. Clean text
  2. Generate embeddings (DziriBERT / sentence-transformers)
  3. UMAP dimensionality reduction
  4. Agglomerative clustering (fixed K or auto-detect via silhouette)
  5. Extract representative comments per cluster

Configuration comes from EmbeddingSettings + ClusteringSettings.
"""
from __future__ import annotations

import logging
import re
import html
import warnings
from typing import Optional

import numpy as np
import torch

from src.app.domain.ports import ClusterInfo, ClusterResult, TopicClusteringPort
from src.app.infrastructure.config.settings import ClusteringSettings, EmbeddingSettings

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT CLEANING (ported from topic_clustering_pipeline.py)
# ═══════════════════════════════════════════════════════════════════════════════

_URL_RE = re.compile(r"(https?://\S+|www\.\S+)", flags=re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
_MENTION_RE = re.compile(r"(?<!\w)@\w+")
_HASHTAG_RE = re.compile(r"#(\w+)")
_EMOJI_RE = re.compile(
    "[\U0001F1E0-\U0001F1FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF\U00002700-\U000027BF\U000024C2-\U0001F251]+",
    flags=re.UNICODE,
)
_DIACRITICS_RE = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u06D6-\u06ED]")
_TATWEEL_RE = re.compile(r"\u0640+")
_MULTISPACE_RE = re.compile(r"\s+")
_REPEATED_RE = re.compile(r"(.)\1{3,}", flags=re.UNICODE)


def _clean(text: str) -> str:
    """Minimal semantic-preserving text cleaning for embedding."""
    if not isinstance(text, str) or not text.strip():
        return ""
    text = html.unescape(text)
    text = _URL_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(r"\1", text)
    text = _EMOJI_RE.sub(" ", text)
    text = re.sub(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]", "", text)
    text = _TATWEEL_RE.sub("", text)
    text = _DIACRITICS_RE.sub("", text)
    text = re.sub(r"[إأآٱ]", "ا", text)
    text = _REPEATED_RE.sub(r"\1\1", text)
    text = re.sub(r"[!?]{3,}", "!", text)
    text = re.sub(r"\.{4,}", "...", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()
    return text


def _is_valid(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    return sum(1 for c in text if c.isalpha() or "\u0600" <= c <= "\u06FF") >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDING
# ═══════════════════════════════════════════════════════════════════════════════

def _embed_texts(
    texts: list[str],
    model_name: str = "intfloat/multilingual-e5-base",
    device: str = "cpu",
    batch_size: int = 64,
    max_length: int = 192,
) -> np.ndarray:
    """Generate L2-normalized multilingual sentence embeddings.

    Uses a real SentenceTransformer (multilingual-e5-base by default) which handles
    Arabic / Darija / French. E5 models require an input prefix ("query: ") — we add it
    automatically so embeddings are semantically meaningful for clustering.
    """
    is_e5 = "e5" in model_name.lower()
    enc_texts = [f"query: {t}" for t in texts] if is_e5 else texts

    # Proper sentence-transformer path (the intended path for e5/mpnet).
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(model_name, device=device)
        model.max_seq_length = max_length
        emb = model.encode(
            enc_texts, batch_size=batch_size, show_progress_bar=False,
            convert_to_numpy=True, normalize_embeddings=True,
        )
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
        return emb
    except Exception:
        pass

    # Fallback: raw transformers + mean-pooling
    from transformers import AutoTokenizer, AutoModel

    logger.info("embedding_fallback_transformers", extra={"model": model_name})
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name).to(device)
    model.eval()

    all_emb = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            enc = tokenizer(
                batch, padding=True, truncation=True,
                max_length=max_length, return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            out = model(**enc)
            tok_emb = out.last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).expand(tok_emb.size()).float()
            mean_emb = torch.sum(tok_emb * mask, dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
            mean_emb = torch.nn.functional.normalize(mean_emb, p=2, dim=1)
            all_emb.append(mean_emb.cpu().numpy())

    del model, tokenizer
    if device == "cuda":
        torch.cuda.empty_cache()
    return np.vstack(all_emb)


# ═══════════════════════════════════════════════════════════════════════════════
# CLUSTERING
# ═══════════════════════════════════════════════════════════════════════════════

def _assign_noise_to_nearest(reduced: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """HDBSCAN marks one-off comments as noise (-1). Assign each to the nearest
    cluster centroid so every comment receives a topic."""
    labels = np.asarray(labels)
    noise = labels == -1
    if not noise.any():
        return labels
    clustered = labels != -1
    if not clustered.any():
        return np.zeros(len(labels), dtype=int)  # all noise → one cluster
    cids = sorted({int(c) for c in labels[clustered]})
    centroids = np.stack([reduced[labels == c].mean(axis=0) for c in cids])
    out = labels.copy()
    for i in np.where(noise)[0]:
        d = np.linalg.norm(centroids - reduced[i], axis=1)
        out[i] = cids[int(np.argmin(d))]
    return out


def _reduce_and_cluster(
    embeddings: np.ndarray,
    n_clusters: Optional[int] = None,
    umap_dim: int = 15,
    umap_neighbors: int = 30,
    umap_min_dist: float = 0.0,
    umap_metric: str = "cosine",
    seed: int = 42,
    k_range: tuple = (3, 20),
    min_cluster_size: int = 8,
) -> tuple[np.ndarray, int]:
    """UMAP reduction → density-based HDBSCAN (auto) or fixed-K Agglomerative."""
    import umap as umap_lib
    from sklearn.cluster import AgglomerativeClustering

    n_samples = embeddings.shape[0]
    effective_neighbors = min(umap_neighbors, n_samples - 1)
    effective_dim = min(umap_dim, n_samples - 2)

    if effective_dim < 2:
        effective_dim = 2
    if effective_neighbors < 2:
        effective_neighbors = 2

    reducer = umap_lib.UMAP(
        n_components=effective_dim,
        n_neighbors=effective_neighbors,
        min_dist=umap_min_dist,
        metric=umap_metric,
        random_state=seed,
        n_jobs=-1,
    )
    reduced = reducer.fit_transform(embeddings)

    if n_clusters is not None:
        # Explicit K requested → Agglomerative (back-compat).
        effective_k = min(n_clusters, n_samples)
        labels = AgglomerativeClustering(
            n_clusters=effective_k, metric="euclidean", linkage="ward",
        ).fit_predict(reduced)
        return labels, effective_k

    # Auto: density-based HDBSCAN discovers the natural number of topics (no forcing
    # everything into K blobs the way silhouette-Agglomerative did) and isolates
    # one-off comments as noise, which we then attach to their nearest topic.
    import hdbscan

    mcs = max(2, min(int(min_cluster_size), max(2, n_samples // 2)))
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs,
        min_samples=1,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    raw_labels = clusterer.fit_predict(reduced)
    labels = _assign_noise_to_nearest(reduced, raw_labels)
    n_found = len({int(x) for x in labels})
    if n_found < 1:
        labels = np.zeros(n_samples, dtype=int)
        n_found = 1
    logger.info(
        "hdbscan_clusters",
        extra={"k": n_found, "min_cluster_size": mcs,
               "noise": int((raw_labels == -1).sum())},
    )
    return labels, n_found


# ═══════════════════════════════════════════════════════════════════════════════
# REPRESENTATIVES
# ═══════════════════════════════════════════════════════════════════════════════

def _get_representatives(
    embeddings: np.ndarray,
    labels: np.ndarray,
    texts: list[str],
    top_k: int = 5,
) -> dict[int, list[int]]:
    """Get representative comment indices per cluster (closest to centroid)."""
    reps: dict[int, list[int]] = {}
    for cid in sorted(set(labels)):
        mask = labels == cid
        indices = [i for i in range(len(texts)) if mask[i]]
        cluster_emb = embeddings[mask]

        if len(indices) <= top_k:
            reps[int(cid)] = indices
        else:
            centroid = cluster_emb.mean(axis=0)
            centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
            sims = cluster_emb @ centroid
            top_idx = np.argsort(sims)[::-1][:top_k]
            reps[int(cid)] = [indices[i] for i in top_idx]
    return reps


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER
# ═══════════════════════════════════════════════════════════════════════════════

class TopicClusteringAdapter(TopicClusteringPort):
    """
    Production adapter implementing TopicClusteringPort.
    Encapsulates: clean → embed → UMAP → cluster → representatives.
    """

    def __init__(
        self,
        embedding_settings: EmbeddingSettings,
        clustering_settings: ClusteringSettings,
    ) -> None:
        self._emb_cfg = embedding_settings
        self._cluster_cfg = clustering_settings
        # Cached from last cluster() call — used by merge_similar_clusters()
        self._last_embeddings: np.ndarray | None = None
        self._last_valid_indices: list[int] | None = None

    def cluster(
        self,
        texts: list[str],
        *,
        n_clusters: Optional[int] = None,
    ) -> ClusterResult:
        if len(texts) < 2:
            return ClusterResult(
                clusters=[ClusterInfo(
                    cluster_id=0,
                    comment_indices=list(range(len(texts))),
                    representative_indices=list(range(len(texts))),
                    size=len(texts),
                )],
                labels=[0] * len(texts),
            )

        cfg = self._cluster_cfg
        emb_cfg = self._emb_cfg
        seed = cfg.random_seed

        np.random.seed(seed)
        torch.manual_seed(seed)

        # Resolve device
        device = emb_cfg.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        # Step 1: Clean for embedding
        cleaned = [_clean(t) for t in texts]
        valid_mask = [_is_valid(c) for c in cleaned]
        valid_indices = [i for i, v in enumerate(valid_mask) if v]
        valid_texts = [cleaned[i] for i in valid_indices]

        if len(valid_texts) < 2:
            return ClusterResult(
                clusters=[ClusterInfo(
                    cluster_id=0,
                    comment_indices=list(range(len(texts))),
                    representative_indices=list(range(min(len(texts), cfg.top_k_representatives))),
                    size=len(texts),
                )],
                labels=[0] * len(texts),
            )

        # Step 2: Embed (and cache for merge_similar_clusters)
        embeddings = _embed_texts(
            valid_texts, emb_cfg.model_name, device,
            emb_cfg.batch_size, emb_cfg.max_length,
        )
        self._last_embeddings = embeddings
        self._last_valid_indices = valid_indices

        # Step 3: Cluster
        effective_k = n_clusters or cfg.n_clusters
        if effective_k is not None:
            effective_k = min(effective_k, len(valid_texts))

        labels_arr, actual_k = _reduce_and_cluster(
            embeddings,
            n_clusters=effective_k,
            umap_dim=cfg.umap_n_components,
            umap_neighbors=cfg.umap_n_neighbors,
            umap_min_dist=cfg.umap_min_dist,
            umap_metric=cfg.umap_metric,
            seed=seed,
            k_range=(cfg.k_range_min, cfg.k_range_max),
            min_cluster_size=cfg.min_cluster_size,
        )

        # Step 4: Representatives (indices into valid_texts)
        rep_map = _get_representatives(
            embeddings, labels_arr, valid_texts, cfg.top_k_representatives,
        )

        # Build ClusterInfo list — map back to original indices
        cluster_infos: list[ClusterInfo] = []
        for cid in sorted(set(labels_arr)):
            mask = labels_arr == cid
            # Map valid_texts indices back to original text indices
            comment_original_indices = [valid_indices[i] for i in range(len(valid_texts)) if mask[i]]
            rep_original_indices = [valid_indices[ri] for ri in rep_map.get(int(cid), [])]

            cluster_infos.append(ClusterInfo(
                cluster_id=int(cid),
                comment_indices=comment_original_indices,
                representative_indices=rep_original_indices,
                size=len(comment_original_indices),
            ))

        # Build full labels array (aligned with input texts)
        full_labels = [-1] * len(texts)
        for ci in cluster_infos:
            for idx in ci.comment_indices:
                full_labels[idx] = ci.cluster_id

        # Assign unclustered (invalid) comments to nearest cluster (cluster 0)
        for i in range(len(full_labels)):
            if full_labels[i] == -1:
                full_labels[i] = 0
                if cluster_infos:
                    cluster_infos[0].comment_indices.append(i)
                    cluster_infos[0].size += 1

        logger.info(
            "clustering_complete",
            extra={
                "n_input": len(texts),
                "n_valid": len(valid_texts),
                "n_clusters": len(cluster_infos),
            },
        )

        return ClusterResult(clusters=cluster_infos, labels=full_labels)

    def merge_similar_clusters(
        self,
        cluster_result: ClusterResult,
    ) -> ClusterResult:
        """
        Merge clusters whose centroid cosine similarity exceeds the threshold.
        Uses cached embeddings from the last cluster() call.
        Strict merging: only clusters covering the exact same topic are merged.
        """
        from collections import defaultdict

        cfg = self._cluster_cfg
        threshold = cfg.merge_similarity_threshold

        if len(cluster_result.clusters) < 2:
            return cluster_result

        if self._last_embeddings is None or self._last_valid_indices is None:
            logger.warning("no_cached_embeddings_skipping_merge")
            return cluster_result

        embeddings = self._last_embeddings
        orig_to_emb = {orig: emb_i for emb_i, orig in enumerate(self._last_valid_indices)}

        # --- 1. Compute centroid per cluster ---
        centroids: dict[int, np.ndarray] = {}
        for ci in cluster_result.clusters:
            emb_rows = [orig_to_emb[idx] for idx in ci.comment_indices if idx in orig_to_emb]
            if not emb_rows:
                continue
            c_emb = embeddings[emb_rows]
            centroid = c_emb.mean(axis=0)
            centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
            centroids[ci.cluster_id] = centroid

        if len(centroids) < 2:
            return cluster_result

        # --- 2. Pairwise cosine similarity ---
        cids = sorted(centroids.keys())
        c_matrix = np.stack([centroids[c] for c in cids])
        sim = c_matrix @ c_matrix.T

        # --- 3. Union-Find for transitive merges ---
        parent: dict[int, int] = {c: c for c in cids}
        rank: dict[int, int] = {c: 0 for c in cids}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            if rank[ra] < rank[rb]:
                ra, rb = rb, ra
            parent[rb] = ra
            if rank[ra] == rank[rb]:
                rank[ra] += 1

        cluster_sizes = {ci.cluster_id: ci.size for ci in cluster_result.clusters}
        for i in range(len(cids)):
            for j in range(i + 1, len(cids)):
                if sim[i, j] >= threshold:
                    # Merge smaller into larger (union by size preference)
                    ci_a, ci_b = cids[i], cids[j]
                    if cluster_sizes.get(ci_a, 0) >= cluster_sizes.get(ci_b, 0):
                        union(ci_a, ci_b)
                    else:
                        union(ci_b, ci_a)

        # --- 4. Group clusters by root ---
        groups: dict[int, list[int]] = defaultdict(list)
        for c in cids:
            groups[find(c)].append(c)

        # No merges happened
        if len(groups) == len(cluster_result.clusters):
            return cluster_result

        # --- 5. Build merged clusters with re-selected representatives ---
        cluster_map = {ci.cluster_id: ci for ci in cluster_result.clusters}
        merged: list[ClusterInfo] = []
        new_id = 0

        for _root, members in sorted(groups.items()):
            all_comment_indices: list[int] = []
            for m in members:
                all_comment_indices.extend(cluster_map[m].comment_indices)

            # Re-select representatives by closeness to merged centroid
            indices_with_emb = [
                (idx, orig_to_emb[idx])
                for idx in all_comment_indices
                if idx in orig_to_emb
            ]

            if indices_with_emb:
                orig_idxs, emb_idxs = zip(*indices_with_emb)
                c_emb = embeddings[list(emb_idxs)]
                centroid = c_emb.mean(axis=0)
                centroid = centroid / (np.linalg.norm(centroid) + 1e-9)
                sims = c_emb @ centroid
                top_k = min(cfg.top_k_representatives, len(orig_idxs))
                top_positions = np.argsort(sims)[::-1][:top_k]
                rep_original = [orig_idxs[p] for p in top_positions]
            else:
                rep_original = all_comment_indices[:cfg.top_k_representatives]

            merged.append(ClusterInfo(
                cluster_id=new_id,
                comment_indices=all_comment_indices,
                representative_indices=list(rep_original),
                size=len(all_comment_indices),
            ))
            new_id += 1

        # --- 6. Rebuild labels ---
        new_labels = [0] * len(cluster_result.labels)
        for ci in merged:
            for idx in ci.comment_indices:
                if idx < len(new_labels):
                    new_labels[idx] = ci.cluster_id

        logger.info(
            "clusters_merged_by_similarity",
            extra={
                "before": len(cluster_result.clusters),
                "after": len(merged),
                "threshold": threshold,
            },
        )

        return ClusterResult(clusters=merged, labels=new_labels)
