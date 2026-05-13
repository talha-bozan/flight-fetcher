"""fast-flights wrapper. One function: fetch_one(origin, dest, date) -> list[dict].

Never raises — returns [] on any error and logs the cause.
"""
import logging

logger = logging.getLogger(__name__)


def fetch_one(origin: str, dest: str, date: str) -> list[dict]:
    """Search Google Flights for one origin × dest × date combo.

    Returns a list of dicts with keys:
      origin, dest, date, airline, departure, arrival, duration, stops, price_str
    Returns [] if no flights or any error occurs.
    """
    try:
        from fast_flights import FlightData, Passengers, get_flights
    except ImportError as e:
        logger.error(f"fast-flights not installed: {e}")
        return []

    try:
        fd = FlightData(date=date, from_airport=origin, to_airport=dest)
        # fetch_mode="fallback" lets fast-flights use its Playwright fallback if
        # the protobuf endpoint gives weird responses.
        result = get_flights(
            flight_data=[fd],
            trip="one-way",
            passengers=Passengers(adults=1),
            seat="economy",
            fetch_mode="fallback",
        )
    except TypeError:
        # Older versions don't accept fetch_mode kwarg
        try:
            fd = FlightData(date=date, from_airport=origin, to_airport=dest)
            result = get_flights(
                flight_data=[fd],
                trip="one-way",
                passengers=Passengers(adults=1),
                seat="economy",
            )
        except Exception as e:
            logger.warning(f"fetch_one({origin}, {dest}, {date}) retry failed: {e}")
            return []
    except Exception as e:
        msg = str(e)
        if "No flights found" in msg:
            return []
        logger.warning(f"fetch_one({origin}, {dest}, {date}) failed: {type(e).__name__}: {msg[:200]}")
        return []

    flights = getattr(result, "flights", None) or []
    out = []
    seen: set[tuple] = set()
    for f in flights:
        departure = str(getattr(f, "departure", "") or "")
        arrival = str(getattr(f, "arrival", "") or "")
        name = str(getattr(f, "name", "") or getattr(f, "airline", "") or "")
        price_str = str(getattr(f, "price", "") or "")
        # fast-flights sometimes returns the same flight multiple times in one
        # response — dedupe by (departure, arrival, airline, price).
        key = (departure, arrival, name, price_str)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "origin": origin,
            "dest": dest,
            "date": date,
            "airline": name or "?",
            "departure": departure or "?",
            "arrival": arrival or "?",
            "duration": str(getattr(f, "duration", "") or "?"),
            "stops": getattr(f, "stops", 0) or 0,
            "price_str": price_str,
        })
    return out
