"""Already-listed check.

Primary path is authenticated: the user's own JWT (copied once from the
browser cookie into web/.env as WFM_JWT) calls GET /v1/profile/orders,
which returns their orders no matter the online status. Invisible hides
listings from every public view, so a token is the only reliable read.

Fallback is the public GET /v1/profile/{username}/orders, which needs no
key but only sees what buyers see. WFM_USERNAME also comes from web/.env.

The token is never logged or returned to the UI. It expires, roughly
every couple of weeks, and the UI says so when calls start failing.
Results are cached on disk for 15 minutes.
"""

import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENV_FILE = BASE / "web" / ".env"
CACHE_FILE = BASE / "my_listings_cache.json"
TTL_SECONDS = 15 * 60


def _env() -> dict:
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    return out


def username() -> str | None:
    import os
    name = os.environ.get("WFM_USERNAME", "").strip()
    if not name:
        name = _env().get("WFM_USERNAME", "")
    return name or None


def token() -> str | None:
    import os
    tok = os.environ.get("WFM_JWT", "").strip()
    if not tok:
        tok = _env().get("WFM_JWT", "")
    return tok or None


def _save(user: str, slugs: list, mode: str) -> None:
    CACHE_FILE.write_text(json.dumps({"name": user, "at": time.time(),
                                      "slugs": slugs, "mode": mode}),
                          encoding="utf-8")


def fetch_listed(user: str | None = None) -> dict:
    """{slugs, name, fetched, stale, mode}. Never raises, never leaks token."""
    import market_client
    import market_items
    user = user or username()
    tok = token()
    cached = {}
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cached = {}
    if cached.get("name") == user and time.time() - cached.get("at", 0) < TTL_SECONDS:
        return {"slugs": cached.get("slugs", []), "name": user,
                "fetched": cached.get("at"), "stale": False,
                "mode": cached.get("mode", "public")}
    # Token first: sees everything, invisible or not.
    if tok:
        try:
            data = market_client.get_json_auth(
                "https://api.warframe.market/v2/orders/my", tok)
            orders = data.get("data", [])
            by_id = market_items.index()["by_id"]
            slugs = set()
            for o in orders:
                if not isinstance(o, dict) or o.get("type") != "sell":
                    continue
                item = o.get("item") or {}
                slug = item.get("slug") or ""
                if not slug and o.get("itemId") and o["itemId"] in by_id:
                    slug = by_id[o["itemId"]].get("slug", "")
                if slug:
                    slugs.add(slug)
            slugs = sorted(slugs)
            _save(user, slugs, "token")
            return {"slugs": slugs, "name": user, "fetched": time.time(),
                    "stale": False, "mode": "token"}
        except Exception as e:
            if "401" in str(e) or "403" in str(e):
                return {"slugs": cached.get("slugs", []) if cached.get("name") == user else [],
                        "name": user, "fetched": cached.get("at"), "stale": True,
                        "mode": "token-expired"}
    # Public fallback: only what buyers can see.
    if user:
        try:
            data = market_client.get_json(
                f"https://api.warframe.market/v1/profile/{user}/orders")
            payload = data.get("payload", {})
            slugs = sorted({o.get("item", {}).get("url_name", "")
                            for o in payload.get("sell_orders", [])
                            if isinstance(o, dict) and o.get("item", {}).get("url_name")})
            _save(user, slugs, "public")
            return {"slugs": slugs, "name": user, "fetched": time.time(),
                    "stale": False, "mode": "public"}
        except Exception:
            pass
    if cached.get("name") == user and cached.get("slugs"):
        return {"slugs": cached["slugs"], "name": user,
                "fetched": cached.get("at"), "stale": True,
                "mode": cached.get("mode", "public")}
    return {"slugs": [], "name": user, "fetched": None, "stale": True,
            "mode": "none"}
