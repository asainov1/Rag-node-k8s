# RAG Gateway on Kubernetes

A retrieval gateway for product search, built as a staging proof on synthetic data: FastAPI in front of
Qdrant, a Redis result cache, Prometheus latency histograms with a Grafana dashboard, and an Argo
Rollouts canary that pauses on p95 latency.

## What is inside

| Area | What it does | Where |
|---|---|---|
| API | `POST /rag` — vector search with optional filters (`lower_cat`, `brand`, `color`) and optional LLM rerank; `POST /answer` — answer grounded in the top hits, with citations; `POST /ingest`, `POST /ingest_batch` — chunk, embed and upsert | `app/main.py` |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` via fastembed (384-dim), falls back to `bge-small-en-v1.5` | `app/main.py` |
| Vector store | Qdrant, HNSW `m=32`, `ef_construct=200` | `scripts/qdrant_bootstrap.py` |
| Cache | Redis cache of search results, keyed by normalised query, `k`, rerank flag and filters | `app/main.py` |
| Resilience | retries with exponential backoff on Qdrant (tenacity), an in-memory circuit breaker that serves cached results while Qdrant is failing, request-size limit, per-IP rate limit in Redis, optional API key | `app/main.py`, `app/config.py` |
| Metrics | `http_server_request_duration_seconds{method,route,status}` histogram, cache hit/miss counters, Qdrant error counter, in-flight gauge | `app/metrics.py` |
| Dashboards | Grafana panels for p95/p99 latency and cache hit rate | `dashboards/` |
| Deploy | Argo Rollouts canary `20% → pause → p95 analysis → 60% → pause`, `AnalysisTemplate` querying Prometheus | `k8s/` |
| CI | GitHub Actions builds the image and pushes it to GHCR | `ci/github-actions.yml` |
| Ops | runbook and an incident write-up template | `ops/`, `postmortem/` |

## Quick start (local, Docker Compose)

```bash
# docker/gateway.env is git-ignored; create it with at least:
#   API_KEY=dev-secret-choose-your-own      (the ingest script sends this key)
#   OPENAI_API_KEY=...                      (optional: enables rerank and LLM answers in /answer)
docker compose -f docker/docker-compose.yml up -d --build

# load products from a CSV with parent_cat, lower_cat, product_description, brand, color
# (the dataset itself is not in the repository)
python3 app/ingest_products_batch.py --csv products.csv --max_rows 10000

# warm up with traffic to fill the metrics
hey -z 30s -c 20 -m POST -H 'Content-Type: application/json' \
    -H 'X-API-Key: dev-secret-choose-your-own' \
    -d '{"q":"running shoes","k":20}' http://localhost:8080/rag
```

Grafana: `http://localhost:3000` → add the Prometheus data source `http://prometheus:9090` → import
`dashboards/grafana-latency-dashboard.json`.

Useful queries:

```promql
# p95 latency
histogram_quantile(0.95, sum(rate(http_server_request_duration_seconds_bucket[5m])) by (le))
# cache hit rate
rate(reranker_cache_hit_total[5m]) / (rate(reranker_cache_hit_total[5m]) + rate(reranker_cache_miss_total[5m]))
```

## Design choices

- **Cache in front of search, not only in front of the reranker.** A repeated query skips embedding,
  search and the LLM call. Cost: results can be up to `CACHE_TTL` seconds stale after an ingest.
- **Circuit breaker serves the cache.** When Qdrant fails, the gateway stops calling it for 5 s and
  answers from Redis where it can, instead of piling up timeouts. Cost: the breaker state is per pod,
  so pods trip independently.
- **Canary gated on p95, not on error rate.** The main risk of a new image here is latency (model and
  index changes), so the analysis watches p95 against a 2 s threshold.

## Known gaps

This is a staging proof, and these parts are not finished:

- `scripts/qdrant_bootstrap.py` creates 768-dim synthetic vectors, while the gateway embeds queries
  into 384 dims. Use the ingest scripts for real searches; the bootstrap only shows the HNSW settings.
- `k8s/hpa.yaml` targets a `Deployment`, but the workload is an Argo `Rollout`; the HPA's
  `scaleTargetRef` must point at the Rollout.
- `helm/` holds `Chart.yaml` and values only; there are no templates yet.
- Tracing is not wired: the OpenTelemetry collector config and env vars exist, the app does not
  export spans.
- CI builds the image but runs no tests.
