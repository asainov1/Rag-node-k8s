# app/main.py
import os, time, logging, json, hashlib, re
from typing import Optional, List

import redis
from fastapi import FastAPI, Response, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
try:
    from qdrant_client.fastembed import TextEmbedding  # if installed via qdrant-client[fastembed]
except Exception:
    from fastembed import TextEmbedding                # direct package fallback

from config import settings
from metrics import HTTP_LATENCY, CACHE_HIT, CACHE_MISS, QDRANT_ERRORS, INFLIGHT, metrics_app

# ---------- logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway-py")

# ---------- clients ----------
r = redis.Redis.from_url(settings.redis_url)
qdr = QdrantClient(url=settings.qdrant_url, timeout=2.0)
app = FastAPI(title="gateway-py")


# ---------- optional LLM client ----------
try:
    from openai import OpenAI
    _openai = OpenAI() if os.getenv("OPENAI_API_KEY") else None
except Exception:
    _openai = None

# ---------- CORS ----------
def _cors_origins():
    v = os.getenv("CORS_ORIGINS")
    if v:
        return [x.strip() for x in v.split(",") if x.strip()]
    return ["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- request size limit ----------
@app.middleware("http")
async def _limit_request_size(request: Request, call_next):
    try:
        cl = request.headers.get("content-length")
        if cl and int(cl) > settings.max_request_bytes:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
    except Exception:
        pass
    return await call_next(request)

# ---------- embedder (384-dim, CPU-friendly) ----------
os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")  # silence ONNX warnings
embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")  # 384-dim

# ---------- models ----------
class RagQuery(BaseModel):
    q: str = Field("test", min_length=1, max_length=2000)
    k: int = Field(50, ge=1, le=200)
    rerank: bool = False   # enable LLM reranking per request

class IngestItem(BaseModel):
    id: int
    text: str
    title: Optional[str] = None
    url: Optional[str] = None

class AnswerQuery(BaseModel):
    q: str = Field(..., min_length=1, max_length=2000)
    k: int = Field(5, ge=1, le=20)
    rerank: bool = True

# --------- simple circuit breaker ---------
_circuit_open = False
_circuit_open_until = 0.0
def circuit_allowed() -> bool:
    return (not _circuit_open) or (time.time() >= _circuit_open_until)
def circuit_trip(seconds: float = 5.0):
    global _circuit_open, _circuit_open_until
    _circuit_open = True
    _circuit_open_until = time.time() + seconds
def circuit_close():
    global _circuit_open
    _circuit_open = False

# --------- helpers: auth + rate limit + cache key ---------
def _normalize_query(q: str) -> str:
    q = q.lower().strip()
    q = re.sub(r'[_\s]+', ' ', q)
    q = re.sub(r'\s+', ' ', q)
    return q

def _cache_key(q: str, k: int, rerank: bool) -> str:
    ver = (r.get("rag:collection_version") or b"1").decode()
    digest = hashlib.sha1(f"{_normalize_query(q)}|{k}|{rerank}".encode()).hexdigest()
    return f"rag:{ver}:{digest}"

def require_api_key(request: Request):
    if settings.api_key:
        token = request.headers.get("x-api-key")
        if token != settings.api_key:
            raise HTTPException(status_code=401, detail="unauthorized")

def rate_limit(request: Request):
    if settings.rate_limit_per_min <= 0:
        return
    ip = (request.client.host if request.client else "unknown")
    bucket = int(time.time() // 60)  # per-minute
    key = f"rl:{ip}:{bucket}"
    n = r.incr(key)
    if n == 1:
        r.expire(key, 70)  # pad a bit over a minute
    if n > settings.rate_limit_per_min:
        raise HTTPException(status_code=429, detail="rate_limited")

# --------- chunking ----------
def simple_chunks(text: str, max_len: int = 800, overlap: int = 160):
    """Split text to word chunks with overlap."""
    words = text.split()
    i = 0
    while i < len(words):
        j = min(len(words), i + max_len)
        yield " ".join(words[i:j])
        i = max(i + max_len - overlap, j)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.1, min=0.2, max=1.0),
       retry=retry_if_exception_type(Exception))
def qdrant_search(vec: List[float], k: int):
    return qdr.search(collection_name=settings.qdrant_collection, query_vector=list(vec), limit=k)

# --------- LLM reranker ----------
def llm_rerank(query: str, hits: List[dict]) -> List[dict]:
    """
    Ask an LLM to score each passage 0-10 for relevance and reorder.
    Falls back gracefully if OPENAI_API_KEY is not set or call fails.
    """
    if not _openai or not hits:
        return hits

    passages = [h.get("text", "") for h in hits]
    prompt = {
        "role": "user",
        "content": (
            "You are a reranker. For the given query, score each passage 0-10 for relevance.\n"
            "Return strictly JSON: {\"scores\":[{\"index\":INT, \"score\":FLOAT}, ...]}\n\n"
            f"Query: {query}\n\n" +
            "\n".join([f"[{i}] {p}" for i, p in enumerate(passages)])
        ),
    }

    try:
        resp = _openai.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[prompt],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        scores = {int(x["index"]): float(x["score"]) for x in data.get("scores", [])}
        ranked = sorted(enumerate(hits), key=lambda t: scores.get(t[0], 0.0), reverse=True)
        hits = [h for _, h in ranked]
        for i, h in enumerate(hits, 1):
            h["rank"] = i
            h["reranked"] = True
    except Exception as e:
        log.warning("LLM rerank failed: %s", e)

    return hits

