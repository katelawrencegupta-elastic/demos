# Lab 03 — EKS restart to reason (U3)

**Goal:** Reconstruct the pod failure timeline from metrics + events + logs (no real cluster required). Optional 30s on Inventory if hosts render.

## Steps

1. **Inventory (30s, skip if empty):** Observability → Inventory. Look for host/node under cluster `eks-elastic-prod-usc1` (`cloud.provider: aws`, `kubernetes.cluster.name`). Click through to the same checkout pod you will show on **EKS Restarts**. If Inventory ignores custom `metrics-elasticco.*` datasets, skip — do not force a dead click (see facilitator notes).
2. Discover data view **Elastic Co. Kubernetes**. Filter `kubernetes.event.reason: OOMKilled`. Note pod names and timestamps.
   Saved searches: **Elastic Co. — EKS OOMKilled / BackOff** and **Elastic Co. — checkout-api restarting pods**.
3. Dashboard **Elastic Co. — EKS Restarts** (`elasticco-eks-restarts`): memory vs limit, restart count by pod, OOMKilled/BackOff over time.
4. ES|QL timeline for one pod (replace `POD`):

```esql
FROM metrics-elasticco.k8s.pod-default, logs-elasticco.k8s.event-default, logs-elasticco.checkout-default
| WHERE @timestamp > NOW() - 3 hours
| WHERE kubernetes.pod.name == "POD"
| KEEP @timestamp, kubernetes.event.reason, kubernetes.pod.memory.usage.bytes, kubernetes.pod.restart.count, message, service.version
| SORT @timestamp ASC
| LIMIT 50
```

5. Sketch the sequence: memory climb → `OutOfMemoryError` log → `OOMKilled` → `BackOff` → restart count++.
6. Tie to deploy: find `service.version: 2.4.1` on the OOM log lines (`CartCache.retainAll`). One sentence: *this is the leak you’d confirm on a flamegraph* — Universal Profiling is not seeded; do not open the Profiling UI.
7. Synthetics is **not** part of this demo. Skip.

Interactive deck: [../presentations/u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html)

## Done when

You can narrate “restart → reason” in under 60 seconds using only evidence fields (not screenshots of kubectl).
