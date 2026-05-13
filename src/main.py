"""Orchestrator: fetch → convert → filter → dedupe → notify → save state.

Always exits 0 so GitHub Actions never disables the cron after transient
failures. Any uncaught exception is written to ``last_error.log`` at the repo
root, which gets committed by the workflow — that way the failure is visible
on GitHub without needing to read the runner's private logs.
"""
import datetime
import logging
import sys
import time
import traceback
from pathlib import Path

from src import config, currency, fetcher, notifier, state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

ERROR_LOG = Path(__file__).resolve().parent.parent / "last_error.log"


def _run() -> None:
    run_started = time.monotonic()
    logger.info(
        "Starting flight check: %d origins x %d destinations x %d dates",
        len(config.ORIGINS), len(config.DESTINATIONS), len(config.DEPARTURE_DATES),
    )
    if config.DRY_RUN:
        logger.info("DRY_RUN mode ON; no emails will be sent")
    logger.info("Threshold: %.0f TL", config.THRESHOLD_TRY)

    st = state.load()
    state.prune(st)
    st["latest_error"] = None  # reset on each run; gets set below if anything fails

    smtp_ok = True
    smtp_msg = "DRY_RUN — skipped"
    if not config.DRY_RUN:
        smtp_ok, smtp_msg = notifier.smtp_self_test()
        if smtp_ok:
            logger.info("SMTP self-test OK")
        else:
            logger.error("SMTP self-test FAILED: %s", smtp_msg)
            _write_error(f"SMTP self-test FAILED: {smtp_msg}")
            st["latest_error"] = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": f"SMTP self-test FAILED: {smtp_msg}",
            }

    all_flights: list[dict] = []
    failures = 0
    total = 0

    for origin in config.ORIGINS:
        for dest in config.DESTINATIONS:
            for date in config.DEPARTURE_DATES:
                total += 1
                logger.info("[%d] Fetch %s -> %s @ %s", total, origin, dest, date)
                results = fetcher.fetch_one(origin, dest, date)
                if not results:
                    failures += 1
                    logger.warning("  no flights")
                else:
                    cheapest_raw = min((r["price_str"] for r in results if r["price_str"]), default="?")
                    logger.info("  got %d flights (cheapest raw: %s)", len(results), cheapest_raw)
                    all_flights.extend(results)
                time.sleep(config.REQUEST_DELAY_SEC)

    logger.info("Fetched %d flights total | %d/%d queries failed", len(all_flights), failures, total)

    for f in all_flights:
        amount, cur = currency.parse_price(f["price_str"])
        if amount is None:
            f["price_try"] = float("inf")
            f["price_num"] = None
            f["currency"] = None
        else:
            f["price_num"] = amount
            f["currency"] = cur
            f["price_try"] = currency.to_try(amount, cur)

    cheap = [
        f for f in all_flights
        if config.MIN_VALID_PRICE_TRY <= f["price_try"] < config.THRESHOLD_TRY
    ]
    invalid = sum(1 for f in all_flights if f["price_try"] < config.MIN_VALID_PRICE_TRY)
    if invalid:
        logger.info("Ignored %d flights with invalid/missing prices (< %.0f TL)",
                    invalid, config.MIN_VALID_PRICE_TRY)
    logger.info("Flights under %.0f TL: %d", config.THRESHOLD_TRY, len(cheap))
    for f in cheap:
        logger.info(
            "  CHEAP %s->%s %s %s: %.0f TL (%s)",
            f["origin"], f["dest"], f["date"], f["airline"], f["price_try"], f["price_str"],
        )

    new_cheap = []
    seen_in_run: set[str] = set()
    for f in cheap:
        key = state.make_key(f, f["price_try"])
        if key in seen_in_run:
            continue
        seen_in_run.add(key)
        if state.should_notify(st, key):
            new_cheap.append(f)
        else:
            logger.info("  SKIP deduped %s", key)

    logger.info("New (not deduped) cheap flights: %d", len(new_cheap))
    emails_sent = 0
    if new_cheap:
        if not smtp_ok:
            # Self-test already failed; don't retry send (it would just re-raise
            # the same auth error and overwrite the cleaner self-test message).
            # DON'T mark notified here — once SMTP is fixed, the next run should
            # re-discover these flights and send the email that this run owed.
            logger.warning(
                "Skipping email send for %d cheap flights — SMTP self-test "
                "failed earlier: %s. Will retry on next run.",
                len(new_cheap), smtp_msg,
            )
        else:
            try:
                notifier.send_alert(new_cheap)
                if not config.DRY_RUN:
                    emails_sent = 1  # one consolidated email per run
                for f in new_cheap:
                    state.mark_notified(st, state.make_key(f, f["price_try"]))
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("send_alert failed: %s\n%s", e, tb)
                _write_error(f"send_alert failed: {e}\n{tb}")
                st["latest_error"] = {
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "message": f"send_alert failed: {e}",
                }

    if total > 0 and failures == total:
        st["consecutive_failures"] = st.get("consecutive_failures", 0) + 1
        logger.warning("All queries failed (consecutive=%d)", st["consecutive_failures"])
        if st["consecutive_failures"] >= config.MAX_CONSECUTIVE_FAILURES:
            try:
                notifier.send_admin_alert(
                    f"flight-fetcher: {st['consecutive_failures']} consecutive runs returned 0 flights "
                    f"across all {total} queries. fast-flights may be broken or Google Flights "
                    f"is blocking GitHub Actions IPs."
                )
            except Exception as e:
                logger.error("send_admin_alert failed: %s", e)
    else:
        if st.get("consecutive_failures", 0) > 0:
            logger.info("Resetting consecutive_failures from %d to 0", st["consecutive_failures"])
        st["consecutive_failures"] = 0

    # Update dashboard data on state.
    valid_prices = [
        f["price_try"] for f in all_flights
        if f["price_try"] != float("inf") and f["price_try"] >= config.MIN_VALID_PRICE_TRY
    ]
    cheapest_try = min(valid_prices) if valid_prices else None
    st["current_cheap_flights"] = [_serialise_flight(f) for f in cheap[:50]]
    st["config_snapshot"] = {
        "threshold_try": config.THRESHOLD_TRY,
        "min_valid_price_try": config.MIN_VALID_PRICE_TRY,
        "origins": list(config.ORIGINS),
        "destinations": list(config.DESTINATIONS),
        "dates": list(config.DEPARTURE_DATES),
        "trip_type": config.TRIP_TYPE,
        "recipient": config.RECIPIENT_EMAIL,
        "sender": config.SENDER_EMAIL,
    }
    state.record_run(st, {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "duration_sec": round(time.monotonic() - run_started, 1),
        "total_queries": total,
        "queries_failed": failures,
        "total_flights": len(all_flights),
        "cheap_count": len(cheap),
        "new_alert_count": len(new_cheap),
        "cheapest_try": round(cheapest_try, 2) if cheapest_try is not None else None,
        "emails_sent": emails_sent,
        "smtp_ok": smtp_ok,
        "smtp_msg": smtp_msg if not smtp_ok else "ok",
        "dry_run": config.DRY_RUN,
    })

    state.save(st)
    logger.info("Done.")


