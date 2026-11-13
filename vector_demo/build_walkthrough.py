"""Render demo1_walkthrough.html from data/demo1_results.json (run 08_capture_demo1.py first)."""
import json, pathlib
H = pathlib.Path(__file__).parent
data = json.loads((H / "data" / "demo1_results.json").read_text())
page = (H / "walkthrough_template.html").read_text().replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
(H / "demo1_walkthrough.html").write_text(page)
print("wrote demo1_walkthrough.html", len(page) // 1024, "KB")
