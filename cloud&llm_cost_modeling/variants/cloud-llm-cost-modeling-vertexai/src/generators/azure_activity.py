"""Azure activity logs -> logs-azure.activitylogs-default.
Raw event-hub-style record JSON in `message`."""
import json

from src.generators.common import log_doc, poisson_count, spread
from src.world.model import stable_uuid
from src.world.scenarios import activity_multiplier, rng_for

DATA_STREAM = "logs-azure.activitylogs-default"
DATASET = "azure.activitylogs"
BASE_RATE_PER_HOUR = 40

OPS = [
    (8, "MICROSOFT.COMPUTE/VIRTUALMACHINES/START/ACTION", "vm"),
    (6, "MICROSOFT.COMPUTE/VIRTUALMACHINES/DEALLOCATE/ACTION", "vm"),
    (4, "MICROSOFT.COMPUTE/VIRTUALMACHINES/RESTART/ACTION", "vm"),
    (5, "MICROSOFT.COMPUTE/VIRTUALMACHINES/WRITE", "vm"),
    (6, "MICROSOFT.STORAGE/STORAGEACCOUNTS/WRITE", "storage"),
    (3, "MICROSOFT.AUTHORIZATION/ROLEASSIGNMENTS/WRITE", "sub"),
    (7, "MICROSOFT.RESOURCES/DEPLOYMENTS/WRITE", "rg"),
    (4, "MICROSOFT.NETWORK/NETWORKSECURITYGROUPS/WRITE", "rg"),
]


def _record(world, rng, ts, sub, op, scope_kind):
    if scope_kind == "vm":
        pool = [v for v in world.azure_vms if v["subscription"]["id"] == sub["id"]]
        vm = rng.choice(pool)
        resource_id = vm["id"].upper()
    else:
        rg = rng.choice(sub["resource_groups"])
        if scope_kind == "storage":
            name = f"stmeridian{rng.randint(100, 999)}"
            resource_id = (f"/SUBSCRIPTIONS/{sub['id'].upper()}/RESOURCEGROUPS/{rg.upper()}"
                           f"/PROVIDERS/MICROSOFT.STORAGE/STORAGEACCOUNTS/{name.upper()}")
        elif scope_kind == "rg":
            resource_id = (f"/SUBSCRIPTIONS/{sub['id'].upper()}/RESOURCEGROUPS/{rg.upper()}"
                           f"/PROVIDERS/MICROSOFT.RESOURCES/DEPLOYMENTS/DEPLOY-{rng.randint(1000, 9999)}")
        else:
            resource_id = f"/SUBSCRIPTIONS/{sub['id'].upper()}"

    humans = world.humans_in_bu(sub["business_unit"])
    ident = rng.choice(humans)
    ok = rng.random() > 0.03
    tenant = world.cfg["azure"]["tenant_id"]
    action = op.title().replace("Microsoft", "Microsoft").lower()
    return {
        "time": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "resourceId": resource_id,
        "operationName": op,
        "operationVersion": "2024-03-01",
        "category": "Administrative",
        "resultType": "Success" if ok else "Failure",
        "resultSignature": "Succeeded." if ok else "Failed.Conflict",
        "durationMs": rng.randint(150, 9000),
        "callerIpAddress": rng.choice(ident.source_ips),
        "correlationId": stable_uuid("azcorr", ts.isoformat(), rng.random()),
        "identity": {
            "authorization": {
                "scope": resource_id,
                "action": action,
                "evidence": {
                    "role": "Contributor",
                    "roleAssignmentScope": f"/subscriptions/{sub['id']}",
                    "roleAssignmentId": stable_uuid("azra", ident.user, sub["id"]),
                    "roleDefinitionId": "b24988ac618042a0ab8820f7382dd24c",
                    "principalId": stable_uuid("azpid", ident.user).replace("-", ""),
                    "principalType": "User",
                },
            },
            "claims": {
                "aud": "https://management.core.windows.net/",
                "iss": f"https://sts.windows.net/{tenant}/",
                "name": ident.user.replace(".", " ").title(),
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name": ident.email,
                "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn": ident.email,
                "http://schemas.microsoft.com/identity/claims/objectidentifier": stable_uuid("azoid", ident.user),
            },
        },
        "level": "Information",
        "location": world.cfg["azure"]["region"],
        "properties": {
            "statusCode": "OK" if ok else "Conflict",
            "serviceRequestId": stable_uuid("azreq", ts.isoformat(), rng.random()),
            "eventCategory": "Administrative",
            "entity": resource_id,
            "message": op,
        },
    }


def emit(world, t0, t1, anchor):
    rng = rng_for("azactivity", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600
    mult = activity_multiplier(world, t0, anchor)
    subs = world.cfg["azure"]["subscriptions"]

    for _ in range(poisson_count(rng, BASE_RATE_PER_HOUR * mult * hours)):
        ts = spread(rng, t0, t1)
        sub = rng.choices(subs, weights=[3, 1, 1.2][:len(subs)])[0]
        _, op, scope_kind = rng.choices(OPS, weights=[o[0] for o in OPS])[0]
        yield log_doc(DATASET, ts, json.dumps(
            _record(world, rng, ts, sub, op, scope_kind)))
