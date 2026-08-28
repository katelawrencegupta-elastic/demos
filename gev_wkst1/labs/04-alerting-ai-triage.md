# Lab 04 — Alert quality + AI triage (U4)

**Goal:** Contrast noisy vs quality alerts; drive AI to the planted RCA.

## Steps

1. Observability → Alerts / Rules: open `elasticco-noisy-node-cpu`, `elasticco-checkout-slo-burn`, and `elasticco-eks-pod-restarts`.
2. Write three differences: context fields, query specificity, actionability for on-call.
3. **Tighten the noisy rule (design only or edit):** require `service.name: checkout-api` and a sustained window, or disable it for the demo project.
4. Observability → Cases: open **EKS restart loop — checkout-api (eks-elastic-prod-usc1)** (created by the RCA agent / Cases action).
5. Open Observability AI Assistant. Paste the **Primary RCA prompt** from [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md).
6. Optional: import [../kibana/knowledge-base-checkout-oom.md](../kibana/knowledge-base-checkout-oom.md) into the AI knowledge base; re-ask “what should we do first?”

Interactive deck: [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)

## Done when

AI (or your manual write-up) lists: v2.4.1 leak → OOM → orchestrator retries → slow `FOR UPDATE` for `acme-retail`, with rollback to 2.4.0 as remediation.

**Next:** [Lab 05 — Application monitoring + RCA agent](05-app-monitoring-rca.md) (U5) · Deck: [u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)
