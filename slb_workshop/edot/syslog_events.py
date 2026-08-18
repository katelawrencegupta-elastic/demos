"""Synthetic host syslog lines: ssh, sudo, useradd/groupadd.

Used by the OTLP factory and by Fleet agents via /var/log/secure and /var/log/messages.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from opentelemetry._logs import SeverityNumber

OPERATORS = ("klg", "deploy", "rigops", "sre-oncall", "ansible", "welldata")
INVALID_USERS = ("oracle", "admin", "ubuntu", "pi", "test")
GROUPS = ("sudo", "docker", "rigops", "sre", "welldata", "systemd-journal")
INTERNAL_IPS = ("10.12.4.18", "10.8.0.14", "10.48.2.7", "10.12.4.41", "10.2.16.9")
EXTERNAL_IPS = ("185.220.101.4", "45.33.32.156", "91.219.236.88", "103.45.78.12")
SUDO_COMMANDS = (
    "/usr/bin/systemctl restart elastic-agent",
    "/usr/bin/systemctl status kibana",
    "/usr/bin/apt-get update",
    "/usr/bin/journalctl -u elastic-agent -n 100",
    "/usr/sbin/useradd -m -s /bin/bash {user}",
    "/usr/sbin/groupadd {group}",
    "/usr/sbin/usermod -aG docker {user}",
    "/usr/bin/visudo",
    "/bin/bash",
    "/usr/bin/cat /etc/shadow",
    "/usr/bin/chmod 600 /etc/elastic-agent/fleet.yml",
)


def syslog_prefix(
    host: str, ident: str, pid: int, when: datetime | None = None
) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%b %e %H:%M:%S")
    return f"{stamp} {host} {ident}[{pid}]"


def uid_for(user: str) -> int:
    return 1000 + (sum(ord(c) for c in user) % 800)


def gid_for(group: str) -> int:
    return 1000 + (sum(ord(c) for c in group) % 800)


def ssh_fp(rng: random.Random) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    return "SHA256:" + "".join(rng.choice(alphabet) for _ in range(43))


def base_attrs(
    *,
    ident: str,
    pid: int,
    action: str,
    outcome: str,
    category: str,
    user: str | None = None,
    log_path: str = "/var/log/secure",
) -> dict[str, object]:
    attrs: dict[str, object] = {
        "event.kind": "event",
        "event.category": category,
        "event.dataset": "system.auth",
        "event.action": action,
        "event.outcome": outcome,
        "event.provider": ident,
        "process.name": ident,
        "process.pid": pid,
        "log.file.path": log_path,
        "log.syslog.facility.name": "authpriv",
        "log.syslog.facility.code": 10,
        "log.syslog.appname": ident,
        "log.syslog.procid": str(pid),
    }
    if user:
        attrs["user.name"] = user
        attrs["related.user"] = user
    return attrs


def ssh_event(
    host: str, rng: random.Random, when: datetime | None = None
) -> tuple[str, dict[str, object], SeverityNumber]:
    pid = rng.randint(1200, 32000)
    port = rng.randint(40000, 62000)
    ident = "sshd"
    prefix = syslog_prefix(host, ident, pid, when)
    roll = rng.random()

    if roll < 0.45:
        user = rng.choice(OPERATORS)
        ip = rng.choice(INTERNAL_IPS)
        method = "publickey" if rng.random() < 0.75 else "password"
        fp = f": ED25519 {ssh_fp(rng)}" if method == "publickey" else ""
        body = f"{prefix}: Accepted {method} for {user} from {ip} port {port} ssh2{fp}"
        attrs = base_attrs(
            ident=ident, pid=pid, action="ssh_login", outcome="success",
            category="authentication", user=user,
        )
        attrs.update({
            "event.type": "start",
            "source.ip": ip,
            "source.port": port,
            "network.peer.address": ip,
            "auth.method": method,
        })
        return body, attrs, SeverityNumber.INFO

    if roll < 0.65:
        user = rng.choice(OPERATORS)
        uid = uid_for(user)
        opened = rng.random() < 0.6
        if opened:
            body = (
                f"{prefix}: pam_unix(sshd:session): session opened for user {user}(uid={uid}) by (uid=0)"
            )
            action, etype, outcome = "session_opened", "start", "success"
        else:
            body = f"{prefix}: pam_unix(sshd:session): session closed for user {user}"
            action, etype, outcome = "session_closed", "end", "success"
        attrs = base_attrs(
            ident=ident, pid=pid, action=action, outcome=outcome,
            category="authentication", user=user,
        )
        attrs.update({"event.type": etype, "user.id": str(uid)})
        return body, attrs, SeverityNumber.INFO

    invalid = rng.random() < 0.55
    user = rng.choice(INVALID_USERS if invalid else OPERATORS)
    ip = rng.choice(EXTERNAL_IPS)
    label = f"invalid user {user}" if invalid else user
    body = f"{prefix}: Failed password for {label} from {ip} port {port} ssh2"
    attrs = base_attrs(
        ident=ident, pid=pid, action="ssh_login", outcome="failure",
        category="authentication", user=user,
    )
    attrs.update({
        "event.type": "start",
        "source.ip": ip,
        "source.port": port,
        "network.peer.address": ip,
        "auth.method": "password",
    })
    if invalid:
        attrs["error.message"] = "invalid user"
    return body, attrs, SeverityNumber.WARN


def sudo_event(
    host: str, rng: random.Random, when: datetime | None = None
) -> tuple[str, dict[str, object], SeverityNumber]:
    pid = rng.randint(1200, 32000)
    user = rng.choice(OPERATORS)
    tty = rng.randint(0, 8)
    pwd = f"/home/{user}" if rng.random() < 0.7 else "/tmp"
    target = rng.choice(OPERATORS)
    cmd = rng.choice(SUDO_COMMANDS).format(user=target, group=rng.choice(GROUPS))
    ident = "sudo"
    prefix = syslog_prefix(host, ident, pid, when)
    denied = rng.random() < 0.18
    if denied:
        body = (
            f"{prefix}: {user} : user NOT in sudoers ; TTY=pts/{tty} ; "
            f"PWD={pwd} ; USER=root ; COMMAND={cmd}"
        )
        outcome, sev = "failure", SeverityNumber.WARN
        action = "sudo_denied"
    else:
        body = (
            f"{prefix}: {user} : TTY=pts/{tty} ; PWD={pwd} ; USER=root ; COMMAND={cmd}"
        )
        outcome, sev = "success", SeverityNumber.INFO
        action = "sudo_command"
    attrs = base_attrs(
        ident=ident, pid=pid, action=action, outcome=outcome,
        category="authentication", user=user,
    )
    attrs.update({
        "event.type": "info",
        "process.command_line": cmd,
        "user.effective.name": "root",
        "sudo.command": cmd,
        "sudo.tty": f"pts/{tty}",
        "sudo.pwd": pwd,
    })
    return body, attrs, sev


def account_event(
    host: str, rng: random.Random, when: datetime | None = None
) -> tuple[str, dict[str, object], SeverityNumber]:
    pid = rng.randint(1200, 32000)
    actor = rng.choice(("root", "ansible", "sre-oncall"))
    kind = rng.choice(("groupadd", "useradd", "usermod", "gpasswd"))
    if kind == "groupadd":
        group = rng.choice(("rigops", "welldata", "sre", "docker", "nightshift"))
        gid = gid_for(group)
        ident = "groupadd"
        prefix = syslog_prefix(host, ident, pid, when)
        body = f"{prefix}: group added to /etc/group: name={group}, GID={gid}"
        attrs = base_attrs(
            ident=ident, pid=pid, action="group_add", outcome="success", category="iam",
        )
        attrs.update({
            "event.type": "change",
            "group.name": group,
            "group.id": str(gid),
            "user.name": actor,
            "related.user": actor,
        })
        return body, attrs, SeverityNumber.INFO

    if kind == "useradd":
        user = rng.choice(("rigops", "welldata", "nightshift", "contractor", "breakglass"))
        uid = uid_for(user)
        ident = "useradd"
        prefix = syslog_prefix(host, ident, pid, when)
        body = (
            f"{prefix}: new user: name={user}, UID={uid}, GID={uid}, "
            f"home=/home/{user}, shell=/bin/bash"
        )
        attrs = base_attrs(
            ident=ident, pid=pid, action="user_add", outcome="success",
            category="iam", user=user,
        )
        attrs.update({
            "event.type": "change",
            "user.id": str(uid),
            "group.id": str(uid),
            "group.name": user,
            "user.home": f"/home/{user}",
            "user.shell": "/bin/bash",
            "related.user": f"{user},{actor}",
        })
        return body, attrs, SeverityNumber.INFO

    user = rng.choice(OPERATORS)
    group = rng.choice(GROUPS)
    if kind == "usermod":
        ident = "usermod"
        prefix = syslog_prefix(host, ident, pid, when)
        body = f"{prefix}: add '{user}' to group '{group}'"
        action = "group_member_add"
    else:
        ident = "gpasswd"
        prefix = syslog_prefix(host, ident, pid, when)
        body = f"{prefix}: user {user} added by {actor} to group {group}"
        action = "group_member_add"
    attrs = base_attrs(
        ident=ident, pid=pid, action=action, outcome="success",
        category="iam", user=user,
    )
    attrs.update({
        "event.type": "change",
        "group.name": group,
        "related.user": f"{user},{actor}",
    })
    return body, attrs, SeverityNumber.INFO


def next_event(
    host: str,
    rng: random.Random,
    when: datetime | None = None,
) -> tuple[str, dict[str, object], SeverityNumber]:
    kind = rng.choices(("ssh", "sudo", "account"), weights=(45, 35, 20), k=1)[0]
    if kind == "ssh":
        return ssh_event(host, rng, when)
    if kind == "sudo":
        return sudo_event(host, rng, when)
    return account_event(host, rng, when)
