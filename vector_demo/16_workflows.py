"""Register the two demo workflows in Kibana Workflows, run them against real inputs, and save the outcomes to
data/workflows_results.json (merged into demo2_walkthrough.html by build_walkthrough2.py).
  workflows/ticket_to_cited_reply.yaml : ticket text -> hybrid search template -> model drafts a cited reply
  workflows/daily_sales_digest.yaml    : ES|QL over orders -> model writes a 3-line digest -> stored in sales-digests
Needs 11_register_hybrid_endpoints.py (docs template) and 15_load_orders.py to have run. Re-runnable.
Pass --no-run to register only."""
import json, pathlib, sys, time, datetime
from common import call, KB
H = pathlib.Path(__file__).parent
OUT = H / "data" / "workflows_results.json"
TICKETS = [("T-1042", "Customer ticket: our vector index uses too much RAM at 3072 dimensions"),
           ("T-1043", "Customer ticket: search got slower after we turned on quantization, is accuracy affected?")]
DIGEST_INPUT = {"start": "2026-11-07T00:00:00Z", "end": "2026-11-14T00:00:00Z"}
DIGEST_MAPPING = {"mappings": {"properties": {"@timestamp": {"type": "date"}, "window_start": {"type": "date"}, "window_end": {"type": "date"},
    "digest": {"type": "text"}, "revenue": {"type": "double"}, "orders": {"type": "long"}, "cancelled_lines": {"type": "long"}, "returned_lines": {"type": "long"}}}}

def register(wid, yaml):
    v = call("POST", "/api/agent_builder/tools/_execute", {"tool_id": "platform.workflows.validate_workflow", "tool_params": {"yaml": yaml}}, base=KB)["results"][0]["data"]["result"]
    errs = [d["message"] for d in v["diagnostics"] if d["severity"] == "error"]
    if errs: raise SystemExit(f"{wid} invalid: {errs}")
    existing = {w["id"] for w in call("GET", "/api/workflows", base=KB)["results"]}
    if wid in existing: call("PUT", f"/api/workflows/workflow/{wid}", {"yaml": yaml}, base=KB); print("updated", wid)
    else: call("POST", "/api/workflows", {"workflows": [{"yaml": yaml}]}, base=KB); print("created", wid)

def trim(o, n=2000):
    if isinstance(o, str): return o if len(o) <= n else o[:n] + "…"
    if isinstance(o, dict): return {k: trim(v, n) for k, v in o.items()}
    if isinstance(o, list): return [trim(v, n) for v in o[:12]]
    return o
def summarize(step):
    o = step.get("output")
    if step["stepType"] == "elasticsearch.request" and isinstance(o, dict) and "hits" in o:   # keep the doc list, drop the long bodies
        o = {"took": o.get("took"), "hits": [{"title": h["_source"].get("title"), "section": h["_source"].get("section"), "version": h["_source"].get("version"), "score": round(h["_score"], 3)} for h in o["hits"]["hits"]]}
    elif isinstance(o, dict) and "columns" in o:
        o = {"columns": [c["name"] for c in o["columns"]], "values": o["values"]}
    return {"id": step["stepId"], "type": step["stepType"], "status": step["status"], "ms": step.get("executionTimeMs"), "output": trim(o)}
def run(wid, inputs):
    eid = call("POST", f"/api/workflows/workflow/{wid}/run", {"inputs": inputs}, base=KB)["workflowExecutionId"]
    for _ in range(80):
        time.sleep(3)
        r = call("GET", f"/api/workflows/executions/{eid}?includeInput=true&includeOutput=true", base=KB)
        if r["status"] in ("completed", "failed", "cancelled", "timed_out"): break
    ai = next((s for s in r["stepExecutions"] if s["stepType"].startswith("ai.")), None)
    model = ((ai or {}).get("output") or {}).get("metadata", {}).get("usage", {})
    return {"inputs": inputs, "status": r["status"], "duration_ms": r.get("duration"), "error": r.get("error"),
            "model": model.get("connectorId"), "tokens": {"in": model.get("inputTokens"), "out": model.get("outputTokens")},
            "steps": [summarize(s) for s in r["stepExecutions"]]}

WF = {"ticket-to-cited-reply": "ticket_to_cited_reply", "sales-digest": "daily_sales_digest"}
try: call("PUT", "/sales-digests", DIGEST_MAPPING)
except SystemExit as e:
    if "resource_already_exists" not in str(e): raise
for wid, f in WF.items(): register(wid, (H / "workflows" / f"{f}.yaml").read_text())
if "--no-run" in sys.argv: raise SystemExit(0)

R = {"captured": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
     "yaml": {wid: (H / "workflows" / f"{f}.yaml").read_text() for wid, f in WF.items()}}
R["tickets"] = [{"ticket_id": t, "text": x, **run("ticket-to-cited-reply", {"ticket_id": t, "ticket_text": x})} for t, x in TICKETS]
R["digest"] = run("sales-digest", DIGEST_INPUT)
def esql(q): r = call("POST", "/_query?format=json", {"query": q}); return {"columns": [c["name"] for c in r["columns"]], "rows": r["values"]}
w = f'@timestamp >= "{DIGEST_INPUT["start"]}" AND @timestamp < "{DIGEST_INPUT["end"]}"'
R["digest_check"] = {"esql": f'FROM orders | WHERE {w} AND status != "cancelled" AND status != "returned" | STATS revenue = ROUND(SUM(line_total)) BY category | SORT revenue DESC | LIMIT 3',
                     "esql_total": f'FROM orders | WHERE {w} AND status != "cancelled" AND status != "returned" | STATS revenue = ROUND(SUM(line_total))'}
R["digest_check"]["categories"] = esql(R["digest_check"]["esql"]); R["digest_check"]["total"] = esql(R["digest_check"]["esql_total"])
time.sleep(6)   # let the stored digest become searchable
hit = call("POST", "/sales-digests/_search", {"size": 1, "sort": [{"@timestamp": "desc"}]})["hits"]["hits"]
R["digest_doc"] = hit[0]["_source"] if hit else None
OUT.write_text(json.dumps(R, indent=1, ensure_ascii=False))
print("saved", OUT, "| statuses:", [t["status"] for t in R["tickets"]], R["digest"]["status"])
