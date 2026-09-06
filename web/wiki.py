"""Wiki reward table source. Bundled file first, live refresh behind."""

import re
import threading
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
INPUT_HTML = BASE / "input.html"
WIKI_URL = "https://wiki.warframe.com/w/Void_Relic/ByRewards/SimpleTable"

_state = {"last_fetch": None, "rows": 0, "source": "none"}
_cached_rows: list = []


def _parse_soup_table(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    wanted = {"item", "part", "relic name", "rarity"}
    target = None
    for t in tables:
        head = t.find("tr")
        if not head:
            continue
        cols = {c.get_text(strip=True).lower() for c in head.find_all(["th", "td"])}
        if wanted.issubset(cols):
            target = t
            break
    if target is None:
        target = max(tables, key=lambda t: len(t.find_all("tr"))) if tables else None
    if target is None:
        raise ValueError("no table found")
    header = [c.get_text(strip=True).lower() for c in target.find("tr").find_all(["th", "td"])]
    idx = {name: i for i, name in enumerate(header)}
    rows = []
    for tr in target.find_all("tr")[1:]:
        cells = [c.get_text(" ", strip=True).replace("\xa0", " ") for c in tr.find_all(["td", "th"])]
        if len(cells) < len(header):
            continue
        rows.append({"item": cells[idx["item"]], "part": cells[idx["part"]],
                     "relic": cells[idx["relic name"]], "rarity": cells[idx["rarity"]],
                     "vaulted": cells[idx.get("relic vaulted?", -1)] if "relic vaulted?" in idx and len(cells) > idx["relic vaulted?"] else ""})
    return rows


def _fetch_live_rows() -> list:
    resp = requests.get(WIKI_URL, headers={"User-Agent": "Mozilla/5.0 (wfm-local-ui)"}, timeout=8)
    resp.raise_for_status()
    return _parse_soup_table(resp.text)


def _background_refresh() -> None:
    """Refresh the cache from the live wiki without stalling a scan pass."""
    global _state, _cached_rows
    try:
        rows = _fetch_live_rows()
    except Exception:
        return
    _cached_rows = rows
    _state = {"last_fetch": time.strftime("%Y-%m-%d %H:%M"), "rows": len(rows), "source": "live wiki"}


def load_rows(refresh: bool = False) -> tuple:
    """Returns (rows, source). The bundled input.html answers instantly so
    Start never waits on the network; the live wiki refreshes in the
    background and later passes pick it up."""
    global _state, _cached_rows
    if _state["rows"] and not refresh:
        return _cached_rows, _state["source"]
    if INPUT_HTML.exists():
        try:
            rows = _parse_soup_table(INPUT_HTML.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            rows = []
        if rows:
            _cached_rows = rows
            _state = {"last_fetch": time.strftime("%Y-%m-%d %H:%M"),
                      "rows": len(rows), "source": "input.html"}
            threading.Thread(target=_background_refresh, daemon=True).start()
            return rows, _state["source"]
    try:
        rows = _fetch_live_rows()
        _cached_rows = rows
        _state = {"last_fetch": time.strftime("%Y-%m-%d %H:%M"), "rows": len(rows), "source": "live wiki"}
    except Exception:
        rows = _cached_rows
    return rows, _state["source"]


def status() -> dict:
    return dict(_state)
