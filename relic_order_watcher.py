"""
relic_order_watcher.py

Watches warframe.market's realtime order feed and alerts the moment a
relic worth buying in bulk shows up: one of its gold-tier rewards is
priced over GOLD_PART_THRESHOLD plat, AND someone is currently selling
6+ of the relic in a single listing.

Pipeline:
  1. Parse input.html (the wiki "Void Relic/ByRewards/SimpleTable" page)
     to build item/part -> relic mapping, restricted to Rare (=gold)
     drops. This replaces the manually-maintained input1.csv.
  2. Bootstrap gold-part prices for every part in that mapping using
     fetch_part_statistics() (unchanged from your existing script),
     cached to disk so repeat runs don't re-hit the API for parts
     already priced recently.
  3. Keep only relics that have at least one gold part priced over
     GOLD_PART_THRESHOLD -> this is the watch list.
  4. Connect to the websocket, subscribe to new orders. When a new
     sell order posts for a watched relic, confirm live via your
     existing fetch_market_data() (which already picks the cheapest
     quantity>=6 listing if one exists) and alert if it still qualifies.

SETUP NEEDED BEFORE THIS WILL WORK:
1. pip install websockets beautifulsoup4
2. Put input.html (the wiki rewards table, saved from
   https://wiki.warframe.com/w/Void_Relic/ByRewards/SimpleTable) next
   to this script.
3. Run once with DISCOVERY_MODE = True. It prints every raw message
   for 30s so you can confirm the actual route name used for new
   sell-order events (I found the *subscribe* command in warframe.market's
   docs, but the page's reply/event-route table renders client-side and
   my page-fetch tool couldn't extract it -- so NEW_ORDER_EVENT_ROUTE
   below is my best guess, unverified). Once confirmed, set it and
   flip DISCOVERY_MODE to False.
   Also worth double checking CONNECTION_URL still matches what you
   see in your browser's devtools if it ever stops connecting --
   this is a pre-1.0 API and can change.
4. Optional: set DISCORD_WEBHOOK_URL (and DISCORD_USER_ID to get pinged)
   near the top of the file to also get alerts in Discord, not just
   locally. Leave blank to skip Discord entirely.
"""

import asyncio
import json
import os
import platform
import re
import subprocess
import time
import urllib.request
from urllib.error import HTTPError, URLError

import websockets
from bs4 import BeautifulSoup

# ============================================================
# Copied unchanged from create_spreadsheet_of_relic_and_part_prices.py
# ============================================================


def normalize_value(value: str) -> str:
    return value.strip().strip('"').strip("'")


def slugify(value: str) -> str:
    value = normalize_value(value).lower()
    value = value.replace(" ", "_").replace("-", "_")
    return "".join(char for char in value if char.isalnum() or char == "_")


def average_bucket_medians(buckets: list) -> float | None:
    medians = [
        float(entry["median"])
        for entry in buckets
        if isinstance(entry, dict) and entry.get("median") is not None
    ]
    if not medians:
        return None
    return sum(medians) / len(medians)


def fetch_part_statistics(item_name: str) -> dict:
    slug = slugify(item_name)
    api_url = f"https://api.warframe.market/v1/items/{slug}/statistics"
    market_url = f"https://warframe.market/items/{slug}"

    request = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        data = json.loads(body)
        closed = data.get("payload", {}).get("statistics_closed", {})

        return {
            "market_link": market_url,
            "median_90d": average_bucket_medians(closed.get("90days", [])),
            "median_48h": average_bucket_medians(closed.get("48hours", [])),
        }


