"""Local WFM web UI. Same PC only, binds 127.0.0.1."""

import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import market_client
import wiki

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts" / "relicscanner"))

app = Flask(__name__)

WATCH_MIN_PART = 40.0  # watch list floor; display dropdowns filter from here
MIN_QTY = 6

_board = {"updated": None, "rows": [], "alerts": [], "running": False,
          "ws": "off", "activity": [],
          "cycle": {"done": 0, "total": 0, "round": 0, "phase": "idle",
                    "current": "", "qualified": 0, "started": None}}
_tile_proc = None
_tile_last = {"status": "stopped"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower().replace("\xa0", " "))


def search_lookup(query: str) -> dict:
    rows, source = wiki.load_rows()
    q = _norm(query)
    by_relic = {}
    by_part = {}
    for r in rows:
        by_relic.setdefault(_norm(r["relic"]), []).append(r)
        full = _norm(f"{r['item']} {r['part']}")
        by_part.setdefault(full, []).append(r)
    hit = None
    if q in by_relic:
        drops = by_relic[q]
        rare = [d for d in drops if d["rarity"].lower() == "rare"]
        hit = (rare or drops)[0]
    if hit is None:
        if q in by_part:
            hit = by_part[q][0]
        else:
            guess = difflib.get_close_matches(q, list(by_part.keys()), n=1, cutoff=0.6)
            if guess:
                hit = by_part[guess[0]][0]
            else:
                guess = difflib.get_close_matches(q, list(by_relic.keys()), n=1, cutoff=0.7)
                if guess:
                    hit = by_relic[guess[0]][0]
    if hit is None:
        return {"ok": False, "error": f"no match for '{query}'", "source": source}
    slug = market_client.slugify(f"{hit['item']} {hit['part']}")
    try:
        stats = market_client.part_statistics(slug)
    except Exception as e:
        return {"ok": False, "error": str(e), "source": source}
    others = [f"{d['item']} {d['part']} ({d['rarity']})"
              for d in by_relic.get(_norm(hit["relic"]), []) if d is not hit]
    return {"ok": True, "slug": slug, "relic": hit["relic"], "rarity": hit["rarity"],
            "vaulted": hit["vaulted"], "also_drops": others,
            "market": stats["market_link"], "p90": stats["median_90d"],
            "p48": stats["median_48h"], "source": source}


def _wait_slot() -> bool:
    """Pause while inventory pricing holds the shared request budget."""
    while _price_lock.locked() and _board["running"]:
        time.sleep(5)
    return _board["running"]


def _note(text: str) -> None:
    _board["activity"].append(f"{time.strftime('%H:%M:%S')} {text}")
    _board["activity"] = _board["activity"][-15:]


def build_watchlist() -> dict:
    """{relic: [(part_label, part_price, part_link), ...]} for relics whose
    gold part hits WATCH_MIN_PART. Part prices come from the 6h cache."""
    c = _board["cycle"]
    c["phase"] = "loading reward table"
    rows, _ = wiki.load_rows()
    gold: dict = {}
    for r in rows:
        if r["rarity"].lower() != "rare":
            continue
        slug = market_client.slugify(f"{r['item']} {r['part']}")
        gold.setdefault(slug, {"relics": set(), "label": f"{r['item']} {r['part']}"})
        gold[slug]["relics"].add(r["relic"])
    watch: dict = {}
    names = list(gold.keys())
    c["phase"] = "pricing gold parts"
    for i, slug in enumerate(names, 1):
        if not _wait_slot():
            return {}
        c["current"] = f"{gold[slug]['label']} ({i}/{len(names)})"
        try:
            s = market_client.part_statistics(slug)
        except Exception as e:
            _note(f"{gold[slug]['label']}: price failed ({e})")
            continue
        if s["median_48h"] is None or s["median_48h"] < WATCH_MIN_PART:
            continue
        for relic in gold[slug]["relics"]:
            watch.setdefault(relic, []).append((gold[slug]["label"], s["median_48h"], s["market_link"]))
    c["current"] = ""
    _note(f"watch list: {len(watch)} relics with a 40p+ gold part")
    return watch


