"""Run every Demo 2 call (RAG + LLM transparency + MCP/A2A) and save real outcomes to data/demo2_results.json
(used by build_walkthrough2.py to render demo2_walkthrough.html). Needs ES_URL, KB_URL, ELASTIC_API_KEY."""
import json, pathlib, datetime, time, urllib.request, urllib.error
from common import call, ES, KB, KEY
OUT = pathlib.Path(__file__).parent / "data" / "demo2_results.json"
DOCS_Q = "how do I reduce memory use for high-dimensional vectors?"
LLM_PROMPT = "In 2 sentences: why use quantization for 3072-dim embeddings?"
LLMS = [".anthropic-claude-5.5-haiku-completion", ".google-gemini-3.5-flash-lite-completion", ".openai-gpt-oss-120b-completion"]
CONVERSE_Q = "Which docs explain BBQ quantization and what are the tradeoffs?"
HDR = {"Authorization": f"ApiKey {KEY}", "kbn-xsrf": "true", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

def kb_post(path, body):
    req = urllib.request.Request(KB + path, data=json.dumps(body).encode(), method="POST", headers=HDR)
    with urllib.request.urlopen(req, timeout=300) as r:
        txt = r.read().decode()
    data = [l[5:].strip() for l in txt.splitlines() if l.startswith("data:")]   # MCP may answer as an SSE stream
    return json.loads(data[-1] if data else txt)
def kb_get(path):
    req = urllib.request.Request(KB + path, headers=HDR)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())
def safe(fn):
    try: return fn()
    except (SystemExit, Exception) as e: return {"error": str(e)[:300]}
def trim(o, n=400):
    if isinstance(o, str): return o if len(o) <= n else o[:n] + "…"
    if isinstance(o, dict): return {k: trim(v, n) for k, v in o.items()}
    if isinstance(o, list): return [trim(v, n) for v in o[:12]]
    return o

R = {"captured": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
     "docs_query": DOCS_Q, "llm_prompt": LLM_PROMPT, "converse_query": CONVERSE_Q}

def retrieve():
    r = call("GET", "/docs-jina/_search", {"size": 3, "_source": ["title", "section", "version"],
        "query": {"semantic": {"field": "body_semantic", "query": DOCS_Q}}})
    return {"took": r["took"], "hits": [{**h["_source"], "score": round(h["_score"], 3)} for h in r["hits"]["hits"]]}
R["retrieve"] = safe(retrieve)

def llm(iid):
    t = time.time(); r = call("POST", f"/_inference/completion/{iid}", {"input": LLM_PROMPT})
    return {"id": iid, "ms": round((time.time() - t) * 1000), "text": r["completion"][0]["result"].strip()}
R["llms"] = [safe(lambda i=i: llm(i)) | {"id": i} for i in LLMS]

def inventory():
    eps = call("GET", "/_inference/_all")["endpoints"]
    by_task, by_prov = {}, {}
    for e in eps:
        by_task[e["task_type"]] = by_task.get(e["task_type"], 0) + 1
        p = e["inference_id"].lstrip(".").split("-")[0]
        by_prov.setdefault(p, {})[e["task_type"]] = by_prov.setdefault(p, {}).get(e["task_type"], 0) + 1
    chat = sorted(e["inference_id"] for e in eps if e["task_type"] in ("chat_completion", "completion"))
    return {"total": len(eps), "by_task": by_task, "by_provider": by_prov, "chat_ids": chat,
            "sample": [{"id": e["inference_id"], "task": e["task_type"], "service": e.get("service")} for e in eps[:8]]}
R["inventory"] = safe(inventory)

def converse():
    r = kb_post("/api/agent_builder/converse", {"input": CONVERSE_Q, "agent_id": "elastic-ai-agent"})
    msg = (r.get("response") or {}).get("message", "")
    return {"keys": sorted(r.keys()), "message": trim(msg, 1200), "model_usage": r.get("model_usage"), "trace_id": r.get("trace_id"),
            "steps": [trim({k: v for k, v in s.items() if k in ("type", "tool_id", "params", "reasoning")}, 160) for s in r.get("steps", [])][:10],
            "n_steps": len(r.get("steps", []))}
R["converse"] = safe(converse)

