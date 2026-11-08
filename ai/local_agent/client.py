import asyncio
import json
import logging
import os
import random

import httpx
import websockets
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("vantex-local-agent")

RELAY_URL = os.getenv("VANTEX_RELAY_WS", "").strip()
from pathlib import Path

TOKEN_FILE = Path.home() / ".config" / "vantex" / "device_token"

def load_device_token():
    if not TOKEN_FILE.is_file():
        raise RuntimeError("Device not paired. Run: python -m ai.local_agent.pair")
    return TOKEN_FILE.read_text().strip()

DEVICE_TOKEN = load_device_token()
LOCAL_SECRET_FILE = Path.home() / ".config" / "vantex" / "local_api_secret"

def load_local_secret():
    if not LOCAL_SECRET_FILE.is_file():
        raise RuntimeError("Local backend secret not found. Start the local backend first.")
    secret = LOCAL_SECRET_FILE.read_text().strip()
    if len(secret) < 48:
        raise RuntimeError("Local backend secret is invalid.")
    return secret

LOCAL_SECRET = load_local_secret()
LOCAL_API = "http://127.0.0.1:8000"


async def execute_command(payload):
    command = payload.get("command")
    history = payload.get("history", [])

    if not isinstance(command, str) or not command.strip():
        raise ValueError("Invalid command.")

    if len(command) > 2000:
        raise ValueError("Command too long.")

    body = {
        "command": command,
        "history": history[-10:] if isinstance(history, list) else [],
    }

    async with httpx.AsyncClient(timeout=115) as client:
        response = await client.post(
            f"{LOCAL_API}/api/agent/local-command",
            headers={"X-VANTEX-LOCAL-SECRET": LOCAL_SECRET},
            json=body,
        )

        response.raise_for_status()
        return response.json()


ALLOWED_OPERATION_PREFIXES = (
    "/api/agent/pc-files/",
    "/api/agent/files/",
    "/api/agent/pc-control/",
    "/api/projects/",
)


async def execute_operation(payload):
    path = payload.get("path")
    method = payload.get("method", "GET")
    query = payload.get("query", {})
    body = payload.get("body")
    user_token = payload.get("user_token")

    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("Invalid local operation path.")
    if path.startswith("//") or ".." in path.split("/") or "\\" in path:
        raise ValueError("Invalid local operation path.")
    if not (
        path.startswith(ALLOWED_OPERATION_PREFIXES)
        or path == "/api/agent/monitor/status"
    ):
        raise ValueError("Local operation is not allowed.")
    if method not in {"GET", "POST"}:
        raise ValueError("Unsupported local operation method.")
    if not isinstance(query, dict) or len(query) > 30:
        raise ValueError("Invalid local operation query.")
    if not isinstance(user_token, str) or not user_token:
        raise ValueError("Missing authenticated user session.")

    headers = {
        "X-VANTEX-LOCAL-SECRET": LOCAL_SECRET,
        "Authorization": f"Bearer {user_token}",
    }

    async with httpx.AsyncClient(timeout=110, follow_redirects=False) as client:
        response = await client.request(
            method,
            f"{LOCAL_API}{path}",
            params=query,
            json=body if method == "POST" else None,
            headers=headers,
        )
        response.raise_for_status()

        try:
            return response.json()
        except ValueError:
            return {"result": response.text[:20000]}



async def run():
    if not RELAY_URL.startswith("wss://"):
        raise RuntimeError("VANTEX_RELAY_WS must use secure wss://.")

    if not DEVICE_TOKEN:
        raise RuntimeError("Device pairing is required.")

    delay = 2

    while True:
        try:
            log.info("Connecting to VANTEX relay...")

            async with websockets.connect(
                RELAY_URL,
                subprotocols=["vantex-agent-v1", DEVICE_TOKEN],
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
                max_size=1024 * 1024,
            ) as ws:
                log.info("Connected to VANTEX relay.")
                delay = 2

                async for raw in ws:
                    message = {}

                    try:
                        message = json.loads(raw)

                        if message.get("type") != "command":
                            continue

                        request_id = message.get("request_id")
                        if not isinstance(request_id, str):
                            continue

                        action = message.get("action")
                        payload = message.get("payload", {})

                        if action == "execute_command":
                            data = await execute_command(payload)
                        elif action == "execute_operation":
                            data = await execute_operation(payload)
                        else:
                            raise ValueError("Unsupported action.")

                        result = {
                            "type": "result",
                            "request_id": request_id,
                            "data": data,
                        }

                    except Exception as exc:
                        log.exception("Command execution failed.")
                        result = {
                            "type": "result",
                            "request_id": message.get("request_id"),
                            "error": str(exc)[:500],
                        }

                    await ws.send(json.dumps(result))

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Connection ended: %s", exc)

        await asyncio.sleep(delay + random.random())
        delay = min(delay * 2, 30)


if __name__ == "__main__":
    asyncio.run(run())
