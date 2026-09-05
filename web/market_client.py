"""Single shared warframe.market client.

Every feature (price search, best board, relic inventory, order watcher)
must go through this module so total traffic stays under ~3 requests/sec
per IP. Uses a token bucket with a lock, plus disk cache for statistics
and short memory cache for top orders.
"""

import json
import threading
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE / "gold_part_price_cache.json"
CACHE_TTL_HOURS = 6
MAX_PER_SECOND = 3
TOP_TTL_SECONDS = 120

_lock = threading.Lock()
_request_times: list = []
_stats = {"total": 0, "limited_waits": 0, "cache_hits": 0, "last_429": None}

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (wfm-local-ui)"})


def normalize(value: str) -> str:
    return value.strip().strip('"').strip("'")


def slugify(value: str) -> str:
    value = normalize(value).lower().replace(" ", "_").replace("-", "_")
    return "".join(c for c in value if c.isalnum() or c == "_")


def relic_slug(name: str) -> str:
    """warframe.market names relics with a _relic suffix (neo_l4_relic)."""
    slug = slugify(name)
    if not slug.endswith("_relic"):
        slug += "_relic"
    return slug


def _throttle() -> None:
    """Block until this request fits inside 3 req/sec. Thread safe."""
    with _lock:
        now = time.monotonic()
        while True:
            _request_times[:] = [t for t in _request_times if now - t < 1.0]
            if len(_request_times) < MAX_PER_SECOND:
                _request_times.append(now)
                return
            oldest = min(_request_times)
            wait = 1.0 - (now - oldest) + 0.02
            _stats["limited_waits"] += 1
            time.sleep(max(wait, 0.02))
            now = time.monotonic()


def _get_json(url: str) -> dict:
    _throttle()
    resp = _session.get(url, timeout=15)
    with _lock:
        _stats["total"] += 1
        if resp.status_code == 429:
            _stats["last_429"] = time.strftime("%H:%M:%S")
    resp.raise_for_status()
    return resp.json()


def _avg_medians(buckets: list) -> float | None:
    medians = [float(e["median"]) for e in buckets
               if isinstance(e, dict) and e.get("median") is not None]
    if not medians:
        return None
    return round(sum(medians) / len(medians), 2)


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


_top_cache: dict = {}


def part_statistics(slug: str) -> dict:
    """Returns {market_link, median_90d, median_48h}. Uses 6h disk cache."""
    cache = load_cache()
    entry = cache.get(slug)
    now = time.time()
    if entry and now - entry.get("fetched_at", 0) < CACHE_TTL_HOURS * 3600:
        with _lock:
            _stats["cache_hits"] += 1
        return {"market_link": entry["market_link"],
                "median_90d": entry["price_90d"],
                "median_48h": entry["price_48h"]}

    url = f"https://api.warframe.market/v1/items/{slug}/statistics"
    data = _get_json(url)
    closed = data.get("payload", {}).get("statistics_closed", {})
    out = {"market_link": f"https://warframe.market/items/{slug}",
           "median_90d": _avg_medians(closed.get("90days", [])),
           "median_48h": _avg_medians(closed.get("48hours", []))}
    cache[slug] = {"price_90d": out["median_90d"], "price_48h": out["median_48h"],
                   "market_link": out["market_link"], "fetched_at": now}
    save_cache(cache)
    return out


def top_orders(item_name: str) -> dict:
    """Cheapest sell (preferring quantity>=6) plus average buy. Short cache."""
    slug = relic_slug(item_name)
    now = time.time()
    hit = _top_cache.get(slug)
    if hit and now - hit["at"] < TOP_TTL_SECONDS:
        with _lock:
            _stats["cache_hits"] += 1
        return hit["data"]

    url = f"https://api.warframe.market/v2/orders/item/{slug}/top"
    data = _get_json(url)
    orders = data.get("data", {})
    sells = [e for e in orders.get("sell", [])
             if isinstance(e, dict) and "platinum" in e]
    buys = [float(e.get("platinum", 0)) for e in orders.get("buy", [])
            if isinstance(e, dict) and "platinum" in e]
    big = [e for e in sells if int(e.get("quantity", 0)) >= 6]
    pool = big if big else sells
    sel = min(pool, key=lambda e: float(e.get("platinum", 0))) if pool else None
    out = {"market_link": f"https://warframe.market/items/{slug}",
           "sell_price": float(sel["platinum"]) if sel else None,
           "sell_qty": int(sel["quantity"]) if sel and "quantity" in sel else None,
           "avg_buy": round(sum(buys) / len(buys), 2) if buys else None}
    _top_cache[slug] = {"at": now, "data": out}
    return out


def stats() -> dict:
    with _lock:
        return dict(_stats)
