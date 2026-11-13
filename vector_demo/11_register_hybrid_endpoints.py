"""Register two stored search templates = reusable hybrid (BM25 + semantic, RRF) search 'endpoints'.
Callers send only parameters to POST _search/template; the retrieval logic lives on the cluster."""
from common import call
TEMPLATES = {
 # use case 1 (application): storefront search with an optional price ceiling
 "demo_hybrid_products": {"source": '{"size":{{size}}{{^size}}5{{/size}},"_source":["sku","name","category","price","rating"],'
   '"retriever":{"rrf":{"rank_window_size":20,"retrievers":['
   '{"standard":{"query":{"bool":{"must":{"match":{"description":"{{query}}"}},"filter":[{"range":{"price":{"lte":{{max_price}}{{^max_price}}100000{{/max_price}}}}}]}}}},'
   '{"standard":{"query":{"semantic":{"field":"description_semantic","query":"{{query}}"}},"filter":[{"range":{"price":{"lte":{{max_price}}{{^max_price}}100000{{/max_price}}}}}]}}]}}}'},
 # use case 2 (workflow): pull the most relevant docs for a ticket so the next workflow step can attach them
 "demo_hybrid_docs": {"source": '{"size":{{size}}{{^size}}3{{/size}},"_source":["title","section","version","body"],'
   '"retriever":{"rrf":{"rank_window_size":20,"retrievers":['
   '{"standard":{"query":{"match":{"body":"{{query}}"}}}},'
   '{"standard":{"query":{"semantic":{"field":"body_semantic","query":"{{query}}"}}}}]}}}'},
}
for sid, script in TEMPLATES.items():
    call("PUT", f"/_scripts/{sid}", {"script": {"lang": "mustache", "source": script["source"]}}); print("registered", sid)
