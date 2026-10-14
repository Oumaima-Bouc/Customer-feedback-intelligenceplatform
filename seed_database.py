"""
Seed script for BehaviorIQ frontend testing.
Inserts sample data into the past 7 days so charts and tables render properly.
"""
import os
import random
from datetime import datetime, timedelta, timezone

import psycopg2

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("POSTGRES_DB", os.environ.get("DB_NAME", "customer_anticipation_db"))
DB_USER = os.environ.get("POSTGRES_USER", os.environ.get("DB_USER", "scrapper_user"))
DB_PASSWORD = os.environ.get("POSTGRES_PASSWORD", os.environ.get("DB_PASSWORD", ""))

TOPICS = ["Service Quality", "Pricing", "Network Coverage", "Customer Support", "Billing"]
SENTIMENTS = ["positive", "neutral", "negative"]
SOURCES = ["facebook", "instagram"]

COMMENTS_POOL = [
    ("Great service today, very helpful staff!", "positive", "Service Quality"),
    ("The prices are way too high compared to competitors.", "negative", "Pricing"),
    ("Network was down for 3 hours yesterday, unacceptable.", "negative", "Network Coverage"),
    ("Customer support resolved my issue quickly.", "positive", "Customer Support"),
    ("Billing statement was confusing and had extra charges.", "negative", "Billing"),
    ("Decent experience, nothing special.", "neutral", "Service Quality"),
    ("Coverage in rural areas needs improvement.", "negative", "Network Coverage"),
    ("Fair pricing for the bundle I got.", "positive", "Pricing"),
    ("Support team was polite but slow to respond.", "neutral", "Customer Support"),
    ("Love the new mobile app design!", "positive", "Service Quality"),
    ("Invoice arrived late again.", "negative", "Billing"),
    ("Data speed is amazing in the city center.", "positive", "Network Coverage"),
    ("Hidden fees are frustrating.", "negative", "Pricing"),
    ("Agent was knowledgeable and fixed everything.", "positive", "Customer Support"),
    ("Average service, met my basic needs.", "neutral", "Service Quality"),
    ("Frequent disconnections in my area.", "negative", "Network Coverage"),
    ("Promotional discount was applied correctly.", "positive", "Pricing"),
    ("Had to wait 20 minutes on hold.", "negative", "Customer Support"),
    ("Bill was accurate this month, thank you.", "positive", "Billing"),
    ("App crashes when I try to pay.", "negative", "Service Quality"),
]

WORDS = [
    ("service", 45, 60.0, 25.0, 15.0, "discovered", None),
    ("price", 38, 30.0, 20.0, 50.0, "discovered", None),
    ("network", 32, 40.0, 30.0, 30.0, "discovered", None),
    ("support", 28, 55.0, 25.0, 20.0, "discovered", None),
    ("billing", 25, 35.0, 30.0, 35.0, "discovered", None),
    ("coverage", 22, 25.0, 35.0, 40.0, "discovered", None),
    ("quality", 20, 70.0, 20.0, 10.0, "discovered", None),
    ("speed", 18, 65.0, 20.0, 15.0, "discovered", None),
    ("app", 15, 40.0, 30.0, 30.0, "discovered", None),
    ("discount", 12, 80.0, 15.0, 5.0, "discovered", None),
    ("outage", 10, 5.0, 15.0, 80.0, "discovered", None),
    ("friendly", 8, 90.0, 10.0, 0.0, "curated", "positive"),
    ("slow", 7, 5.0, 20.0, 75.0, "curated", "negative"),
    ("excellent", 6, 95.0, 5.0, 0.0, "curated", "positive"),
    ("frustrating", 5, 0.0, 10.0, 90.0, "curated", "negative"),
]


def _conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


def seed_sources(cur):
    cur.execute("DELETE FROM scraping_sources WHERE external_id LIKE 'seed_%';")
    cur.execute(
        """
        INSERT INTO scraping_sources (platform, external_id, name, is_active, health_status, total_comments_scraped)
        VALUES
            ('facebook', 'seed_fb_001', 'Algérie Télécom', TRUE, 'healthy', 60),
            ('instagram', 'seed_ig_001', 'Algérie Télécom IG', TRUE, 'healthy', 40)
        ON CONFLICT (platform, external_id) DO UPDATE SET
            is_active = TRUE,
            health_status = 'healthy',
            total_comments_scraped = EXCLUDED.total_comments_scraped;
        """
    )


def seed_posts(cur, source_ids):
    cur.execute("DELETE FROM active_posts WHERE post_id LIKE 'seed_post_%';")
    posts = []
    for i in range(4):
        sid = source_ids[i % len(source_ids)]
        pid = f"seed_post_{i+1}"
        posts.append((pid, datetime.now(timezone.utc) - timedelta(days=random.randint(1, 6)), sid))
    cur.executemany(
        "INSERT INTO active_posts (post_id, created_at, status, source_id) VALUES (%s, %s, 'active', %s) ON CONFLICT DO NOTHING;",
        posts
    )


