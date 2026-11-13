import json, pathlib, sys
from common import call
D = pathlib.Path(__file__).parent / "data"

def bulk(index, rows, idf):
    for i in range(0, len(rows), 20):
        nd = "".join(json.dumps({"index": {"_index": index, "_id": r[idf]}}) + "\n" + json.dumps(r) + "\n" for r in rows[i:i+20])
        res = call("POST", "/_bulk", nd, ndjson=True)
        if res.get("errors"):
            print([x["index"]["error"] for x in res["items"] if "error" in x["index"]][:2])
    print(index, len(rows))

products = json.loads((D / "products.json").read_text())
docs = json.loads((D / "docs.json").read_text())
only = sys.argv[1:]  # optionally restrict to specific indices
for idx in ["products-elser", "products-jina", "products-large-float", "products-large-int8", "products-large-bbq"]:
    if not only or idx in only: bulk(idx, products, "sku")
if not only or "docs-jina" in only: bulk("docs-jina", docs, "doc_id")
