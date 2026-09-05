"""Map AlecaFrame internal uniqueNames to warframe.market slugs.

Primary source is the v2 catalog (gameRef field), which covers every
tradable item including ones no relic drops. Falls back to the WFCD
Relics.json cache when offline.
"""

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RELICS_JSON = BASE / "Relics.json"

_cache: dict = {}


def load_map() -> dict:
    """Returns {uniqueName: {'name': ..., 'url': ...}}."""
    global _cache
    if _cache:
        return _cache
    try:
        import market_items
        idx = market_items.index()
        for ref, e in idx["by_ref"].items():
            name = ((e.get("i18n") or {}).get("en") or {}).get("name", "")
            _cache[ref] = {"name": name, "url": e["slug"]}
        return _cache
    except Exception:
        pass
    data = json.loads(RELICS_JSON.read_text(encoding="utf-8"))
    for relic in data:
        for reward in relic.get("rewards", []):
            item = reward.get("item") or {}
            unique = item.get("uniqueName")
            market = item.get("warframeMarket") or {}
            if unique and market.get("urlName"):
                _cache.setdefault(unique, {"name": item.get("name", ""),
                                           "url": market["urlName"]})
    return _cache


def lookup(item_type: str) -> dict | None:
    """{'name', 'url'} for a dump ItemType, or None if unmapped."""
    return load_map().get(item_type)
