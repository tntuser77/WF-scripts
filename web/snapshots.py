"""Session snapshots: before/after AlecaFrame dump diffs.

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


def diff(a: dict, b: dict) -> dict:
    """Diff snapshot a -> b. Values priced at 48h medians."""
    import advisor
    import market_client
    parts_a, parts_b = a.get("parts", {}), b.get("parts", {})
    relics_a, relics_b = a.get("relics", {}), b.get("relics", {})
    slugs = set(parts_a) | set(parts_b)
    prices = advisor.price_parts(sorted(slugs)) if slugs else {}

    def val(s):
        v = prices.get(s, {}).get("p48")
        return v if isinstance(v, (int, float)) else 0.0

    parts_in = [{"part": s, "n": (parts_b.get(s, 0) - parts_a.get(s, 0)),
                 "p48": prices.get(s, {}).get("p48"),
                 "value": round(val(s) * (parts_b.get(s, 0) - parts_a.get(s, 0)), 1)}
                for s in slugs if parts_b.get(s, 0) > parts_a.get(s, 0)]
    parts_out = [{"part": s, "n": (parts_a.get(s, 0) - parts_b.get(s, 0)),
                  "p48": prices.get(s, {}).get("p48"),
                  "value": round(val(s) * (parts_a.get(s, 0) - parts_b.get(s, 0)), 1)}
                 for s in slugs if parts_a.get(s, 0) > parts_b.get(s, 0)]
    relics_out = [{"relic": r, "n": (relics_a.get(r, 0) - relics_b.get(r, 0))}
                  for r in set(relics_a) | set(relics_b)
                  if relics_a.get(r, 0) > relics_b.get(r, 0)]
    relics_in = [{"relic": r, "n": (relics_b.get(r, 0) - relics_a.get(r, 0))}
                 for r in set(relics_a) | set(relics_b)
                 if relics_b.get(r, 0) > relics_a.get(r, 0)]

    # Opportunity cost of cracked relics at market sell, best effort.
    relic_cost = 0.0
    for e in relics_out:
        try:
            t = market_client.top_orders(e["relic"])
            if t.get("sell_price"):
                e["sell"] = t["sell_price"]
                relic_cost += t["sell_price"] * e["n"]
        except Exception:
            continue
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
            "sold_est": sold_est, "relic_cost": round(relic_cost, 1)}
