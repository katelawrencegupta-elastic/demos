"""Load only NEW products (not in data/products_base.json) into all five product indices, in parallel with retries.
Usage: python3 07_load_parallel.py [index ...]   (default: all five)"""
import json, pathlib, sys, time
from concurrent.futures import ThreadPoolExecutor
from common import call
D = pathlib.Path(__file__).parent / "data"
base = {p["sku"] for p in json.loads((D / "products_base.json").read_text())}
new = [p for p in json.loads((D / "products.json").read_text()) if p["sku"] not in base]
INDICES = sys.argv[1:] or ["products-elser","products-jina","products-large-float","products-large-int8","products-large-bbq"]
BATCH, WORKERS = 20, 6

def send(index, rows):
    for attempt in range(5):
        nd = "".join(json.dumps({"index": {"_index": index, "_id": r["sku"]}}) + "\n" + json.dumps(r) + "\n" for r in rows)
        try:
            res = call("POST", "/_bulk", nd, ndjson=True, timeout=600)
        except SystemExit as e:
            time.sleep(3 * (attempt + 1)); continue
        bad = [r for r, it in zip(rows, res["items"]) if "error" in it["index"]]
        if not bad: return 0
        rows = bad; time.sleep(3 * (attempt + 1))
    return len(rows)

for ix in INDICES:
    t = time.time()
    chunks = [new[i:i + BATCH] for i in range(0, len(new), BATCH)]
    with ThreadPoolExecutor(WORKERS) as ex: failed = sum(ex.map(lambda c: send(ix, c), chunks))
    print(f"{ix}: loaded {len(new) - failed}/{len(new)} new products in {time.time() - t:.0f}s", flush=True)
