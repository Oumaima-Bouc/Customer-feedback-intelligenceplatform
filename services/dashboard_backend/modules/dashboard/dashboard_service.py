from __future__ import annotations
import re
import time
from typing import Any, Dict
import psycopg2.extras
from config.database import get_conn
from infrastructure.consul.consul_client import consul_client
from shared.utils.date_helper import to_iso, utc_now_iso
from datetime import datetime, timezone, timedelta

# ── Live-recompute cache (Label Feedback Pass 2, R7/R14) ──────────────────────
# Aggregate dashboards recompute live from `comments` so corrections show on visit.
# Results are cached per (endpoint, params, feedback_version) with a short TTL: a
# correction bumps Consul `feedback/version`, so the first visit after any correction
# recomputes once and later visits hit cache. `label_feedback` is never read here.
_CACHE_TTL_SECONDS = 30
_recompute_cache: Dict[tuple, tuple] = {}

# "Last successful run" scoping: the comments table holds the latest run's data;
# superseded runs are flagged `archived` (migration 012). Every read filters to the
# live (non-archived) set so all frontend data reflects exactly the last run and is
# never empty between runs.
LIVE = "NOT archived"


def invalidate_cache() -> None:
    """Drop all cached aggregates so the next read recomputes (used after a manual run)."""
    _recompute_cache.clear()


def _feedback_version() -> int:
    try:
        return consul_client.get_int("feedback/version", 0)
    except Exception:
        return 0


def _cached(name: str, params: tuple, compute):
    key = (name, params, _feedback_version())
    now = time.time()
    hit = _recompute_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = compute()
    _recompute_cache[key] = (now + _CACHE_TTL_SECONDS, value)
    if len(_recompute_cache) > 128:
        for k, (exp, _) in list(_recompute_cache.items()):
            if exp <= now:
                _recompute_cache.pop(k, None)
    return value


def get_stats() -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.cursor(); stats = {}
        cur.execute(f"SELECT COUNT(*) FROM comments WHERE {LIVE}"); stats["total_comments"] = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM comments WHERE topic IS NOT NULL AND {LIVE}"); stats["enriched_comments"] = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM comments WHERE topic IS NULL AND {LIVE}"); stats["pending_comments"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM active_posts WHERE status = 'active'"); stats["active_posts"] = cur.fetchone()[0]
        cur.execute("SELECT status, last_success_at FROM schedule_state WHERE job_id = 'meta_page_scraper'"); row = cur.fetchone()
        if row: stats["scraper_status"] = row[0]; stats["last_success"] = to_iso(row[1])
    return stats


# ── Word cloud (computed live from the last run's comment text) ───────────────
# `word_cloud_snapshot` is only populated by the (currently dormant) enrichment
# producer, so the cloud is built live here: tokenize the live comments, count
# document frequency, derive per-word sentiment, honour the curated/hidden lists,
# and apply the Consul-stored `min_frequency` / `max_words` settings.
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)  # letter runs ≥3, no digits/punct
_STOPWORDS = {
    # French
    "les", "des", "une", "que", "qui", "pas", "pour", "dans", "sur", "avec", "vous",
    "nous", "est", "sont", "mais", "plus", "tout", "tous", "cette", "ces", "son", "ses",
    "par", "aux", "ont", "été", "être", "fait", "comme", "leur", "elle", "ils", "elles",
    "votre", "notre", "même", "aussi", "donc", "car", "très", "bien", "non", "oui", "moi",
    "toi", "lui", "sans", "deux", "alors", "encore", "depuis", "chez", "entre",
    # English
    "the", "and", "for", "you", "are", "with", "this", "that", "not", "but", "your",
    "have", "from", "they", "was", "can", "all", "will", "what", "when", "how", "why",
    # Arabic
    "في", "من", "على", "إلى", "عن", "مع", "هذا", "هذه", "ذلك", "التي", "الذي", "ما",
    "لا", "أو", "ثم", "قد", "كان", "هو", "هي", "نحن", "انا", "انت", "هم", "كل", "بعض",
    "غير", "عند", "لكن", "حتى", "اذا", "لم", "لن", "يا", "اين", "كيف", "متى", "كما",
    "كانت", "هناك", "الان", "بعد", "قبل", "حول", "الى", "علي", "انه", "اني", "فيها",
}


def _wc_settings() -> tuple[int, int]:
    """(max_words, min_frequency) from the Consul word-cloud settings (with defaults)."""
    try:
        cfg = consul_client.get("config/ai-service-a") or {}
        wc = cfg.get("word_cloud", {}) if isinstance(cfg, dict) else {}
        return int(wc.get("max_words", 200)), int(wc.get("min_frequency", 3))
    except Exception:
        return 200, 3


