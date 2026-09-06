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
DETAIL_CACHE_FILE = BASE / "my_orders_cache.json"
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


def my_sell_orders() -> dict:
    """{slug: [{price, qty, rank}]} for own visible sell orders. Token
    first, public profile fallback. 15 minute disk cache. Never raises."""
    import market_client

    user = username()
    tok = token()
    if DETAIL_CACHE_FILE.exists():
        try:
            cached = json.loads(DETAIL_CACHE_FILE.read_text(encoding="utf-8"))
            if cached.get("name") == user and \
                    time.time() - cached.get("at", 0) < TTL_SECONDS:
                return cached.get("orders", {})
        except Exception:
            pass
    orders: dict = {}

    def add(slug, price, qty, rank):
        if slug:
            orders.setdefault(slug, []).append(
                {"price": price, "qty": qty, "rank": rank})

    if tok:
        try:
            data = market_client.get_json_auth(
                "https://api.warframe.market/v2/orders/my", tok)
            for o in data.get("data", []):
                if not isinstance(o, dict) or o.get("type") != "sell":
                    continue
                item = o.get("item") or {}
                slug = item.get("slug") or ""
                if not slug and o.get("itemId"):
                    try:
                        import market_items
                        slug = market_items.index()["by_id"].get(
                            o["itemId"], {}).get("slug", "")
                    except Exception:
                        pass
                add(slug, o.get("platinum"), o.get("quantity"),
                    o.get("rank"))
            DETAIL_CACHE_FILE.write_text(json.dumps(
                {"name": user, "at": time.time(), "orders": orders}),
                encoding="utf-8")
            return orders
        except Exception:
            pass
    if user:
        try:
            data = market_client.get_json(
                f"https://api.warframe.market/v1/profile/{user}/orders")
            for o in (data.get("payload", {}).get("sell_orders", []) or []):
                if not isinstance(o, dict):
                    continue
                add((o.get("item") or {}).get("url_name", ""),
                    o.get("platinum"), o.get("quantity"),
                    (o.get("item") or {}).get("mod_rank"))
            DETAIL_CACHE_FILE.write_text(json.dumps(
                {"name": user, "at": time.time(), "orders": orders}),
                encoding="utf-8")
            return orders
        except Exception:
            pass
    return orders


def _consensus_subtype(slug: str) -> str | None:
    """Most common subtype among live orders, for variant items like the
    Regular versus Atragraph Target Cracker. None when the market shows
    no consensus."""
    import market_client
    from collections import Counter

    try:
        data = market_client.get_json(
            f"https://api.warframe.market/v2/orders/item/{slug}/top")
        orders = data.get("data", {})
        votes = Counter(
            e.get("subtype") for e in (orders.get("sell", []) +
                                       orders.get("buy", []))
            if isinstance(e, dict) and e.get("subtype"))
        return votes.most_common(1)[0][0] if votes else None
    except Exception:
        return None


def _error_detail(e: Exception) -> str:
    try:
        return (e.response.text or "")[:160]
    except Exception:
        return ""


def _post_order(tok: str, body: dict) -> dict:
    import market_client

    data = market_client.post_json_auth(
        "https://api.warframe.market/v2/order", tok, body)
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    if DETAIL_CACHE_FILE.exists():
        DETAIL_CACHE_FILE.unlink()
    order = (data.get("data") or {})
    return {"ok": True, "order_id": order.get("id")}


def create_sell_order(slug: str, price: int, quantity: int,
                      rank: int | None = None,
                      subtype: str | None = None) -> dict:
    """List owned stock at a fixed unit price. Rankable items (mods) need
    their rank, unranked copies list at 0. Variant items like the
    Regular versus Atragraph Target Cracker need their subtype, resolved
    from live orders when the caller does not name one. Returns
    {ok, order_id/error}.

    Visible immediately. Callers confirm with the user first, this does
    not second guess them.
    """
    import market_client
    import market_items
    tok = token()
    if not tok:
        return {"ok": False, "error": "no token, add WFM_JWT to web/.env"}
    if not slug or price < 1 or quantity < 1:
        return {"ok": False, "error": "bad slug, price, or quantity"}
    try:
        entry = market_items.index()["by_slug"].get(slug, {})
        item_id = entry.get("id")
        if not item_id:
            return {"ok": False, "error": f"unknown item {slug}"}
        body = {"itemId": item_id, "type": "sell", "platinum": int(price),
                "quantity": int(quantity), "visible": True}
        if entry.get("bulkTradable"):
            body["perTrade"] = 1
        if rank is not None:
            top = entry.get("maxRank")
            if top is not None and not (0 <= int(rank) <= int(top)):
                return {"ok": False,
                        "error": f"rank {rank} outside 0-{top} for {slug}"}
            body["rank"] = int(rank)
        if subtype:
            body["subtype"] = subtype
        try:
            return _post_order(tok, body)
        except Exception as e:
            detail = _error_detail(e)
            if "subtype" not in detail or subtype:
                raise
            consensus = _consensus_subtype(slug)
            if not consensus:
                raise
            body["subtype"] = consensus
            return _post_order(tok, body)
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg:
            return {"ok": False, "error": "token expired, paste a fresh JWT"}
        detail = _error_detail(e)
        return {"ok": False, "error": (msg[:120] + " " + detail).strip()}
