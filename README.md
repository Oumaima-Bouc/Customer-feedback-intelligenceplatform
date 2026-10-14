<p align="center">
  <img src="services/behavioriq/public/assets/images/algerie-telecom-logo.svg" alt="Algérie Télécom" width="340"/>
</p>

<h1 align="center">Customer Feedback Intelligence Platform</h1>

<p align="center">
  AI-powered social-media feedback analysis for Algérie Télécom — scrape, cluster, label, and act on customer comments.
</p>

---

## What it is

The platform scrapes public **Facebook** and **Instagram** comments from Algérie Télécom's pages, then uses AI to:

- **Cluster** comments into topics (multilingual embeddings + density clustering for Arabic, Algerian Darija, and French),
- **Label** each topic and classify **sentiment** (positive / neutral / negative),
- surface everything in a **dashboard** where the CX team can read mentions, see topic/sentiment trends, **reply in bulk**, and **correct** any AI label (human‑in‑the‑loop).

A single **“Run Now”** button (or a daily schedule) runs the whole chain — scrape → analyse → refresh.

## Architecture

A microservices stack on a private Docker network, coordinated through PostgreSQL and dynamic Consul config.

| Service | Port | Role |
|---|---|---|
| `behavioriq` (frontend) | 4028 | Next.js / React dashboard |
| `dashboard_backend` | 3000 | FastAPI API gateway (auth, reads, orchestration) |
| `ai-service-a` | 8080 | ML pipeline: embed → cluster (UMAP+HDBSCAN) → label (LLM) → sentiment |
| `ai-service-b` | 8081 | Meta Graph scraper |
| `lm-service` | 11434 | Ollama serving the labeling LLM (`gemma3:4b`) |
| `reply-service` | 8083 | Publishes analyst replies to Meta |
| `feedback-service` | 8084 | Human label-correction write path |
| `restart-orchestrator` | 8082 | Rolling restarts on config change |
| `postgres-db` / `consul` | 5432 / 8500 | System of record / dynamic config |
| `loki` + `promtail` + `grafana` | 3100 / 4000 | Centralised logs & dashboards |

**Stack:** Python (FastAPI, SQLAlchemy, APScheduler), PostgreSQL, Consul, Ollama, sentence‑transformers + UMAP + HDBSCAN, Next.js 15 / React 19, Docker Compose.

## Run it

**Prerequisites:** Docker + Docker Compose, ~10 GB RAM available to the Docker VM, and the model files placed on disk (mounted at runtime, not committed).

```bash
# 1. Provide configuration & secrets (not committed):
#    create .env.platform  (shared: POSTGRES_*, JWT_SECRET, META_ACCESS_TOKEN, internal secrets, ...)
#    create .env           (ai-service-a model/pipeline tuning)

# 2. Place the runtime models on disk (mounted by ai-service-a):
#    models/multilingual-e5-base/      (embedder)
#    ensia-emobert-training/           (sentiment model)
#    dziri_topic_classifier_v2/        (fallback topic classifier)

# 3. Build & start the whole platform
docker compose -f docker-compose.platform.yml --env-file .env.platform up -d --build

# 4. Apply database migrations (in order)
for f in migrations/topic_extraction/0*.sql; do
  docker exec -i postgres-db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$f"
done

# 5. Pull the labeling LLM once (persists in the lm-models volume)
docker exec lm-service ollama pull gemma3:4b

# 6. Frontend dependencies (gitignored node_modules)
cd services/behavioriq && npm install && cd ../..
```

Then open the dashboard at **http://localhost:4028** (API at **http://localhost:3000/api**, Grafana at **http://localhost:4000**).

> The vendored Linux `hdbscan` wheel in `wheels/` lets the `ai-service-a` image build offline. Runtime config (schedules, thresholds, models) is hot‑reloadable via Consul / the in‑app Settings page.

## Repository layout

```
docker-compose.platform.yml   # full platform definition
services/                     # all services (frontend + 6 backend services)
shared/                       # shared libs (Consul config, structured logging, job tracker)
migrations/                   # ordered SQL migrations
consul/                       # dynamic-config bootstrap/seed
docker/                       # logging stack (Loki / Promtail / Grafana) config
wheels/                       # vendored Linux hdbscan wheel for offline build
words.yaml · seed_database.py # word-cloud dictionary · DB seeder
```

## Notes

- **Models** (`models/`, `ensia-emobert-training/`, `dziri_topic_classifier_v2/`) and `node_modules/` are gitignored; conntact me to get them.
- The pipeline is **idempotent** (only new/unclassified comments are processed) and human corrections are protected from re‑labeling.