def check_relic(relic: str, hits: list) -> tuple:
    """(deal, note, ok). ok=False means the check itself failed, so the
    caller should keep any existing row instead of dropping it."""
    try:
        t = market_client.top_orders(relic)
    except Exception as e:
        err = str(e)
        short = "no market data (404)" if "404" in err else f"order check failed ({err[:80]})"
        return None, f"{relic}: {short}", False
    if t["sell_price"] is None:
        return None, f"{relic}: no sell orders", True
    if (t["sell_qty"] or 0) < MIN_QTY:
        return None, f"{relic}: {t['sell_price']}p x{t['sell_qty']} (needs 6+ bulk)", True
    best = None
    for label, price, link in hits:
        profit = round(((price / 3) - t["sell_price"]) * 27 / 1.5, 1)
        if best is None or profit > best["profit_hr"]:
            best = {"relic": relic, "relic_price": t["sell_price"], "qty": t["sell_qty"],
                    "relic_link": t["market_link"], "part": label,
                    "part_price": price, "part_link": link, "profit_hr": profit}
    return best, f"{relic}: {t['sell_price']}p x{t['sell_qty']}, best {best['profit_hr']}/hr", True


def board_refresh_once() -> None:
    """One full pass over all watched relics. Rolling snapshot: rows update
    in place as each relic is checked, so the page is live mid cycle."""
    watch = build_watchlist()
    names = sorted(watch.keys())
    _board["cycle"] = {"done": 0, "total": len(names), "round": _board["cycle"]["round"] + 1,
                       "phase": "checking sell orders", "current": "",
                       "qualified": 0, "started": time.strftime("%H:%M:%S")}
    for i, relic in enumerate(names, 1):
        if not _board["running"]:
            return
        if not _wait_slot():
            return
        _board["cycle"]["current"] = f"{relic} ({i}/{len(names)})"
        deal, note, ok = check_relic(relic, watch[relic])
        if not ok:
            _note(note + " (kept old row)")
        else:
            _board["rows"] = [r for r in _board["rows"] if r["relic"] != relic]
            if deal:
                _board["rows"].append(deal)
                _board["cycle"]["qualified"] += 1
                _note(f"QUALIFIES: {note}")
            else:
                _note(note + " (cleared)")
        _board["cycle"]["done"] = i
        _board["updated"] = time.strftime("%H:%M:%S")
    # Drop rows whose relic fell out of the watch list entirely (gold part
    # decayed below the floor), so dead deals never linger.
    _board["rows"] = [r for r in _board["rows"] if r["relic"] in watch]
    _board["cycle"]["phase"] = "resting between passes"
    _board["cycle"]["current"] = ""


def board_loop() -> None:
    ws_thread = threading.Thread(target=ws_loop, daemon=True)
    ws_thread.start()
    while _board["running"]:
        try:
            board_refresh_once()
        except Exception as e:
            _board["alerts"].append(f"board error: {e}")
            _board["alerts"] = _board["alerts"][-20:]
        for _ in range(120):
            if not _board["running"]:
                return
            time.sleep(1)


WS_URL = "wss://ws.warframe.market/socket"
WS_SUB = {"route": "@wfm|cmd/subscribe/newOrders", "id": "wfm-board-1",
          "payload": {"platform": "pc", "crossplay": True}}
WS_EVENT = "@wfm|event/subscribe/newOrders"  # unverified, may need correcting


