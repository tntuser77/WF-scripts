"""
relic_db.py

Storage + price-checking layer that sits on top of list_of_relics.py.

Workflow:
    1. list_of_relics.py builds `localRelics` (owned relics + their gold part urlName)
    2. upsert_inventory() writes that into SQLite (relics + gold_parts tables)
    3. refresh_prices() rate-limit-fetches any prices that are missing/stale
    4. relics_worth_upgrading() / relics_worth_opening() give you the two lists

Run this file directly (after importing localRelics) to print both lists.
"""

import re
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

DB_PATH = "relics.db"

FLIP_THRESHOLD_PLAT = 38        # your existing "worth it" cutoff
BUCKET_SIZE_PLAT = 10           # bucket width for the grouped report below
MIN_BUCKET_PLAT = 37            # floor for the grouped report -- lower than
                                 # FLIP_THRESHOLD_PLAT so you can see a couple
                                 # of cheaper tiers and judge for yourself
RATE_LIMIT_DELAY = 0.34         # ~3 requests/sec, with a little headroom

# Tiered re-check cadence, based on the LAST KNOWN price for that part.
# A part's own last-seen price decides how eager we are to refresh it --
# expensive parts move fast and are worth checking every run; cheap parts
# aren't worth the request budget.
TIER_ALWAYS_PLAT = 37    # last known price >= this -> re-check every run
TIER_DAILY_PLAT = 33     # last known price >= this -> re-check at most daily
STALE_ALWAYS = timedelta(0)
STALE_DAILY = timedelta(days=1)
STALE_WEEKLY = timedelta(days=7)   # everything else (including never-priced)


def _stale_threshold_for_price(avg_48h):
    """Never-priced parts are always stale (we have nothing to go on)."""
    if avg_48h is None:
        return STALE_ALWAYS
    if avg_48h >= TIER_ALWAYS_PLAT:
        return STALE_ALWAYS
    if avg_48h >= TIER_DAILY_PLAT:
        return STALE_DAILY
    return STALE_WEEKLY

# NOTE: relic uniqueNames / display names typically end in one of these.
# CONFIRM this against a real sample of r.Name / r.uniqueName before trusting
# the split — see check_refinement_parsing() at the bottom.
REFINEMENT_SUFFIXES = ["Radiant", "Flawless", "Exceptional", "Intact"]