def _serialise_flight(f: dict) -> dict:
    return {
        "origin": f["origin"],
        "dest": f["dest"],
        "date": f["date"],
        "airline": f["airline"],
        "departure": f["departure"],
        "arrival": f["arrival"],
        "duration": f["duration"],
        "stops": f["stops"],
        "price_str": f["price_str"],
        "price_try": round(f["price_try"], 2) if f["price_try"] != float("inf") else None,
        "currency": f.get("currency"),
    }


def _write_error(text: str) -> None:
    """Append an error entry to last_error.log so it survives in the commit."""
    try:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n========== {timestamp} ==========\n{text}\n")
    except Exception as e:
        logger.error("Failed to write last_error.log: %s", e)


def main() -> None:
    """Top-level entry: catches every exception and exits 0 always."""
    try:
        _run()
    except SystemExit:
        raise
    except BaseException as e:
        tb = traceback.format_exc()
        logger.error("UNCAUGHT in _run(): %s\n%s", e, tb)
        _write_error(f"UNCAUGHT in _run(): {e}\n{tb}")
        # Try to surface in state.json too, so dashboard shows the crash.
        try:
            st = state.load()
            st["latest_error"] = {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "message": f"UNCAUGHT: {e}\n{tb}"[:4000],
            }
            state.save(st)
        except Exception:
            pass
        try:
            notifier.send_admin_alert(f"flight-fetcher CRASH:\n{tb}")
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
