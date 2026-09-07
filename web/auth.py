"""WFM sign-in, same shape as QuantFrame.

First login posts email + password to /v1/auth/signin and takes the
JWT from the response Authorization header. The password lives only
inside that one request: never stored, never logged, never returned.
The token is saved into web/.env as WFM_JWT, the same slot the old
manual cookie paste used, so every existing caller keeps working
unchanged. Non-secret bits (device id, last presence) live in
wfm_session.json.

Presence (online / ingame / offline) goes over the same websocket the
site itself uses: sign the socket in with the token, then send
cmd/status/set and wait for the ack.
"""

import json
import time
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ENV_FILE = BASE / "web" / ".env"
SESSION_FILE = BASE / "wfm_session.json"

SIGNIN_URL = "https://api.warframe.market/v1/auth/signin"
WS_URL = "wss://ws.warframe.market/socket"

# The socket refuses "offline" (app.errors.invalidStatus). Invisible is
# WFM's real hidden state: listings stay up, nobody sees you.
STATUSES = ("online", "ingame", "invisible")


def _session() -> dict:
    if SESSION_FILE.exists():
        try:
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_session(patch: dict) -> dict:
    data = _session()
    data.update(patch)
    SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def device_id() -> str:
    """Reuse one device id per machine, like QuantFrame does."""
    did = _session().get("device_id", "")
    if not did:
        did = str(uuid.uuid4())
        _save_session({"device_id": did})
    return did


def _write_env(updates: dict) -> None:
    """Set keys in web/.env, keeping comments and other lines as they are."""
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def signin(email: str, password: str) -> dict:
    """Trade email + password for a JWT, once. Returns {ok, username}."""
    import market_client

    email = (email or "").strip()
    if not email or not password:
        return {"ok": False, "error": "email and password are both needed"}
    code, data, headers = market_client.post_json(
        SIGNIN_URL,
        {"auth_type": "header", "email": email,
         "password": password, "device_id": device_id()},
        {"Authorization": "JWT"})
    if code in (400, 401, 403, 422):
        return {"ok": False, "error": "bad email or password"}
    if code == 429:
        return {"ok": False, "error": "rate limited, try again in a minute"}
    if code < 200 or code >= 300:
        return {"ok": False, "error": f"signin failed ({code})"}
    raw = headers.get("Authorization", "")
    token = raw[len("JWT "):].strip() if raw.startswith("JWT ") else ""
    if not token:
        return {"ok": False, "error": "no token in signin response"}
    user = ((data.get("payload") or {}).get("user") or {}) if isinstance(data, dict) else {}
    username = (user.get("ingame_name") or user.get("ingameName")
                or user.get("username") or "")
    _write_env({"WFM_JWT": token, "WFM_USERNAME": username})
    if str(user.get("status", "")).lower() in STATUSES:
        _save_session({"last_status": str(user.get("status")).lower()})
    return {"ok": True, "username": username}


def signout() -> dict:
    """Forget the token. A WFM_JWT set as a real environment variable
    still wins on next boot, the status call says so when that happens."""
    _write_env({"WFM_JWT": ""})
    if SESSION_FILE.exists():
        try:
            SESSION_FILE.unlink()
        except Exception:
            pass
    return {"ok": True}


def status() -> dict:
    """{logged_in, username, source, last_status}. Token never included."""
    import os
    import listings

    if os.environ.get("WFM_JWT", "").strip():
        source = "environment"
    elif listings.token():
        source = "file"
    else:
        source = "none"
    last = _session().get("last_status", "")
    if source != "none" and not last:
        try:
            last = get_presence() or ""
        except Exception:
            last = ""
        if last:
            _save_session({"last_status": last})
    return {"logged_in": source != "none",
            "username": listings.username() or "",
            "source": source,
            "last_status": last}


async def _ws_current_status(token: str) -> str:
    """Sign a throwaway socket in and read the presence push that follows."""
    import asyncio
    import websockets as _ws

    async with _ws.connect(WS_URL) as sock:
        await sock.send(json.dumps(
            {"route": "@wfm|cmd/auth/signIn", "id": "whoami",
             "payload": {"token": token}}))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            left = deadline - time.monotonic()
            try:
                raw = await asyncio.wait_for(sock.recv(), timeout=left)
            except asyncio.TimeoutError:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "status/set" not in str(msg.get("route", "")):
                continue
            seen = str((msg.get("payload") or {}).get("status", "")).lower()
            if seen:
                return seen
        raise TimeoutError("no presence answer")


def get_presence() -> str:
    """Current presence, or '' when it cannot be read. Never raises."""
    import asyncio
    import listings

    try:
        tok = listings.token()
        if not tok:
            return ""
        seen = asyncio.run(_ws_current_status(tok))
        return seen if seen in STATUSES else ""
    except Exception:
        return ""


async def _ws_set_status(token: str, want: str) -> str:
    """Sign a throwaway socket in, set presence, return confirmed status.

    Acks echo the message id, which separates them from the server's own
    presence pushes (those carry no id). Matching on id is what makes
    this race free.
    """
    import asyncio
    import websockets as _ws

    async def wait_for(sock, needle: str, mid: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(
                    sock.recv(), timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if needle not in str(msg.get("route", "")):
                continue
            if msg.get("id") != mid:
                continue
            return msg
        raise TimeoutError(f"no answer for {needle}")

    async with _ws.connect(WS_URL) as sock:
        auth_id = f"auth-{uuid.uuid4().hex[:8]}"
        await sock.send(json.dumps(
            {"route": "@wfm|cmd/auth/signIn", "id": auth_id,
             "payload": {"token": token}}))
        await wait_for(sock, "auth/signIn", auth_id, 10)
        set_id = f"status-{uuid.uuid4().hex[:8]}"
        await sock.send(json.dumps(
            {"route": "@wfm|cmd/status/set", "id": set_id,
             "payload": {"status": want}}))
        done = await wait_for(sock, "status/set", set_id, 10)
        if not str(done.get("route", "")).endswith(":ok"):
            detail = json.dumps(done.get("payload", ""))[:120]
            raise ValueError(f"status refused ({detail})")
        return (done.get("payload") or {}).get("status") or want


def set_presence(want: str) -> dict:
    """Set online / ingame / invisible. Returns {ok, status/error}."""
    import asyncio
    import listings

    want = (want or "").strip().lower()
    if want not in STATUSES:
        return {"ok": False, "error": f"want one of {', '.join(STATUSES)}"}
    tok = listings.token()
    if not tok:
        return {"ok": False, "error": "not signed in"}
    try:
        confirmed = asyncio.run(_ws_set_status(tok, want))
    except TimeoutError:
        return {"ok": False,
                "error": "market socket stayed silent, token may be stale"}
    except ValueError as e:
        return {"ok": False, "error": str(e)[:160]}
    except Exception as e:
        return {"ok": False, "error": f"socket failed ({str(e)[:100]})"}
    _save_session({"last_status": confirmed})
    return {"ok": True, "status": confirmed}
