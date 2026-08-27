# Lab 04 — Alert quality + AI triage

**Goal:** Contrast noisy vs quality alerts; drive AI to the planted RCA.

## Steps

1. Observability → Alerts / Rules: open `elasticco-noisy-node-cpu` and `elasticco-checkout-slo-burn`.
2. Write three differences: context fields, query specificity, actionability for on-call.
3. **Tighten the noisy rule (design only or edit):** require `service.name: checkout-api` and a sustained window, or disable it for the demo project.
4. Open Observability AI Assistant. Paste the **Primary RCA prompt** from [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md).
5. Optional: add the runbook note from that file to the AI knowledge base; re-ask “what should we do first?”

## Done when

AI (or your manual write-up) lists: v2.4.1 leak → OOM → orchestrator retries → slow `FOR UPDATE` for `acme-retail`, with rollback to 2.4.0 as remediation.
