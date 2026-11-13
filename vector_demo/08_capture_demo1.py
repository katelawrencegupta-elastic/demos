"""Run every Demo 1 call against the live cluster and save the real outcomes to data/demo1_results.json
(used by build_walkthrough.py to render demo1_walkthrough.html)."""
import json, pathlib, datetime
from common import call, ES
OUT = pathlib.Path(__file__).parent / "data" / "demo1_results.json"
MAIN = "know when someone is at my front door while I'm away"
STORIES = [MAIN, "work from home without wrecking my back", "gift for someone who just started running", "make café-quality drinks at home"]
OVERLAP_Q = STORIES + ["lightweight shelter for two people backpacking","track my heart rate during workouts","quiet gear for early morning rides",
 "protect my laptop and desk setup ergonomically","smart lock battery life","keep my dog entertained while I'm at work","carry-on bag that fits overhead bins",
 "baby monitor with video and temperature","charge my phone on a long hike","wake up gently without a loud alarm","brew coffee without a machine",
 "stop my bike from being stolen","reduce noise while working in an open office","gift for a new parent","clean floors automatically",
 "waterproof speaker for the beach","protect my skin on a long run","something to help me sleep on a plane","keep pipes from flooding the basement","trim my beard neatly"]
def hit(h): s = h["_source"]; return {"sku": s.get("sku"), "name": s.get("name"), "category": s.get("category"), "sub": s.get("subcategory"), "price": s.get("price"), "score": round(h["_score"], 3) if h.get("_score") is not None else None}
def run(ix, body, n=5):
    r = call("POST", f"/{ix}/_search", {"size": n, "_source": ["sku","name","category","subcategory","price"], **body})
    return {"took": r["took"], "total": r["hits"]["total"]["value"], "hits": [hit(h) for h in r["hits"]["hits"]]}
bm25 = lambda q: {"query": {"match": {"description": q}}}
sem = lambda q: {"query": {"semantic": {"field": "description_semantic", "query": q}}}
def rrf(q, rerank=False):
    inner = {"rrf": {"rank_window_size": 20, "retrievers": [{"standard": bm25(q)}, {"standard": sem(q)}]}}
    if not rerank: return {"retriever": inner}
    return {"retriever": {"text_similarity_reranker": {"retriever": inner, "field": "description", "inference_id": ".jina-reranker-v3", "inference_text": q, "rank_window_size": 20}}}
R = {"captured": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "main_query": MAIN, "stories": STORIES}
# models
R["models"] = {}
for iid in [".elser-2-elastic", ".jina-embeddings-v5-text-small", ".openai-text-embedding-3-large", ".jina-reranker-v3"]:
    e = call("GET", f"/_inference/{iid}")["endpoints"][0]
    ss = e.get("service_settings", {})
    R["models"][iid] = {"task_type": e.get("task_type"), "service": e.get("service"), "model_id": ss.get("model_id"), "dimensions": ss.get("dimensions"), "similarity": ss.get("similarity"), "element_type": ss.get("element_type")}
inf = call("GET", "/_inference")["endpoints"]
R["catalog"] = {"total": len(inf), "embedding": sum(1 for e in inf if e["task_type"] in ("text_embedding","embedding","sparse_embedding")), "rerank": sum(1 for e in inf if e["task_type"] == "rerank"), "chat": sum(1 for e in inf if e["task_type"] == "chat_completion")}
# mappings
R["mappings"] = {}
for ix in ["products-jina","products-large-float","products-large-int8","products-large-bbq"]:
    m = call("GET", f"/{ix}/_mapping")[ix]["mappings"]["properties"]["description_semantic"]
    R["mappings"][ix] = {"inference_id": m.get("inference_id"), "index_options": m.get("index_options"), "chunking_settings": m.get("chunking_settings"), "dims": (m.get("model_settings") or {}).get("dimensions")}
