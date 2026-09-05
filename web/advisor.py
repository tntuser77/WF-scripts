"""Set-aware sell advisor.

Reads the AlecaFrame dump, groups owned prime parts into sets via sets.py,
prices parts at 48h medians, prices full sets via top sell listings on
*_set slugs, and sources missing pieces from Relics.json.

Conventions kept deliberately simple for the first panel:
- sell-now for a set counts every owned copy at median (part-out value).
- owned-1x counts one of each owned part (completion math only).
- marginal = set price - owned-1x. That is YOUR value of the missing piece.
- verdict compares marginal against buying the missing piece outright.
- expected runs assume intact relics, 4 squad rolls per run.
"""

import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts" / "relicscanner"))

import market_client
import market_items
import item_map
import sets

# Fixed refinement tier odds: common / uncommon / rare per single roll.
ODDS = {
    "intact": (0.76, 0.22, 0.02),
    "exceptional": (0.70, 0.26, 0.04),
    "flawless": (0.60, 0.34, 0.06),
    "radiant": (0.50, 0.40, 0.10),
}

DUMP_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "AlecaFrame", "lastData.dat")
WFCD_CACHE = BASE / "Relics.json"


def load_dump() -> dict:
    from decrypt import process_data
    return json.loads(process_data(DUMP_PATH))


def owned_from_dump(data: dict | None = None) -> dict:
    """{parts: {slug: count}, relics: {base: {ref: count, total}}, plat, unmapped}."""
    data = data if data is not None else load_dump()
    mp = item_map.load_map()
    parts: dict = {}
    relics: dict = {}
    unmapped = []
    ducats = None
    wfcd = {r["uniqueName"]: r for r in json.loads(WFCD_CACHE.read_text(encoding="utf-8"))} \
        if WFCD_CACHE.exists() else {}
    for it in data.get("MiscItems", []):
        t = it.get("ItemType", "")
        c = it.get("ItemCount", 0)
        if c <= 0:
            continue
        if "PrimeBucks" in t:
            ducats = c
            continue
        if "Projection" in t:
            r = wfcd.get(t)
            if not r:
                continue
            name = r.get("name", "")
            base, ref = name, "Intact"
            for suf in ("Radiant", "Flawless", "Exceptional", "Intact"):
                if name.endswith(" " + suf) or name.endswith(suf):
                    base = name[: -len(suf)].strip()
                    ref = suf
                    break
            e = relics.setdefault(base, {"total": 0})
            e[ref] = e.get(ref, 0) + c
            e["total"] += c
            continue
        hit = mp.get(t)
        if not hit:
            if "Prime" in t or "prime" in t or "Primes" in t:
                unmapped.append(t)
            continue
        parts[hit["url"]] = parts.get(hit["url"], 0) + c
    return {"parts": parts, "relics": relics,
            "plat": data.get("PremiumCredits"), "ducats": ducats,
            "unmapped": sorted(set(unmapped))}


def _tradable_parts(owned_parts: dict) -> dict:
    """Keep only slugs with cached v2 detail (prime parts, not resources)."""
    det = market_items.load_details()
    return {s: c for s, c in owned_parts.items() if s in det}


def price_parts(slugs: list) -> dict:
    """{slug: {p48, p90, link, ducats}}. Medians use the 6h disk cache."""
    out = {}
    for s in slugs:
        try:
            st = market_client.part_statistics(s)
        except Exception:
            st = {"median_48h": None, "median_90d": None, "market_link": ""}
        try:
            dq = market_items.fetch_detail(s).get("ducats")
        except Exception:
            dq = None
        out[s] = {"p48": st.get("median_48h"), "p90": st.get("median_90d"),
                  "link": st.get("market_link", ""), "ducats": dq}
    return out


