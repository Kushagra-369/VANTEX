import getpass
import os
import stat
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv(
    "VANTEX_API_URL",
    "https://vantex-2d4l.onrender.com",
).rstrip("/")

CONFIG_DIR = Path.home() / ".config" / "vantex"
TOKEN_FILE = CONFIG_DIR / "device_token"


def save_token(token):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)

    fd = os.open(
        TOKEN_FILE,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        stat.S_IRUSR | stat.S_IWUSR,
    )
    with os.fdopen(fd, "w") as file:
        file.write(token)

    TOKEN_FILE.chmod(0o600)


def main():
    code = getpass.getpass("Enter VANTEX pairing code: ").strip()

    if not code:
        print("Pairing code is required.")
        return

    try:
        response = httpx.post(
            f"{API_URL}/api/agent/pair",
            json={"code": code},
            timeout=15,
        )
        response.raise_for_status()

        token = response.json().get("device_token")
        if not token:
            raise ValueError("Server returned no device token.")

        save_token(token)
        print("Device paired successfully.")
        print("Device token saved securely in ~/.config/vantex/")

    except Exception as exc:
        print(f"Pairing failed: {exc}")


if __name__ == "__main__":
    main()