R["counts"] = {ix: call("GET", f"/{ix}/_count")["count"] for ix in ["products-elser","products-jina","products-large-float","products-large-int8","products-large-bbq"]}
R["dept_counts"] = {b["key"]: b["doc_count"] for b in call("POST","/products-jina/_search",{"size":0,"aggs":{"c":{"terms":{"field":"category","size":30}}}})["aggregations"]["c"]["buckets"]}
# step: keyword vs semantic, then models
R["compare"] = {q: {"bm25": run("products-jina", bm25(q)), "jina": run("products-jina", sem(q)), "elser": run("products-elser", sem(q)), "large_bbq": run("products-large-bbq", sem(q))} for q in STORIES}
# large embeddings: float vs int8 vs bbq
R["large"] = {q: {k: run(f"products-large-{k}", sem(q)) for k in ("float","int8","bbq")} for q in [MAIN, STORIES[1]]}
ov = []
for q in OVERLAP_Q:
    t = {k: [h["sku"] for h in run(f"products-large-{k}", sem(q), 10)["hits"]] for k in ("float","int8","bbq")}
    ov.append({"q": q, "int8@10": len(set(t["float"]) & set(t["int8"])) / 10, "bbq@10": len(set(t["float"]) & set(t["bbq"])) / 10,
               "int8@3": len(set(t["float"][:3]) & set(t["int8"][:3])) / 3, "bbq@3": len(set(t["float"][:3]) & set(t["bbq"][:3])) / 3, "bbq_top1_same": t["float"][:1] == t["bbq"][:1]})
n = len(ov); R["overlap"] = {"n": n, "rows": ov, **{k: round(sum(r[k] for r in ov) / n, 3) for k in ("int8@10","bbq@10","int8@3","bbq@3")}, "bbq_top1_same": sum(r["bbq_top1_same"] for r in ov)}
cat = {r["index"]: r for r in call("GET", "/_cat/indices/products-*?format=json&h=index,docs.count,store.size&s=index")}
R["docs_total"] = {ix: int(cat[ix]["docs.count"]) for ix in R["counts"]}
R["reported_store"] = {ix: cat[ix]["store.size"] for ix in R["counts"]}   # node-local on Serverless: unreliable, kept only for transparency
parents = R["counts"]["products-jina"]; chunks = R["docs_total"]["products-jina"] - parents
R["chunk_stats"] = {"products": parents, "docs_total": R["docs_total"]["products-jina"], "chunks": chunks, "avg_chunks_per_product": round(chunks / parents, 2)}
def foot(dims, fmt, n):
    raw = 4 * dims
    q = {"float": 0, "int8": dims + 4, "bbq": dims / 8 + 14}[fmt]
    return {"vectors": n, "dims": dims, "ram_bytes": n * (raw if fmt == "float" else q), "disk_bytes": n * (raw + q)}
dj = R["models"][".jina-embeddings-v5-text-small"]["dimensions"]; dl = R["models"][".openai-text-embedding-3-large"]["dimensions"]
R["footprint"] = [{"index": "products-jina", "label": "Jina v5 small, float", **foot(dj, "float", chunks)},
                  {"index": "products-large-float", "label": "OpenAI 3-large, float32", **foot(dl, "float", chunks)},
                  {"index": "products-large-int8", "label": "OpenAI 3-large, int8", **foot(dl, "int8", chunks)},
                  {"index": "products-large-bbq", "label": "OpenAI 3-large, BBQ", **foot(dl, "bbq", chunks)}]
# chunking
c = call("POST", "/products-jina/_search", {"size": 1, "_source": ["sku","name"], **sem(MAIN), "highlight": {"fields": {"description_semantic": {"number_of_fragments": 3}}}})
h = c["hits"]["hits"][0]; src = call("GET", f"/products-jina/_doc/{h['_id']}")["_source"]
R["chunking"] = {"name": h["_source"]["name"], "sku": h["_source"]["sku"], "words": len(src["description"].split()), "fragments": h.get("highlight", {}).get("description_semantic", [])}
# hybrid
R["hybrid"] = {q: {"bm25": run("products-jina", bm25(q)), "semantic": run("products-jina", sem(q)), "rrf": run("products-jina", rrf(q)), "rerank": run("products-jina", rrf(q, True))} for q in [MAIN, STORIES[1], STORIES[2]]}
OUT.write_text(json.dumps(R, indent=1, ensure_ascii=False))
print("saved", OUT, "| counts", R["counts"], "| overlap bbq@10", R["overlap"]["bbq@10"])