def get_word_cloud(min_frequency: int = 0, source: str = "") -> Dict[str, Any]:
    max_words, cfg_min = _wc_settings()
    min_freq = max(int(min_frequency or 0), cfg_min, 1)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT word, frequency, positive_pct, neutral_pct, negative_pct, category FROM word_cloud_snapshot WHERE source = 'curated'")
        curated = cur.fetchall()
        cur.execute("SELECT lower(word) FROM word_cloud_snapshot WHERE source = 'discovered' AND frequency = 0")
        hidden = {r[0] for r in cur.fetchall()}
        q = f"SELECT text_content, sentiment FROM comments WHERE text_content IS NOT NULL AND {LIVE}"
        p: list = []
        if source in ("facebook", "instagram", "twitter", "tiktok"):
            q += " AND source = %s"; p.append(source)
        cur.execute(q, p); rows = cur.fetchall()

    # word → [doc_count, pos, neu, neg]  (counted once per comment = document frequency)
    agg: Dict[str, list] = {}
    for text, sent in rows:
        if not text:
            continue
        for tok in set(_WORD_RE.findall(text.lower())):
            if tok in _STOPWORDS:
                continue
            a = agg.get(tok)
            if a is None:
                a = agg[tok] = [0, 0, 0, 0]
            a[0] += 1
            if sent == "positive": a[1] += 1
            elif sent == "neutral": a[2] += 1
            elif sent == "negative": a[3] += 1

    words: list = []
    curated_keys = set()
    for w, freq, pos, neu, neg, cat in curated:
        curated_keys.add(w.lower())
        words.append({"word": w, "frequency": freq, "positive_pct": float(pos or 0), "neutral_pct": float(neu or 0), "negative_pct": float(neg or 0), "source": "curated", "category": cat or "manual"})
    for w, (c, pos, neu, neg) in agg.items():
        if c < min_freq or w in hidden or w in curated_keys:
            continue
        words.append({"word": w, "frequency": c, "positive_pct": round(pos / c * 100, 2), "neutral_pct": round(neu / c * 100, 2), "negative_pct": round(neg / c * 100, 2), "source": "discovered", "category": "auto"})

    words.sort(key=lambda x: x["frequency"], reverse=True)
    words = words[:max_words]
    return {"updated_at": utc_now_iso(), "total_words": len(words), "words": words}


def list_jobs(service: str = "", job_name: str = "", status: str = "", limit: int = 50) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        q = "SELECT id, job_name, service, status, started_at, finished_at, duration_ms, records_in, records_out, error_count, error_message, metadata FROM job_executions WHERE 1=1"; p=[]
        if service: q += " AND service = %s"; p.append(service)
        if job_name: q += " AND job_name = %s"; p.append(job_name)
        if status in ("running","completed","failed","partial"): q += " AND status = %s"; p.append(status)
        q += " ORDER BY started_at DESC LIMIT %s"; p.append(limit); cur.execute(q,p); rows = cur.fetchall()
    return {"total": len(rows), "executions": [{"id": r["id"], "job_name": r["job_name"], "service": r["service"], "status": r["status"], "started_at": to_iso(r["started_at"]), "finished_at": to_iso(r["finished_at"]), "duration_ms": r["duration_ms"], "records_in": r["records_in"], "records_out": r["records_out"], "error_count": r["error_count"], "error_message": r["error_message"], "metadata": r["metadata"] or {}} for r in rows]}

def get_job_logs(execution_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor); cur.execute("SELECT id, logged_at, level, event, message, details FROM job_log_entries WHERE execution_id = %s ORDER BY logged_at ASC", (execution_id,)); rows = cur.fetchall()
    return {"execution_id": execution_id, "total_logs": len(rows), "logs": [{"id": r["id"], "logged_at": to_iso(r["logged_at"]), "level": r["level"], "event": r["event"], "message": r["message"], "details": r["details"] or {}} for r in rows]}

def get_overview() -> Dict[str, Any]:
    return _cached("overview", (), _compute_overview)