# ---------- routes ----------
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/metrics")
def metrics():
    ct, data = metrics_app()
    return Response(content=data, media_type=ct)

@app.post("/ingest")
def ingest(item: IngestItem, _: None = Depends(require_api_key), __: None = Depends(rate_limit)):
    try:
        # Chunk → embed batch → upsert each chunk with metadata
        chunks = list(simple_chunks(item.text, max_len=800, overlap=160)) or [item.text]
        vecs = list(embedder.embed(chunks))
        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
            points.append(
                qm.PointStruct(
                    id=f"{item.id}:{i}",
                    vector=list(vec),
                    payload={
                        "doc_id": item.id,
                        "chunk": i,
                        "text": chunk,
                        **({"title": item.title} if item.title else {}),
                        **({"url": item.url} if item.url else {}),
                    },
                )
            )
        qdr.upsert(collection_name=settings.qdrant_collection, points=points, wait=True)
        r.incr("rag:collection_version")  # invalidate old cache
        return {"ok": True, "doc_id": item.id, "chunks": len(points)}
    except Exception as e:
        log.exception("ingest failed: %s", e)
        raise HTTPException(status_code=500, detail="ingest_failed")

@app.post("/rag")
async def rag(body: RagQuery, _: None = Depends(require_api_key), __: None = Depends(rate_limit)):
    start = time.perf_counter()
    route = "/rag"
    status = "200"
    INFLIGHT.labels(route=route).inc()
    try:
        key = _cache_key(body.q, body.k, body.rerank)

        # Circuit-open: try cache or 503
        if not circuit_allowed():
            cached = r.get(key)
            if cached:
                CACHE_HIT.inc(); status = "200"
                return JSONResponse(json.loads(cached))
            status = "503"
            return JSONResponse({"error": "circuit_open"}, status_code=503)

        # Cache first
        cached = r.get(key)
        if cached:
            CACHE_HIT.inc(); status = "200"
            return JSONResponse(json.loads(cached))

        # Miss → embed → search
        CACHE_MISS.inc()
        vec = next(embedder.embed([body.q]))
        try:
            res = qdrant_search(vec, body.k); circuit_close()
        except Exception as e:
            QDRANT_ERRORS.inc(); log.warning("qdrant error: %s", e); circuit_trip(5.0)
            c2 = r.get(key)
            if c2:
                CACHE_HIT.inc(); status="200"
                return JSONResponse(json.loads(c2))
            status = "500"
            return JSONResponse({"error":"search_failed"}, status_code=500)

        hits = [
            {
                "rank": i+1,
                "id": p.id,
                "score": p.score,
                "text": (p.payload or {}).get("text", ""),
                "title": (p.payload or {}).get("title"),
                "url": (p.payload or {}).get("url"),
                "doc_id": (p.payload or {}).get("doc_id"),
                "chunk": (p.payload or {}).get("chunk"),
            }
            for i, p in enumerate(res)
        ]

        # Optional LLM reranking
        if body.rerank:
            hits = llm_rerank(body.q, hits)

        payload = {"hits": hits}
        ttl = 10 if not hits else settings.cache_ttl
        r.setex(key, ttl, json.dumps(payload))
        status = "200"
        return JSONResponse(payload)

    except Exception as e:
        log.exception("Unhandled /rag error: %s", e)
        status = "500"
        return JSONResponse({"error":"internal_error"}, status_code=500)
    finally:
        HTTP_LATENCY.labels(method="POST", route=route, status=status).observe(time.perf_counter() - start)
        INFLIGHT.labels(route=route).dec()

@app.post("/answer")
def answer(body: AnswerQuery, _: None = Depends(require_api_key), __: None = Depends(rate_limit)):
    """G-step: retrieve → optional rerank → LLM answer (fallback to extractive stub)."""
    vec = next(embedder.embed([body.q]))
    res = qdr.search(collection_name=settings.qdrant_collection, query_vector=list(vec), limit=body.k)
    hits = [
        {
            "rank": i+1,
            "id": p.id,
            "score": p.score,
            "text": (p.payload or {}).get("text", ""),
            "title": (p.payload or {}).get("title"),
            "url": (p.payload or {}).get("url"),
            "doc_id": (p.payload or {}).get("doc_id"),
            "chunk": (p.payload or {}).get("chunk"),
        }
        for i, p in enumerate(res)
    ]

    if body.rerank:
        hits = llm_rerank(body.q, hits)

    answer = None
    if _openai:
        context = "\n".join(f"- {h['text']}" for h in hits[: min(5, body.k)])
        prompt = {
            "role": "user",
            "content": (
                "Answer the question concisely using ONLY the provided context. "
                "If unsure, say you don't know.\n\n"
                f"Question: {body.q}\n\nContext:\n{context}\n\nAnswer:"
            ),
        }
        try:
            resp = _openai.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.2,
                messages=[prompt],
            )
            answer = resp.choices[0].message.content.strip()
        except Exception as e:
            log.warning("LLM answer failed: %s", e)

    if not answer:
        answer = " ".join(h["text"] for h in hits[:2]) or "(no relevant context)"

    return {"answer": answer, "citations": hits}