def seed_comments(cur, source_ids):
    cur.execute("DELETE FROM comments WHERE comment_id LIKE 'seed_comment_%';")
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(100):
        text, sentiment, topic = random.choice(COMMENTS_POOL)
        source = random.choice(SOURCES)
        source_id = source_ids[0] if source == "facebook" else source_ids[1]
        created = now - timedelta(days=random.randint(0, 6), hours=random.randint(0, 23))
        rows.append((
            f"seed_comment_{i+1}",
            f"seed_post_{(i % 4) + 1}",
            text,
            random.randint(0, 50),
            created,
            random.choice([True, False]),
            topic,
            sentiment,
            source,
            now,
        ))
    cur.executemany(
        """
        INSERT INTO comments (comment_id, post_id, text_content, like_count, created_at, is_reply, topic, sentiment, source, scraped_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (comment_id) DO NOTHING;
        """,
        rows
    )


def seed_topic_daily_tracking(cur):
    cur.execute("DELETE FROM topic_daily_tracking WHERE run_date >= CURRENT_DATE - INTERVAL '10 days';")
    today = datetime.now(timezone.utc).date()
    rows = []
    for day_offset in range(7):
        run_date = today - timedelta(days=day_offset)
        for topic in TOPICS:
            count = random.randint(5, 25)
            pos = round(random.uniform(20, 70), 2)
            neg = round(random.uniform(10, 40), 2)
            neu = round(100 - pos - neg, 2)
            rows.append((run_date, topic, count, pos, neu, neg))
    cur.executemany(
        """
        INSERT INTO topic_daily_tracking (run_date, topic, comment_count, positive_pct, neutral_pct, negative_pct)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_date, topic) DO UPDATE SET
            comment_count = EXCLUDED.comment_count,
            positive_pct = EXCLUDED.positive_pct,
            neutral_pct = EXCLUDED.neutral_pct,
            negative_pct = EXCLUDED.negative_pct;
        """,
        rows
    )


def seed_word_cloud(cur):
    cur.execute("DELETE FROM word_cloud_snapshot WHERE word IN (SELECT word FROM word_cloud_snapshot LIMIT 1000);")
    # safer: truncate
    cur.execute("TRUNCATE TABLE word_cloud_snapshot;")
    cur.executemany(
        """
        INSERT INTO word_cloud_snapshot (word, frequency, positive_pct, neutral_pct, negative_pct, source, category)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (word) DO UPDATE SET
            frequency = EXCLUDED.frequency,
            positive_pct = EXCLUDED.positive_pct,
            neutral_pct = EXCLUDED.neutral_pct,
            negative_pct = EXCLUDED.negative_pct,
            source = EXCLUDED.source,
            category = EXCLUDED.category;
        """,
        WORDS
    )


def seed_job_executions(cur):
    cur.execute("DELETE FROM job_executions WHERE job_name = 'ml_pipeline' AND metadata->>'seed' = 'true';")
    now = datetime.now(timezone.utc)
    cur.executemany(
        """
        INSERT INTO job_executions (job_name, service, status, started_at, finished_at, duration_ms, records_in, records_out, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        [
            ("ml_pipeline", "ai-service-a", "completed", now - timedelta(days=1), now - timedelta(days=1) + timedelta(minutes=5), 300000, 85, 85, '{"seed": "true"}'),
            ("ml_pipeline", "ai-service-a", "completed", now - timedelta(days=2), now - timedelta(days=2) + timedelta(minutes=4), 240000, 72, 72, '{"seed": "true"}'),
        ]
    )


def main():
    print("Connecting to database...")
    conn = _conn()
    cur = conn.cursor()
    try:
        print("Seeding scraping_sources...")
        seed_sources(cur)
        cur.execute("SELECT id, platform FROM scraping_sources WHERE external_id LIKE 'seed_%';")
        source_rows = cur.fetchall()
        source_ids = [r[0] for r in source_rows]
        print(f"  -> sources: {source_ids}")

        print("Seeding active_posts...")
        seed_posts(cur, source_ids)

        print("Seeding comments...")
        seed_comments(cur, source_ids)

        print("Seeding topic_daily_tracking...")
        seed_topic_daily_tracking(cur)

        print("Seeding word_cloud_snapshot...")
        seed_word_cloud(cur)

        print("Seeding job_executions...")
        seed_job_executions(cur)

        conn.commit()
        print("Done! Database seeded with 7 days of sample data.")
    except Exception as exc:
        conn.rollback()
        print(f"Error: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
