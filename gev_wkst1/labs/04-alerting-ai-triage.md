# Lab 04 — Alert quality: noisy vs SLO vs correlation (U4)

**Goal:** Contrast three objects — noisy CPU, a **native** checkout SLO, and the ES|QL correlation alert that starts RCA. U5 (Agent Builder) is the close, not a pasted AI Assistant prompt.

## Steps

1. Observability → Alerts / Rules: open `elasticco-noisy-node-cpu`, `elasticco-checkout-correlated-rca`, and `elasticco-eks-pod-restarts`.
2. Observability → **SLOs**: open **`elasticco-slo-checkout-availability`** (checkout-api / acme-retail). This is what you page on — not the ES|QL rule.
3. Write the differences: noisy (no context) vs native SLO (error budget) vs correlation (OOM + slow DB + OOM logs, Cases action).
4. **Tighten the noisy rule (design only or edit):** require `service.name: checkout-api` and a sustained window, or disable it for the demo project.
5. Observability → Cases: open the case created by `elasticco-eks-pod-restarts` or `elasticco-checkout-correlated-rca`.
6. Optional contrast: Observability AI Assistant + the **contrast opener** in [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md). Do not treat that paste as the demo close — continue to [Lab 05](05-app-monitoring-rca.md) / Agent Builder.
7. Optional: import [../kibana/knowledge-base-checkout-oom.md](../kibana/knowledge-base-checkout-oom.md) into a knowledge base.

Interactive deck: [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)

## Done when

You can name three objects: anti-pattern CPU, native SLO burn, correlated RCA alert — and you have **not** called the ES|QL rule an SLO.

**Next:** [Lab 05 — Agent Builder RCA](05-app-monitoring-rca.md) (U5) · Deck: [u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)
