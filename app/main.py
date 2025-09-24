import os, time, math, logging
from typing import Optional

import redis
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from config import settings
from metrics import HTTP_LATENCY, CACHE_HIT, CACHE_MISS, QDRANT_ERRORS, INFLIGHT, metrics_app

# ---------- logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway-py")

# ---------- clients ----------
r = redis.Redis.from_url(settings.redis_url)
qdr = QdrantClient(url=settings.qdrant_url)

app = FastAPI(title="gateway-py")

class RagQuery(BaseModel):
    q: Optional[str] = "test"
    k: int = 50

# --------- simple circuit breaker ---------
_circuit_open = False
_circuit_open_until = 0.0
def circuit_allowed() -> bool:
    import time
    return (not _circuit_open) or (time.time() >= _circuit_open_until)
def circuit_trip(seconds: float = 5.0):
    global _circuit_open, _circuit_open_until
    _circuit_open = True
    _circuit_open_until = time.time() + seconds
def circuit_close():
    global _circuit_open
    _circuit_open = False

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.1, min=0.2, max=1.0),
       retry=retry_if_exception_type(Exception))
def qdrant_search(vec, k: int):
    return qdr.search(collection_name=settings.qdrant_collection, query_vector=vec, limit=k)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/metrics")
def metrics():
    ct, data = metrics_app()
    return Response(content=data, media_type=ct)

@app.post("/rag")
async def rag(body: RagQuery):
    start = time.perf_counter()
    status = "200"
    route = "/rag"
    INFLIGHT.labels(route=route).inc()
    try:
        # fallback: serve from cache if circuit is open
        key = f"rerank:{body.q}:{body.k}"
        if not circuit_allowed():
            cached = r.get(key)
            if cached:
                CACHE_HIT.inc()
                result_len = int(cached)
                return JSONResponse({"hits": result_len, "fallback": "cache"})
            # no cache -> quick fail
            return JSONResponse({"error":"circuit_open"}, status_code=503)

        cached = r.get(key)
        if cached:
            CACHE_HIT.inc()
            result_len = int(cached)
        else:
            CACHE_MISS.inc()
            vec = [math.sin((i+1)/37.0) for i in range(768)]
            try:
                res = qdrant_search(vec, body.k)
                circuit_close()
            except Exception as e:
                QDRANT_ERRORS.inc()
                log.warning("qdrant error: %s", e)
                circuit_trip(5.0)
                # try cache fallback
                c2 = r.get(key)
                if c2:
                    CACHE_HIT.inc()
                    result_len = int(c2)
                    return JSONResponse({"hits": result_len, "fallback": "cache"})
                raise
            result_len = len(res)
            r.setex(key, settings.cache_ttl, result_len)
        return JSONResponse({"hits": result_len})
    except Exception:
        status = "500"
        return JSONResponse({"error":"search_failed"}, status_code=500)
    finally:
        HTTP_LATENCY.labels(method="POST", route=route, status=status).observe(time.perf_counter()-start)
        INFLIGHT.labels(route=route).dec()
