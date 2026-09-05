"""Group owned parts into sets.

Set membership comes from the v2 item detail endpoint (setParts ids),
resolved to slugs through the catalog index. Membership barely changes
so details are cached on disk indefinitely. All market calls go through
the shared market_client limiter.
"""

import market_client
import market_items


def fetch_set_members(slug: str) -> list:
    """[url_names] in the same set as slug. Cached."""
    detail = market_items.fetch_detail(slug)
    idx = market_items.index()
    out = []
    for part_id in detail.get("setParts", []):
        entry = idx["by_id"].get(part_id)
        if entry:
            out.append(entry["slug"])
    return sorted(set(out))


def group_owned(owned: dict) -> dict:
    """owned: {url: count}. Returns {key: group} where group is
    {'members': [...], 'parts': [...] (members minus the _set root),
     'set_slug': '<name>_set' or None, 'owned': {url: count}}.

    Members found through any owned part merge together. The _set root is
    the sellable product, never an owned part, so completion math uses
    'parts' only.
    """
    groups: dict = {}
    for url in owned:
        try:
            members = fetch_set_members(url)
        except Exception:
            members = []
        if not members:
            groups.setdefault(("__single__", url), {"members": [url], "parts": [url],
                                                   "set_slug": None, "owned": {}})["owned"] = {url: owned[url]}
            continue
        key = tuple(sorted(set(members) | {url}))
        g = groups.setdefault(key, {"members": list(key),
                                    "parts": [m for m in key if not m.endswith("_set")],
                                    "set_slug": next((m for m in key if m.endswith("_set")), None),
                                    "owned": {}})
        for m in key:
            if m in owned:
                g["owned"][m] = owned[m]
    return groups


def ducats(slug: str) -> int | None:
    try:
        return market_items.fetch_detail(slug).get("ducats")
    except Exception:
        return None
