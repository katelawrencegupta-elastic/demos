"""Run the hybrid-search-API use case end to end and save real outcomes to data/hybrid_api_results.json
(used by build_hybrid_api_walkthrough.py). Needs 11_register_hybrid_endpoints.py to have run once."""
import json, pathlib, datetime, time
from common import call
OUT = pathlib.Path(__file__).parent / "data" / "hybrid_api_results.json"
APP_Q = "ergonomic chair for long work days"
TICKETS = [("T-1042", "Customer ticket: our vector index uses too much RAM at 3072 dimensions"),
           ("T-1043", "Customer ticket: search got slower after we turned on quantization, is accuracy affected?")]
SCRATCH = "demo_hybrid_scratch"
def safe(fn):
    try: return fn()
    except (SystemExit, Exception) as e: return {"error": str(e)[:300]}
def pretty(src):
    """Indent a mustache JSON template for display, leaving {{vars}} alone."""
    s = src.replace("{{", "\x01").replace("}}", "\x02"); out, d, i, instr = [], 0, 0, False
    for ch in s:
        if ch == '"': instr = not instr
        if instr: out.append(ch); continue
        if ch in "{[": d += 1; out.append(ch + "\n" + "  " * d)
        elif ch in "}]": d -= 1; out.append("\n" + "  " * d + ch)
        elif ch == ",": out.append(",\n" + "  " * d)
        else: out.append(ch)
    return "".join(out).replace("\x01", "{{").replace("\x02", "}}")
def tpl(index, tid, params, fields):
    t = time.time(); r = call("POST", f"/{index}/_search/template", {"id": tid, "params": params})
    return {"took": r["took"], "hits": [{**{k: h["_source"].get(k) for k in fields}, "score": round(h["_score"], 3)} for h in r["hits"]["hits"]]}
R = {"captured": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "app_query": APP_Q}

# the stored templates, as the cluster returns them
R["templates"] = safe(lambda: {sid: pretty(call("GET", f"/_scripts/{sid}")["script"]["source"]) for sid in ("demo_hybrid_products", "demo_hybrid_docs")})

# use case 1 (application): same text, hybrid vs keyword only, then with a tighter price ceiling
PF = ["name", "category", "price", "rating"]
def kw(max_price):
    r = call("POST", "/products-jina/_search", {"size": 3, "_source": PF, "query": {"bool": {"must": {"match": {"description": APP_Q}}, "filter": [{"range": {"price": {"lte": max_price}}}]}}})
    return {"took": r["took"], "hits": [{**{k: h["_source"].get(k) for k in PF}, "score": round(h["_score"], 3)} for h in r["hits"]["hits"]]}
R["app"] = safe(lambda: {"keyword_500": kw(500), "hybrid_500": tpl("products-jina", "demo_hybrid_products", {"query": APP_Q, "max_price": 500, "size": 3}, PF),
                         "hybrid_250": tpl("products-jina", "demo_hybrid_products", {"query": APP_Q, "max_price": 250, "size": 3}, PF)})

# use case 2 (workflow): two tickets, plus the payload a workflow would hand to its next step
def ticket(tid, text):
    r = tpl("docs-jina", "demo_hybrid_docs", {"query": text, "size": 3}, ["title", "section", "version"])
    r["handoff"] = {"ticket_id": tid, "query": text, "suggested_docs": [{"title": h["title"], "section": h["section"], "version": h["version"]} for h in r["hits"]]}
    return r
R["workflow"] = safe(lambda: [{"ticket_id": t, "text": x, **ticket(t, x)} for t, x in TICKETS])

# change the ranking once, in one place: same call before and after the template is updated
V1 = ('{"size":{{size}}{{^size}}3{{/size}},"_source":["title","section","version"],"retriever":{"rrf":{"rank_window_size":20,"retrievers":['
      '{"standard":{"query":{"match":{"body":"{{query}}"}}}},{"standard":{"query":{"semantic":{"field":"body_semantic","query":"{{query}}"}}}}]}}}')
V2 = ('{"size":{{size}}{{^size}}3{{/size}},"_source":["title","section","version"],"retriever":{"text_similarity_reranker":{"retriever":{"rrf":{"rank_window_size":20,"retrievers":['
      '{"standard":{"query":{"match":{"body":"{{query}}"}}}},{"standard":{"query":{"semantic":{"field":"body_semantic","query":"{{query}}"}}}}]}},'
      '"field":"body","inference_id":".jina-reranker-v3","inference_text":"{{query}}","rank_window_size":20}}}')
def evolve():
    params = {"query": TICKETS[1][1], "size": 5}
    call("PUT", f"/_scripts/{SCRATCH}", {"script": {"lang": "mustache", "source": V1}})
    before = tpl("docs-jina", SCRATCH, params, ["title", "section"])
    call("PUT", f"/_scripts/{SCRATCH}", {"script": {"lang": "mustache", "source": V2}})
    after = tpl("docs-jina", SCRATCH, params, ["title", "section"])
    call("PUT", f"/_scripts/{SCRATCH}", {"script": {"lang": "mustache", "source": V1}})   # leave it at v1 so the demo can be re-run
    return {"params": params, "before": before, "after": after, "v2_template": pretty(V2)}
R["evolve"] = safe(evolve)
OUT.write_text(json.dumps(R, indent=1, ensure_ascii=False))
print("saved", OUT, "| errors:", [k for k, v in R.items() if isinstance(v, dict) and "error" in v])
