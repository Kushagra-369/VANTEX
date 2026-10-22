"""
VANTEX Cloudinary OAuth + Gallery API.

Required environment variables:
  CLOUDINARY_OAUTH_CLIENT_ID
  CLOUDINARY_OAUTH_CLIENT_SECRET
  CLOUDINARY_OAUTH_REDIRECT_URI   e.g. https://vantex-2d4l.onrender.com/api/cloudinary/oauth/callback
  VANTEX_FRONTEND_URL              e.g. https://your-vantex-frontend.example
  VANTEX_SESSION_SECRET            long random secret (32+ bytes)
  VANTEX_TOKEN_ENCRYPTION_KEY      Fernet key; generate with the command below

Generate encryption key:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Install dependency:
  pip install httpx cryptography

Then in ai/main.py:
  from ai.cloudinary_oauth import router as cloudinary_oauth_router
  app.include_router(cloudinary_oauth_router)

This module uses an HttpOnly browser-session cookie and SQLite storage. It does not
use any user's Cloudinary API secret. Each browser profile/session is isolated.
For account-level isolation across devices, bind this record to VANTEX's authenticated
user ID once VANTEX login is available. Set VANTEX_CLOUDINARY_DB to a persistent disk path
in production; the default local file may be lost on ephemeral hosting.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/cloudinary", tags=["Cloudinary Gallery"])

CLIENT_ID = os.getenv("CLOUDINARY_OAUTH_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("CLOUDINARY_OAUTH_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("CLOUDINARY_OAUTH_REDIRECT_URI", "").strip()
FRONTEND_URL = os.getenv("VANTEX_FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")
SESSION_SECRET = os.getenv("VANTEX_SESSION_SECRET", "").strip()
TOKEN_ENCRYPTION_KEY = os.getenv("VANTEX_TOKEN_ENCRYPTION_KEY", "").strip()
DB_PATH = Path(os.getenv("VANTEX_CLOUDINARY_DB", str(Path(__file__).with_name("cloudinary_oauth.sqlite3"))))

AUTH_URL = "https://oauth.cloudinary.com/oauth2/auth"
TOKEN_URL = "https://oauth.cloudinary.com/oauth2/token"
COOKIE_NAME = "vantex_gallery_session"
SCOPES = "upload asset_management offline_access openid"
CLOUD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _check_config() -> None:
    if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
        raise HTTPException(
            status_code=503,
            detail="Set the Cloudinary OAuth app Client ID, Client Secret, and Redirect URI on the backend.",
        )
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        raise HTTPException(
            status_code=503,
            detail="Set VANTEX_SESSION_SECRET to a random secret at least 32 characters long.",
        )
    try:
        Fernet(TOKEN_ENCRYPTION_KEY.encode("ascii"))
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Set VANTEX_TOKEN_ENCRYPTION_KEY to a valid Fernet key.",
        )


def _encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return Fernet(TOKEN_ENCRYPTION_KEY.encode("ascii")).encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return Fernet(TOKEN_ENCRYPTION_KEY.encode("ascii")).decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        raise HTTPException(status_code=500, detail="Stored Cloudinary credentials could not be decrypted. Check the encryption key.")


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cloudinary_sessions (
            session_hash TEXT PRIMARY KEY,
            cloud_name TEXT NOT NULL,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at REAL NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cloudinary_oauth_states (
            state_hash TEXT PRIMARY KEY,
            session_hash TEXT NOT NULL,
            cloud_name TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


def _hash(value: str) -> str:
    return hmac.new(SESSION_SECRET.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _get_session(request: Request, create: bool = False) -> tuple[str | None, str | None]:
    raw = request.cookies.get(COOKIE_NAME)
    if raw and re.fullmatch(r"[A-Za-z0-9_-]{40,100}", raw):
        return raw, _hash(raw)
    if create:
        raw = secrets.token_urlsafe(32)
        return raw, _hash(raw)
    return None, None


def _set_cookie(response: RedirectResponse, raw_session: str) -> None:
    production = REDIRECT_URI.startswith("https://")
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_session,
        httponly=True,
        secure=production,
        samesite="none" if production else "lax",
        path="/",
        max_age=60 * 60 * 24 * 30,
    )


async def _refresh_if_needed(session_hash: str, row: sqlite3.Row) -> sqlite3.Row:
    if float(row["expires_at"]) > time.time() + 45:
        return row
    refresh_token = _decrypt(row["refresh_token"])
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Cloudinary connection expired. Connect Cloudinary again.")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }
    # Cloudinary's default confidential-client setting is "Client secret post".
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data=data)
    if response.status_code >= 400:
        raise HTTPException(status_code=401, detail="Cloudinary session expired. Reconnect your account.")
    payload = response.json()
    access = payload.get("access_token")
    if not access:
        raise HTTPException(status_code=502, detail="Cloudinary did not return an access token.")
    new_refresh = payload.get("refresh_token")
    if not new_refresh:
        raise HTTPException(
            status_code=502,
            detail="Cloudinary did not rotate the refresh token. Reconnect and verify Offline Access scope.",
        )
    expires_in = int(payload.get("expires_in", 300))
    with _db() as conn:
        conn.execute(
            "UPDATE cloudinary_sessions SET access_token=?, refresh_token=?, expires_at=? WHERE session_hash=?",
            (_encrypt(access), _encrypt(new_refresh), time.time() + expires_in, session_hash),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM cloudinary_sessions WHERE session_hash=?", (session_hash,)
        ).fetchone()
    return updated


@router.get("/oauth/start")
async def cloudinary_oauth_start(request: Request, cloud_name: str = Query(..., min_length=1, max_length=128)):
    _check_config()
    cloud_name = cloud_name.strip()
    if not CLOUD_RE.fullmatch(cloud_name):
        raise HTTPException(status_code=400, detail="Invalid Cloudinary cloud name.")
    raw_session, session_hash = _get_session(request, create=True)
    state = secrets.token_urlsafe(32)
    with _db() as conn:
        conn.execute(
            "INSERT INTO cloudinary_oauth_states(state_hash, session_hash, cloud_name, expires_at) VALUES (?, ?, ?, ?)",
            (_hash(state), session_hash, cloud_name, time.time() + 600),
        )
        conn.commit()
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "cloud_name": cloud_name,
    }
    response = RedirectResponse(f"{AUTH_URL}?{urlencode(params)}", status_code=302)
    _set_cookie(response, raw_session)
    return response


@router.get("/oauth/callback")
async def cloudinary_oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    _check_config()
    if error:
        return RedirectResponse(f"{FRONTEND_URL}/?cloudinary_oauth=denied", status_code=303)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state.")
    raw_session, session_hash = _get_session(request)
    if not session_hash:
        raise HTTPException(status_code=400, detail="OAuth session cookie is missing. Please try connecting again.")
    with _db() as conn:
        state_row = conn.execute(
            "SELECT * FROM cloudinary_oauth_states WHERE state_hash=? AND session_hash=? AND expires_at>?",
            (_hash(state), session_hash, time.time()),
        ).fetchone()
        if not state_row:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state. Please try again.")
        conn.execute("DELETE FROM cloudinary_oauth_states WHERE state_hash=?", (_hash(state),))
        conn.commit()

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
    }
    # Cloudinary's default confidential-client setting is "Client secret post".
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data=data)
    if response.status_code >= 400:
        # Do not return provider response body because it may contain sensitive details.
        raise HTTPException(status_code=502, detail="Cloudinary token exchange failed. Check OAuth app settings.")
    payload = response.json()
    access = payload.get("access_token")
    if not access:
        raise HTTPException(status_code=502, detail="Cloudinary did not return an access token.")
    if not payload.get("refresh_token"):
        raise HTTPException(
            status_code=502,
            detail="Cloudinary did not return a refresh token. Enable Offline Access in your OAuth app.",
        )
    with _db() as conn:
        conn.execute(
            """INSERT INTO cloudinary_sessions(session_hash, cloud_name, access_token, refresh_token, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(session_hash) DO UPDATE SET cloud_name=excluded.cloud_name,
               access_token=excluded.access_token, refresh_token=excluded.refresh_token, expires_at=excluded.expires_at""",
            (
                session_hash,
                state_row["cloud_name"],
                _encrypt(access),
                _encrypt(payload.get("refresh_token")),
                time.time() + int(payload.get("expires_in", 300)),
                time.time(),
            ),
        )
        conn.commit()
    return RedirectResponse(f"{FRONTEND_URL}/?cloudinary_oauth=connected", status_code=303)


@router.get("/connection")
async def cloudinary_connection(request: Request):
    _, session_hash = _get_session(request)
    if not session_hash:
        return {"connected": False}
    with _db() as conn:
        row = conn.execute(
            "SELECT cloud_name FROM cloudinary_sessions WHERE session_hash=?", (session_hash,)
        ).fetchone()
    return {"connected": bool(row), "cloud_name": row["cloud_name"] if row else None}


@router.get("/images")
async def cloudinary_images(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    next_cursor: str | None = Query(None, max_length=2048),
):
    _, session_hash = _get_session(request)
    if not session_hash:
        raise HTTPException(status_code=401, detail="Connect your Cloudinary account first.")
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM cloudinary_sessions WHERE session_hash=?", (session_hash,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Connect your Cloudinary account first.")
    row = await _refresh_if_needed(session_hash, row)
    params: dict[str, str | int] = {"max_results": limit}
    if next_cursor:
        params["next_cursor"] = next_cursor
    url = f"https://api.cloudinary.com/v1_1/{row['cloud_name']}/resources/image/upload"
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {_decrypt(row['access_token'])}"},
        )
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Cloudinary rejected the token. Reconnect your account.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Could not retrieve Cloudinary assets. Verify Asset Management scope and account permissions.")
    data = response.json()
    return {
        "resources": data.get("resources", []),
        "next_cursor": data.get("next_cursor"),
        "total_count": data.get("total_count"),
        "cloud_name": row["cloud_name"],
    }


@router.post("/disconnect")
async def cloudinary_disconnect(request: Request):
    _, session_hash = _get_session(request)
    if session_hash:
        with _db() as conn:
            conn.execute("DELETE FROM cloudinary_sessions WHERE session_hash=?", (session_hash,))
            conn.execute("DELETE FROM cloudinary_oauth_states WHERE session_hash=?", (session_hash,))
            conn.commit()
    response = RedirectResponse(f"{FRONTEND_URL}/", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
