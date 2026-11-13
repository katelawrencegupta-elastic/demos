"""Generate synthetic long-form data using an Elastic-hosted LLM (EIS) - no external keys."""
import json, re, pathlib
from common import call

LLM = ".anthropic-claude-5.5-haiku-completion"
OUT = pathlib.Path(__file__).parent / "data"

def ask(prompt):
    r = call("POST", f"/_inference/completion/{LLM}", {"input": prompt})
    txt = r["completion"][0]["result"]
    m = re.search(r"\[.*\]", txt, re.S)
    return json.loads(m.group(0))

CATS = ["outdoor & camping gear", "home espresso & kitchen appliances", "running & fitness wearables",
        "home office & ergonomic furniture", "smart home & security devices", "bike components & accessories"]
products = []
for c in CATS:
    items = ask(f"Return ONLY a JSON array of 10 distinct ecommerce products in the category '{c}'. Each object: "
                '{"name","brand","category","price"(number),"rating"(1-5 float),"tags"(array of 4 strings),'
                '"description"(a long, realistic 250-350 word product description with specs, use cases, materials, care and warranty)}.')
    products += items
    print(c, len(items))
for i, p in enumerate(products, 1):
    p["sku"] = f"SKU-{i:04d}"
(OUT / "products.json").write_text(json.dumps(products, indent=1))

TOPICS = ["Elasticsearch-style search platform: indexing & mapping guide", "vector search & embeddings configuration guide",
          "security & access control (API keys, RBAC) guide", "troubleshooting & performance tuning guide"]
docs = []
for t in TOPICS:
    items = ask(f"Return ONLY a JSON array of 8 distinct technical product documentation pages for a fictional "
                f"'{t}'. Each object: " '{"title","section","version","body"(a long 350-500 word markdown technical doc with headings, '
                'a code example and a warning/note)}.')
    docs += items
    print(t, len(items))
for i, d in enumerate(docs, 1):
    d["doc_id"] = f"DOC-{i:03d}"
(OUT / "docs.json").write_text(json.dumps(docs, indent=1))
print("products", len(products), "docs", len(docs))
