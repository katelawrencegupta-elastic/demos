"""Create the `orders` index and bulk-load data/orders.json (from 14_generate_orders.py).
Re-runnable: document IDs are order_id-line_no, so loading again overwrites rather than duplicates."""
import json, pathlib, sys
from common import call
D = pathlib.Path(__file__).parent / "data"
INDEX = "orders"
MAPPING = {"mappings": {"properties": {
    "@timestamp": {"type": "date"}, "delivered_at": {"type": "date"},
    "order_id": {"type": "keyword"}, "line_no": {"type": "short"}, "order_line_count": {"type": "short"},
    "customer_id": {"type": "keyword"}, "region": {"type": "keyword"}, "country": {"type": "keyword"},
    "channel": {"type": "keyword"}, "payment_method": {"type": "keyword"}, "coupon_code": {"type": "keyword"},
    "sku": {"type": "keyword"}, "product_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
    "brand": {"type": "keyword"}, "category": {"type": "keyword"},
    "quantity": {"type": "short"}, "unit_price": {"type": "float"}, "discount_pct": {"type": "short"}, "line_total": {"type": "float"},
    "status": {"type": "keyword"}}}}
rows = json.loads((D / "orders.json").read_text())
if "--recreate" in sys.argv:
    try: call("DELETE", f"/{INDEX}")
    except SystemExit: pass
try: call("PUT", f"/{INDEX}", MAPPING); print("created", INDEX)
except SystemExit as e:
    if "resource_already_exists" not in str(e): raise
    print(INDEX, "exists; loading into it (use --recreate to start clean)")
B = 1000
for i in range(0, len(rows), B):
    chunk = rows[i:i + B]
    nd = "".join(json.dumps({"index": {"_index": INDEX, "_id": f"{r['order_id']}-{r['line_no']}"}}) + "\n" + json.dumps({k: v for k, v in r.items() if v is not None}) + "\n" for r in chunk)
    res = call("POST", "/_bulk", nd, ndjson=True)
    if res.get("errors"): print([x["index"]["error"] for x in res["items"] if "error" in x["index"]][:2])
print("loaded", len(rows), "order lines into", INDEX)
