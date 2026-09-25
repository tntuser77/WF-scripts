"""Session snapshots: before/after inventory dump diffs.

Each snapshot stores plat, part counts keyed by market slug, and relic
counts keyed by base name. Diffing two snapshots shows relics out,
parts in, plat delta, cracked value at median, and sold estimate from
part outflows. All part values use 48h medians, so plat made is an
estimate, not a ledger.

Relic cost is opportunity cost at market sell price when available.
Bought vs farmed relics look identical in the dump, so we value every
cracked relic the same way and say so in the UI.
"""

import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SNAP_DIR = BASE / "snapshots"
SNAP_DIR.mkdir(exist_ok=True)


def save(name: str | None = None) -> dict:
    import advisor
    live = advisor.owned_from_dump()
    snap = {"name": name or time.strftime("%Y-%m-%d %H:%M"),
            "taken": time.strftime("%Y-%m-%d %H:%M:%S"),
            "plat": live["plat"], "ducats": live.get("ducats"),
            "parts": live["parts"],
            "relics": {k: v.get("total", 0) for k, v in live["relics"].items()}}
    path = SNAP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return {"file": path.name, "snap": snap}


def load(name: str) -> dict:
    return json.loads((SNAP_DIR / name).read_text(encoding="utf-8"))


def list_all() -> list:
    out = []
    for p in sorted(SNAP_DIR.glob("*.json"), reverse=True):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            out.append({"file": p.name, "name": s.get("name"),
                        "taken": s.get("taken"), "plat": s.get("plat")})
        except Exception:
            continue
    return out


FODDER_MAX_PLAT = 20.0  # per-unit p48 under this goes to ducats
# Fixed ducat band between two anchor trades: own Primed Flow listing
# (33p / 350d) as the low end, Primed Redirection flip target
# (53p / 350d) as the top. Used whenever flip-plan rates are absent.
FLOW_PPD = 0.094
RED_PPD = 0.151
LOW_PPD = FLOW_PPD
AVG_PPD = round((FLOW_PPD + RED_PPD) / 2, 3)  # 0.122
ARCANES_PER_MAX = 21  # copies combined into one max-rank arcane


def ducat_rates() -> dict:
    """Fixed low/average plat per ducat from the Flow/Redirection band."""
    return {"low_ppd": LOW_PPD, "avg_ppd": AVG_PPD,
            "low_src": "own Primed Flow listing 33p/350d",
            "avg_src": "mean of Flow 0.094 and Redirection 0.151"}


def _classify(slugs: list) -> tuple:
    """{slug: prime|arcane|other|unknown} plus the catalog entries.

    Only prime parts and arcanes count in the tracker now. Mods and
    anything else catalogued are ignored. Slugs missing from the
    catalog keep the old pricing so new items never vanish silently."""
    import market_items
    try:
        by = market_items.index()["by_slug"]
    except Exception:
        by = {}
    kind = {}
    for s in slugs:
        entry = by.get(s)
        if entry is None:
            kind[s] = "unknown"
            continue
        tags = entry.get("tags") or []
        if "arcane_enhancement" in tags:
            kind[s] = "arcane"
        elif "prime" in tags:
            kind[s] = "prime"
        else:
            kind[s] = "other"
    return kind, by


