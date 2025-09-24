# RAG Gateway — Staging Proof (Python)

🗒️ **Мои комментарии (для рекрутера/тимлида):**
- Это *staging* на синтетических данных, но 1:1 повторяет мои прод-паттерны: Prometheus-гистограммы (p95/p99), Redis-кэш реранкера, векторка в Qdrant (HNSW `m=32`, `ef_construct=200`), канареечные деплои через Argo Rollouts, автоскейл HPA, CI в GitHub Actions.
- Скриншоты, которые я обычно прикладываю: (1) Qdrant collection info, (2) Grafana p95/p99, (3) Redis hit-rate, (4) Argo Rollouts `setWeight 20/60`, (5) CI run со сборкой образа, (6) короткий пост‑мортем.
- Если нужен трейсинг — включаю OTLP (OpenTelemetry) через env `OTEL_EXPORTER_OTLP_ENDPOINT` (collector можно поднять из `docker/otel-collector.yaml`).

## Быстрый старт (5 минут)
```bash
docker compose -f docker/docker-compose.yml up -d --build
python3 scripts/qdrant_bootstrap.py
# прогрев трафиком, чтобы собрать метрики
hey -z 30s -c 20 -m POST -d '{"q":"test","k":50}' http://localhost:8080/rag
```
Затем зайдите в Grafana `http://localhost:3000` → добавьте Prometheus `http://prometheus:9090` → импортуйте дашборд из `dashboards/grafana-latency-dashboard.json`.

## Что здесь есть
- **FastAPI** сервис с гистограммой `http_server_request_duration_seconds{method,route,status}` + счётчики `reranker_cache_hit_total/miss_total`.
- **Qdrant** (векторка) + скрипт инициализации коллекции с HNSW и 2k синтетических точек.
- **Redis** для кэша реранкера.
- **Prometheus/Grafana** для p95/p99 + hit-rate.
- **Argo Rollouts** c канарейкой и **AnalysisTemplate** (auto-pause по метрике p95 из Prometheus).
- **HPA** пример + **Helm values** (OTel/реплики/env).
- **GitHub Actions** для сборки и пуша образа.
- **RUNBOOK** и **INCIDENT_TEMPLATE** (STAR).

## Мои «прод»-детали (которые обычно проверяют)
- **Векторка:** Qdrant 1.x, HNSW `m=32`, `ef_construct=200`, `ef_search` регулирую по трафику (hot tenants). Скрин `GET /collections/<name>`.
- **Метрики:** `histogram_quantile(0.95, sum(rate(http_server_request_duration_seconds_bucket[5m])) by (le))` — панель p95, рядом p99; hit‑rate Redis = hit / (hit+miss).
- **Деплой:** Argo Rollouts: `setWeight 20 → pause → 60 → pause`, auto‑rollback по Analysis (см. `k8s/analysis-template.yaml`).
- **Устойчивость:** кэш реранкера, backoff+джиттер на внешние вызовы, простейший circuit‑breaker (in‑memory).

---
