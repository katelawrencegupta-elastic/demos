"""Create indices. Same ecommerce data, multiple embedding setups, so the demo can compare them side by side."""
from common import call

def mapping(inference_id, index_options=None, chunking=None):
    st = {"type": "semantic_text", "inference_id": inference_id}
    if index_options: st["index_options"] = {"dense_vector": index_options}
    if chunking: st["chunking_settings"] = chunking
    return {"mappings": {"properties": {
        "sku": {"type": "keyword"}, "name": {"type": "text"}, "brand": {"type": "keyword"},
        "category": {"type": "keyword"}, "price": {"type": "float"}, "rating": {"type": "float"},
        "tags": {"type": "keyword"},
        "description": {"type": "text", "copy_to": "description_semantic"},
        "description_semantic": st}}}

CHUNK = {"strategy": "sentence", "max_chunk_size": 250, "sentence_overlap": 1}
INDICES = {
  # EIS: managed, no ML nodes. Sparse (ELSER) vs dense (Jina v5)
  "products-elser":        mapping(".elser-2-elastic"),
  "products-jina":         mapping(".jina-embeddings-v5-text-small", chunking=CHUNK),
  # Large (3072-dim) embeddings: full float vs quantized
  "products-large-float":  mapping(".openai-text-embedding-3-large", {"type": "hnsw"}, CHUNK),
  "products-large-int8":   mapping(".openai-text-embedding-3-large", {"type": "int8_hnsw"}, CHUNK),
  "products-large-bbq":    mapping(".openai-text-embedding-3-large", {"type": "bbq_hnsw"}, CHUNK),
}
docs_map = {"mappings": {"properties": {
    "doc_id": {"type": "keyword"}, "title": {"type": "text"}, "section": {"type": "keyword"},
    "version": {"type": "keyword"},
    "body": {"type": "text", "copy_to": "body_semantic"},
    "body_semantic": {"type": "semantic_text", "inference_id": ".jina-embeddings-v5-text-small", "chunking_settings": CHUNK}}}}
INDICES["docs-jina"] = docs_map

for name, body in INDICES.items():
    call("DELETE", f"/{name}") if False else None
    try:
        call("PUT", f"/{name}", body); print("created", name)
    except SystemExit as e:
        print("skip/exists?", name, str(e)[:160])