def fetch_market_data(item_name: str) -> dict:
    slug = slugify(item_name)
    api_url = f"https://api.warframe.market/v2/orders/item/{slug}/top"
    market_url = f"https://warframe.market/items/{slug}"

    request = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        data = json.loads(body)
        orders = data.get("data", {})

        sell_entries = [
            entry for entry in orders.get("sell", []) if isinstance(entry, dict) and "platinum" in entry
        ]
        buy_entries = orders.get("buy", [])

        qualifying_sell_entries = [
            entry for entry in sell_entries if "quantity" in entry and int(entry.get("quantity", 0)) >= 6
        ]

        buy_prices = [
            float(entry.get("platinum", 0)) for entry in buy_entries if isinstance(entry, dict) and "platinum" in entry
        ]

        if qualifying_sell_entries:
            selected_entry = min(qualifying_sell_entries, key=lambda entry: float(entry.get("platinum", 0)))
        elif sell_entries:
            selected_entry = min(sell_entries, key=lambda entry: float(entry.get("platinum", 0)))
        else:
            selected_entry = None

        if selected_entry is not None:
            selected_price = float(selected_entry.get("platinum", 0))
            selected_quantity = int(selected_entry.get("quantity", 0))
        else:
            selected_price = None
            selected_quantity = None

        return {
            "market_link": market_url,
            "average_sell": selected_price,
            "average_buy": sum(buy_prices) / len(buy_prices) if buy_prices else None,
            "sell_quantity": selected_quantity,
        }


# ============================================================
# New: input.html mapping + price bootstrap + websocket watcher
# ============================================================

INPUT_HTML = "input.html"
PRICE_CACHE_FILE = "gold_part_price_cache.json"
PRICE_CACHE_TTL_HOURS = 6
GOLD_PART_THRESHOLD = 47  # 
GOLD_PROFIT_PER_HOUR_THRESHOLD = 100  # ((gold_price/3) - relic_price) * 27/1.5 must exceed this

# Discord: Server Settings -> Integrations -> Webhooks -> New Webhook, copy URL.
# User ID: enable Developer Mode (User Settings -> Advanced), right-click your
# name -> Copy User ID. Leave DISCORD_WEBHOOK_URL empty to disable this.
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1538535663924940892/p0FDWhRzljParz_lc9qIcKjyd_-c25c_kHUvlhKoGcGDQJJLTjZ7zLgaBdlF-mAEx-EY"  # e.g. "https://discord.com/api/webhooks/123.../abc..."
DISCORD_USER_ID = "945137263304671262"  # e.g. "123456789012345678"
REQUEST_DELAY = 0.4  # matches your existing script's rate-limit pacing
ALERT_COOLDOWN_SECONDS = 60  # don't re-confirm the same relic more than once a minute
ALERT_BEEP_COUNT = 1  # how many beeps to play per alert
POLL_INTERVAL_SECONDS = 300  # how often to re-check the full watch list via REST

CONNECTION_URL = "wss://ws.warframe.market/socket"
DISCOVERY_MODE = False
NEW_ORDER_EVENT_ROUTE = "@wfm|event/subscribe/newOrders"  # unverified, see docstring
SUBSCRIBE_MESSAGE = {
    "route": "@wfm|cmd/subscribe/newOrders",
    "id": "relic-watcher-1",
    "payload": {"platform": "pc", "crossplay": True},
}


def parse_relic_rewards(path: str) -> dict:
    """Returns {part_display_name: {relic_display_name, ...}} for Rare (gold) drops only."""
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    table = soup.find("table", class_="article-table")
    mapping: dict[str, set] = {}

    for row in table.find("tbody").find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        item = cells[0].get_text(strip=True)
        part = cells[1].get_text(strip=True)
        relic_name = cells[2].get_text(strip=True).replace("\xa0", " ")
        if not relic_name.endswith("Relic"):
            relic_name = f"{relic_name} Relic"
        rarity = cells[3].get_text(strip=True)
        if rarity != "Rare":
            continue
        part_name = f"{item} {part}"
        mapping.setdefault(part_name, set()).add(relic_name)

    return mapping


