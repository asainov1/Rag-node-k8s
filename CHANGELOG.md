# Changelog

## 2025-09-24
- feat(app): initial FastAPI service with Prometheus histograms and cache counters
- feat(vec): Qdrant bootstrap (HNSW m=32, ef_construct=200) + 2k synthetic points
- feat(obs): Prometheus scrape + Grafana dashboard (p95/p99, hit-rate panel)
- feat(ci): GitHub Actions build & push to GHCR
- feat(k8s): Argo Rollouts canary + AnalysisTemplate (Prometheus p95 guard)
- feat(ops): Runbook + Incident template