def ws_loop() -> None:
    """New-order feed: on a fresh sell listing for a watched relic, re-check
    it immediately instead of waiting for the next poll pass."""
    import asyncio as _aio

    async def run():
        import websockets as _ws
        try:
            async with _ws.connect(WS_URL) as sock:
                await sock.send(json.dumps(WS_SUB))
                _board["ws"] = "live"
                async for raw in sock:
                    if not _board["running"]:
                        return
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if msg.get("route") != WS_EVENT:
                        continue
                    p = msg.get("payload", {})
                    slug = (p.get("item") or {}).get("urlName") or p.get("item_name")
                    otype = p.get("orderType") or p.get("order_type") or p.get("type")
                    if otype != "sell" or not slug:
                        continue
                    relic = slug.replace("_", " ")
                    watch = build_watchlist()
                    for name, hits in watch.items():
                        if market_client.relic_slug(name) == slug:
                            relic, hits = name, hits
                            break
                    else:
                        continue
                    if not _wait_slot():
                        return
                    deal, note, ok = check_relic(relic, hits)
                    if not ok:
                        continue
                    if deal:
                        _board["rows"] = [r for r in _board["rows"] if r["relic"] != relic]
                        _board["rows"].append(deal)
                        _board["alerts"].append(
                            f"new order: {relic} {deal['relic_price']}p x{deal['qty']} ({deal['profit_hr']}/hr)")
                        _board["alerts"] = _board["alerts"][-20:]
                        _board["updated"] = time.strftime("%H:%M:%S")
        except Exception as e:
            _board["ws"] = f"error: {e}"

    while _board["running"]:
        _board["ws"] = "connecting"
        try:
            _aio.run(run())
        except Exception as e:
            _board["ws"] = f"error: {e}"
        if _board["running"]:
            time.sleep(30)
    _board["ws"] = "off"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "error": "empty query"})
    return jsonify(search_lookup(q))


@app.get("/api/board")
def api_board():
    try:
        min_part = float(request.args.get("min_part", 40))
    except (TypeError, ValueError):
        min_part = 40
    try:
        min_profit = float(request.args.get("min_profit", 90))
    except (TypeError, ValueError):
        min_profit = 90
    rows = [r for r in _board["rows"]
            if r["part_price"] >= min_part and r["profit_hr"] >= min_profit]
    rows.sort(key=lambda r: r["profit_hr"], reverse=True)
    fallback = False
    if not rows:
        near = [r for r in _board["rows"] if r["part_price"] >= min_part]
        near.sort(key=lambda r: r["profit_hr"], reverse=True)
        rows = [{**r, "fallback": True} for r in near[:3]]
        fallback = bool(rows)
    return jsonify({"updated": _board["updated"], "rows": rows,
                    "shown": len(rows), "tracked": len(_board["rows"]),
                    "fallback": fallback, "activity": _board["activity"][-8:],
                    "alerts": _board["alerts"], "running": _board["running"],
                    "ws": _board["ws"], "cycle": _board["cycle"],
                    "min_part": min_part, "min_profit": min_profit,
                    "wiki": wiki.status(), "market": market_client.stats()})


@app.post("/api/board/start")
def api_board_start():
    if not _board["running"]:
        _board["running"] = True
        _board["activity"] = []
        _board["cycle"] = {"done": 0, "total": 0, "round": 0, "phase": "starting",
                           "current": "", "qualified": 0, "started": time.strftime("%H:%M:%S")}
        _note("scanner started")
        threading.Thread(target=board_loop, daemon=True).start()
    return jsonify({"running": True})


@app.post("/api/board/stop")
def api_board_stop():
    _board["running"] = False
    return jsonify({"running": False})


@app.post("/api/board/refresh")
def api_board_refresh():
    threading.Thread(target=board_refresh_once, daemon=True).start()
    return jsonify({"started": True})


_sets = {"state": "idle", "step": "", "done": 0, "total": 0,
         "updated": None, "report": None, "plat": None, "listed": None,
         "error": None}


