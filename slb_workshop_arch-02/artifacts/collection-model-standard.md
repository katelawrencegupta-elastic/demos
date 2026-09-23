# Collection model standard

**Owner (role):** platform architects + domain team leads  
**Workshop evidence:** design review (lab 4). SRE-01 already ran Fleet vs EDOT as an operator lab.

| Team type / use case | Path | Config governance required |
|---|---|---|
| Shared platform collectors, regulated hosts | Fleet-managed Elastic Agent (`arch-02-platform-prod` / `-nonprod`) | Fleet policy owned by platform; System integration allow-list |
| Domain team still on Fleet (drilling-apps) | Fleet-managed Elastic Agent (`arch-02-drilling-prod`) | Same allow-list. Team does not add packages. |
| App teams needing vendor-neutral collector config | EDOT-native / standalone (`agents/docker-compose.otel.yml`, team `reservoir-apps`) | git (or equivalent) versioning, approval, promotion, audit **before** first prod ship — workshop evidence: `otel-agent.yml` |
| EDOT SDKs | Managed OTLP or Elastic Agent Gateway only | APM Server OTLP is unsupported (do not re-argue; see SRE-01) |

Switching paths later is allowed and **not free**.

**Decision recorded:** _which team types are allowed on EDOT-native on day one?_
