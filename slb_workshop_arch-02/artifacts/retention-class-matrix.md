# Retention class matrix

**Owner (role):** platform architects  
**Workshop evidence:** `scripts/verify.py`, streams in lab 1

| Class | Data value | Query frequency | Compliance | Serverless DLM | Hosted ILM / DLM | Cost tier |
|---|---|---|---|---|---|---|
| Platform metrics | Capacity / saturation | High | Low | 7d on `metrics-workshop.platform-prod` | hot → delete 7d | hot only |
| Application logs | Incident + trend | Medium | Low/medium | 30d prod / 14d nonprod | hot → warm 7d → delete 30d | hot + warm |
| Audit / security | Accountability | Low | High | 90d stand-in on `logs-workshop.audit-prod` | hot → warm → cold → frozen → delete 365d | include frozen |
| Traces (sampled) | Request path | High, short window | Low | 3d on `traces-workshop.app-prod` | hot → delete 3d | hot only |

**Q1 answer:** _who owns this matrix and exception approval at 10x scale?_