def _compute_overview() -> Dict[str, Any]:
    """KPI strip for the dashboard.
      - daily_treatment.count   = comments processed in the LAST run (live non-archived set)
      - daily_treatment.change_pct = % change in processed count vs the PREVIOUS run
      - overall_sentiment.positive_pct = positive% over the last run's comments
      - overall_sentiment.change_pct   = RELATIVE % change of positive% vs the previous run
                                         (15% → 30% = +100%); can be negative.
      - total_comments_scraped  = cumulative system total (no delta).
    Previous-run figures come from topic_daily_tracking, which snapshots per-run (run_date)
    comment counts + sentiment — the only record of prior runs."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT started_at FROM job_executions WHERE job_name = 'ml_pipeline' AND status = 'completed' ORDER BY started_at DESC LIMIT 1"); latest = cur.fetchone()
        # THIS run — live (reflects corrections).
        cur.execute(f"SELECT COUNT(*) FROM comments WHERE topic IS NOT NULL AND {LIVE}"); this_count = cur.fetchone()[0]
        cur.execute(f"SELECT sentiment, COUNT(*) FROM comments WHERE topic IS NOT NULL AND sentiment IS NOT NULL AND {LIVE} GROUP BY sentiment")
        sent = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM comments"); total_comments = cur.fetchone()[0]
        # PREVIOUS run — the 2nd-most-recent run_date in the per-run history.
        cur.execute(
            "SELECT run_date, SUM(comment_count) AS cnt, "
            "CASE WHEN SUM(comment_count) > 0 THEN SUM(comment_count * positive_pct) / SUM(comment_count) ELSE 0 END AS pos "
            "FROM topic_daily_tracking GROUP BY run_date ORDER BY run_date DESC LIMIT 2"
        )
        runs = cur.fetchall()
    tot = sum(sent.values())
    pct = lambda k: round(sent.get(k, 0) / tot * 100, 1) if tot else 0.0
    this_pos = pct("positive")
    prev_count = int(runs[1][1]) if len(runs) > 1 and runs[1][1] else 0
    prev_pos = float(runs[1][2]) if len(runs) > 1 and runs[1][2] else 0.0
    treat_change = round((this_count - prev_count) / prev_count * 100, 1) if prev_count > 0 else 0.0
    pos_change = round((this_pos - prev_pos) / prev_pos * 100, 1) if prev_pos > 0 else 0.0
    return {
        "latest_run_date": to_iso(latest[0]) if latest else None,
        "daily_treatment": {"count": this_count, "previous_count": prev_count, "change_pct": treat_change, "change_direction": "down" if treat_change < 0 else "up"},
        "total_comments_scraped": total_comments,
        "overall_sentiment": {"positive_pct": this_pos, "neutral_pct": pct("neutral"), "negative_pct": pct("negative"), "change_pct": pos_change, "change_direction": "down" if pos_change < 0 else "up"},
    }

def get_sources_chart() -> Dict[str, Any]:
    # Per-page counts for the last run: the page (scraping_sources) with the most
    # comments is the "top source", shown with its name + platform logo. Falls back to
    # the platform string when a comment's post can't be resolved to a tracked page.
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(NULLIF(btrim(ss.name), ''), c.source) AS name, "
            "       COALESCE(ss.platform, c.source) AS platform, COUNT(*) AS cnt "
            "FROM comments c "
            "LEFT JOIN active_posts ap ON ap.post_id = c.post_id "
            "LEFT JOIN scraping_sources ss ON ss.id = ap.source_id "
            f"WHERE {LIVE} "
            "GROUP BY COALESCE(NULLIF(btrim(ss.name), ''), c.source), COALESCE(ss.platform, c.source) "
            "ORDER BY cnt DESC"
        )
        rows = cur.fetchall()
    total = sum(r[2] for r in rows) if rows else 0
    return {
        "run_date": utc_now_iso(),
        "total": total,
        "sources": [
            {"name": r[0] or "Unknown", "platform": (r[1] or "unknown"), "source": (r[1] or "unknown"), "count": r[2], "pct": round(r[2] / total * 100, 1) if total else 0.0}
            for r in rows
        ],
    }

def get_topics_trend(days: int = 7) -> Dict[str, Any]:
    return _cached("topics_trend", (days,), lambda: _compute_topics_trend(days))


def _compute_topics_trend(days: int = 7) -> Dict[str, Any]:
    # Anchor the window to the last run's most recent comment day (not "today"), so a
    # run that landed weeks ago still shows its data; days with no run fall to the zero
    # baseline. Corrections appear on each comment's own day (live over comments).
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT max(created_at)::date FROM comments WHERE topic IS NOT NULL AND {LIVE}")
        row = cur.fetchone()
        end_date = (row[0] if row and row[0] else datetime.now(timezone.utc).date())
        dates = [(end_date - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
        cur.execute(
            f"SELECT created_at::date AS d, lower(btrim(topic)) AS k, COUNT(*) AS cnt "
            f"FROM comments WHERE topic IS NOT NULL AND {LIVE} "
            "AND created_at::date >= %s::date AND created_at::date <= %s::date "
            "GROUP BY d, k ORDER BY d",
            (dates[0], dates[-1]),
        )
        count_rows = cur.fetchall()
        cur.execute(
            f"SELECT lower(btrim(topic)) AS k, sentiment, COUNT(*) "
            f"FROM comments WHERE topic IS NOT NULL AND sentiment IS NOT NULL AND {LIVE} "
            "AND created_at::date >= %s::date AND created_at::date <= %s::date "
            "GROUP BY k, sentiment",
            (dates[0], dates[-1]),
        )
        sent_rows = cur.fetchall()
        cur.execute("SELECT topic_key, display_label FROM topics")
        disp = {r[0]: r[1] for r in cur.fetchall()}

    series: Dict[str, Dict[str, int]] = {}
    totals: Dict[str, int] = {}
    for d, k, cnt in count_rows:
        series.setdefault(k, {})[str(d)] = cnt
        totals[k] = totals.get(k, 0) + cnt
    sent: Dict[str, Dict[str, int]] = {}
    for k, s, cnt in sent_rows:
        sent.setdefault(k, {})[s] = cnt
    topics = []
    for k in sorted(totals, key=lambda x: -totals[x]):
        st = sent.get(k, {})
        stot = sum(st.values()) or 0
        topics.append({
            "name": disp.get(k, k),
            "data": [series[k].get(d, 0) for d in dates],
            "sentiment": {
                "positive_pct": round(st.get("positive", 0) / stot * 100, 1) if stot else 0.0,
                "neutral_pct": round(st.get("neutral", 0) / stot * 100, 1) if stot else 0.0,
                "negative_pct": round(st.get("negative", 0) / stot * 100, 1) if stot else 0.0,
            },
        })
    return {"dates": dates, "topics": topics}

def get_topic_cards() -> Dict[str, Any]:
    return _cached("topic_cards", (), _compute_topic_cards)


def _compute_topic_cards() -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.cursor()
        # Live per-(normalized)-topic counts + sentiment over the last run, joined to the
        # registry for the display label and so zero-count topics still appear (R10).
        # Driven by the comments of the latest run: only topics that actually have
        # comments appear (zero-count registry topics are intentionally excluded). The
        # registry is joined only to resolve the canonical display label.
        cur.execute(
            "WITH agg AS ("
            "  SELECT lower(btrim(topic)) AS k, MAX(btrim(topic)) AS sample, COUNT(*) AS cnt,"
            "         COUNT(*) FILTER (WHERE sentiment='positive') AS pos,"
            "         COUNT(*) FILTER (WHERE sentiment='neutral')  AS neu,"
            "         COUNT(*) FILTER (WHERE sentiment='negative') AS neg"
            f"  FROM comments WHERE topic IS NOT NULL AND {LIVE}"
            "  GROUP BY lower(btrim(topic))"
            ") "
            # Label = registry display if registered, else a real-cased comment value
            # (NOT the lowercased key) so the topics page can look comments back up.
            "SELECT a.k, COALESCE(t.display_label, a.sample), a.cnt, a.pos, a.neu, a.neg "
            "FROM agg a LEFT JOIN topics t ON t.topic_key = a.k "
            "ORDER BY a.cnt DESC"
        )
        rows = cur.fetchall()
        cur.execute(f"SELECT lower(btrim(topic)) AS k, source, COUNT(*) FROM comments WHERE topic IS NOT NULL AND {LIVE} GROUP BY k, source")
        source_map: Dict[str, list] = {}
        for k, src, cnt in cur.fetchall():
            source_map.setdefault(k, []).append({"source": src or "unknown", "count": cnt})
        prev = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        result = []
        for topic_key, label, cnt, pos, neu, neg in rows:
            previews = []
            if cnt > 0:
                prev.execute(
                    "SELECT comment_id, text_content, like_count, sentiment, created_at FROM comments "
                    f"WHERE topic IS NOT NULL AND {LIVE} AND lower(btrim(topic)) = %s "
                    "ORDER BY like_count DESC LIMIT 3",
                    (topic_key,),
                )
                previews = [{"comment_id": p["comment_id"], "text_content": p["text_content"], "like_count": p["like_count"], "sentiment": p["sentiment"], "created_at": to_iso(p["created_at"])} for p in prev.fetchall()]
            tot = pos + neu + neg
            result.append({
                "topic": label,
                "comment_count": cnt,
                "sentiment": {
                    "positive_pct": round(pos / tot * 100, 2) if tot else 0.0,
                    "neutral_pct": round(neu / tot * 100, 2) if tot else 0.0,
                    "negative_pct": round(neg / tot * 100, 2) if tot else 0.0,
                },
                "sources": source_map.get(topic_key, []),
                "preview_comments": previews,
                "has_more_comments": cnt > 3,
            })
    return {"topics": result}
