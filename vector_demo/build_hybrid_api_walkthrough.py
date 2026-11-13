"""Render hybrid_api_walkthrough.html from data/hybrid_api_results.json (run 12_capture_hybrid_api.py first).
Without that file the page still builds and shows the calls, with 'not captured yet' in place of outcomes."""
import json, pathlib
H = pathlib.Path(__file__).parent
f = H / "data" / "hybrid_api_results.json"
data = json.loads(f.read_text()) if f.exists() else {}
page = (H / "hybrid_api_template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
(H / "hybrid_api_walkthrough.html").write_text(page)
print("wrote hybrid_api_walkthrough.html", len(page) // 1024, "KB", "(with captured data)" if data else "(no data yet)")
