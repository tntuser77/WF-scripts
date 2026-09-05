"""warframe.market v2 item catalog. Master key for the whole tracker.

One call returns every item with id, slug, gameRef (the internal
uniqueName AlecaFrame uses), tags, and ducats. Cached on disk for 7 days.
Detail endpoint adds setParts for set grouping, cached indefinitely.
All traffic through market_client's limiter.
"""

import json
import time
from pathlib import Path

import market_client

BASE = Path(__file__).resolve().parent.parent
CATALOG_CACHE = BASE / "market_catalog.json"
CATALOG_TTL_DAYS = 7
DETAIL_CACHE = BASE / "market_detail_cache.json"

LIST_URL = "https://api.warframe.market/v2/items"
DETAIL_URL = "https://api.warframe.market/v2/items/{slug}"


def load_catalog(max_age_days: int = CATALOG_TTL_DAYS) -> list:
    if CATALOG_CACHE.exists():
        age = time.time() - CATALOG_CACHE.stat().st_mtime
        if age < max_age_days * 86400:
            return json.loads(CATALOG_CACHE.read_text(encoding="utf-8"))
    data = market_client.get_json(LIST_URL)["data"]
    CATALOG_CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def index(catalog: list | None = None) -> dict:
    """{'by_ref': {gameRef: entry}, 'by_id': {id: entry}, 'by_slug': {slug: entry}}."""
    catalog = catalog if catalog is not None else load_catalog()
    idx = {"by_ref": {}, "by_id": {}, "by_slug": {}}
    for e in catalog:
        if e.get("gameRef"):
            idx["by_ref"][e["gameRef"]] = e
        idx["by_id"][e["id"]] = e
        idx["by_slug"][e["slug"]] = e
    return idx


def load_details() -> dict:
    if Path(DETAIL_CACHE).exists():
        try:
            return json.loads(Path(DETAIL_CACHE).read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_details(cache: dict) -> None:
    Path(DETAIL_CACHE).write_text(json.dumps(cache), encoding="utf-8")


def fetch_detail(slug: str) -> dict:
    """v2 item detail: setParts ids, ducats, tradable, canonical slug."""
    cache = load_details()
    if slug in cache:
        return cache[slug]
    data = market_client.get_json(DETAIL_URL.format(slug=slug))["data"]
    cache[data.get("slug", slug)] = data
    save_details(cache)
    return data
