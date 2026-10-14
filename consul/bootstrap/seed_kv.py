"""
seed_kv.py — One-shot Consul KV initializer.

Seeds ALL initial configuration keys into Consul KV.
Only writes keys that do NOT already exist (idempotent).
Run once by the consul-bootstrap container on first deployment.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import consul

CONSUL_HOST = os.environ.get("CONSUL_HOST", "consul")
CONSUL_PORT = int(os.environ.get("CONSUL_PORT", "8500"))

# ---------------------------------------------------------------------------
# Initial KV structure
# ---------------------------------------------------------------------------
INITIAL_KV: dict[str, dict] = {
    # ── Global ────────────────────────────────────────────────────────────
    "config/global": {
        "_version": 1,
        "version": 1,
        "maintenance_mode": False,
        "logging_level": "INFO",
    },

    # ── AI Service A — Topic Extraction ───────────────────────────────────
    "config/ai-service-a": {
        "_version": 1,
        "thresholds": {
            "sentiment_confidence_min": 0.5,
            "cluster_merge_similarity": 0.85,
            "topic_confidence_min": 0.3,
            "max_clusters": 20,
            "min_cluster_size": 2,
            "top_k_representatives": 15,
        },
        "model": {
            "embedding_model_path": "/app/models/dziri_topic_classifier_v2",
            "sentiment_model_path": "/app/models/ensia-emobert-training",
            "topic_model_path": "/app/models/dziri_topic_classifier_v2",
            "embedding_device": "auto",
            "embedding_batch_size": 64,
            "embedding_max_length": 512,
        },
        "workers": {
            "batch_size": 256,
            "max_batches": 100,
        },
        "runtime": {
            "llm_enabled": True,
            # Ollama container on the ai-platform-network — no external LLM needed
            "llm_api_base_url": "http://lm-service:11434",
            "llm_api_format": "openai",
            "llm_model_name": "gemma3:4b",
            "llm_max_tokens": 100,
            "llm_temperature": 0.1,
            "llm_retry_attempts": 3,
            "llm_retry_delay_seconds": 2.0,
            "fallback_topic_label": "other",
            "fallback_sentiment_label": "neutral",
            "process_only_unclassified": True,
            "umap_n_components": 15,
            "umap_n_neighbors": 30,
            "umap_min_dist": 0.0,
            "umap_metric": "cosine",
            # ── Scheduler (controllable from Dashboard / Consul UI) ─────────
            "schedule_cron": "0 1 * * *",   # 01:00 every day, Africa/Algiers
            "run_on_startup": True,           # also run immediately on container start
            "lookback_days": 1,
        },
        "word_cloud": {
            "max_words": 200,
            "min_frequency": 3,
        },
    },

    # ── AI Service B — Meta Scraper ───────────────────────────────────────
    "config/ai-service-b": {
        "_version": 1,
        "thresholds": {
            "rate_limit_threshold": 0.85,
            "like_skip_threshold": 0.90,
            "max_post_age_h": 24,
            "max_active_posts": 15,
            "scrape_replies": False,
            "reply_max_depth": 5,
        },
        "scheduler": {
            "scraper_interval_h": 4,
            "scraper_stagger_seconds": 30,
            "job_timeout_m": 10,
        },
        "runtime": {
            "semaphore_limit": 10,
            "retry_max_attempts": 3,
            "batch_like_size": 50,
        },
    },

    # ── Reply Service — Group Reply (engagement plane) ────────────────────
    "config/reply-service": {
        "_version": 1,
        "window": {"hours": 24},
        "capacity": {"daily_per_page": 1000, "max_backlog_days": 3},
        "coordination": {"reply_usage_ceiling": 60.0, "reply_min_per_hour": 30},
        "pacing": {"reply_max_per_minute": 20},
        "dispatch": {"tick_seconds": 15, "worker_pool_size": 12},
        "send": {"max_attempts": 5, "claim_timeout_seconds": 120},
    },

    # ── Feedback Service — Label Feedback ─────────────────────────────────
    "config/feedback-service": {
        "_version": 1,
        "topic": {"max_len": 80, "allow_digits_if_not_only": True},
        "read": {"recompute_cache_ttl_seconds": 30, "run_boundary_source": "job_executions"},
        "export": {"schedule_cron": ""},
        "similarity": {"enabled": False},
    },

    # ── Restart-required placeholders ─────────────────────────────────────
    "config/restart-required/ai-service-a": {
        "status": "none",
        "config_version": 0,
    },
    "config/restart-required/ai-service-b": {
        "status": "none",
        "config_version": 0,
    },
    "config/restart-required/reply-service": {
        "status": "none",
        "config_version": 0,
    },
}


def main() -> None:
    print(f"[consul-bootstrap] Connecting to Consul at {CONSUL_HOST}:{CONSUL_PORT}")

    # Wait for Consul to be ready
    c = None
    for attempt in range(30):
        try:
            c = consul.Consul(host=CONSUL_HOST, port=CONSUL_PORT)
            leader = c.status.leader()
            if leader:
                print(f"[consul-bootstrap] Connected — leader: {leader}")
                break
        except Exception as exc:
            print(f"[consul-bootstrap] Waiting for Consul... ({attempt + 1}/30) {exc}")
            time.sleep(2)
    else:
        print("[consul-bootstrap] FATAL: Could not connect to Consul after 30 attempts")
        sys.exit(1)

    # Seed keys (only if not already present)
    seeded = 0
    skipped = 0
    for key, value in INITIAL_KV.items():
        try:
            _, existing = c.kv.get(key)
            if existing is not None:
                print(f"  [skip] {key} (already exists)")
                skipped += 1
                continue

            payload = json.dumps(value, default=str)
            c.kv.put(key, payload)
            print(f"  [seed] {key}")
            seeded += 1
        except Exception as exc:
            print(f"  [ERROR] {key}: {exc}")
            sys.exit(1)

    print(f"[consul-bootstrap] Done: {seeded} seeded, {skipped} skipped")


if __name__ == "__main__":
    main()