def _sets_run() -> None:
    import advisor
    import listings
    try:
        _sets.update({"state": "working", "error": None, "report": None,
                      "step": "reading AlecaFrame dump"})
        live = advisor.owned_from_dump()
        _sets["plat"] = live["plat"]
        tradable = advisor._tradable_parts(live["parts"])
        groups = __import__("sets").group_owned(tradable) if tradable else {}
        part_slugs = sorted({p for g in groups.values() for p in g["parts"]})
        set_slugs = sorted({g["set_slug"] for g in groups.values() if g["set_slug"]})
        prices, set_prices = {}, {}
        total = len(part_slugs) + len(set_slugs)
        _sets.update({"done": 0, "total": total})
        with _price_lock:
            for i, s in enumerate(part_slugs, 1):
                if _sets.get("state") != "working":
                    return
                _sets.update({"step": f"pricing part {i}/{len(part_slugs)}: {s}",
                              "done": i})
                try:
                    st = market_client.part_statistics(s)
                except Exception:
                    st = {"median_48h": None, "median_90d": None, "market_link": ""}
                try:
                    dq = advisor.market_items.fetch_detail(s).get("ducats")
                except Exception:
                    dq = None
                prices[s] = {"p48": st.get("median_48h"), "p90": st.get("median_90d"),
                             "link": st.get("market_link", ""), "ducats": dq}
            for j, s in enumerate(set_slugs, 1):
                if _sets.get("state") != "working":
                    return
                _sets.update({"step": f"pricing set {j}/{len(set_slugs)}: {s}",
                              "done": len(part_slugs) + j})
                try:
                    t = market_client.top_orders_by_slug(s, min_qty=1)
                except Exception:
                    t = {"sell_price": None, "sell_qty": None, "avg_buy": None,
                         "market_link": f"https://warframe.market/items/{s}"}
                set_prices[s] = {"sell": t.get("sell_price"), "qty": t.get("sell_qty"),
                                 "avg_buy": t.get("avg_buy"),
                                 "link": t.get("market_link", "")}
        _sets["step"] = "grouping sets and sourcing missing pieces"
        listed = listings.fetch_listed()
        _sets["listed"] = listed
        report = advisor.build_report(
            live["parts"], live["relics"],
            price_fn=lambda slugs: {s: prices.get(s, {}) for s in slugs},
            set_price_fn=lambda slugs: {s: set_prices.get(s, {}) for s in slugs},
            listed=set(listed.get("slugs", [])))
        _sets.update({"state": "done", "report": report,
                      "step": f"done: {len(groups)} sets",
                      "updated": time.strftime("%H:%M:%S")})
    except Exception as e:
        _sets.update({"state": "error", "error": str(e)})


@app.get("/api/sets")
def api_sets_start():
    if _sets["state"] != "working":
        _sets.update({"state": "working", "step": "starting"})
        threading.Thread(target=_sets_run, daemon=True).start()
    return jsonify({"started": True, "state": _sets["state"]})


@app.get("/api/sets/status")
def api_sets_status():
    return jsonify({k: v for k, v in _sets.items()})


@app.post("/api/snapshots/save")
def api_snap_save():
    import snapshots
    name = (request.get_json(silent=True) or {}).get("name")
    try:
        out = snapshots.save(name)
        return jsonify({"ok": True, **out})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.get("/api/snapshots/list")
def api_snap_list():
    import snapshots
    return jsonify({"snaps": snapshots.list_all()})


