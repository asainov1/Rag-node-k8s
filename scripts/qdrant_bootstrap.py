import math
from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams, Distance, PointStruct

client = QdrantClient(url='http://localhost:6333')
COL = 'moderation'

client.recreate_collection(
    collection_name=COL,
    vectors=VectorParams(size=768, distance=Distance.COSINE),
    hnsw_config={'m': 32, 'ef_construct': 200},
)

pts = []
for i in range(1, 2001):
    vec = [math.sin((j+i)/50.0) for j in range(768)]
    pts.append(PointStruct(id=i, vector=vec, payload={'tenant':'demo'}))

client.upsert(collection_name=COL, points=pts)
info = client.get_collection(COL)
print({
    'status': info.status,
    'vectors_count': info.points_count,
    'hnsw_config': info.hnsw_config,
})
