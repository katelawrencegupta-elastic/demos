"""Deterministic expansion of config/world.yaml into a full resource inventory.

Every generator consumes the same World instance, so identifiers (account ids,
instance ids, user ARNs, source IPs, tags) line up across activity logs,
security findings, metrics, and billing -- which is what makes correlation in
Elastic work.
"""
import hashlib
import random
from dataclasses import dataclass, field

import yaml

from src.config import WORLD_CONFIG

# hourly on-demand USD prices used to tie usage to billing
EC2_TYPES = {
    "t3.medium": 0.0416, "m5.large": 0.096, "m5.xlarge": 0.192,
    "c5.2xlarge": 0.34, "r5.large": 0.126, "g4dn.xlarge": 0.526,
}
GCE_TYPES = {
    "e2-medium": 0.033, "n2-standard-4": 0.194, "n2-standard-8": 0.389,
    "a2-highgpu-1g": 3.67,
}
AZURE_VM_SIZES = {
    "Standard_B2s": 0.041, "Standard_D4s_v5": 0.192,
    "Standard_D8s_v5": 0.384, "Standard_E4s_v5": 0.252,
}

APP_NAMES = ["checkout", "catalog", "search", "payments", "ingest", "api-gw",
             "worker", "cache", "featurestore", "trainer", "scoring", "etl",
             "vdi", "identity", "fileshare", "monitor", "bastion", "web"]


def _tags_with_drift(rng, bu, cost_center, env, app):
    """~80% fully tagged; the rest exhibit realistic drift."""
    roll = rng.random()
    tags = {"env": env, "team": bu, "app": app}
    if cost_center is None:
        # skunkworks: mostly untagged shadow IT
        return {} if rng.random() < 0.7 else {"app": app}
    if roll < 0.80:
        tags["cost_center"] = cost_center
    elif roll < 0.90:
        pass  # missing cost_center entirely
    elif roll < 0.95:
        tags["costcenter"] = cost_center      # misspelled key
    else:
        tags = {}                             # completely untagged
    return tags


@dataclass
class Ec2Instance:
    instance_id: str
    account: dict
    region: str
    az: str
    itype: str
    name: str
    tags: dict
    private_ip: str
    public_ip: str
    hourly_usd: float = 0.0
    monitored: bool = True

    def __post_init__(self):
        self.hourly_usd = EC2_TYPES[self.itype]


@dataclass
class Identity:
    user: str
    bu: str
    role: str
    email: str
    source_ips: list
    is_service: bool = False
    aws_access_key: str = ""


@dataclass
class World:
    cfg: dict
    rng: random.Random
    ec2_instances: list = field(default_factory=list)
    gce_instances: list = field(default_factory=list)
    azure_vms: list = field(default_factory=list)
    identities: list = field(default_factory=list)
    attacker_ip: str = "185.220.101.34"      # crypto-incident C2 / miner pool
    mining_pool_ip: str = "45.9.148.117"

    # -- lookups ----------------------------------------------------------
    @property
    def aws_accounts(self):
        return self.cfg["aws"]["accounts"]

    def aws_account(self, acct_id):
        return next(a for a in self.aws_accounts if a["id"] == acct_id)

    def bu(self, key):
        return next(b for b in self.cfg["business_units"] if b["key"] == key)

    def humans_in_bu(self, bu_key):
        return [i for i in self.identities if i.bu == bu_key and not i.is_service]

    def ec2_in_account(self, acct_id):
        return [i for i in self.ec2_instances if i.account["id"] == acct_id]

    @property
    def scenarios(self):
        return self.cfg["scenarios"]


def _hex(rng, n):
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


def _corp_ip(rng):
    return f"203.0.113.{rng.randint(2, 250)}"


def _vpc_ip(rng):
    return f"10.{rng.randint(0, 3)}.{rng.randint(0, 254)}.{rng.randint(2, 254)}"


def _pub_ip(rng):
    return f"54.{rng.randint(64, 95)}.{rng.randint(0, 254)}.{rng.randint(2, 254)}"


