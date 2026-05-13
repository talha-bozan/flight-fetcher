"""Quick smoke test: single fast-flights query + price parsing + TRY conversion.

Run: python smoke_test.py
"""
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from src import fetcher, currency

print("=" * 70)
print("Smoke test: AMS -> IST on 2026-07-22")
print("=" * 70)

flights = fetcher.fetch_one("AMS", "IST", "2026-07-22")
print(f"\nGot {len(flights)} flights")

if not flights:
    print("FAIL: no flights returned. Check fast-flights API or network.")
    raise SystemExit(1)

# Show first 5
for i, f in enumerate(flights[:5]):
    amount, cur = currency.parse_price(f["price_str"])
    if amount is None:
        try_price = "?"
    else:
        try_price = f"{currency.to_try(amount, cur):.0f} TL"
    print(
        f"  {i+1}. {f['airline']:<20} {f['departure']:<28} -> {f['arrival']:<28} "
        f"{f['duration']:<14} {f['price_str']:<10} ~{try_price}"
    )

print(f"\nTotal: {len(flights)} flights")
print("OK: fast-flights API works, price parsing + TRY conversion works.")
