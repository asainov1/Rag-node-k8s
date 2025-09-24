from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, CONTENT_TYPE_LATEST, generate_latest

registry = CollectorRegistry()

HTTP_LATENCY = Histogram(
    'http_server_request_duration_seconds',
    'HTTP request latency (seconds)',
    ['method','route','status'],
    buckets=[0.05,0.1,0.2,0.5,1,2,5],
    registry=registry,
)
QDRANT_ERRORS = Counter('qdrant_errors_total','Qdrant errors', registry=registry)
CACHE_HIT = Counter('reranker_cache_hit_total','Cache hits', registry=registry)
CACHE_MISS = Counter('reranker_cache_miss_total','Cache misses', registry=registry)
INFLIGHT = Gauge('inflight_requests','In-flight requests', ['route'], registry=registry)

def metrics_app():
    data = generate_latest(registry)
    return CONTENT_TYPE_LATEST, data