def load_world() -> World:
    cfg = yaml.safe_load(WORLD_CONFIG.read_text())
    rng = random.Random(cfg["seed"])
    w = World(cfg=cfg, rng=rng)

    # identities -----------------------------------------------------------
    domain = cfg["domain"]
    for h in cfg["identities"]["humans"]:
        w.identities.append(Identity(
            user=h["user"], bu=h["bu"], role=h["role"],
            email=f"{h['user']}@{domain}",
            source_ips=[_corp_ip(rng), _corp_ip(rng)],
            aws_access_key="AKIA" + _hex(rng, 16).upper(),
        ))
    for s in cfg["identities"]["service_accounts"]:
        w.identities.append(Identity(
            user=s["user"], bu=s["bu"], role="service",
            email=f"{s['user']}@svc.{domain}",
            source_ips=[_vpc_ip(rng)],
            is_service=True,
            aws_access_key="AKIA" + _hex(rng, 16).upper(),
        ))

    # AWS EC2 inventory ----------------------------------------------------
    regions = cfg["aws"]["regions"]
    for acct in cfg["aws"]["accounts"]:
        bu = w.bu(acct["business_unit"])
        for n in range(acct["ec2_count"]):
            region = rng.choices(regions, weights=[5, 3, 2])[0]
            itype = rng.choice(list(EC2_TYPES))
            if acct["business_unit"] == "skunkworks" and rng.random() < 0.4:
                itype = "g4dn.xlarge"        # GPU boxes in the sandbox
            app = rng.choice(APP_NAMES)
            w.ec2_instances.append(Ec2Instance(
                instance_id="i-0" + _hex(rng, 16),
                account=acct, region=region, az=region + rng.choice("abc"),
                itype=itype,
                name=f"{acct['env']}-{app}-{n:02d}",
                tags=_tags_with_drift(rng, acct["business_unit"],
                                      bu["cost_center"], acct["env"], app),
                private_ip=_vpc_ip(rng), public_ip=_pub_ip(rng),
                monitored=(acct["env"] == "prod" or rng.random() < 0.5),
            ))

    # GCP GCE inventory ----------------------------------------------------
    for proj in cfg["gcp"]["projects"]:
        for n in range(proj["gce_count"]):
            mtype = rng.choice(list(GCE_TYPES))
            if proj["business_unit"] == "mlplatform" and rng.random() < 0.3:
                mtype = "a2-highgpu-1g"
            app = rng.choice(APP_NAMES)
            zone = rng.choice(cfg["gcp"]["regions"]) + rng.choice(["-a", "-b"])
            w.gce_instances.append({
                "id": str(rng.randint(10 ** 18, 9 * 10 ** 18)),
                "name": f"{proj['env']}-{app}-{n:02d}",
                "project": proj, "zone": zone, "machine_type": mtype,
                "hourly_usd": GCE_TYPES[mtype],
                "labels": _tags_with_drift(
                    rng, proj["business_unit"],
                    w.bu(proj["business_unit"])["cost_center"],
                    proj["env"], app),
            })

    # Azure VM inventory ---------------------------------------------------
    for sub in cfg["azure"]["subscriptions"]:
        for n in range(sub["vm_count"]):
            size = rng.choice(list(AZURE_VM_SIZES))
            rg = rng.choice(sub["resource_groups"])
            app = rng.choice(APP_NAMES)
            name = f"vm-{app}-{n:02d}"
            w.azure_vms.append({
                "name": name, "size": size, "resource_group": rg,
                "subscription": sub,
                "id": (f"/subscriptions/{sub['id']}/resourceGroups/{rg}"
                       f"/providers/Microsoft.Compute/virtualMachines/{name}"),
                "hourly_usd": AZURE_VM_SIZES[size],
                "tags": _tags_with_drift(
                    rng, sub["business_unit"],
                    w.bu(sub["business_unit"])["cost_center"],
                    sub["env"], app),
            })

    return w


def stable_uuid(*parts) -> str:
    """Deterministic uuid-shaped string from arbitrary parts."""
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
