# Template ownership model

**Owner (role):** platform (base) / domain teams (`@custom` only)

| Object | Owner | Teams may |
|---|---|---|
| `arch02-*-mappings` component templates | platform | read; not edit |
| Index templates `logs-workshop.*`, `metrics-workshop.*`, `traces-workshop.*` | platform | not fork |
| `logs-workshop.app@custom` (and future `@custom`) | domain team, reviewed | add **approved** fields only (`slb.well_id` is the example) |
| Ingest pipelines `logs-workshop.*` | platform | request processors via exception |
| Built-in `logs-*-*` / integration templates | Elastic + platform allow-list | not edit vendor defaults; use `@custom` |

Priority **500+** is reserved for platform templates so they beat generic `logs-*-*`.

**Q4 (templates):** _template modifications require central approval — yes/no._
