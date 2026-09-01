"""RCA agent — investigate checkout failure, approve remediation, email summary (U5)."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

import requests

from src.cases import add_comment, case_url, ensure_case, set_status
from src.config import (
    DS_CHECKOUT,
    DS_INCIDENT,
    DS_K8S_EVENT,
    DS_K8S_POD,
    DS_ORCHESTRATOR,
    DS_TRACES,
    ELASTIC_URL,
    ES_HEADERS,
    ROOT,
)
from src.generators.common import base_labels, ds_meta, iso
from src.incident_notify import render_email_html, send_incident_email
from src.sink.elastic import es_search
from src.world.model import World, load_world, utcnow


@dataclass
class IncidentReport:
    incident_id: str
    title: str
    service: str
    tenant: str
    severity: str
    status: str
    root_cause: str
    impact: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    remediation_actions: list[str] = field(default_factory=list)
    approval: dict = field(default_factory=dict)
    remediated: bool = False
    email_to: str = ""
    email_sent: bool = False
    generated_at: str = ""
    hero_trace_id: str = ""
    metrics: dict = field(default_factory=dict)
    case_id: str = ""
    case_url: str = ""
    evidence_ok: bool = True

    def to_email_report(self) -> dict:
        d = asdict(self)
        d["email_subject"] = (
            f"[Elastic Co.] {self.severity.upper()} — {self.service} incident resolved "
            f"({self.tenant})"
        )
        return d


def _count(index: str, query: dict, start: datetime, end: datetime) -> int:
    q = {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": iso(start), "lte": iso(end)}}},
                    query,
                ]
            }
        },
    }
    try:
        r = es_search(index, q)
        return int(r["hits"]["total"]["value"])
    except Exception:
        return 0


def _max_pod_restarts(service: str, start: datetime, end: datetime) -> int:
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": iso(start), "lte": iso(end)}}},
                    {"term": {"service.name": service}},
                    {"term": {"labels.demo": "elastic-co"}},
                ]
            }
        },
        "aggs": {"max_restarts": {"max": {"field": "kubernetes.pod.restart.count"}}},
    }
    try:
        r = es_search(DS_K8S_POD, body)
        val = r.get("aggregations", {}).get("max_restarts", {}).get("value") or 0
        return int(val)
    except Exception:
        return 0


def _apm_error_stats(service: str, start: datetime, end: datetime) -> dict:
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": iso(start), "lte": iso(end)}}},
                    {"term": {"processor.event": "transaction"}},
                    {"term": {"service.name": service}},
                    {"term": {"labels.demo": "elastic-co"}},
                ]
            }
        },
        "aggs": {
            "total": {"value_count": {"field": "trace.id"}},
            "failures": {
                "filter": {"term": {"event.outcome": "failure"}},
            },
            "p95": {"percentiles": {"field": "transaction.duration.us", "percents": [95]}},
            "by_tenant": {
                "terms": {"field": "tenant.id", "size": 5},
                "aggs": {
                    "p95": {"percentiles": {"field": "transaction.duration.us", "percents": [95]}}
                },
            },
        },
    }
    try:
        r = es_search(DS_TRACES, body)
        aggs = r.get("aggregations", {})
        total = aggs.get("total", {}).get("value", 0) or 0
        fails = aggs.get("failures", {}).get("doc_count", 0) or 0
        p95_us = aggs.get("p95", {}).get("values", {}).get("95.0", 0) or 0
        tenants = {}
        for b in aggs.get("by_tenant", {}).get("buckets", []):
            tenants[b["key"]] = round((b.get("p95", {}).get("values", {}).get("95.0", 0) or 0) / 1000, 0)
        return {
            "total": total,
            "failures": fails,
            "error_rate": round(fails / max(total, 1), 3),
            "p95_ms": round(p95_us / 1000, 0),
            "tenant_p95_ms": tenants,
        }
    except Exception:
        return {"total": 0, "failures": 0, "error_rate": 0, "p95_ms": 0, "tenant_p95_ms": {}}


def _evidence_supports_rca(
    stats: dict, threshold: float, oom: int, oom_logs: int, slow_db: int
) -> bool:
    """Planted story needs OOM evidence and slow DB, or a real error-rate breach."""
    has_oom = oom >= 1 or oom_logs >= 1
    has_db = slow_db >= 1
    has_errors = stats.get("error_rate", 0) >= threshold and stats.get("total", 0) > 5
    return (has_oom and has_db) or has_errors


def investigate(world: World, anchor: datetime | None = None) -> IncidentReport:
    """Query Elasticsearch and build a structured RCA report."""
    anchor = anchor or utcnow()
    start, end = world.incident_window(anchor)
    # Scope to the planted window so healthy recovery traffic does not dilute RCA.
    evidence_start, evidence_end = start, min(end, anchor)
    am = world.cfg.get("app_monitoring", {})
    service = am.get("monitored_service", "checkout-api")
    tenant = am.get("blast_tenant", world.blast_tenant["id"])
    inc = world.cfg["incident"]
    bad_ver = inc.get("bad_deploy_version", "2.4.1")
    good_ver = am.get("remediation", {}).get("rollback_version", "2.4.0")

    stats = _apm_error_stats(service, evidence_start, evidence_end)
    oom = _count(DS_K8S_EVENT, {"term": {"kubernetes.event.reason": "OOMKilled"}}, evidence_start, evidence_end)
    backoff = _count(DS_K8S_EVENT, {"term": {"kubernetes.event.reason": "BackOff"}}, evidence_start, evidence_end)
    max_restarts = _max_pod_restarts(service, evidence_start, evidence_end)
    oom_logs = _count(
        DS_CHECKOUT,
        {"query_string": {"query": "*OutOfMemory*", "fields": ["message"]}},
        evidence_start,
        evidence_end,
    )
    slow_db = _count(
        DS_TRACES,
        {
            "bool": {
                "must": [
                    {"term": {"span.type": "db"}},
                    {"term": {"tenant.id": tenant}},
                    {"range": {"span.duration.us": {"gte": 2_000_000}}},
                ]
            }
        },
        evidence_start,
        evidence_end,
    )
    orch_errors = _count(
        DS_ORCHESTRATOR,
        {
            "bool": {
                "must": [
                    {"term": {"tenant.id": tenant}},
                    {"terms": {"log.level": ["error", "warning"]}},
                ]
            }
        },
        evidence_start,
        evidence_end,
    )

    heroes = world.hero_traces(anchor)
    hero_tid = heroes[0].trace_id if heroes else ""

    tenant_p95 = stats["tenant_p95_ms"].get(tenant, stats["p95_ms"])
    slo = am.get("slo_target_ms", 400)
    threshold = am.get("error_rate_threshold", 0.10)

    evidence = [
        f"checkout-api error rate {stats['error_rate']*100:.1f}% "
        f"({stats['failures']}/{stats['total']} transactions) — threshold {threshold*100:.0f}%",
        f"Tenant {tenant} p95 latency {tenant_p95:.0f} ms vs SLO {slo} ms",
        f"{oom} OOMKilled Kubernetes events on checkout-api pods",
        f"{backoff} BackOff events (restart loop) on checkout-api",
        f"Max kubernetes.pod.restart.count = {max_restarts} on {service}",
        f"{oom_logs} OutOfMemoryError lines in checkout logs",
        f"{slow_db} slow PostgreSQL spans (>2s) for {tenant}",
        f"{orch_errors} orchestrator warning/error lines for {tenant} (DAG fulfillment.checkout)",
    ]
    if hero_tid:
        evidence.append(f"Correlated trace.id {hero_tid[:16]}… links orchestrator ↔ APM waterfall")

    weak = not _evidence_supports_rca(stats, threshold, oom, oom_logs, slow_db)
    if weak:
        evidence.append(
            "INSUFFICIENT EVIDENCE for planted RCA — re-run backfill; "
            "incident window may have aged out of the last 60 minutes"
        )

    root_cause = inc.get("root_cause", "").strip().replace("\n", " ")
    impact = (
        f"Tenant {tenant} checkout SLO burn: p95 {tenant_p95:.0f} ms vs target {slo} ms. "
        f"Peer tenants remain near baseline. Blast radius: {service}, orders-db, orchestrator retries."
    )

    timeline = [
        {"time": f"{start:%H:%M} UTC", "event": f"{service} deploy v{bad_ver} rolled out"},
        {"time": f"{start:%H:%M}+15m", "event": "Memory usage climbs toward pod limit (512 MiB)"},
        {"time": f"{start:%H:%M}+25m", "event": "OOMKilled events — pod restart loop begins"},
        {"time": f"{start:%H:%M}+30m", "event": f"Error rate exceeds {threshold*100:.0f}% — alert fires"},
        {"time": f"{start:%H:%M}+35m", "event": "Orchestrator retries amplify DB lock contention"},
        {"time": f"{end:%H:%M} UTC", "event": "RCA agent invoked — rollback planned"},
    ]

    remediation = am.get("remediation", {}).get("actions", [
        f"Roll back {service} to v{good_ver}",
        f"Pause orchestrator retries for {tenant}",
        f"Verify {tenant} p95 < {slo} ms",
    ])

    summary = (
        f"Incident on {service} affecting {tenant}: deploy v{bad_ver} introduced a memory leak "
        f"(CartCache.retainAll), causing OOMKills and {stats['error_rate']*100:.1f}% transaction failures. "
        f"Orchestrator DAG fulfillment.checkout retries worsened postgres lock contention. "
        f"Remediation: roll back to v{good_ver}."
    )

    return IncidentReport(
        incident_id=f"INC-{uuid.uuid4().hex[:12]}",
        title=f"{service} degradation — {tenant}",
        service=service,
        tenant=tenant,
        severity="high" if (stats["error_rate"] >= threshold or oom >= 1 or max_restarts >= 1) else "medium",
        status="detected",
        root_cause=root_cause,
        impact=impact,
        summary=summary,
        evidence=evidence,
        timeline=timeline,
        remediation_actions=remediation,
        hero_trace_id=hero_tid,
        metrics={**stats, "oom_events": oom, "backoff_events": backoff, "max_restarts": max_restarts},
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        email_to=am.get("rca_agent", {}).get("default_email", "oncall@elastic.co"),
        evidence_ok=not weak,
    )


def print_report(report: IncidentReport) -> None:
    print("\n" + "=" * 72)
    print(f"  RCA AGENT — {report.title}")
    print("=" * 72)
    print(f"  Incident ID : {report.incident_id}")
    print(f"  Service     : {report.service}")
    print(f"  Tenant      : {report.tenant}")
    print(f"  Severity    : {report.severity}")
    print(f"  Error rate  : {report.metrics.get('error_rate', 0)*100:.1f}%")
    print(f"  p95 latency : {report.metrics.get('p95_ms', 0):.0f} ms")
    print(f"  Restarts    : max={report.metrics.get('max_restarts', 0)} "
          f"OOM={report.metrics.get('oom_events', 0)} "
          f"BackOff={report.metrics.get('backoff_events', 0)}")
    if report.case_url:
        print(f"  Case        : {report.case_url}")
    print("\n  ROOT CAUSE")
    print(f"  {report.root_cause}\n")
    print("  EVIDENCE")
    for e in report.evidence:
        print(f"    • {e}")
    print("\n  PROPOSED REMEDIATION")
    for i, a in enumerate(report.remediation_actions, 1):
        print(f"    {i}. {a}")
    print("=" * 72 + "\n")


def request_approval(report: IncidentReport, auto: bool = False) -> bool:
    """Return True if remediation is approved."""
    if auto:
        report.approval = {"mode": "automatic", "approved_by": "rca-agent"}
        return True
    print("Human approval required before remediation and email notification.")
    print("Review the report above. Remediation will:")
    for a in report.remediation_actions:
        print(f"  • {a}")
    while True:
        ans = input("\nApprove remediation? [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            approver = input("Approver name [on-call]: ").strip() or "on-call"
            report.approval = {"mode": "manual", "approved_by": approver}
            return True
        if ans in ("n", "no", ""):
            report.approval = {"mode": "rejected", "approved_by": None}
            report.status = "rejected"
            return False
        print("Please enter y or n.")


def _case_description(report: IncidentReport) -> str:
    return (
        f"**Alert:** `elasticco-eks-pod-restarts`\n\n"
        f"{report.summary}\n\n"
        f"Cluster `eks-elastic-prod-usc1` · service `{report.service}` · "
        f"tenant `{report.tenant}` · incident `{report.incident_id}`."
    )


def _triage_markdown(report: IncidentReport) -> str:
    evidence = "\n".join(f"- {e}" for e in report.evidence)
    timeline = "\n".join(f"- `{t['time']}` — {t['event']}" for t in report.timeline)
    rem = "\n".join(f"{i}. {a}" for i, a in enumerate(report.remediation_actions, 1))
    return (
        f"## RCA agent triage — `{report.incident_id}`\n\n"
        f"**Severity:** {report.severity}  \n"
        f"**Root cause:** {report.root_cause}\n\n"
        f"### Evidence\n{evidence}\n\n"
        f"### Timeline\n{timeline}\n\n"
        f"### Proposed remediation\n{rem}\n"
    )


def post_triage_to_case(report: IncidentReport) -> None:
    """Open (or reuse) the Observability case and attach the RCA write-up."""
    case = ensure_case(
        description=_case_description(report),
        severity="high" if report.severity in ("high", "critical") else "medium",
    )
    if not case:
        print("  [warn] Kibana case was not created — continuing without it")
        return
    report.case_id = case["id"]
    report.case_url = case_url(case)
    updated = add_comment(case["id"], _triage_markdown(report))
    latest = updated if isinstance(updated, dict) and updated.get("id") else case
    inprog = set_status(latest, "in-progress")
    if isinstance(inprog, dict) and inprog.get("id"):
        latest = inprog
    print(f"  [ok] RCA triage posted to case {case_url(latest)}")


def post_resolution_to_case(report: IncidentReport, *, rejected: bool = False) -> None:
    if not report.case_id:
        return
    if rejected:
        comment = (
            f"## Remediation rejected — `{report.incident_id}`\n\n"
            "On-call declined the rollback. Case left open for follow-up."
        )
        add_comment(report.case_id, comment)
        return
    comment = (
        f"## Remediation applied — `{report.incident_id}`\n\n"
        f"Approved by **{report.approval.get('approved_by')}** "
        f"({report.approval.get('mode')}).\n\n"
        + "\n".join(f"- {a}" for a in report.remediation_actions)
        + f"\n\nStatus: **{report.status}**."
    )
    updated = add_comment(report.case_id, comment)
    if isinstance(updated, dict) and updated.get("id"):
        closed = set_status(updated, "closed")
        if closed:
            print(f"  [ok] case closed: {report.case_url}")


def _index_incident_event(report: IncidentReport, phase: str, message: str) -> None:
    doc = {
        "@timestamp": iso(utcnow()),
        "data_stream": ds_meta("logs", "elasticco.incident"),
        "labels": base_labels(),
        "message": message,
        "incident.id": report.incident_id,
        "incident.status": report.status,
        "incident.phase": phase,
        "incident.service": report.service,
        "incident.tenant.id": report.tenant,
        "incident.root_cause": report.root_cause,
        "incident.summary": report.summary,
        "incident.remediation": "; ".join(report.remediation_actions),
        "incident.approval.mode": report.approval.get("mode", ""),
        "incident.approval.approved_by": report.approval.get("approved_by") or "",
        "incident.email.to": report.email_to,
        "incident.email.sent": report.email_sent,
        "incident.case.id": report.case_id,
        "incident.case.url": report.case_url,
    }
    r = requests.post(
        f"{ELASTIC_URL}/{DS_INCIDENT}/_doc?refresh=wait_for",
        headers=ES_HEADERS,
        json=doc,
        timeout=60,
    )
    if r.status_code >= 300:
        print(f"  [warn] incident audit write: {r.status_code} {r.text[:200]}")


def apply_remediation(world: World, report: IncidentReport) -> None:
    """Record remediation in incident stream + emit rollback log line."""
    am = world.cfg.get("app_monitoring", {})
    good_ver = am.get("remediation", {}).get("rollback_version", "2.4.0")
    service = report.service

    _index_incident_event(
        report,
        "remediation",
        f"Remediation approved ({report.approval.get('mode')}): rollback {service} to v{good_ver}",
    )

    checkout_pods = world.pods_for("checkout-api")
    if checkout_pods:
        pod = checkout_pods[0]
        rollback_doc = {
            "@timestamp": iso(utcnow()),
            "data_stream": ds_meta("logs", "elasticco.checkout"),
            "labels": base_labels(),
            "service": {"name": service, "version": good_ver},
            "kubernetes": {
                "pod": {"name": pod.name},
                "namespace": pod.namespace,
                "deployment": {"name": service},
            },
            "log": {"level": "info"},
            "message": (
                f"Deployment rollback complete deploy={good_ver} pod={pod.name} "
                f"action=rollback incident={report.incident_id} approved_by={report.approval.get('approved_by')}"
            ),
        }
        r = requests.post(
            f"{ELASTIC_URL}/{DS_CHECKOUT}/_doc",
            headers=ES_HEADERS,
            json=rollback_doc,
            timeout=60,
        )
        if r.status_code < 300:
            print(f"  [ok] rollback log indexed for {service} v{good_ver}")
        else:
            print(f"  [warn] rollback log: {r.status_code}")

    report.remediated = True
    report.status = "resolved"


def run_incident_workflow(
    *,
    auto: bool = False,
    email: str | None = None,
    dry_run: bool = False,
    skip_email: bool = False,
    skip_case: bool = False,
) -> IncidentReport:
    """Full U5 workflow: investigate → case triage → approve → remediate → email."""
    world = load_world()
    report = investigate(world)
    if email:
        report.email_to = email

    if not skip_case:
        post_triage_to_case(report)

    print_report(report)
    _index_incident_event(report, "detected", f"RCA agent detected incident on {report.service}")

    if not report.evidence_ok:
        print(
            "[fail] RCA evidence does not support the planted story "
            "(need OOM + slow DB, or error rate above threshold). "
            "Re-run: python -m src.cli backfill --hours 6"
        )
        if dry_run:
            raise SystemExit(1)

    if dry_run:
        print("[dry-run] stopping before approval/remediation/email")
        return report

    approved = request_approval(report, auto=auto)
    if not approved:
        _index_incident_event(report, "rejected", "Human rejected remediation plan")
        post_resolution_to_case(report, rejected=True)
        print("Remediation rejected — no changes applied, email not sent.")
        return report

    apply_remediation(world, report)
    _index_incident_event(report, "resolved", report.summary)
    post_resolution_to_case(report)

    if skip_email:
        print(f"  [skip] email to {report.email_to}")
        return report

    sent, msg = send_incident_email(report.to_email_report(), report.email_to)
    report.email_sent = sent
    _index_incident_event(
        report,
        "notified",
        f"Incident summary emailed to {report.email_to}: {msg}",
    )
    print(f"  [{'ok' if sent else 'info'}] {msg}")
    if not sent:
        preview = ROOT / "output" / "incident-emails" / f"{report.incident_id}.html"
        print(f"  Open {preview} to review the email body before sending manually.")

    return report
