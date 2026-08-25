# Dataset / namespace taxonomy

**Owner (role):** platform architects  
**Workshop evidence:** lab 3 streams

## Naming

```text
<type>-<dataset>-<namespace>
```

| Part | Allowed values | Notes |
|---|---|---|
| type | `logs`, `metrics`, `traces` | no other types without an exception |
| dataset | bounded context or integration (`workshop.app`, `workshop.audit`, `workshop.platform`) | **not** one dataset per microservice |
| namespace | `prod`, `nonprod` | **working proposal: environment** |

## Who may create a dataset?

| Actor | May create | Path |
|---|---|---|
| Platform | yes | change the published taxonomy |
| Domain team | no | exception process |

Unsanctioned example (exists to show the failure): `logs-rogue.drilling-prod`.

**Q3 answer:** _environment, team, region, or tenancy? If not environment, what are the allowed values?_
