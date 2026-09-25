"""Void Trader watch. Baro brings primed mods for ducats every two weeks.

One cached call to the worldstate feed gives the active window plus the
full inventory with ducat prices. Junk parts under the 25p trade floor
turn into ducats, ducats turn into primed mods, mods recover and sell.
"""

import calendar
import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE / "baro_cache.json"
TTL_SECONDS = 3600
URL = "https://api.warframestat.us/pc/voidTrader"


def _ts(s) -> float:
    """Parse a worldstate timestamp as UTC, not local time.

    The feed sends ISO UTC like 2026-09-18T13:00:00.000Z. The old code
    used time.mktime, which reads the same digits as local time, so on
    US Eastern Baro looked absent for 4 hours after each arrival.
    """
    try:
        return float(calendar.timegm(
            time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        return 0


def _is_active(activation, expiry, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return bool(_ts(activation) < now < _ts(expiry))


def fetch() -> dict:
    """{active, activation, expiry, location, primed: [...], items, stale}."""
    import market_client
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cached.get("at", 0) < TTL_SECONDS:
                # Recompute active from the timestamps so a cache written
                # just before arrival flips on its own instead of hiding
                # the module for up to an hour.
                cached["active"] = _is_active(
                    cached.get("activation"), cached.get("expiry"))
                cached["stale"] = False
                return cached
        except Exception:
            pass
    try:
        d = market_client.get_json(URL)
        inv = d.get("inventory", []) or []
        primed = sorted(
            ({"item": i.get("item", ""), "ducats": i.get("ducats"),
              "credits": i.get("credits")}
             for i in inv if "Primed" in str(i.get("item", ""))),
            key=lambda x: x["item"])

        now = time.time()
        out = {"at": now, "stale": False,
               "activation": d.get("activation"), "expiry": d.get("expiry"),
               "location": d.get("location"),
               "active": _is_active(d.get("activation"), d.get("expiry"), now),
               "primed": primed, "items": len(inv)}
        CACHE_FILE.write_text(json.dumps(out), encoding="utf-8")
        return out
    except Exception:
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                cached["active"] = _is_active(
                    cached.get("activation"), cached.get("expiry"))
                cached["stale"] = True
                return cached
            except Exception:
                pass
        return {"stale": True, "active": False, "primed": [], "items": 0,
                "activation": None, "expiry": None, "location": None}
