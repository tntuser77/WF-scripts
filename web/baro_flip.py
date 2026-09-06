"""Baro flip advisor. Unranked primed mods, advice only.

For each primed mod Baro stocks, this reads 90 days of rank 0 sale
history and answers two questions: what to list it at, and how many
to buy. Targets come from the last recovery ceiling, never the
pre-crash baseline. Quantities come from ducat budget and online
hours, halved for mods Baro repeats quickly.
"""

import json
import statistics
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CACHE_FILE = BASE / "baro_flip_cache.json"
CACHE_TTL_HOURS = 6

CAPTURE_SHARE = 0.10
WINDOW_WEEKS = 8
REPEAT_HALVE = 0.5
UNDERCUT = 2
MIN_TARGET = 25


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


def rank0_buckets(slug: str) -> list:
    """90d closed buckets for unranked copies, oldest first. 6h disk cache."""
    import market_client

    cache = _load_cache()
    entry = cache.get(slug)
    now = time.time()
    if entry and now - entry.get("at", 0) < CACHE_TTL_HOURS * 3600:
        return entry["buckets"]
    data = market_client.get_json(
        f"https://api.warframe.market/v1/items/{slug}/statistics")
    closed = data.get("payload", {}).get("statistics_closed", {})
    rows = [
        {"t": e.get("datetime", ""), "vol": e.get("volume") or 0,
         "median": e.get("median"), "max": e.get("max_price")}
        for e in closed.get("90days", [])
        if isinstance(e, dict) and e.get("mod_rank") == 0
    ]
    rows.sort(key=lambda r: r["t"])
    cache[slug] = {"at": now, "buckets": rows}
    _save_cache(cache)
    return rows


def _medians(rows: list) -> list:
    return [float(r["median"]) for r in rows if r["median"] is not None]


def find_crashes(rows: list) -> list:
    """Start dates of crash events: median drops to 70 percent or less of
    the prior 14 day peak. Days within 14 days of an event belong to it."""
    from datetime import date

    meds = [(r["t"][:10], float(r["median"])) for r in rows if r["median"] is not None]
    hits = []
    for i, (day, med) in enumerate(meds):
        window = [m for _, m in meds[max(0, i - 14):i]]
        if window and med <= 0.7 * max(window):
            hits.append(day)
    merged = []
    for day in hits:
        if merged and (date.fromisoformat(day) - date.fromisoformat(merged[-1])).days <= 14:
            continue
        merged.append(day)
    return merged


def analyze(item: str, ducats: int, credits: int) -> dict:
    """Flip row for one primed mod. Skips with a reason when untradable."""
    import market_client

    slug = market_client.slugify(item)
    rows = rank0_buckets(slug)
    meds = _medians(rows)
    if len(meds) < 30:
        return {"item": item, "slug": slug, "skip": True,
                "reason": "not enough sale history"}
    from datetime import date, timedelta
    crashes = find_crashes(rows)
    pre = [r for r in rows if not crashes or r["t"][:10] < crashes[0]]
    pre_meds = _medians(pre[-30:] if pre else rows[:30])
    baseline = round(statistics.median(pre_meds), 1)
    low = 0.7 * baseline
    last = rows[-1]
    in_crash = (last["median"] or 0) <= low
    if in_crash and crashes:
        anchor = crashes[-1]
        prior = crashes[-2] if len(crashes) >= 2 else None
        start = (date.fromisoformat(prior) + timedelta(days=7)).isoformat() \
            if prior else (date.fromisoformat(anchor) - timedelta(days=60)).isoformat()
        zone = [r for r in rows if start <= r["t"][:10] < anchor]
    elif crashes:
        start = (date.fromisoformat(crashes[-1]) + timedelta(days=7)).isoformat()
        zone = [r for r in rows if r["t"][:10] >= start]
    else:
        zone = rows
    zone_meds = _medians(zone)
    if not zone_meds:
        return {"item": item, "slug": slug, "skip": True,
                "reason": "no recovered market seen yet"}
    ceiling = min(max(zone_meds), baseline)
    target = max(MIN_TARGET, int(ceiling - UNDERCUT))
    fast = len(crashes) >= 2
    last30 = rows[-30:]
    daily_vol = sum(r["vol"] for r in last30) / max(len(last30), 1)
    hourly_rate = daily_vol * CAPTURE_SHARE / 24
    return {"item": item, "slug": slug, "ducats": ducats, "credits": credits,
            "baseline": baseline, "ceiling": round(ceiling, 1),
            "target": target, "crashed_now": in_crash,
            "repeat_hits_90d": len(crashes), "fast_repeater": fast,
            "daily_vol": round(daily_vol, 1),
            "hourly_rate": round(hourly_rate, 2)}


