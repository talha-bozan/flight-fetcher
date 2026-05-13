"""Price-string parser + EUR/USD/GBP/TRY → TRY conversion via Frankfurter API.

fast-flights returns prices in whatever currency Google Flights serves to the
caller (depends on IP geolocation): for example `'TRY\\xa011254'` from a TR
IP or `'€185'` / `'$210'` from US/EU IPs. parse_price() handles all common
forms; to_try() converts via Frankfurter, falling back to hardcoded rates.
"""
import logging
import re
from typing import Optional

import requests

from src import config

logger = logging.getLogger(__name__)

_SYMBOL_TO_CCY = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "₺": "TRY",
    "TL": "TRY",
}
_KNOWN_CCY = {"EUR", "USD", "GBP", "TRY"}

_NUMBER_RE = re.compile(r"[\d][\d,.\s ]*\d|\d")

# Module-level cache. Populated once per run.
_rates: dict[str, float] = {}


def parse_price(price_str: str) -> tuple[Optional[float], Optional[str]]:
    """Parse strings like 'TRY 11254', '€185', '$210', '9,800 TL', '₺ 8500'.

    Returns (amount, currency) or (None, None) if unparseable.
    """
    if not price_str:
        return None, None
    s = price_str.strip()
    s_upper = s.upper()

    # 1. Detect currency. Try codes first (more specific), then symbols.
    currency: Optional[str] = None
    for code in _KNOWN_CCY:
        if code in s_upper:
            currency = code
            break
    if currency is None:
        # "TL" as a substring (matches Turkish-localized output)
        if "TL" in s_upper and not any(c in s_upper for c in _KNOWN_CCY):
            currency = "TRY"
    if currency is None:
        for sym, ccy in _SYMBOL_TO_CCY.items():
            if sym in s:
                currency = ccy
                break

    # 2. Extract digits.
    num_match = _NUMBER_RE.search(s)
    if not num_match:
        return None, None
    num_raw = num_match.group(0)
    amount = _parse_number(num_raw)
    if amount is None:
        return None, None

    # 3. Default currency = EUR (most likely for European origin if undetected).
    if currency is None:
        currency = "EUR"

    return amount, currency


def _parse_number(s: str) -> Optional[float]:
    """Handle '11254', '11,254', '11.254', '11.254,99' (EU), '11,254.99' (US)."""
    cleaned = s.replace(" ", "").replace(" ", "")
    if not cleaned:
        return None
    # European decimal: 11.254,99 -> 11254.99
    if re.search(r",\d{1,2}$", cleaned) and re.search(r"\d\.\d{3}", cleaned):
        whole, dec = cleaned.rsplit(",", 1)
        whole = whole.replace(".", "").replace(",", "")
        try:
            return float(f"{whole}.{dec}")
        except ValueError:
            return None
    # US decimal: 11,254.99 -> 11254.99
    if re.search(r"\.\d{1,2}$", cleaned) and re.search(r"\d,\d{3}", cleaned):
        whole, dec = cleaned.rsplit(".", 1)
        whole = whole.replace(",", "").replace(".", "")
        try:
            return float(f"{whole}.{dec}")
        except ValueError:
            return None
    # Single decimal point with 1-2 digits at end -> treat as decimal
    if re.search(r"^\d+\.\d{1,2}$", cleaned):
        try:
            return float(cleaned)
        except ValueError:
            return None
    # Single comma with 1-2 digits at end -> EU decimal
    if re.search(r"^\d+,\d{1,2}$", cleaned):
        try:
            return float(cleaned.replace(",", "."))
        except ValueError:
            return None
    # Otherwise, all commas/dots are thousand separators
    try:
        return float(cleaned.replace(",", "").replace(".", ""))
    except ValueError:
        return None


def _fetch_rates() -> dict[str, float]:
    """Fetch EUR→{TRY,USD,GBP} once; cache. Falls back to hardcoded on error."""
    if _rates:
        return _rates
    try:
        r = requests.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": "EUR", "symbols": "TRY,USD,GBP"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        rates = data.get("rates", {})
        if "TRY" in rates:
            _rates.update(rates)
            _rates["EUR"] = 1.0
            logger.info(
                f"Frankfurter rates: EUR=1, TRY={rates['TRY']:.2f}, "
                f"USD={rates.get('USD', '?')}, GBP={rates.get('GBP', '?')}"
            )
            return _rates
    except Exception as e:
        logger.warning(f"Frankfurter API failed ({e}); using fallback")

    _rates.update({
        "EUR": 1.0,
        "TRY": config.EUR_TRY_FALLBACK,
        "USD": config.USD_PER_EUR_FALLBACK,
        "GBP": config.GBP_PER_EUR_FALLBACK,
    })
    return _rates


def to_try(amount: float, currency: str) -> float:
    """Convert `amount` in `currency` to TRY using EUR-based cross rates."""
    if currency == "TRY":
        return amount
    rates = _fetch_rates()
    if currency not in rates:
        logger.warning(f"Unknown currency {currency!r}; treating as EUR")
        currency = "EUR"
    amount_eur = amount if currency == "EUR" else amount / rates[currency]
    return amount_eur * rates["TRY"]
