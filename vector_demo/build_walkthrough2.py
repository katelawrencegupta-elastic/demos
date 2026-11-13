"""Render demo2_walkthrough.html from data/demo2_results.json (run 10_capture_demo2.py first).
Without that file the page still builds and shows the calls, with 'not captured yet' in place of outcomes."""
import json, pathlib
H = pathlib.Path(__file__).parent
f = H / "data" / "demo2_results.json"
data = json.loads(f.read_text()) if f.exists() else {}
w = H / "data" / "workflows_results.json"   # written by 16_workflows.py
if w.exists(): data["workflows"] = json.loads(w.read_text())
page = (H / "walkthrough2_template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
(H / "demo2_walkthrough.html").write_text(page)
print("wrote demo2_walkthrough.html", len(page) // 1024, "KB", "(with captured data)" if data else "(no data yet)")
