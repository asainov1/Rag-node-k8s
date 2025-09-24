import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    qdrant_url: str = os.getenv("QDRANT_URL", "http://qdrant:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "moderation")
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    cache_ttl: int = int(os.getenv("CACHE_TTL", "1800"))  # sec
    slo_p95_e2e_sec: float = float(os.getenv("SLO_P95_E2E_SEC", "2.5"))
    enable_tracing: bool = os.getenv("ENABLE_TRACING", "false").lower() == "true"
    otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")

settings = Settings()
