"""All tunable settings. Edit dates/airports/threshold here.

Most values can also be overridden via environment variables for the GitHub
Actions workflow without touching the file.
"""
import os


def _csv(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# === Route ===
ORIGINS: list[str] = _csv("FF_ORIGINS", "AMS,EIN,RTM")
DESTINATIONS: list[str] = _csv("FF_DESTINATIONS", "IST,SAW")

# === Travel window (editable!) ===
# Default: July 20-25, 2026 (6 dates). Change here or via FF_DATES env var.
DEPARTURE_DATES: list[str] = _csv(
    "FF_DATES",
    "2026-07-20,2026-07-21,2026-07-22,2026-07-23,2026-07-24,2026-07-25",
)

TRIP_TYPE = "one-way"
SEAT = "economy"
ADULTS = 1

# === Alert threshold ===
THRESHOLD_TRY: float = float(os.environ.get("FF_THRESHOLD_TRY", "10000"))
# Anything below this is treated as a data error (missing price), not a deal.
MIN_VALID_PRICE_TRY: float = float(os.environ.get("FF_MIN_PRICE_TRY", "500"))

# === Email ===
SENDER_EMAIL = os.environ.get("FF_SENDER", "talhabozan@gmail.com")
RECIPIENT_EMAIL = os.environ.get("FF_RECIPIENT", "zubeyirtemel@outlook.com")
ADMIN_EMAIL = os.environ.get("FF_ADMIN", "talhabozan@gmail.com")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
_raw_app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
# Gmail app passwords are displayed as 4 space-separated groups of 4 chars
# (`abcd efgh ijkl mnop`) but the SMTP server expects no whitespace. Strip
# defensively so we work regardless of how the secret was pasted.
GMAIL_APP_PASSWORD = "".join(_raw_app_pw.split())

# === Behavior ===
COOLDOWN_HOURS = 24
PRICE_BUCKET_TRY = 500
REQUEST_DELAY_SEC: float = float(os.environ.get("FF_DELAY_SEC", "1.5"))
MAX_CONSECUTIVE_FAILURES = 3

# === Toggles ===
DRY_RUN: bool = os.environ.get("DRY_RUN", "false").lower() in {"true", "1", "yes"}

# === Currency fallback (if Frankfurter API is unreachable) ===
EUR_TRY_FALLBACK = 53.2
USD_PER_EUR_FALLBACK = 1.08
GBP_PER_EUR_FALLBACK = 0.85