def size_qty(row: dict, hours_per_week: float) -> dict:
    """Gross copies wanted from time alone. Ducat budget gets allocated
    later, best returns first, so this names no limit yet."""
    want = int(row["hourly_rate"] * hours_per_week * WINDOW_WEEKS)
    if row["fast_repeater"]:
        want = int(want * REPEAT_HALVE)
    if want < 1:
        return {"qty": 0,
                "reason": f"{row['hourly_rate']}/hr x {hours_per_week}h x "
                          f"{WINDOW_WEEKS}w covers less than 1 copy"}
    return {"qty": want,
            "reason": f"{row['hourly_rate']}/hr x {hours_per_week}h x "
                      f"{WINDOW_WEEKS}w" +
                      (" halved, fast repeater" if row["fast_repeater"] else "")}


def compute(hours_per_week: float = 9.0) -> dict:
    """Full flip table for this visit's primed stock."""
    import baro

    visit = baro.fetch()
    mods = visit.get("primed", [])
    try:
        import advisor
        live = advisor.owned_from_dump()
        balance = live.get("ducats")
        owned = live.get("parts", {})
    except Exception:
        balance = None
        owned = {}
    rows = []
    for m in mods:
        try:
            row = analyze(m["item"], m["ducats"], m.get("credits"))
        except Exception as e:
            row = {"item": m["item"], "slug": m["item"],
                   "skip": True, "reason": str(e)[:80]}
        if row.get("skip"):
            rows.append(row)
            continue
        row["ppd"] = round(row["target"] / row["ducats"], 3) if row["ducats"] else 0
        row.update(size_qty(row, hours_per_week))
        row["owned"] = owned.get(row["slug"], 0)
        row["need"] = max(0, row["qty"] - row["owned"])
        rows.append(row)
    # Ducats go to the best plat per ducat first. Whatever is left stays
    # unspent for next visit instead of dribbling into weak returns.
    priced = sorted([r for r in rows if not r.get("skip")],
                    key=lambda r: r["ppd"], reverse=True)
    remaining = balance if balance else None
    best = priced[0]["item"] if priced else ""
    for row in priced:
        if remaining is None or not row["ducats"]:
            row["buy"] = row["need"]
            row["limited_by"] = "time"
            continue
        afford = int(remaining // row["ducats"])
        row["buy"] = min(row["need"], afford)
        row["limited_by"] = "ducats" if afford < row["need"] else "time"
        if row["buy"] < row["need"]:
            row["reason"] += f". Ducats earn more on {best}, saving the rest" \
                if row["item"] != best else ". Budget runs out here"
        remaining -= row["buy"] * row["ducats"]
    for row in rows:
        if row.get("skip"):
            continue
        row["credit_total"] = (row["credits"] or 0) * row["buy"]
        row["expect_plat"] = round(row["target"] * row["buy"], 1)
    rows.sort(key=lambda r: r.get("expect_plat", 0), reverse=True)
    return {"active": visit.get("active"), "expiry": visit.get("expiry"),
            "location": visit.get("location"), "stale": visit.get("stale"),
            "ducats_balance": balance, "unspent_ducats": remaining,
            "hours_per_week": hours_per_week, "rows": rows}