def price_sets(set_slugs: list) -> dict:
    """{slug: {sell, qty, avg_buy, link}}. Sets sell x1, no bulk rule."""
    out = {}
    for s in set_slugs:
        try:
            t = market_client.top_orders_by_slug(s, min_qty=1)
        except Exception:
            t = {"sell_price": None, "sell_qty": None, "avg_buy": None,
                 "market_link": f"https://warframe.market/items/{s}"}
        out[s] = {"sell": t.get("sell_price"), "qty": t.get("sell_qty"),
                  "avg_buy": t.get("avg_buy"), "link": t.get("market_link", "")}
    return out


def _wfcd_intact_tier_sizes() -> dict:
    """{(base relic, rarity-lower): count} from intact WFCD entries."""
    if not WFCD_CACHE.exists():
        return {}
    data = json.loads(WFCD_CACHE.read_text(encoding="utf-8"))
    sizes = {}
    for r in data:
        name = r.get("name", "")
        if not name.endswith(" Intact"):
            continue
        base = name[: -len(" Intact")].strip()
        for rw in r.get("rewards", []):
            key = (base, str(rw.get("rarity", "")).lower())
            sizes[key] = sizes.get(key, 0) + 1
    return sizes


def _reward_rarity(unique: str) -> str | None:
    if not WFCD_CACHE.exists():
        return None
    data = json.loads(WFCD_CACHE.read_text(encoding="utf-8"))
    for r in data:
        for rw in r.get("rewards", []) or []:
            item = rw.get("item") or {}
            if item.get("uniqueName") == unique:
                return str(rw.get("rarity", "")).lower()
    return None


def sources_for_missing(missing_slug: str, owned_relics: dict) -> list:
    """Relic sources for one missing part slug.

    Returns [{relic, rarity, owned, p_run, exp_runs}] sorted by owned desc
    then expected runs asc. Math assumes intact odds, 4 squad rolls.
    """
    if not WFCD_CACHE.exists():
        return []
    data = json.loads(WFCD_CACHE.read_text(encoding="utf-8"))
    mp = item_map.load_map()
    # uniqueNames that map to this slug
    refs = [ref for ref, e in mp.items() if e["url"] == missing_slug]
    sizes = _wfcd_intact_tier_sizes()
    common_p, uncom_p, rare_p = ODDS["intact"]
    found = {}
    for r in data:
        name = r.get("name", "")
        if not name.endswith(" Intact"):
            continue
        base = name[: -len(" Intact")].strip()
        for rw in r.get("rewards", []) or []:
            item = rw.get("item") or {}
            if item.get("uniqueName") not in refs:
                continue
            rar = str(rw.get("rarity", "")).lower()
            tier_n = sizes.get((base, rar), 1) or 1
            tier_p = {"common": common_p, "uncommon": uncom_p,
                      "rare": rare_p}.get(rar, 0.02)
            p_item = tier_p / tier_n
            p_run = 1 - (1 - p_item) ** 4
            exp_runs = round(1 / p_run, 1) if p_run > 0 else None
            key = (base, rar)
            prev = found.get(key)
            owned = (owned_relics.get(base, {}) or {}).get("total", 0)
            if prev is None or owned > prev["owned"]:
                found[key] = {"relic": base, "rarity": rar, "owned": owned,
                              "p_run": round(p_run, 4), "exp_runs": exp_runs}
    return sorted(found.values(), key=lambda x: (-x["owned"], x["exp_runs"] or 999))


