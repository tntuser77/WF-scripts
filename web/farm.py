"""Banshee / Mirage farm tracker.

Target block is the frames-only plan from chat:
  300x Neo B6 radiant, 300x Lith M7 radiant,
  220x Lith K5 flawless, 220x Axi A12 flawless,
  200x Axi H5 flawless, 0x Meso E5.
Parts goal is 100 of each frame part.

Reads the same inventory dump as advisor, so counts match the
rest of the page. No market calls, fully offline.
"""

FARM_TARGETS = [
    {"relic": "Neo B6", "ref": "Radiant", "need": 300,
     "target": "Banshee Chassis"},
    {"relic": "Lith M7", "ref": "Radiant", "need": 300,
     "target": "Mirage Blueprint"},
    {"relic": "Lith K5", "ref": "Flawless", "need": 220,
     "target": "Banshee Systems"},
    {"relic": "Axi A12", "ref": "Flawless", "need": 220,
     "target": "Banshee Blueprint"},
    {"relic": "Axi H5", "ref": "Flawless", "need": 200,
     "target": "Mirage Systems"},
    {"relic": "Meso E5", "ref": "none", "need": 0,
     "target": "skipped"},
]

PART_TARGETS = [
    {"slug": "banshee_prime_blueprint", "label": "Banshee Blueprint",
     "need": 100},
    {"slug": "banshee_prime_chassis_blueprint", "label": "Banshee Chassis",
     "need": 100},
    {"slug": "banshee_prime_neuroptics_blueprint", "label": "Banshee Neuroptics",
     "need": 100},
    {"slug": "banshee_prime_systems_blueprint", "label": "Banshee Systems",
     "need": 100},
    {"slug": "mirage_prime_blueprint", "label": "Mirage Blueprint",
     "need": 100},
    {"slug": "mirage_prime_chassis_blueprint", "label": "Mirage Chassis",
     "need": 100},
    {"slug": "mirage_prime_neuroptics_blueprint", "label": "Mirage Neuroptics",
     "need": 100},
    {"slug": "mirage_prime_systems_blueprint", "label": "Mirage Systems",
     "need": 100},
]

UPGRADE_COST = {"Radiant": 100, "Flawless": 50,
                "Exceptional": 25, "Intact": 0, "none": 0}

SUPPLY = {
    "Neo B6": ["banshee_prime_chassis_blueprint",
               "mirage_prime_neuroptics_blueprint"],
    "Lith M7": ["mirage_prime_blueprint",
                "banshee_prime_neuroptics_blueprint"],
    "Lith K5": ["banshee_prime_systems_blueprint",
                "mirage_prime_chassis_blueprint"],
    "Axi A12": ["banshee_prime_blueprint",
                "mirage_prime_chassis_blueprint"],
    "Axi H5": ["mirage_prime_systems_blueprint",
               "banshee_prime_neuroptics_blueprint"],
    "Meso E5": [],
}


def _dynamic_need(base_need: int, slugs: list, remaining: dict) -> int:
    import math
    if base_need <= 0 or not slugs:
        return base_need
    frac = 0.0
    for s in slugs:
        need = 100
        for p in PART_TARGETS:
            if p["slug"] == s:
                need = int(p["need"])
                break
        rem = int(remaining.get(s, need) or 0)
        frac = max(frac, rem / need if need else 0.0)
    return int(math.ceil(base_need * frac))


def _ref_counts(entry: dict) -> dict:
    out = {"Intact": 0, "Exceptional": 0, "Flawless": 0, "Radiant": 0}
    for k in out:
        try:
            out[k] = int(entry.get(k, 0) or 0)
        except (TypeError, ValueError):
            out[k] = 0
    return out


def farm_status() -> dict:
    import advisor

    live = advisor.owned_from_dump()
    owned_relics = live.get("relics", {}) or {}
    owned_parts = live.get("parts", {}) or {}

    relic_rows = []
    total_buy = 0
    total_traces = 0
    remaining_map = {}
    for p in PART_TARGETS:
        have = int(owned_parts.get(p["slug"], 0) or 0)
        remaining_map[p["slug"]] = max(0, int(p["need"]) - have)
    for t in FARM_TARGETS:
        base = t["relic"]
        ref = t["ref"]
        base_need = int(t["need"])
        need = _dynamic_need(base_need, SUPPLY.get(base, []),
                             remaining_map)
        entry = owned_relics.get(base, {}) or {}
        counts = _ref_counts(entry)
        total = int(entry.get("total", 0) or 0)
        have_ref = counts.get(ref, 0) if ref in counts else total
        upgradeable = max(0, total - have_ref)
        buy = max(0, need - total)
        # upgrades still needed to hit `need` at target refinement
        upgrade_need = max(0, need - have_ref)
        # traces assume upgrading from intact; refining in steps costs
        # the difference, so full cost is a safe upper bound
        traces = upgrade_need * UPGRADE_COST.get(ref, 0)
        total_buy += buy
        total_traces += traces
        relic_rows.append({
            "relic": base, "ref": ref, "need": need,
            "base_need": base_need,
            "have_total": total, "have_ref": have_ref,
            "have_intact": counts["Intact"],
            "have_exceptional": counts["Exceptional"],
            "have_flawless": counts["Flawless"],
            "have_radiant": counts["Radiant"],
            "upgradeable": upgradeable, "buy": buy,
            "upgrade_need": upgrade_need, "traces": traces,
            "target": t["target"],
        })

    part_rows = []
    counts_only = []
    for p in PART_TARGETS:
        have = int(owned_parts.get(p["slug"], 0) or 0)
        need = int(p["need"])
        remaining = max(0, need - have)
        counts_only.append(have)
        part_rows.append({
            "slug": p["slug"], "label": p["label"],
            "need": need, "have": have, "remaining": remaining,
        })

    banshee_sets = min(counts_only[0:4]) if counts_only else 0
    mirage_sets = min(counts_only[4:8]) if counts_only else 0

    return {
        "ok": True,
        "relics": relic_rows,
        "parts": part_rows,
        "banshee_sets": banshee_sets,
        "mirage_sets": mirage_sets,
        "total_buy": total_buy,
        "total_traces": total_traces,
        "plat": live.get("plat"),
    }
