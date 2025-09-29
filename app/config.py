# app/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    qdrant_url: str = Field("http://qdrant:6333", env="QDRANT_URL")
    qdrant_collection: str = Field("moderation", env="QDRANT_COLLECTION")
    redis_url: str = Field("redis://redis:6379/0", env="REDIS_URL")
    cache_ttl: int = Field(120, env="CACHE_TTL")

    # NEW: guardrails
    api_key: Optional[str] = Field(None, env="API_KEY")                 # if set, require X-API-Key
    rate_limit_per_min: int = Field(60, env="RATE_LIMIT_PER_MIN")       # <=0 disables
    max_request_bytes: int = Field(1_000_000, env="MAX_REQUEST_BYTES")  # ~1MB

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
