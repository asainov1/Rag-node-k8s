# Incident YYYY-MM-DD (UTC)

## Impact
- Error rate: X% (peak), p99: Ys, affected endpoints: /rag

## Root Cause
- Qdrant optimizer + hot shard under load → latency spikes

## Actions
- limit max_optimizers, enable mmap, reshard 1→3, add circuit-breaker + Redis fallback

## Result
- error-rate ↓ to 0.3%, p99 ~420ms, e2e p95 −28%