def load_price_cache() -> dict:
    if os.path.exists(PRICE_CACHE_FILE):
        with open(PRICE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_price_cache(cache: dict) -> None:
    with open(PRICE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def bootstrap_gold_part_prices(part_names, cache: dict) -> dict:
    """Fill in cache[part_name] = {price, market_link, fetched_at} for any part
    missing or stale, respecting the same request pacing as your existing script."""
    now = time.time()
    ttl_seconds = PRICE_CACHE_TTL_HOURS * 3600
    total = len(part_names)

    for i, part_name in enumerate(part_names, 1):
        entry = cache.get(part_name)
        if entry and now - entry["fetched_at"] < ttl_seconds:
            continue
        try:
            stats = fetch_part_statistics(part_name)
            cache[part_name] = {
                "price": stats["median_48h"],
                "market_link": stats["market_link"],
                "fetched_at": now,
            }
            print(f"  [{i}/{total}] {part_name}: {stats['median_48h']}")
        except (HTTPError, URLError) as error:
            print(f"  [{i}/{total}] {part_name}: failed ({error})")
        time.sleep(REQUEST_DELAY)

    save_price_cache(cache)
    return cache


def play_alert_sound(times: int = ALERT_BEEP_COUNT) -> None:
    """Loud, blocking-free-ish alert beep. Tries the native mechanism for
    the current OS first; falls back to the terminal bell if none work."""
    system = platform.system()

    for _ in range(times):
        try:
            if system == "Windows":
                import winsound

                winsound.Beep(1000, 350)
            elif system == "Darwin":
                subprocess.run(
                    ["afplay", "/System/Library/Sounds/Sosumi.aiff"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif system == "Linux":
                subprocess.run(
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                raise RuntimeError("unrecognized platform")
        except Exception:
            # Fall back to the terminal bell -- less loud, but always works.
            print("\a", end="", flush=True)
            time.sleep(0.2)


def send_discord_alert(message: str) -> None:
    """POSTs to a Discord webhook, pinging DISCORD_USER_ID if set. No-op if
    DISCORD_WEBHOOK_URL is empty. Runs synchronously -- call via
    asyncio.to_thread from async code so it doesn't block the event loop."""
    if not DISCORD_WEBHOOK_URL:
        return

    mention = f"<@{DISCORD_USER_ID}> " if DISCORD_USER_ID else ""
    body = json.dumps({"content": f"{mention}{message}"}).encode("utf-8")
    request = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (relic-order-watcher)",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"  Discord webhook failed: {error.code} {error.reason} -- {detail}")
    except URLError as error:
        print(f"  Discord webhook failed: {error}")


def compute_watched_relics(part_to_relics: dict, price_cache: dict) -> dict:
    """Returns {relic_display_name: [(part_name, price, market_link), ...]}
    for relics with at least one gold part over GOLD_PART_THRESHOLD."""
    relic_to_hits: dict[str, list] = {}
    for part_name, relics in part_to_relics.items():
        entry = price_cache.get(part_name)
        if not entry or entry["price"] is None:
            continue
        if entry["price"] > GOLD_PART_THRESHOLD:
            for relic in relics:
                relic_to_hits.setdefault(relic, []).append(
                    (part_name, entry["price"], entry["market_link"])
                )
    return relic_to_hits


async def confirm_and_alert(relic_name: str, relic_to_hits: dict, last_checked: dict, source: str) -> None:
    """Shared by both the websocket trigger and the poll loop: re-confirms
    live price/quantity via fetch_market_data and alerts if it still qualifies."""
    slug = slugify(relic_name)
    now = time.time()
    if now - last_checked.get(slug, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_checked[slug] = now

    try:
        relic_data = await asyncio.to_thread(fetch_market_data, relic_name)
    except (HTTPError, URLError) as error:
        print(f"  couldn't confirm {relic_name}: {error}")
        return

    if relic_data["average_sell"] is None or relic_data["sell_quantity"] is None:
        return
    if relic_data["sell_quantity"] < 6:
        return

    relic_price = relic_data["average_sell"]
    qualifying_parts = []
    for part_name, part_price, part_link in relic_to_hits[relic_name]:
        profit_per_hour = ((part_price / 3) - relic_price) * 27 / 1.5
        if profit_per_hour > GOLD_PROFIT_PER_HOUR_THRESHOLD:
            qualifying_parts.append((part_name, part_price, part_link, profit_per_hour))

    if not qualifying_parts:
        return

    print(
        f"[{time.strftime('%H:%M:%S')}] ({source}) "
        f"{relic_name} {relic_price:.0f} platinum "
        f"{relic_data['sell_quantity']}x {relic_data['market_link']}"
    )
    discord_lines = [
        f"**{relic_name}** {relic_price:.0f} platinum "
        f"{relic_data['sell_quantity']}x <{relic_data['market_link']}>"
    ]
    for part_name, part_price, part_link, profit_per_hour in qualifying_parts:
        print(f"    {part_name} {part_price:.0f} platinum ({profit_per_hour:.0f}/hr) {part_link}")
        discord_lines.append(
            f"> {part_name} {part_price:.0f} platinum ({profit_per_hour:.0f}/hr) <{part_link}>"
        )
    asyncio.create_task(asyncio.to_thread(play_alert_sound))
    asyncio.create_task(asyncio.to_thread(send_discord_alert, "\n".join(discord_lines)))


async def watch(relic_to_hits: dict, last_checked: dict) -> None:
    """Fast path: catches brand-new order postings the instant they happen."""
    watched_slugs = {slugify(relic): relic for relic in relic_to_hits}

    async with websockets.connect(CONNECTION_URL) as ws:
        await ws.send(json.dumps(SUBSCRIBE_MESSAGE))
        print(
            f"[{time.strftime('%H:%M:%S')}] Watching {len(watched_slugs)} relics "
            f"with a gold part over {GOLD_PART_THRESHOLD}p (new-order feed)..."
        )

        discovery_deadline = time.time() + 30

        async for raw in ws:
            if DISCOVERY_MODE:
                print(raw)
                if time.time() > discovery_deadline:
                    print("\n--- 30s of raw messages printed above. ---")
                    print("Find the route name used for new sell-order events,")
                    print("set NEW_ORDER_EVENT_ROUTE to it, flip DISCOVERY_MODE")
                    print("to False, and rerun.")
                    return
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("route") != NEW_ORDER_EVENT_ROUTE:
                continue

            payload = msg.get("payload", {})
            item_slug = payload.get("item", {}).get("urlName") or payload.get("item_name")
            order_type = payload.get("orderType") or payload.get("order_type") or payload.get("type")

            if order_type != "sell" or item_slug not in watched_slugs:
                continue

            await confirm_and_alert(watched_slugs[item_slug], relic_to_hits, last_checked, "new order")


async def poll(relic_to_hits: dict, last_checked: dict) -> None:
    """Slow path: catches listings that become visible again without a new
    order being created -- e.g. someone flipping an existing listing from
    offline back to online. The newOrders websocket feed does NOT see this
    (confirmed empirically), so this fills the gap by periodically
    re-checking every watched relic via REST, same as your original script."""
    relic_names = list(relic_to_hits.keys())
    print(
        f"[{time.strftime('%H:%M:%S')}] Polling {len(relic_names)} relics "
        f"every {POLL_INTERVAL_SECONDS}s (catches offline->online restocks)..."
    )

    while True:
        for relic_name in relic_names:
            await confirm_and_alert(relic_name, relic_to_hits, last_checked, "poll")
            await asyncio.sleep(REQUEST_DELAY)  # keep pace with the 3 req/sec limit
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    print("Parsing input.html for gold-drop relic mapping...")
    part_to_relics = parse_relic_rewards(INPUT_HTML)
    print(f"Found {len(part_to_relics)} distinct gold-tier parts.")

    cache = load_price_cache()
    print("Pricing gold parts (cached entries under "
          f"{PRICE_CACHE_TTL_HOURS}h old are skipped)...")
    cache = bootstrap_gold_part_prices(part_to_relics.keys(), cache)

    relic_to_hits = compute_watched_relics(part_to_relics, cache)
    if not relic_to_hits:
        print(f"No relics currently have a gold part over {GOLD_PART_THRESHOLD}p. Nothing to watch.")
        return

    asyncio.run(run_both(relic_to_hits))


async def run_both(relic_to_hits: dict) -> None:
    last_checked: dict[str, float] = {}
    await asyncio.gather(
        watch(relic_to_hits, last_checked),
        poll(relic_to_hits, last_checked),
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
