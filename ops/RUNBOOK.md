# RUNBOOK — gateway-py

## Health/Readiness
- `/health` → 200 OK
- `/metrics` → Prometheus exposition

## Qdrant
- Bootstrap: `python3 scripts/qdrant_bootstrap.py`
- Check collection: `curl -s http://localhost:6333/collections/moderation | jq '.result | {status, vectors_count, hnsw_config}'`

## Load
- `hey -z 60s -c 50 -m POST -d '{"q":"test","k":50}' http://localhost:8080/rag`

## Rollouts
- Apply: `kubectl apply -f k8s/`
- Watch: `kubectl argo rollouts get rollout gateway-py --watch`

## Dashboards
- Import `dashboards/grafana-latency-dashboard.json` into Grafana
