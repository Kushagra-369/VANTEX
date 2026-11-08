import asyncio
import os
import secrets
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/agent")

# One connected device per user in this initial MVP.
# Requires a single Render worker/instance.
connections = {}
pending = {}


async def verify_user(token: str) -> str:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")

    if not url or not key:
        raise ValueError("Supabase authentication is not configured.")

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{url}/auth/v1/user",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {token}",
            },
        )

    if response.status_code != 200:
        raise ValueError("Invalid or expired Supabase session.")

    user_id = response.json().get("id")
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("Invalid user identity.")

    return user_id


@router.websocket("/connect")
async def connect_agent(ws: WebSocket):
    # Authenticate before accepting the connection.
    # Token is supplied in the first WebSocket subprotocol entry.
    protocols = ws.scope.get("subprotocols", [])
    if len(protocols) != 2 or protocols[0] != "vantex-agent-v1":
        await ws.close(code=1008)
        return

    device_token = protocols[1]
    user_id = verify_device_token(device_token)

    if not user_id:
        await ws.close(code=1008, reason="Invalid device token")
        return

    await ws.accept(subprotocol="vantex-agent-v1")

    # Do not allow a second agent to silently replace an existing device.
    if user_id in connections:
        await ws.close(code=1008, reason="Agent already connected")
        return

    connections[user_id] = ws

    try:
        while True:
            message = await ws.receive_json()

            if message.get("type") != "result":
                continue

            request_id = message.get("request_id")
            item = pending.get(request_id)

            if not item or item["user_id"] != user_id:
                continue

            future = item["future"]
            if not future.done():
                future.set_result(message)

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if connections.get(user_id) is ws:
            connections.pop(user_id, None)

        for request_id, item in list(pending.items()):
            if item["user_id"] == user_id:
                future = item["future"]
                if not future.done():
                    future.set_exception(
                        ConnectionError("Local Agent disconnected.")
                    )


class RelayCommand(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)


async def dispatch(user_id: str, action: str, payload: dict):
    ws = connections.get(user_id)

    if ws is None:
        raise HTTPException(
            status_code=503,
            detail="Your Local Agent is offline. Start it on your laptop.",
        )

    request_id = str(uuid.uuid4())
    future = asyncio.get_running_loop().create_future()

    pending[request_id] = {
        "user_id": user_id,
        "future": future,
    }

    try:
        await ws.send_json({
            "type": "command",
            "request_id": request_id,
            "action": action,
            "payload": payload,
        })

        response = await asyncio.wait_for(future, timeout=110)

        if response.get("error"):
            raise HTTPException(
                status_code=502,
                detail=str(response["error"])[:500],
            )

        return response.get("data", {})

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Local Agent response timed out.",
        )
    except (ConnectionError, WebSocketDisconnect):
        raise HTTPException(
            status_code=503,
            detail="Local Agent disconnected.",
        )
    finally:
        pending.pop(request_id, None)


async def authenticated_user(request: Request):
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Sign in required.")

    try:
        return await verify_user(token.strip())
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid session.")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Authentication unavailable.")


@router.get("/connection")
async def agent_connection(request: Request):
    user_id = await authenticated_user(request)
    ws = connections.get(user_id)

    return {
        "connected": ws is not None,
        "agent": "VANTEX Local Agent",
    }



# Only these local API routes may be reached through the device relay.
def allowed_local_operation(path: str, method: str) -> bool:
    if method not in {"GET", "POST"}:
        return False
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        return False
    if ".." in path.split("/") or "\\" in path or "\x00" in path:
        return False

    allowed_prefixes = (
        "/api/agent/pc-files/",
        "/api/agent/files/",
        "/api/agent/pc-control/",
        "/api/projects/",
    )
    return (
        path.startswith(allowed_prefixes)
        or path == "/api/agent/monitor/status"
    )


class RelayOperation(BaseModel):
    path: str = Field(min_length=2, max_length=300)
    method: str = Field(default="GET", max_length=8)
    query: dict[str, str] = Field(default_factory=dict)
    body: dict | list | None = None


@router.post("/operation")
async def dispatch_operation(request: Request, body: RelayOperation):
    user_id = await authenticated_user(request)
    method = body.method.upper()

    if not allowed_local_operation(body.path, method):
        raise HTTPException(status_code=403, detail="This local operation is not allowed.")

    if len(body.query) > 30 or any(
        len(str(k)) > 100 or len(str(v)) > 2000
        for k, v in body.query.items()
    ):
        raise HTTPException(status_code=422, detail="Invalid operation query.")

    authorization = request.headers.get("Authorization", "")
    token = authorization.partition(" ")[2].strip()

    if not token:
        raise HTTPException(status_code=401, detail="Sign in required.")

    return await dispatch(
        user_id,
        "execute_operation",
        {
            "path": body.path,
            "method": method,
            "query": body.query,
            "body": body.body,
            "user_token": token,
        },
    )


@router.post("/dispatch")
async def dispatch_command(request: Request, body: RelayCommand):
    user_id = await authenticated_user(request)

    return await dispatch(
        user_id,
        "execute_command",
        {
            "command": body.command,
            "history": body.history[-10:],
        },
    )


# VANTEX DEVICE PAIRING
import base64
import hashlib
import hmac
import json
import time
from fastapi import Request
from pydantic import BaseModel, Field

pairing_codes = {}


def _agent_secret():
    secret = os.getenv("VANTEX_AGENT_SECRET", "")
    if len(secret) < 48:
        raise HTTPException(
            status_code=503,
            detail="Device authentication is not configured.",
        )
    return secret.encode()


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def create_device_token(user_id):
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 90 * 86400,
        "jti": secrets.token_urlsafe(16),
    }
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        _agent_secret(), encoded.encode(), hashlib.sha256
    ).digest()
    return encoded + "." + _b64(signature)


def verify_device_token(token):
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            _agent_secret(), encoded.encode(), hashlib.sha256
        ).digest()

        if not hmac.compare_digest(
            expected, base64.urlsafe_b64decode(
                signature + "=" * (-len(signature) % 4)
            )
        ):
            return None

        payload = json.loads(
            base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            )
        )

        if payload.get("exp", 0) < time.time():
            return None

        if not isinstance(payload.get("sub"), str):
            return None

        return payload["sub"]
    except Exception:
        return None


@router.post("/pairing/create")
async def create_pairing(request: Request):
    user_id = await authenticated_user(request)

    now = time.time()
    for code, item in list(pairing_codes.items()):
        if item["expires"] < now:
            pairing_codes.pop(code, None)

    code = secrets.token_urlsafe(9)
    pairing_codes[code] = {
        "user_id": user_id,
        "expires": now + 300,
    }

    return {
        "pairing_code": code,
        "expires_in": 300,
    }


class PairingRequest(BaseModel):
    code: str = Field(min_length=8, max_length=40)


@router.post("/pair")
async def pair_device(body: PairingRequest):
    item = pairing_codes.pop(body.code, None)

    if not item or item["expires"] < time.time():
        raise HTTPException(
            status_code=400,
            detail="Pairing code is invalid or expired.",
        )

    return {
        "device_token": create_device_token(item["user_id"]),
        "message": "Device paired successfully.",
    }