@app.get("/api/snapshots/diff")
def api_snap_diff():
    import snapshots
    a = request.args.get("a", "")
    b = request.args.get("b", "")
    try:
        return jsonify({"ok": True, "diff": snapshots.diff(
            snapshots.load(a), snapshots.load(b))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


_inv = {"state": "idle", "step": "", "done": 0, "total": 0,
       "updated": None, "types": 0, "count": 0,
       "up_raw": [], "op_raw": [],
       "dump_mtime": None, "dump_age": "", "error": None}
WFCD_URL = "https://raw.githubusercontent.com/WFCD/warframe-items/refs/heads/master/data/json/Relics.json"
WFCD_CACHE = BASE / "Relics.json"
WFCD_TTL_HOURS = 24

# One pricer at a time: inventory (relic_db pacing) and board (market_client
# pacing) share the same 3 req/sec IP budget, so they take turns.
_price_lock = threading.Lock()


def _dump_info() -> dict:
    dump = os.path.join(os.environ.get("LOCALAPPDATA", ""), "AlecaFrame", "lastData.dat")
    p = Path(dump)
    if not p.exists():
        return {"path": dump, "exists": False}
    mtime = p.stat().st_mtime
    age_s = time.time() - mtime
    if age_s < 3600:
        age = f"{int(age_s // 60)} min ago"
    elif age_s < 86400:
        age = f"{age_s / 3600:.1f} hours ago"
    else:
        age = f"{age_s / 86400:.1f} days ago"
    return {"path": dump, "exists": True,
            "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
            "age": age}


def _wfcd_relics() -> list:
    _inv["step"] = "fetching WFCD relic data"
    if WFCD_CACHE.exists() and time.time() - WFCD_CACHE.stat().st_mtime < WFCD_TTL_HOURS * 3600:
        return json.loads(WFCD_CACHE.read_text(encoding="utf-8"))
    import requests as _rq
    data = _rq.get(WFCD_URL, timeout=30).json()
    WFCD_CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def _bucketed(rows, kind: str, min_price: float, bucket_size: int = 10) -> list:
    """Filter rows to avg >= min_price, then group into buckets, richest first.

    Mirrors relic_db._print_bucketed_report: bucket label rounds to the
    nearest bucket_size, header carries total relic count + type count.
    """
    from collections import defaultdict

    def label(avg: float) -> int:
        return int((avg / bucket_size) + 0.5) * bucket_size

    buckets: dict = defaultdict(list)
    for row in rows:
        if kind == "upgrading":
            base, ref, count, part, avg, down = row
            line = {"relic": base, "ref": ref, "count": count,
                    "part": part, "price": round(avg, 1), "down": bool(down)}
        else:
            base, count, part, avg, down = row
            line = {"relic": base, "ref": "", "count": count,
                    "part": part, "price": round(avg, 1), "down": bool(down)}
        if avg >= min_price:
            buckets[label(avg)].append(line)
    out = []
    for key in sorted(buckets.keys(), reverse=True):
        items = buckets[key]
        out.append({"bucket": key, "relics": sum(i["count"] for i in items),
                    "types": len(items), "rows": items})
    return out


def _inventory_run() -> None:
    import types as _t

    import relic_db
    relic_db.DB_PATH = str(BASE / "relics.db")

    # Feed relic_db's terminal progress bar into the UI state.
    def _prog(current: int, total: int, label: str, bar_width: int = 30):
        _inv["done"] = current
        _inv["total"] = total
        _inv["step"] = f"price-checking {current}/{total}: {label}"
    relic_db._print_progress = _prog

    try:
        _inv.update({"state": "working", "error": None, "done": 0, "total": 0,
                     "up_raw": [], "op_raw": []})
        info = _dump_info()
        _inv["dump_mtime"] = info.get("mtime")
        _inv["dump_age"] = info.get("age", "")
        if not info["exists"]:
            _inv.update({"state": "error", "error": f"dump not found: {info['path']}"})
            return
        _inv["step"] = "decrypting AlecaFrame dump"
        from decrypt import process_data
        data = json.loads(process_data(info["path"]))
        relic_info = _wfcd_relics()
        _inv["step"] = "matching local relics"
        by_unique = {r["uniqueName"]: r for r in relic_info}
        adapters = []
        total_count = 0
        for item in data.get("MiscItems", []):
            if "Projection" not in item.get("ItemType", ""):
                continue
            r = by_unique.get(item["ItemType"])
            if not r or not r.get("name", "").startswith(("Lith", "Meso", "Neo", "Axi")):
                continue
            rewards = r.get("rewards", [])
            gold = min(rewards, key=lambda x: x.get("chance", 99)) if rewards else {}
            gitem = gold.get("item") or {}
            url = ((gitem.get("warframeMarket") or {}).get("urlName", ""))
            total_count += item.get("ItemCount", 0)
            adapters.append(_t.SimpleNamespace(
                Name=r["name"], Count=item.get("ItemCount", 0),
                goldUrlName=url,
                goldReward=_t.SimpleNamespace(item={"name": gitem.get("name", "")})))
        _inv["types"] = len(adapters)
        _inv["count"] = total_count

        conn = relic_db.init_db(relic_db.DB_PATH)
        try:
            relic_db.upsert_inventory(conn, adapters)
            _inv["step"] = "price-checking (tiered cache: 37p+ every run)"
            with _price_lock:
                relic_db.refresh_prices(conn, show_progress=True)
            _inv["step"] = "grouping into tiers"
            up = relic_db.relics_worth_upgrading(conn, relic_db.MIN_BUCKET_PLAT)
            op = relic_db.relics_worth_opening(conn, relic_db.MIN_BUCKET_PLAT)
            _inv["up_raw"] = [list(r) for r in up]
            _inv["op_raw"] = [list(r) for r in op]
        finally:
            conn.close()
        _inv.update({"state": "done",
                     "step": f"done: {len(adapters)} types, {total_count} relics",
                     "updated": time.strftime("%H:%M:%S")})
    except Exception as e:
        _inv.update({"state": "error", "error": str(e)})


@app.get("/api/inventory")
def api_inventory():
    if _inv["state"] != "working":
        threading.Thread(target=_inventory_run, daemon=True).start()
    return jsonify({"started": True, "state": _inv["state"]})


@app.get("/api/inventory/status")
def api_inventory_status():
    import relic_db
    try:
        selected = float(request.args.get("min", 40))
    except (TypeError, ValueError):
        selected = 40
    # Buckets round to the nearest 10p, so a 40p bucket holds 35p+ items.
    # Pull the cutoff 2.5p below the pick so the bottom bucket is complete:
    # 40 -> 37.5, 35 -> 32.5, 30 -> 27.5.
    min_price = selected - 2.5
    base = {k: v for k, v in _inv.items() if k not in ("up_raw", "op_raw")}
    base.update({"dump": _dump_info(), "min": selected,
                 "upgrading": _bucketed(_inv["up_raw"], "upgrading", min_price),
                 "opening": _bucketed(_inv["op_raw"], "opening", min_price)})
    return jsonify(base)


@app.get("/api/tile")
def api_tile():
    global _tile_proc
    running = _tile_proc is not None and _tile_proc.poll() is None
    return jsonify({"running": running, "info": _tile_last})


@app.post("/api/tile/start")
def api_tile_start():
    global _tile_proc
    if _tile_proc is not None and _tile_proc.poll() is None:
        return jsonify({"running": True})
    script = str(BASE / "Tile Scanner")
    _tile_proc = subprocess.Popen([sys.executable, script])
    _tile_last["status"] = f"started pid {_tile_proc.pid}"
    return jsonify({"running": True, "pid": _tile_proc.pid})


@app.post("/api/tile/stop")
def api_tile_stop():
    global _tile_proc
    if _tile_proc is not None and _tile_proc.poll() is None:
        _tile_proc.terminate()
    _tile_last["status"] = "stopped"
    return jsonify({"running": False})


_server = None


@app.post("/api/quit")
def api_quit():
    """Stop everything: board loop, tile scanner, then the server itself."""
    def stop():
        time.sleep(0.5)
        _board["running"] = False
        global _tile_proc
        if _tile_proc is not None and _tile_proc.poll() is None:
            _tile_proc.terminate()
        if _server is not None:
            _server.shutdown()
    threading.Thread(target=stop, daemon=True).start()
    return jsonify({"quitting": True})


if __name__ == "__main__":
    import socket as _sock
    probe = _sock.socket()
    try:
        probe.bind(("127.0.0.1", 5000))
    except OSError:
        sys.exit(0)  # another copy already serves this port
    probe.close()
    from werkzeug.serving import make_server
    _server = make_server("127.0.0.1", 5000, app)
    _server.serve_forever()