def diff(a: dict, b: dict, progress=None) -> dict:
    """Diff snapshot a -> b. Values priced at 48h medians.

    Parts gained under FODDER_MAX_PLAT per unit count as ducat fodder:
    their plat value uses the fixed Flow/Redirection band instead of the
    median. Only prime parts and arcanes count; mods are ignored.
    progress(i, total, label) feeds the UI progress bar."""
    import advisor
    import market_client
    parts_a, parts_b = a.get("parts", {}), b.get("parts", {})
    relics_a, relics_b = a.get("relics", {}), b.get("relics", {})
    slugs = sorted(set(parts_a) | set(parts_b))
    kinds, catalog = _classify(slugs)
    # Only changed stacks need prices. Unchanged counts never enter a
    # value, so pricing all 1000+ owned slugs just burns minutes.
    changed = sorted(s for s in slugs
                     if parts_b.get(s, 0) != parts_a.get(s, 0))
    priced = [s for s in changed if kinds[s] in ("prime", "unknown")]
    arcane_slugs = [s for s in changed if kinds[s] == "arcane"]
    relic_names = sorted(set(relics_a) | set(relics_b))
    total = len(priced) + len(arcane_slugs) + len(relic_names) + 1
    done = 0

    def prog(label: str) -> None:
        nonlocal done
        done += 1
        if progress:
            progress(done, total, label)

    if progress:
        progress(0, total, "pricing gained and lost parts")
    prices = advisor.price_parts(
        priced,
        progress=lambda i, n, s: progress(i, total, s)
        if progress else None) if priced else {}
    arcane_max = {}
    for s in arcane_slugs:
        prog(f"arcane price {s}")
        try:
            top = (catalog.get(s) or {}).get("maxRank")
            arcane_max[s] = market_client.arcane_max_median(s, top)["median_max"]
        except Exception:
            arcane_max[s] = None
    done = len(priced) + len(arcane_slugs)

    def val(s):
        if kinds[s] == "arcane":
            m = arcane_max.get(s)
            return round(m / ARCANES_PER_MAX, 2) if isinstance(m, (int, float)) else 0.0
        v = prices.get(s, {}).get("p48")
        return v if isinstance(v, (int, float)) else 0.0

    def unit(s):
        if kinds[s] == "arcane":
            m = arcane_max.get(s)
            return round(m / ARCANES_PER_MAX, 2) if isinstance(m, (int, float)) else None
        v = prices.get(s, {}).get("p48")
        return v if isinstance(v, (int, float)) else None

    parts_in = []
    for s in changed:
        if kinds[s] == "other":
            continue
        n = parts_b.get(s, 0) - parts_a.get(s, 0)
        if n <= 0:
            continue
        u = unit(s)
        dq = prices.get(s, {}).get("ducats")
        # Arcanes never count as fodder: they hold plat value per copy
        # and have no ducat value to convert into.
        fodder = kinds[s] != "arcane" and u is not None and u < FODDER_MAX_PLAT
        parts_in.append({
            "part": s, "n": n, "kind": kinds[s],
            "p48": (u if kinds[s] == "arcane" else prices.get(s, {}).get("p48")),
            "value": round(val(s) * n, 1), "fodder": fodder,
            "ducats_each": dq if fodder and isinstance(dq, (int, float)) else None,
            "ducats": (dq * n) if fodder and isinstance(dq, (int, float)) else None,
        })
    parts_out = [{"part": s, "n": (parts_a.get(s, 0) - parts_b.get(s, 0)),
                   "p48": prices.get(s, {}).get("p48"),
                   "value": round(val(s) * (parts_a.get(s, 0) - parts_b.get(s, 0)), 1)}
                  for s in changed
                  if kinds[s] != "other" and parts_a.get(s, 0) > parts_b.get(s, 0)]
    relics_out = [{"relic": r, "n": (relics_a.get(r, 0) - relics_b.get(r, 0))}
                  for r in set(relics_a) | set(relics_b)
                  if relics_a.get(r, 0) > relics_b.get(r, 0)]
    relics_in = [{"relic": r, "n": (relics_b.get(r, 0) - relics_a.get(r, 0))}
                 for r in set(relics_a) | set(relics_b)
                 if relics_b.get(r, 0) > relics_a.get(r, 0)]

    # Opportunity cost of cracked relics at market sell, best effort.
    relic_cost = 0.0
    for e in relics_out:
        prog(f"relic price {e['relic']}")
        try:
            t = market_client.top_orders(e["relic"])
            if t.get("sell_price"):
                e["sell"] = t["sell_price"]
                relic_cost += t["sell_price"] * e["n"]
        except Exception:
            continue
    prog("ducat conversion rates")
    rates = ducat_rates()
    fodder_lines = [x for x in parts_in if x["fodder"]]
    fodder_ducats = sum(x["ducats"] or 0 for x in fodder_lines)
    fodder_plat_low = round(fodder_ducats * rates["low_ppd"], 1)
    fodder_plat_avg = round(fodder_ducats * rates["avg_ppd"], 1)
    arcane_plat_value = round(sum(x["value"] for x in parts_in
                                  if x.get("kind") == "arcane"), 1)
    cracked_plat_value = round(sum(x["value"] for x in parts_in
                                   if not x["fodder"]
                                   and x.get("kind") != "arcane"), 1)
    cracked_value = round(sum(x["value"] for x in parts_in), 1)
    sold_est = round(sum(x["value"] for x in parts_out), 1)
    plat_delta = None
    if isinstance(a.get("plat"), (int, float)) and isinstance(b.get("plat"), (int, float)):
        plat_delta = b["plat"] - a["plat"]
    ducat_delta = None
    if isinstance(a.get("ducats"), (int, float)) and isinstance(b.get("ducats"), (int, float)):
        ducat_delta = b["ducats"] - a["ducats"]
    parts_in.sort(key=lambda x: x["value"], reverse=True)
    parts_out.sort(key=lambda x: x["value"], reverse=True)
    relics_out.sort(key=lambda x: x["n"], reverse=True)
    return {"plat_from": a.get("plat"), "plat_to": b.get("plat"),
            "plat_delta": plat_delta, "ducats_from": a.get("ducats"),
            "ducats_to": b.get("ducats"), "ducat_delta": ducat_delta,
            "parts_in": parts_in[:30],
            "parts_out": parts_out[:30], "relics_out": relics_out[:30],
            "relics_in": relics_in[:30], "cracked_value": cracked_value,
            "cracked_plat_value": cracked_plat_value,
            "arcane_plat_value": arcane_plat_value,
            "fodder_ducats": fodder_ducats,
            "fodder_plat_low": fodder_plat_low,
            "fodder_plat_avg": fodder_plat_avg,
            "session_est": round(cracked_plat_value + arcane_plat_value
                                 + fodder_plat_low, 1),
            "rates": rates, "fodder_floor": FODDER_MAX_PLAT,
            "sold_est": sold_est, "relic_cost": round(relic_cost, 1)}
