import json, os, time, urllib.request, urllib.error, pathlib

def _load_env():
    p = pathlib.Path(__file__).parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()
ES = os.environ["ES_URL"].rstrip("/")
KB = os.environ.get("KB_URL", "").rstrip("/")
KEY = os.environ["ELASTIC_API_KEY"]

def call(method, path, body=None, base=None, ndjson=False, timeout=300):
    data = None
    headers = {"Authorization": f"ApiKey {KEY}", "kbn-xsrf": "true"}
    if body is not None:
        data = body.encode() if ndjson else json.dumps(body).encode()
        headers["Content-Type"] = "application/x-ndjson" if ndjson else "application/json"
    for attempt in range(5):
        req = urllib.request.Request((base or ES) + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode()
            if e.code in (429, 502, 503, 504) and attempt < 4:   # transient inference/EIS timeouts: back off and retry
                time.sleep(2 * (attempt + 1)); continue
            raise SystemExit(f"{method} {path} -> {e.code}: {body_txt[:600]}")
