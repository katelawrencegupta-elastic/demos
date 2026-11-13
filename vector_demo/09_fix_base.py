"""Repair the original 60 products: regenerate missing descriptions and normalise category names, then reindex those SKUs everywhere."""
import json, pathlib, re, time
from concurrent.futures import ThreadPoolExecutor
from common import call
D = pathlib.Path(__file__).parent / "data"
LLM = ".anthropic-claude-5.5-haiku-completion"
INDICES = ["products-elser","products-jina","products-large-float","products-large-int8","products-large-bbq"]
DEPTS = ["outdoor & camping gear","home espresso & kitchen appliances","running & fitness wearables","home office & ergonomic furniture","smart home & security devices","bike components & accessories"]
canon = {d.lower(): d for d in DEPTS}
allp = json.loads((D / "products.json").read_text())
def fix_cat(c): return canon.get(str(c).strip().lower(), c)
def desc(p):
    prompt = (f"Write a long, realistic 220-320 word ecommerce product description for '{p['name']}' by {p['brand']} (category: {p['category']}, tags: {', '.join(p.get('tags', []))}). "
              "Cover features, specs, materials, intended use cases, care and warranty. Return ONLY the description text, no title or markdown.")
    for _ in range(3):
        try:
            t = call("POST", f"/_inference/completion/{LLM}", {"input": prompt}, timeout=300)["completion"][0]["result"].strip()
            if len(t.split()) >= 120: return t
        except SystemExit: time.sleep(2)
    return None
missing = [p for p in allp if "description" not in p]
with ThreadPoolExecutor(6) as ex: out = list(ex.map(desc, missing))
for p, d in zip(missing, out):
    if d: p["description"] = d
changed = [p for p in allp if p["sku"] in {m["sku"] for m in missing} or fix_cat(p["category"]) != p["category"]]
for p in allp: p["category"] = fix_cat(p["category"])
still = [p["sku"] for p in allp if "description" not in p]
(D / "products.json").write_text(json.dumps(allp, indent=1))
base = {p["sku"] for p in json.loads((D / "products_base.json").read_text())}
(D / "products_base.json").write_text(json.dumps([p for p in allp if p["sku"] in base], indent=1))
print("regenerated", sum(1 for d in out if d), "of", len(missing), "| still missing", still, "| reindexing", len(changed), "docs")
for ix in INDICES:
    nd = "".join(json.dumps({"index": {"_index": ix, "_id": p["sku"]}}) + "\n" + json.dumps(p) + "\n" for p in changed)
    r = call("POST", "/_bulk", nd, ndjson=True, timeout=900)
    print(ix, "errors" if r["errors"] else "ok", flush=True)
