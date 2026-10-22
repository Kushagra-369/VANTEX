"""Secure, read-only Cloudinary gallery endpoint for VANTEX."""
import base64
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Header, HTTPException, Query

router = APIRouter(prefix="/api/cloudinary", tags=["Cloudinary"])

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@router.get("/images")
def list_cloudinary_images(
    next_cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=30, ge=1, le=100),
    access_token: str | None = Header(default=None, alias="X-VANTEX-Gallery-Token"),
):
    """Return one page of image assets. Credentials never leave the server."""
    expected_token = os.getenv("VANTEX_GALLERY_ACCESS_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="VANTEX_GALLERY_ACCESS_TOKEN is not configured on the backend.")
    if not access_token or not secrets.compare_digest(access_token, expected_token):
        raise HTTPException(status_code=401, detail="Gallery access token is missing or invalid.")

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()

    if not cloud_name or not api_key or not api_secret:
        raise HTTPException(
            status_code=503,
            detail=("Cloudinary Admin API is not configured on the backend. Set "
                    "CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and "
                    "CLOUDINARY_API_SECRET in the backend environment, then restart VANTEX."),
        )

    params = {"max_results": limit}
    if next_cursor:
        params["next_cursor"] = next_cursor
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/resources/image/upload?" + urlencode(params)
    token = base64.b64encode(f"{api_key}:{api_secret}".encode("utf-8")).decode("ascii")
    request = Request(url, headers={
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "User-Agent": "VANTEX-Cloudinary-Gallery/1.0",
    }, method="GET")

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise HTTPException(status_code=502, detail="Cloudinary rejected the Admin API credentials. Verify API key/secret and cloud name.") from exc
        if exc.code == 429:
            raise HTTPException(status_code=429, detail="Cloudinary Admin API rate limit reached. Wait a little and retry.") from exc
        raise HTTPException(status_code=502, detail=f"Cloudinary Admin API request failed (HTTP {exc.code}).") from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Could not reach Cloudinary. Check internet connection and retry.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="Cloudinary returned an unreadable response.") from exc

    resources = []
    for item in payload.get("resources", []):
        resources.append({
            "asset_id": item.get("asset_id"),
            "public_id": item.get("public_id"),
            "display_name": item.get("display_name") or item.get("public_id", "").split("/")[-1],
            "secure_url": item.get("secure_url"),
            "format": item.get("format"),
            "width": item.get("width"),
            "height": item.get("height"),
            "bytes": item.get("bytes"),
            "created_at": item.get("created_at"),
        })
    return {"resources": resources, "next_cursor": payload.get("next_cursor"), "total_count": len(resources)}
