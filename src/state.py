"""state.json read/write + dedupe.

Avoids re-emailing the same flight within COOLDOWN_HOURS; bucketed by
PRICE_BUCKET_TRY so trivial price flutter doesn't re-trigger.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import config

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).resolve().parent.parent / "docs" / "state.json"
MAX_RECENT_RUNS = 20


def load() -> dict:
    if not STATE_FILE.exists():
        return _empty()
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("alerts", {})
        data.setdefault("consecutive_failures", 0)
        data.setdefault("last_run", None)
        data.setdefault("stats", {"total_runs": 0, "total_emails_sent": 0})
        data.setdefault("current_cheap_flights", [])
        data.setdefault("recent_runs", [])
        data.setdefault("latest_error", None)
        data.setdefault("config_snapshot", {})
        return data
    except Exception as e:
        logger.warning(f"state.json corrupted ({e}); resetting")
        return _empty()


def save(state: dict) -> None:
    state["last_run"] = _now().isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True, ensure_ascii=False)


def record_run(state: dict, run_summary: dict) -> None:
    """Append a run summary to recent_runs (bounded), bump total_runs."""
    state.setdefault("recent_runs", []).insert(0, run_summary)
    state["recent_runs"] = state["recent_runs"][:MAX_RECENT_RUNS]
    state.setdefault("stats", {"total_runs": 0, "total_emails_sent": 0})
    state["stats"]["total_runs"] = state["stats"].get("total_runs", 0) + 1
    if run_summary.get("emails_sent", 0):
        state["stats"]["total_emails_sent"] = (
            state["stats"].get("total_emails_sent", 0) + run_summary["emails_sent"]
        )


def prune(state: dict) -> None:
    """Drop alert entries older than 7 days."""
    cutoff = _now() - timedelta(days=7)
    kept = {}
    for k, v in state["alerts"].items():
        try:
            if _parse_iso(v) > cutoff:
                kept[k] = v
        except ValueError:
            continue
    if len(kept) != len(state["alerts"]):
        logger.info(f"Pruned {len(state['alerts']) - len(kept)} old alert entries")
    state["alerts"] = kept


def make_key(flight: dict, price_try: float) -> str:
    bucket = int(price_try // config.PRICE_BUCKET_TRY) * config.PRICE_BUCKET_TRY
    return f"{flight['origin']}-{flight['dest']}-{flight['date']}-{bucket}"


def should_notify(state: dict, key: str) -> bool:
    ts = state["alerts"].get(key)
    if ts is None:
        return True
    try:
        last = _parse_iso(ts)
    except ValueError:
        return True
    cutoff = _now() - timedelta(hours=config.COOLDOWN_HOURS)
    return last < cutoff


def mark_notified(state: dict, key: str) -> None:
    state["alerts"][key] = _now().isoformat()


def _empty() -> dict:
    return {
        "alerts": {},
        "consecutive_failures": 0,
        "last_run": None,
        "stats": {"total_runs": 0, "total_emails_sent": 0},
        "current_cheap_flights": [],
        "recent_runs": [],
        "latest_error": None,
        "config_snapshot": {},
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
