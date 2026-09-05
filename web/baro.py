"""Void Trader watch. Baro brings primed mods for ducats every two weeks.

One cached call to the worldstate feed gives the active window plus the
full inventory with ducat prices. Junk parts under the 25p trade floor
turn into ducats, ducats turn into primed mods, mods recover and sell.
"""

import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE / "baro_cache.json"
TTL_SECONDS = 3600
URL = "https://api.warframestat.us/pc/voidTrader"


def fetch() -> dict:
    """{active, activation, expiry, location, primed: [...], items, stale}."""
    import market_client
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cached.get("at", 0) < TTL_SECONDS:
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

        def _ts(s):
            try:
                return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                return 0

        now = time.time()
        out = {"at": now, "stale": False,
               "activation": d.get("activation"), "expiry": d.get("expiry"),
               "location": d.get("location"),
               "active": bool(_ts(d.get("activation")) < now < _ts(d.get("expiry"))),
               "primed": primed, "items": len(inv)}
        CACHE_FILE.write_text(json.dumps(out), encoding="utf-8")
        return out
    except Exception:
        if CACHE_FILE.exists():
            try:
                cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                cached["stale"] = True
                return cached
            except Exception:
                pass
        return {"stale": True, "active": False, "primed": [], "items": 0,
                "activation": None, "expiry": None, "location": None}
