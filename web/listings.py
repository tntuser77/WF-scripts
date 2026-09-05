"""Already-listed check via the public profile orders endpoint.

No API key needed: GET /v1/profile/{username}/orders is public and
returns buy_orders + sell_orders. We only need the user's WFM username,
read from web/.env (WFM_USERNAME) so it never touches git.

Results are cached on disk for 15 minutes. A visible sell order for a
slug means "already listed", and best-to-list hides those parts.
"""

import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENV_FILE = BASE / "web" / ".env"
CACHE_FILE = BASE / "my_listings_cache.json"
TTL_SECONDS = 15 * 60


def username() -> str | None:
    import os
    name = os.environ.get("WFM_USERNAME", "").strip()
    if name:
        return name
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("WFM_USERNAME="):
                name = line.split("=", 1)[1].strip().strip("\"'")
                if name:
                    return name
    return None


def fetch_listed(user: str | None = None) -> dict:
    """{slugs: [...], name, fetched, stale}. Never raises, stale cache on fail."""
    import market_client
    user = user or username()
    if not user:
        return {"slugs": [], "name": None, "fetched": None, "stale": False}
    cached = {}
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
    if cached.get("name") == user and time.time() - cached.get("at", 0) < TTL_SECONDS:
        return {"slugs": cached.get("slugs", []), "name": user,
                "fetched": cached.get("at"), "stale": False}
    try:
        data = market_client.get_json(
            f"https://api.warframe.market/v1/profile/{user}/orders")
        payload = data.get("payload", {})
        slugs = sorted({o.get("item", {}).get("url_name", "")
                        for o in payload.get("sell_orders", [])
                        if isinstance(o, dict) and o.get("item", {}).get("url_name")})
        CACHE_FILE.write_text(json.dumps({"name": user, "at": time.time(),
                                          "slugs": slugs}), encoding="utf-8")
        return {"slugs": slugs, "name": user, "fetched": time.time(), "stale": False}
    except Exception:
        if cached.get("name") == user and cached.get("slugs"):
            return {"slugs": cached["slugs"], "name": user,
                    "fetched": cached.get("at"), "stale": True}
        return {"slugs": [], "name": user, "fetched": None, "stale": True}
