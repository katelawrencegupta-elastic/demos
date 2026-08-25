# Exception process

**Owner (role):** _name the approving role_  
**SLA:** _e.g. 5 business days_

| Change | Central approval? | Notes |
|---|---|---|
| New dataset | **yes** | fastest path to fragmentation |
| New namespace value | **yes** | if namespace ≠ environment, this table must change |
| Custom field (`@custom`) | **yes** unless on a published allow-list | `slb.well_id` is pre-approved for this workshop |
| New ingest pipeline / processor | **yes** | shared processors stay central |
| Template fork | **yes, discouraged** | prefer `@custom` |
| Retention class change | **yes** | cost + compliance |
| Collector path (Fleet ↔ EDOT-native) | **yes** | operating-model change |

Request path: _ticket / PR against `artifacts/` + this file_.

**Q4 answer:** _list the change types that always require approval._
