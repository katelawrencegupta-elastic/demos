# Lab 03 — EKS restart to reason (U3)

**Goal:** Reconstruct the pod failure timeline from metrics + events + logs (no real cluster required).

## Steps

1. Discover data view **Elastic Co. Kubernetes**. Filter `kubernetes.event.reason: OOMKilled`. Note pod names and timestamps.
   Saved searches: **Elastic Co. — EKS OOMKilled / BackOff** and **Elastic Co. — checkout-api restarting pods**.
2. Dashboard **Elastic Co. — EKS Restarts** (`elasticco-eks-restarts`): memory vs limit, restart count by pod, OOMKilled/BackOff over time.
3. ES|QL timeline for one pod (replace `POD`):

```esql
FROM metrics-elasticco.k8s.pod-default, logs-elasticco.k8s.event-default, logs-elasticco.checkout-default
| WHERE @timestamp > NOW() - 3 hours
| WHERE kubernetes.pod.name == "POD"
| KEEP @timestamp, kubernetes.event.reason, kubernetes.pod.memory.usage.bytes, kubernetes.pod.restart.count, message, service.version
| SORT @timestamp ASC
| LIMIT 50
```

3. Sketch the sequence: memory climb → `OutOfMemoryError` log → `OOMKilled` → `BackOff` → restart count++.
4. Tie to deploy: find `service.version: 2.4.1` on the OOM log lines.

Interactive deck: [../presentations/u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html)

## Done when

You can narrate “restart → reason” in under 60 seconds using only evidence fields (not screenshots of kubectl).