# --- the demo agent answering sales questions, checked against ES|QL on the same index ---
AGENT = "vector-demo-agent"
NOT_RET = 'WHERE status != "cancelled" AND status != "returned"'
SALES_QS = [
    {"q": "What were our top 3 product categories by revenue this past month?",
     "truth_label": "Revenue by category, excluding cancelled and returned lines",
     "truth_esql": f'FROM orders | {NOT_RET} | STATS revenue = ROUND(SUM(line_total)) BY category | SORT revenue DESC | LIMIT 3'},
    {"q": "What share of orders were returned or cancelled, and which category has the most returns?",
     "truth_label": "Order lines by status, then returned lines by category",
     "truth_esql": ['FROM orders | STATS lines = COUNT(*) BY status | SORT lines DESC',
                    'FROM orders | WHERE status == "returned" | STATS returned_lines = COUNT(*) BY category | SORT returned_lines DESC | LIMIT 3']},
    {"q": "Which was the best-selling product by revenue, and what does it do?",
     "truth_label": "Top products by revenue, excluding cancelled and returned lines",
     "truth_esql": f'FROM orders | {NOT_RET} | STATS revenue = ROUND(SUM(line_total)) BY product = product_name.keyword | SORT revenue DESC | LIMIT 2'},
]
def esql_rows(q):
    r = call("POST", "/_query?format=json", {"query": q})
    return {"columns": [c["name"] for c in r["columns"]], "rows": r["values"]}
def ask_agent(item):
    t = time.time()
    r = kb_post("/api/agent_builder/converse", {"input": item["q"], "agent_id": AGENT})
    u = r.get("model_usage") or {}
    truth = [esql_rows(x) for x in (item["truth_esql"] if isinstance(item["truth_esql"], list) else [item["truth_esql"]])]
    return {"q": item["q"], "agent_id": AGENT, "seconds": round(time.time() - t), "message": trim((r.get("response") or {}).get("message", ""), 1800),
            "tools": [s.get("tool_id") for s in r.get("steps", []) if s.get("tool_id")], "trace_id": r.get("trace_id"),
            "usage": {k: u.get(k) for k in ("model", "llm_calls", "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")},
            "truth_label": item["truth_label"], "truth_esql": item["truth_esql"], "truth": truth}
R["sales"] = [safe(lambda i=i: ask_agent(i)) | {"q": i["q"]} for i in SALES_QS]

def mcp():
    r = kb_post("/api/agent_builder/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = [t["name"] for t in r["result"]["tools"]]
    return {"count": len(tools), "names": tools, "demo_tools": [t for t in tools if t.startswith("demo")]}
R["mcp"] = safe(mcp)

def a2a():
    c = kb_get("/api/agent_builder/a2a/elastic-ai-agent.json")
    return {"name": c.get("name"), "description": trim(c.get("description", ""), 240), "protocolVersion": c.get("protocolVersion"),
            "skills": [s.get("id") or s.get("name") for s in c.get("skills", [])][:12], "n_skills": len(c.get("skills", []))}
R["a2a"] = safe(a2a)

def a2a_send():
    r = kb_post("/api/agent_builder/a2a/elastic-ai-agent", {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message":
        {"role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": "Find an ergonomic office chair under $500 and cite the product."}]}}})
    return trim(r.get("result", r), 500)
R["a2a_send"] = safe(a2a_send)

UC_APP = {"query": "ergonomic chair for long work days", "max_price": 500, "size": 3}
UC_WF = {"query": "Customer ticket: our vector index uses too much RAM at 3072 dimensions", "size": 3}
def use_case(index, tid, params, fields):
    r = call("POST", f"/{index}/_search/template", {"id": tid, "params": params})
    return {"template": tid, "index": index, "params": params, "took": r["took"],
            "hits": [{**{k: h["_source"].get(k) for k in fields}, "score": round(h["_score"], 3)} for h in r["hits"]["hits"]]}
R["uc_app"] = safe(lambda: use_case("products-jina", "demo_hybrid_products", UC_APP, ["name", "category", "price", "rating"]))
R["uc_workflow"] = safe(lambda: use_case("docs-jina", "demo_hybrid_docs", UC_WF, ["title", "section", "version"]))
OUT.write_text(json.dumps(R, indent=1, ensure_ascii=False))
print("saved", OUT, "| errors:", [k for k, v in R.items() if isinstance(v, dict) and "error" in v])
