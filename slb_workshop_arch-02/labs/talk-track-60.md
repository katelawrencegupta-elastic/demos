# ARCH-02 talk track — 60 minutes

**Session:** Lifecycle, Governance & Standards (lecture)  
**When:** Wed Sep 23, 2026 · ARCH-02  
**Audience:** Architects  
**Visual:** keep the governance-decisions slide (deck slide 3) on screen after the open.  
**Live cluster:** Elastic Cloud Hosted `f427dfc2751c468f942dcf7e7d46b323`

This is a **design review**. Do not start Docker or enroll agents. Hands-on lives in labs 1–4. Show Kibana only when a decision needs evidence (retention table, schema miss).

| Clock | Block | Minutes |
|---|---|---|
| 0:00 | Open — do not repeat the 5-tool mess | 5 |
| 5:00 | Seven governance decisions | 8 |
| 13:00 | Retention classes (policy first) | 10 |
| 23:00 | Collection model (Fleet vs EDOT) | 8 |
| 31:00 | ECS ↔ OTel: aligned, not unified | 10 |
| 41:00 | Taxonomy, templates, ownership | 8 |
| 49:00 | Artifacts + Q1–Q4 | 8 |
| 57:00 | Close | 3 |

**If you are over time, cut in this order:** Fleet UI glance, hosted ILM mapping detail, template `@custom` walk. **Never cut:** policy-before-mechanism, mixed-authoring prohibition, Q1–Q4.

Do not paste API keys.

---

## 0:00–5:00 · Open

**Thesis (say this almost verbatim):**  
SLB is consolidating 5+ tools into one platform. Scaling that without governance recreates the fragmented dashboards, schemas, and ownership you are trying to leave. OTel/EDOT makes this **harder**, not easier — it expands the governance surface. With 200 engineers across three sites, standards must be explicit, not tribal. The objective is controlled consistency that still leaves teams autonomy.

**Promise the room:** by minute 57 they can name retention classes, say who owns templates, and answer whether a new dataset is allowed without a meeting.

---

## 5:00–13:00 · Seven decisions

Walk the table on slide 3. These are design choices, not product features:

| Decision | The question |
|---|---|
| Retention classes | What data deserves different retention? |
| Lifecycle mechanism | ILM vs data stream lifecycle — cover both |
| Collection model | Fleet where central policy is required; EDOT-native only with external config governance |
| Schema standard | Where is translation required? Where is mixed authoring prohibited? |
| Dataset / namespace | Who can create datasets? What does namespace **mean**? |
| Template ownership | Who owns base mappings? How do teams extend? |
| Exception process | What needs central approval, and how fast? |

**Line to say:** if you leave this room with concepts and no owners, you have not done the session.

---

## 13:00–23:00 · Retention

**Architect rule:** don't define governance as ILM settings. Define classes by value, cost, and compliance, **then** map to a mechanism.

| Class | Workshop DLM (this cluster) | Hosted ILM mapping |
|---|---|---|
| Platform metrics | 7d | hot → delete 7d |
| Application logs | 30d prod / 14d nonprod | hot → warm 7d → delete 30d |
| Audit / security | 90d (stand-in for 1y+) | hot → warm → cold → frozen → delete 365d |
| Traces | 3d sampled | hot → delete 3d |

On **this** Serverless project the lever is `data_retention`. ILM is unavailable. In 9.5, DLM frozen searchable snapshots are GA on hosted — the ILM-vs-DLM choice is real. Do not hardcode one.

Evidence: `scripts/verify.py` prints the four classes and their lifecycle.

---

## 23:00–31:00 · Collection model

This is an **operating model** decision.

- **Fleet-managed:** central policy, health, versions. Less collector flexibility. Use where central governance is required.
- **EDOT-native / standalone:** full OTel flexibility. Config lifecycle (version, approve, promote, audit) is now **the team's problem**. If SLB allows this path, that governance model must exist on day one.

SRE-01 already covered "switching is allowed and not free." Do not re-argue Agent vs OTel. Architects decide **who is allowed which path**.

---

## 31:00–41:00 · ECS ↔ OTel

9.5 alignment **increases** the need for a standard. Four buckets from the deck:

1. Clean mappings (aliases / light transforms).
2. Equivalent but renamed — `trace.id` ↔ `trace_id`, `message` ↔ `body.text`, `log.level` ↔ `severity_text`. Queries break without translation.
3. Related / translation required — aliasing would lie.
4. Metrics data-model gap — not a rename. Cannot be solved by field aliases.

**Working proposal to put on the table:** new telemetry is OTel-native. ECS-compatible paths are migration exceptions. Mixed authoring on one stream is prohibited.

Evidence: `scripts/compare_schema.py` — the same incident is invisible across schemas.

---

## 41:00–49:00 · Taxonomy and ownership

```text
<type>-<dataset>-<namespace>
logs-workshop.app-prod
```

- **type** = logs / metrics / traces  
- **dataset** = integration or service shape (`workshop.app`), not one dataset per microservice  
- **namespace** = working proposal **environment** (`prod` / `nonprod`). If you don't decide, every team picks a different answer.

Platform owns base component templates. Teams extend via `@custom` (see `logs-workshop.app@custom` → `slb.well_id`). Unsanctioned datasets (`logs-rogue.drilling-prod`) skip the contract.

---

## 49:00–57:00 · Artifacts + questions

Leave with six named deliverables (slides 10 / `artifacts/`):

1. Retention class matrix  
2. Dataset / namespace taxonomy  
3. Schema decision policy  
4. Collection model standard  
5. Template ownership model  
6. Exception process  

Then the four questions. Do not skip Q2 (default schema) or Q3 (namespace).

---

## 57:00–60:00 · Close

**Checkout:** name one retention class, one thing only platform may change, and one thing a domain team may change without an exception. If they cannot, the ownership model is still tribal.
