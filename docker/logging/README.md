# AI Platform Logging Stack

This directory contains the runtime configuration mounted by `docker-compose.platform.yml`.

## Flow

1. Services write one structured JSON log line per event to `/logs/{service}.jsonl`.
2. Promtail tails `/logs/*.jsonl` and sends logs to Loki.
3. Loki stores logs for 31 days.
4. Grafana provisions the Loki datasource and the `AI Platform Observability` dashboard.

## Label Strategy

Promtail only promotes stable fields to Loki labels:

- `job`
- `service`
- `level`
- `logger`

Fields such as `correlation_id`, `event`, `job_id`, `comment_id`, `post_id`, and
`source_id` remain inside the JSON log body. This keeps Loki cardinality under
control while still allowing full filtering in Grafana with `| json`.

## Useful Queries

All errors:

```logql
{job="ai-platform", level=~"ERROR|CRITICAL"} | json
```

Single request or pipeline run:

```logql
{job="ai-platform"} | json | correlation_id="paste-id-here"
```

AI Service A pipeline steps:

```logql
{job="ai-platform", service="ai-service-a"} | json | event=~".*pipeline.*|.*cluster.*|.*sentiment.*|.*llm.*|.*word_cloud.*"
```

AI Service B scraper phases:

```logql
{job="ai-platform", service="ai-service-b"} | json | event=~"pipeline.*|discovery.*|comment_engine.*|like_sync.*|persistence.*|rate_guard.*|recovery.*"
```
