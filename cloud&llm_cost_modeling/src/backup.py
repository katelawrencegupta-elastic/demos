"""Snapshot Kibana / Fleet / Elasticsearch objects into ./elastic.

Does not dump document data, API keys, or enrollment tokens. Known secret
fields are replaced with [REDACTED] before write.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_URL, ROOT

BACKUP_ROOT = ROOT / "elastic"

# Saved-object types Kibana Serverless will export. Non-exportable types
# are skipped when the API returns 400.
SO_TYPES = [
    "dashboard",
    "visualization",
    "index-pattern",
    "search",
    "lens",
    "map",
    "query",
    "tag",
    "url",
    "config",
    "links",
    "event-annotation-group",
    "osquery-saved-query",
    "osquery-pack",
    "alert",
    "action",
    "cases",
    "inventory-view",
    "infrastructure-ui-source",
    "apm-service-group",
    "apm-custom-dashboards",
]

_SECRET_EXACT = {
    "password", "secret", "secrets", "api_key", "apikey",
    "access_key", "accesskey", "secret_key", "secretkey",
    "access_key_id", "accesskeyid", "secret_access_key",
    "client_secret", "clientsecret", "private_key", "privatekey",
    "credentials", "credential", "bearer", "session_token",
    "sessiontoken", "secret_references", "ssl.key", "ssl.certificate",
    "ssl.key_passphrase", "access_token", "refresh_token", "id_token",
    "auth_token", "bearer_token", "enrollment_api_keys",
}
_SECRET_SUFFIXES = (
    "_password", "_secret", "_apikey", "_api_key", "_access_key",
    "_private_key", "_client_secret",
)


def _is_secret_key(key: str) -> bool:
    lk = key.lower().replace("-", "_")
    if lk in _SECRET_EXACT:
        return True
    return any(lk.endswith(sfx) for sfx in _SECRET_SUFFIXES)


def redact(obj):
    if isinstance(obj, dict):
        if obj.get("isSecretRef") is True:
            return "[REDACTED]"
        if obj.get("type") == "password" and "value" in obj:
            return {**obj, "value": "[REDACTED]"}
        out = {}
        for k, v in obj.items():
            if _is_secret_key(str(k)):
                out[k] = "[REDACTED]"
            elif k == "service_settings":
                out[k] = "[REDACTED]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def safe_name(name: str) -> str:
    name = name.replace("*", "star")
    return re.sub(r"[^\w.@+=-]+", "_", name)[:180]


def write_json(path: Path, obj, *, redact_secrets: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = redact(obj) if redact_secrets else obj
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _kbn(method: str, path: str, **kw):
    r = requests.request(
        method, f"{KIBANA_URL}{path}", headers=KBN_HEADERS, timeout=kw.pop("timeout", 120), **kw)
    return r


def _es(method: str, path: str, **kw):
    r = requests.request(
        method, f"{ELASTIC_URL}{path}", headers=ES_HEADERS, timeout=kw.pop("timeout", 120), **kw)
    return r


def backup_spaces(counts: Counter) -> None:
    r = _kbn("GET", "/api/spaces/space")
    r.raise_for_status()
    spaces = r.json()
    write_json(BACKUP_ROOT / "kibana" / "spaces.json", spaces)
    counts["kibana.spaces"] = len(spaces)
    print(f"  spaces: {len(spaces)}")


def backup_data_views(counts: Counter) -> None:
    r = _kbn("GET", "/api/data_views")
    r.raise_for_status()
    views = r.json().get("data_view", [])
    n = 0
    for summary in views:
        vid = summary["id"]
        r = _kbn("GET", f"/api/data_views/data_view/{vid}")
        if r.status_code != 200:
            write_json(BACKUP_ROOT / "kibana" / "data_views" / f"{safe_name(vid)}.json", summary)
        else:
            write_json(BACKUP_ROOT / "kibana" / "data_views" / f"{safe_name(vid)}.json", r.json())
        n += 1
    counts["kibana.data_views"] = n
    print(f"  data views: {n}")


def backup_dashboards(counts: Counter) -> None:
    items = []
    page = 1
    while True:
        r = _kbn("GET", "/api/dashboards", params={"page": page, "per_page": 100})
        r.raise_for_status()
        body = r.json()
        batch = body.get("data") or []
        items.extend(batch)
        meta = body.get("meta") or {}
        total = meta.get("total", len(items))
        if len(items) >= total or not batch:
            break
        page += 1
    dest = BACKUP_ROOT / "kibana" / "dashboards"
    meridian_dest = ROOT / "dashboards"
    meridian_dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for item in items:
        did = item["id"]
        r = _kbn("GET", f"/api/dashboards/{did}")
        if r.status_code != 200:
            print(f"  [warn] dashboard {did}: {r.status_code}")
            continue
        payload = r.json()
        data = payload.get("data", payload)
        write_json(dest / f"{safe_name(did)}.json", payload)
        if did.startswith("meridian-"):
            write_json(meridian_dest / f"{safe_name(did)}.json", data)
        n += 1
    counts["kibana.dashboards"] = n
    print(f"  dashboards: {n}")


def backup_saved_objects(counts: Counter) -> None:
    exportable = []
    per_type = BACKUP_ROOT / "kibana" / "saved_objects"
    for so_type in SO_TYPES:
        r = _kbn("POST", "/api/saved_objects/_export", json={
            "type": [so_type],
            "includeReferencesDeep": False,
            "excludeExportDetails": True,
        })
        if r.status_code == 400 and "non-exportable" in r.text:
            continue
        if r.status_code != 200:
            print(f"  [warn] saved object {so_type}: {r.status_code} {r.text[:160]}")
            continue
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        if not lines:
            continue
        exportable.append(so_type)
        write_text(per_type / f"{so_type}.ndjson", "\n".join(lines) + "\n")
        counts[f"kibana.so.{so_type}"] = len(lines)
        print(f"  saved objects {so_type}: {len(lines)}")
    if exportable:
        r = _kbn("POST", "/api/saved_objects/_export", json={
            "type": exportable,
            "includeReferencesDeep": True,
            "excludeExportDetails": False,
        }, timeout=180)
        if r.status_code == 200:
            write_text(BACKUP_ROOT / "kibana" / "saved_objects.ndjson", r.text
                       if r.text.endswith("\n") else r.text + "\n")
            n_lines = sum(1 for ln in r.text.splitlines() if ln.strip())
            counts["kibana.saved_objects_export_lines"] = n_lines
            print(f"  combined saved-objects export: {n_lines} lines")
        else:
            print(f"  [warn] combined export: {r.status_code} {r.text[:200]}")


def backup_alerting(counts: Counter) -> None:
    rules = []
    page = 1
    while True:
        r = _kbn("GET", "/api/alerting/rules/_find",
                 params={"page": page, "per_page": 100})
        r.raise_for_status()
        body = r.json()
        batch = body.get("data") or []
        rules.extend(batch)
        if len(rules) >= body.get("total", 0) or not batch:
            break
        page += 1
    dest = BACKUP_ROOT / "kibana" / "rules"
    for rule in rules:
        write_json(dest / f"{safe_name(rule['id'])}.json", rule)
    write_json(BACKUP_ROOT / "kibana" / "rules.json", rules)
    counts["kibana.rules"] = len(rules)
    print(f"  alerting rules: {len(rules)}")


def backup_connectors(counts: Counter) -> None:
    r = _kbn("GET", "/api/actions/connectors")
    r.raise_for_status()
    connectors = r.json()
    dest = BACKUP_ROOT / "kibana" / "connectors"
    for c in connectors:
        write_json(dest / f"{safe_name(c['id'])}.json", c)
    write_json(BACKUP_ROOT / "kibana" / "connectors.json", connectors)
    counts["kibana.connectors"] = len(connectors)
    print(f"  connectors: {len(connectors)} (secrets redacted)")


def backup_fleet(counts: Counter) -> None:
    r = _kbn("GET", "/api/fleet/epm/packages/installed")
    r.raise_for_status()
    pkgs = r.json().get("items", [])
    slim = []
    for p in pkgs:
        slim.append({
            "name": p.get("name"),
            "title": p.get("title"),
            "version": p.get("version"),
            "status": p.get("status"),
            "type": p.get("type"),
            "dataStreams": p.get("dataStreams"),
            "installationInfo": {
                k: (p.get("installationInfo") or {}).get(k)
                for k in ("installed_kibana", "install_source", "install_scope")
            } if p.get("installationInfo") else None,
        })
    write_json(BACKUP_ROOT / "fleet" / "installed_packages.json", slim)
    counts["fleet.packages"] = len(slim)
    print(f"  fleet packages: {len(slim)}")

    r = _kbn("GET", "/api/fleet/agent_policies", params={"perPage": 100, "full": True})
    r.raise_for_status()
    policies = r.json().get("items", [])
    write_json(BACKUP_ROOT / "fleet" / "agent_policies.json", policies)
    counts["fleet.agent_policies"] = len(policies)
    print(f"  agent policies: {len(policies)}")

    r = _kbn("GET", "/api/fleet/package_policies", params={"perPage": 100})
    r.raise_for_status()
    pkg_policies = r.json().get("items", [])
    write_json(BACKUP_ROOT / "fleet" / "package_policies.json", pkg_policies)
    counts["fleet.package_policies"] = len(pkg_policies)
    print(f"  package policies: {len(pkg_policies)} (secrets redacted)")

    r = _kbn("GET", "/api/fleet/outputs")
    r.raise_for_status()
    outputs = r.json().get("items", [])
    write_json(BACKUP_ROOT / "fleet" / "outputs.json", outputs)
    counts["fleet.outputs"] = len(outputs)
    print(f"  fleet outputs: {len(outputs)}")


def _split_named(payload, list_key: str, dest: Path, counts_key: str, counts: Counter, label: str,
                 *, redact_secrets: bool = True):
    items = payload.get(list_key) if isinstance(payload, dict) and list_key else None
    if items is None and isinstance(payload, dict):
        n = 0
        for name, body in payload.items():
            write_json(
                dest / f"{safe_name(name)}.json",
                {"name": name, **body} if isinstance(body, dict) else body,
                redact_secrets=redact_secrets,
            )
            n += 1
        counts[counts_key] = n
        print(f"  {label}: {n}")
        return
    n = 0
    for item in items or []:
        name = item.get("name") or item.get("id")
        write_json(dest / f"{safe_name(name)}.json", item, redact_secrets=redact_secrets)
        n += 1
    counts[counts_key] = n
    print(f"  {label}: {n}")


def backup_elasticsearch(counts: Counter) -> None:
    r = _es("GET", "/_index_template")
    r.raise_for_status()
    _split_named(r.json(), "index_templates",
                 BACKUP_ROOT / "elasticsearch" / "index_templates",
                 "es.index_templates", counts, "index templates",
                 redact_secrets=False)

    r = _es("GET", "/_component_template")
    r.raise_for_status()
    _split_named(r.json(), "component_templates",
                 BACKUP_ROOT / "elasticsearch" / "component_templates",
                 "es.component_templates", counts, "component templates",
                 redact_secrets=False)

    r = _es("GET", "/_ingest/pipeline")
    r.raise_for_status()
    _split_named(r.json(), None,
                 BACKUP_ROOT / "elasticsearch" / "ingest_pipelines",
                 "es.ingest_pipelines", counts, "ingest pipelines",
                 redact_secrets=False)

    r = _es("GET", "/_data_stream")
    r.raise_for_status()
    streams = r.json().get("data_streams", [])
    slim = []
    for ds in streams:
        slim.append({
            "name": ds.get("name"),
            "timestamp_field": ds.get("timestamp_field"),
            "indices": [i.get("index_name") for i in ds.get("indices") or []],
            "generation": ds.get("generation"),
            "status": ds.get("status"),
            "template": ds.get("template"),
            "ilm_policy": ds.get("ilm_policy"),
            "hidden": ds.get("hidden"),
            "system": ds.get("system"),
            "allow_custom_routing": ds.get("allow_custom_routing"),
            "replicated": ds.get("replicated"),
            "next_generation_managed_by": ds.get("next_generation_managed_by"),
            "time_series": ds.get("time_series"),
        })
    write_json(BACKUP_ROOT / "elasticsearch" / "data_streams.json", slim, redact_secrets=False)
    counts["es.data_streams"] = len(slim)
    print(f"  data streams: {len(slim)}")

    r = _es("GET", "/_transform")
    r.raise_for_status()
    transforms = r.json().get("transforms", [])
    dest = BACKUP_ROOT / "elasticsearch" / "transforms"
    for t in transforms:
        write_json(dest / f"{safe_name(t['id'])}.json", t, redact_secrets=False)
    counts["es.transforms"] = len(transforms)
    print(f"  transforms: {len(transforms)}")

    r = _es("GET", "/_alias")
    if r.status_code == 200:
        write_json(BACKUP_ROOT / "elasticsearch" / "aliases.json", r.json(), redact_secrets=False)
        counts["es.alias_indices"] = len(r.json())
        print(f"  alias indices: {len(r.json())}")

    r = _es("GET", "/_inference")
    if r.status_code == 200:
        endpoints = r.json().get("endpoints", [])
        slim = []
        for ep in endpoints:
            slim.append({
                "inference_id": ep.get("inference_id"),
                "task_type": ep.get("task_type"),
                "service": ep.get("service"),
            })
        write_json(BACKUP_ROOT / "elasticsearch" / "inference_endpoints.json", slim)
        counts["es.inference_endpoints"] = len(slim)
        print(f"  inference endpoints: {len(slim)} (settings omitted)")

    r = _es("GET", "/_ml/trained_models")
    if r.status_code == 200:
        models = r.json().get("trained_model_configs", [])
        write_json(BACKUP_ROOT / "elasticsearch" / "trained_models.json", models, redact_secrets=False)
        counts["es.trained_models"] = len(models)
        print(f"  trained models: {len(models)}")


def run() -> Path:
    started = datetime.now(timezone.utc)
    print(f"== backing up Elastic objects -> {BACKUP_ROOT} ==")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()

    r = _es("GET", "/")
    r.raise_for_status()
    version = r.json().get("version", {})

    print("== kibana ==")
    backup_spaces(counts)
    backup_data_views(counts)
    backup_dashboards(counts)
    backup_saved_objects(counts)
    backup_alerting(counts)
    backup_connectors(counts)

    print("== fleet ==")
    backup_fleet(counts)

    print("== elasticsearch ==")
    backup_elasticsearch(counts)

    manifest = {
        "taken_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "elasticsearch": {
            "version": version.get("number"),
            "build_flavor": version.get("build_flavor"),
        },
        "kibana_url_host": urlparse(KIBANA_URL).netloc,
        "counts": dict(sorted(counts.items())),
        "notes": [
            "Document data is not included.",
            "API keys, enrollment tokens, and secret fields are redacted.",
            "Inference endpoint service_settings are omitted.",
            "kibana/saved_objects.ndjson can be imported via POST /api/saved_objects/_import.",
        ],
    }
    write_json(BACKUP_ROOT / "manifest.json", manifest)
    print(f"== done: {sum(counts.values())} objects in {BACKUP_ROOT} ==")
    return BACKUP_ROOT
