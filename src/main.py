"""Orchestrator: fetch → convert → filter → dedupe → notify → save state.

Always exits 0 so GitHub Actions never disables the cron after transient
failures. Real failures are surfaced via the admin-alert email after
MAX_CONSECUTIVE_FAILURES empty runs.
"""
import logging
import sys
import time

from src import config, currency, fetcher, notifier, state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def main() -> None:
    logger.info(
        "Starting flight check: %d origins x %d destinations x %d dates",
        len(config.ORIGINS), len(config.DESTINATIONS), len(config.DEPARTURE_DATES),
    )
    if config.DRY_RUN:
        logger.info("DRY_RUN mode ON; no emails will be sent")
    logger.info("Threshold: %.0f TL", config.THRESHOLD_TRY)

    st = state.load()
    state.prune(st)

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
    if new_cheap:
        notifier.send_alert(new_cheap)
        for f in new_cheap:
            state.mark_notified(st, state.make_key(f, f["price_try"]))

    if total > 0 and failures == total:
        st["consecutive_failures"] = st.get("consecutive_failures", 0) + 1
        logger.warning("All queries failed (consecutive=%d)", st["consecutive_failures"])
        if st["consecutive_failures"] >= config.MAX_CONSECUTIVE_FAILURES:
            notifier.send_admin_alert(
                f"flight-fetcher: {st['consecutive_failures']} consecutive runs returned 0 flights "
                f"across all {total} queries. fast-flights may be broken or Google Flights "
                f"is blocking GitHub Actions IPs."
            )
    else:
        if st.get("consecutive_failures", 0) > 0:
            logger.info("Resetting consecutive_failures from %d to 0", st["consecutive_failures"])
        st["consecutive_failures"] = 0

    state.save(st)
    logger.info("Done.")
    sys.exit(0)


if __name__ == "__main__":
    main()
