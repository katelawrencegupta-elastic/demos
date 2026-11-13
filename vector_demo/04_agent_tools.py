"""Register custom Agent Builder tools over the demo indices (these are what MCP + A2A clients will see)."""
from common import call, KB
TOOLS = [
 {"id": "demo.search_products", "type": "index_search",
  "description": "Semantic search over the ecommerce product catalog (long descriptions, price, rating, brand).",
  "configuration": {"pattern": "products-jina"}, "tags": ["demo"]},
 {"id": "demo.search_orders", "type": "index_search",
  "description": "Sales and order data for the last month: one document per order line with timestamp, order_id, customer_id, region, country, channel, payment_method, coupon_code, sku, product_name, brand, category, quantity, unit_price, discount_pct, line_total and status (processing, shipped, delivered, cancelled, returned). Use for revenue, units, trends, top products or categories, and order status questions.",
  "configuration": {"pattern": "orders"}, "tags": ["demo"]},
 {"id": "demo.search_docs", "type": "index_search",
  "description": "Semantic search over technical product documentation pages.",
  "configuration": {"pattern": "docs-jina"}, "tags": ["demo"]},
]
for t in TOOLS:
    try: call("POST", "/api/agent_builder/tools", t, base=KB); print("registered", t["id"])
    except SystemExit as e:   # already exists (possibly in use by an agent, so it cannot be deleted): update in place
        if "already exists" not in str(e): raise
        call("PUT", f"/api/agent_builder/tools/{t['id']}", {k: v for k, v in t.items() if k not in ("id", "type")}, base=KB); print("updated", t["id"])
