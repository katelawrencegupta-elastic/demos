"""Seasonality curves and scenario (incident / narrative) windows.

All effects are pure functions of (world, timestamp, anchor) so backfill and
live streaming produce one continuous, reproducible timeline. `anchor` is the
run's notion of "now"; scenario windows in world.yaml are days relative to it.
"""
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone


def rng_for(*parts) -> random.Random:
    """Deterministic RNG scoped to arbitrary parts (e.g. dataset + hour)."""
    seed = int(hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def diurnal(dt: datetime) -> float:
    """Business-hours curve, peak ~15-20 UTC (US working day), min at night."""
    h = dt.hour + dt.minute / 60.0
    return 0.35 + 0.65 * max(0.0, math.sin((h - 6) / 16 * math.pi)) ** 1.5


def weekday_factor(dt: datetime) -> float:
    return 0.45 if dt.weekday() >= 5 else 1.0


def sunday_batch_factor(dt: datetime) -> float:
    """Weekly ETL / reporting batch window: Sunday 02-08 UTC spikes hard."""
    if dt.weekday() != 6:
        return 1.0
    h = dt.hour + dt.minute / 60.0
    if 2 <= h < 8:
        return 3.2
    return 1.15


def growth(world, dt: datetime, anchor: datetime) -> float:
    pct = world.scenarios.get("growth_pct_per_day", 0.0)
    days = (dt - anchor).total_seconds() / 86400.0
    return (1.0 + pct / 100.0) ** days


def activity_multiplier(world, dt: datetime, anchor: datetime) -> float:
    """Combined seasonality for human-driven activity volume."""
    return (diurnal(dt) * weekday_factor(dt) * sunday_batch_factor(dt)
            * growth(world, dt, anchor))


def usage_multiplier(world, dt: datetime, anchor: datetime) -> float:
    """Infra usage dips less at night/weekends than human activity does."""
    base = 0.75 + 0.25 * diurnal(dt) / 1.0
    wk = 0.85 if dt.weekday() >= 5 else 1.0
    return base * wk * sunday_batch_factor(dt) * growth(world, dt, anchor)


def _window(world, key: str, anchor: datetime):
    sc = world.scenarios[key]
    start = anchor + timedelta(days=sc["start_day"])
    end = anchor + timedelta(days=sc["end_day"])
    return start, end


def crypto_incident_active(world, dt: datetime, anchor: datetime) -> bool:
    start, end = _window(world, "crypto_incident", anchor)
    return start <= dt <= end


def ml_burn_active(world, dt: datetime, anchor: datetime) -> bool:
    start, end = _window(world, "ml_burn", anchor)
    return start <= dt <= end


def s3_exposure_active(world, dt: datetime, anchor: datetime) -> bool:
    start, end = _window(world, "s3_exposure", anchor)
    return start <= dt <= end


def genai_ramp_active(world, dt: datetime, anchor: datetime) -> bool:
    sc = world.scenarios["genai_ramp"]
    start = anchor + timedelta(days=sc["start_day"])
    return dt >= start


def genai_ramp_multiplier(world, dt: datetime, anchor: datetime) -> float:
    """Linear ramp from 1.0 at start_day to end_multiplier at anchor."""
    sc = world.scenarios["genai_ramp"]
    if not genai_ramp_active(world, dt, anchor):
        return 1.0
    start = anchor + timedelta(days=sc["start_day"])
    span = (anchor - start).total_seconds()
    if span <= 0:
        return sc["end_multiplier"]
    progress = min(1.0, (dt - start).total_seconds() / span)
    return 1.0 + progress * (sc["end_multiplier"] - 1.0)


def llm_agent_loop_active(world, dt: datetime, anchor: datetime) -> bool:
    start, end = _window(world, "llm_agent_loop", anchor)
    return start <= dt <= end


def llm_cache_miss_active(world, dt: datetime, anchor: datetime) -> bool:
    start, end = _window(world, "llm_cache_miss_storm", anchor)
    return start <= dt <= end


def llm_migration_provider(world, app_id: str, dt: datetime, anchor: datetime):
    """Return forced provider after cutover for the migrated app, else None."""
    sc = world.scenarios.get("llm_model_migration")
    if not sc or sc["app"] != app_id:
        return None
    cutover = anchor + timedelta(days=sc["cutover_day"])
    if dt < cutover:
        return sc["from_provider"]
    return sc["to_provider"]


def compromised_instance(world):
    """The dev-account instance hijacked during the crypto incident."""
    acct = world.scenarios["crypto_incident"]["aws_account"]
    return world.ec2_in_account(acct)[0]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