def split_refinement(name: str):
    """'Meso V1 Relic Radiant' -> ('Meso V1 Relic', 'Radiant')"""
    for suffix in REFINEMENT_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)].strip(), suffix
    return name, "Intact"  # fallback assumption if no suffix is present


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relics (
            base_name  TEXT,
            refinement TEXT,
            count      INTEGER,
            last_seen  TEXT,
            PRIMARY KEY (base_name, refinement)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_parts (
            base_name TEXT PRIMARY KEY,
            part_name TEXT,
            url_name  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_cache (
            url_name         TEXT PRIMARY KEY,
            avg_48h          REAL,
            is_trending_down INTEGER,
            checked_at       TEXT
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Ingest owned relics (from list_of_relics.py's `localRelics`)
# ---------------------------------------------------------------------------

def upsert_inventory(conn: sqlite3.Connection, local_relics):
    now = datetime.now(timezone.utc).isoformat()

    for r in local_relics:
        base_name, refinement = split_refinement(r.Name)

        conn.execute("""
            INSERT INTO relics (base_name, refinement, count, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(base_name, refinement) DO UPDATE SET
                count = excluded.count,
                last_seen = excluded.last_seen
        """, (base_name, refinement, r.Count, now))

        if r.goldUrlName:
            part_name = ""
            if r.goldReward and isinstance(r.goldReward.item, dict):
                part_name = r.goldReward.item.get("name", "")

            conn.execute("""
                INSERT INTO gold_parts (base_name, part_name, url_name)
                VALUES (?, ?, ?)
                ON CONFLICT(base_name) DO UPDATE SET
                    part_name = excluded.part_name,
                    url_name  = excluded.url_name
            """, (base_name, part_name, r.goldUrlName))

    conn.commit()


# ---------------------------------------------------------------------------
# Price fetching (rate-limited, cache-aware)
# ---------------------------------------------------------------------------

def _fetch_price_from_api(url_name: str):
    """
    Hits warframe.market's statistics endpoint and returns
    (avg_48h, is_trending_down) or (None, None) on failure.

    NOTE: this is the v1 API (api.warframe.market/v1/...). It still works
    but WFM has a v2 in progress that will eventually replace it -- worth
    revisiting this function if v1 gets shut off.
    """
    url = f"https://api.warframe.market/v1/items/{url_name}/statistics"
    try:
        resp = requests.get(url, params={"include": "item"}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()["payload"]["statistics_closed"]["48hours"]
    except (requests.RequestException, KeyError, ValueError):
        return None, None

    if not payload:
        return None, None

    # payload is a list of hourly buckets across the 48h window, oldest first
    latest = payload[-1]
    avg_48h = sum(bucket.get("avg_price", 0) for bucket in payload) / len(payload)

    # "trending down": most recent bucket's avg is meaningfully below the
    # 48h average AND it has real volume (not just one stale listing)
    is_trending_down = int(
        latest.get("volume", 0) > 0
        and latest.get("avg_price", avg_48h) < avg_48h * 0.85
    )

    return avg_48h, is_trending_down


def _print_progress(current: int, total: int, label: str, bar_width: int = 30):
    """
    Simple dependency-free progress bar, e.g.:
    [######............] 6/20 (30%) - Akstiletto Prime Barrel
    Overwrites the same terminal line via \r; prints a final newline when done.
    """
    filled = int(bar_width * current / total) if total else bar_width
    bar = "#" * filled + "." * (bar_width - filled)
    pct = int(100 * current / total) if total else 100
    # pad label field so shorter names fully overwrite longer previous ones
    line = f"\r[{bar}] {current}/{total} ({pct}%) - {label}"
    print(line.ljust(100), end="", flush=True)
    if current == total:
        print()


def refresh_prices(conn: sqlite3.Connection, show_progress: bool = True):
    """
    Refetches prices using a tiered cadence keyed off each part's LAST KNOWN
    price (see _stale_threshold_for_price): >=37p re-checked every run,
    >=33p at most once a day, anything cheaper (or never priced) at most
    once a week. Only touches parts relevant right now: gold parts for
    relics you currently own at Intact/Exceptional/Flawless (candidates to
    upgrade) or already at Radiant (candidates to open).
    """
    now = datetime.now(timezone.utc)

    candidates = conn.execute("""
        SELECT DISTINCT gp.url_name, gp.part_name, gp.base_name, pc.avg_48h, pc.checked_at
        FROM gold_parts gp
        JOIN relics r ON r.base_name = gp.base_name
        LEFT JOIN price_cache pc ON pc.url_name = gp.url_name
        WHERE r.count > 0
          AND gp.url_name != ''
    """).fetchall()

    rows = []
    for url_name, part_name, base_name, avg_48h, checked_at in candidates:
        if checked_at is None:
            stale = True
        else:
            checked_dt = datetime.fromisoformat(checked_at)
            stale = (now - checked_dt) >= _stale_threshold_for_price(avg_48h)
        if stale:
            rows.append((url_name, part_name, base_name))

    total = len(rows)
    if show_progress and total == 0:
        print("Nothing to price-check -- all cached prices are still fresh.")

    for i, (url_name, part_name, base_name) in enumerate(rows, start=1):
        label = part_name or url_name
        if show_progress:
            _print_progress(i, total, f"{base_name}: {label}")

        avg_48h, is_trending_down = _fetch_price_from_api(url_name)
        if avg_48h is not None:
            conn.execute("""
                INSERT INTO price_cache (url_name, avg_48h, is_trending_down, checked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(url_name) DO UPDATE SET
                    avg_48h = excluded.avg_48h,
                    is_trending_down = excluded.is_trending_down,
                    checked_at = excluded.checked_at
            """, (url_name, avg_48h, is_trending_down, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        time.sleep(RATE_LIMIT_DELAY)


# ---------------------------------------------------------------------------
# The two lists you actually want
# ---------------------------------------------------------------------------

def relics_worth_upgrading(conn: sqlite3.Connection, threshold=FLIP_THRESHOLD_PLAT):
    return conn.execute("""
        SELECT r.base_name, r.refinement, r.count, gp.part_name, pc.avg_48h, pc.is_trending_down
        FROM relics r
        JOIN gold_parts gp ON gp.base_name = r.base_name
        JOIN price_cache pc ON pc.url_name = gp.url_name
        WHERE r.count > 0
          AND r.refinement != 'Radiant'
          AND pc.avg_48h >= ?
        ORDER BY pc.avg_48h DESC
    """, (threshold,)).fetchall()


def relics_worth_opening(conn: sqlite3.Connection, threshold=FLIP_THRESHOLD_PLAT):
    return conn.execute("""
        SELECT r.base_name, r.count, gp.part_name, pc.avg_48h, pc.is_trending_down
        FROM relics r
        JOIN gold_parts gp ON gp.base_name = r.base_name
        JOIN price_cache pc ON pc.url_name = gp.url_name
        WHERE r.count > 0
          AND r.refinement = 'Radiant'
          AND pc.avg_48h >= ?
        ORDER BY pc.avg_48h DESC
    """, (threshold,)).fetchall()



def check_refinement_parsing(local_relics, sample=10, verbose=True):
    """
    Parses every relic's Name and separates the ones that matched a known
    refinement suffix from the ones that fell through to the ('Intact')
    fallback in split_refinement(). A fallback hit either means:
      (a) it's a genuinely Intact relic whose name has no suffix at all, or
      (b) split_refinement() failed to recognize the suffix it actually has.
    This can't tell (a) from (b) automatically -- that's why every fallback
    hit is printed for a quick manual glance, rather than silently trusted.

    Returns (matched, unmatched) -- two lists of localRelic objects.
    """
    matched, unmatched = [], []

    for r in local_relics:
        name = r.Name or ""
        hit_suffix = next((s for s in REFINEMENT_SUFFIXES if name.endswith(s)), None)
        (matched if hit_suffix else unmatched).append(r)

    if verbose:
        print(f"Parsed {len(local_relics)} relics: "
              f"{len(matched)} matched a known suffix, {len(unmatched)} fell back.")

        print(f"\nSample of matched parses (showing {min(sample, len(matched))}):")
        for r in matched[:sample]:
            print(f"  {r.Name!r} -> {split_refinement(r.Name)}")

        if unmatched:
            print(f"\nAll {len(unmatched)} relics that fell back to the 'Intact' "
                  f"default (verify these by hand -- see docstring above):")
            for r in unmatched:
                print(f"  {r.Name!r} -> {split_refinement(r.Name)}")
        else:
            print("\nNo fallback hits -- every relic name matched a known suffix.")

    return matched, unmatched


def _bucket_price(avg_48h: float, bucket_size: int = BUCKET_SIZE_PLAT) -> int:
    """47 -> 50, 37 -> 40, 33 -> 30 (round to nearest bucket, ties round up)."""
    return int((avg_48h / bucket_size) + 0.5) * bucket_size


def _print_bucketed_report(rows, title: str, row_kind: str, bucket_size: int = BUCKET_SIZE_PLAT):
    """
    Groups rows into price buckets and prints each bucket as:

        --- <title> <bucket>p: <N>x relics total ---
          <relic line>
          <relic line>
          ...

    row_kind is 'upgrading' or 'opening' -- controls tuple unpacking, since
    relics_worth_upgrading() rows carry an extra `refinement` field.
    """
    if not rows:
        print(f"\n=== {title} ===\n  Nothing worth running right now.")
        return

    buckets = defaultdict(list)
    for row in rows:
        if row_kind == "upgrading":
            base_name, refinement, count, part_name, avg_48h, trending_down = row
            line = f"  {base_name} [{refinement}] x{count}  ->  {part_name}: {avg_48h:.1f}p"
        else:
            base_name, count, part_name, avg_48h, trending_down = row
            line = f"  {base_name} x{count}  ->  {part_name}: {avg_48h:.1f}p"
        if trending_down:
            line += "  << price dropping"
        buckets[_bucket_price(avg_48h, bucket_size)].append((count, line))

    print(f"\n=== {title} ===")
    for label in sorted(buckets.keys(), reverse=True):
        items = buckets[label]
        total_relics = sum(count for count, _ in items)

        print(f"\n--- {title} {label}p: "
              f"{total_relics}x relics ({len(items)} types) ---")
        for _, line in items:
            print(line)


def _print_recommendations(conn: sqlite3.Connection, min_threshold=MIN_BUCKET_PLAT):
    upgrading = relics_worth_upgrading(conn, min_threshold)
    opening = relics_worth_opening(conn, min_threshold)

    _print_bucketed_report(upgrading, "Worth upgrading", "upgrading")
    _print_bucketed_report(opening, "Worth opening", "opening")

    if not upgrading and not opening:
        print("\nNothing worth running right now -- check back after your next mission.")


if __name__ == "__main__":
    from list_of_relics import localRelics

    conn = init_db()

    _, unmatched = check_refinement_parsing(localRelics, verbose=False)
    if unmatched:
        print(f"Note: {len(unmatched)} relic(s) didn't match a known refinement "
              f"suffix and were kept as 'Intact' by default -- verify these:")
        for r in unmatched:
            print(f"  - {r.Name}")

    upsert_inventory(conn, localRelics)
    refresh_prices(conn)
    _print_recommendations(conn)

