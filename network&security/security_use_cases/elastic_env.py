"""Load Elastic Cloud credentials from a local .env file."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _apply_dotenv(path: Path, *, override: bool = False) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or (key in os.environ and not override):
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def load_dotenv_for_use_case(script_file: str | Path) -> Path:
    """Load `.env` from the use-case directory, then `logstash/.env` as fallback."""
    use_case_dir = Path(script_file).resolve().parent
    logstash_env = use_case_dir.parents[1] / "logstash" / ".env"
    _apply_dotenv(logstash_env)
    _apply_dotenv(use_case_dir / ".env", override=True)
    return use_case_dir


def load_elastic_env(
    script_file: str | Path,
    *,
    admin: bool = False,
) -> tuple[str, str]:
    use_case_dir = load_dotenv_for_use_case(script_file)
    hosts = os.environ.get("ELASTIC_HOSTS", "").strip()
    if admin:
        api_key = (
            os.environ.get("ELASTIC_ADMIN_API_KEY", "").strip()
            or os.environ.get("ELASTIC_API_KEY", "").strip()
        )
        api_hint = "ELASTIC_ADMIN_API_KEY (or ELASTIC_API_KEY)"
    else:
        api_key = os.environ.get("ELASTIC_API_KEY", "").strip()
        api_hint = "ELASTIC_API_KEY"

    if not hosts or not api_key:
        sys.exit(
            f"Set ELASTIC_HOSTS and {api_hint} in {use_case_dir / '.env'} "
            f"(copy from .env.example)."
        )
    return hosts.rstrip("/"), api_key