def build_report(owned_parts: dict | None = None,
                 owned_relics: dict | None = None,
                 price_fn=None, set_price_fn=None,
                 listed: set | None = None) -> dict:
    """Full advisor report. price_fn/set_price_fn injectable for tests."""
    listed = listed or set()
    if owned_parts is None or owned_relics is None:
        live = owned_from_dump()
        owned_parts = live["parts"] if owned_parts is None else owned_parts
        owned_relics = live["relics"] if owned_relics is None else owned_relics
    tradable = _tradable_parts(owned_parts)
    groups = sets.group_owned(tradable) if tradable else {}
    part_slugs = sorted({p for g in groups.values() for p in g["parts"]})
    set_slugs = sorted({g["set_slug"] for g in groups.values() if g["set_slug"]})

    prices = (price_fn(part_slugs) if price_fn else price_parts(part_slugs))
    set_prices = (set_price_fn(set_slugs) if set_price_fn
                  else price_sets(set_slugs))

    def p48(s):
        v = prices.get(s, {}).get("p48")
        return v if isinstance(v, (int, float)) else 0.0

    near, complete, dust = [], [], []
    sell_rank = []
    for g in groups.values():
        parts = g["parts"]
        owned_1x = sum(p48(p) for p in parts if g["owned"].get(p, 0) > 0)
        sell_now = round(sum(p48(p) * g["owned"].get(p, 0) for p in parts), 1)
        missing = [p for p in parts if g["owned"].get(p, 0) <= 0]
        sp = set_prices.get(g["set_slug"] or "", {}) if g["set_slug"] else {}
        set_sell = sp.get("sell")
        ducats = sum((prices.get(p, {}).get("ducats") or 0)
                     for p in parts if g["owned"].get(p, 0) > 0)
        row = {"set": g["set_slug"], "parts": parts,
               "have": sum(1 for p in parts if g["owned"].get(p, 0) > 0),
               "need": len(parts), "missing": missing,
               "owned_1x": round(owned_1x, 1), "sell_now": sell_now,
               "set_sell": set_sell, "set_link": sp.get("link", ""),
               "ducats": ducats, "owned": dict(g["owned"]),
               "listed_parts": sorted([p for p in parts if p in listed]),
               "set_listed": (g["set_slug"] in listed) if g["set_slug"] else False,
               "prices": {p: prices.get(p, {}) for p in parts}}
        if not missing and g["set_slug"]:
            row["marginal"] = round((set_sell or 0) - 0, 1)
            complete.append(row)
        elif len(missing) == 1 and g["set_slug"]:
            m = missing[0]
            marginal = (set_sell - owned_1x) if set_sell else None
            buy = None
            try:
                buy = market_client.top_orders_by_slug(m, min_qty=1).get("sell_price")
            except Exception:
                buy = None
            srcs = sources_for_missing(m, owned_relics)
            best = next((s for s in srcs if s["owned"] > 0), srcs[0] if srcs else None)
            if marginal is not None and buy and buy < marginal:
                verdict = f"buy {m} at {buy}p, finish for {(set_sell or 0)}p"
            elif best and best["owned"] >= (best["exp_runs"] or 999):
                verdict = f"farm {best['relic']} ({best['exp_runs']} runs, own {best['owned']})"
            elif marginal is not None and marginal > 0:
                verdict = "hold, farm when you can"
            else:
                verdict = "sell parts"
            row.update({"marginal": round(marginal, 1) if marginal is not None else None,
                        "buy": buy, "source": best, "sources": srcs[:3],
                        "verdict": verdict})
            near.append(row)
        else:
            dust.append(row)
        for p in parts:
            if g["owned"].get(p, 0) > 0 and p48(p) > 0 and p not in listed:
                sell_rank.append({"part": p, "count": g["owned"][p],
                                  "p48": prices.get(p, {}).get("p48"),
                                  "value": round(p48(p) * g["owned"][p], 1),
                                  "set": g["set_slug"],
                                  "hold": len(missing) == 1,
                                  "link": prices.get(p, {}).get("link", "")})
    near.sort(key=lambda r: (r.get("marginal") or 0), reverse=True)
    complete.sort(key=lambda r: (r.get("set_sell") or 0), reverse=True)
    dust.sort(key=lambda r: r["sell_now"], reverse=True)
    sell_rank.sort(key=lambda r: r["value"], reverse=True)
    hidden = sum(1 for g in groups.values() for p in g["parts"]
                 if g["owned"].get(p, 0) > 0 and p in listed)
    return {"near": near, "complete": complete, "dust": dust,
            "sell_rank": sell_rank[:50], "hidden_listed": hidden,
            "listed_count": len(listed)}
