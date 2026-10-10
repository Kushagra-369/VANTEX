from urllib.parse import urljoin, urlparse
import psutil
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from pathlib import Path
from fastapi import Query
import difflib
import hashlib
import secrets
from datetime import datetime, timezone
app = FastAPI(
    title="VANTEX API",
    description="VANTEX Website QA Engine",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class WebsiteTestRequest(BaseModel):
    url: HttpUrl


@app.get("/")
def home():
    return {
        "name": "VANTEX",
        "message": "Backend is running",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "vantex-api"}

@app.get("/api/agent/system")
def get_system_status():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "agent": "VANTEX Local Agent",
        "connected": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "ram_percent": memory.percent,
            "ram_total_gb": round(memory.total / (1024 ** 3), 2),
            "ram_available_gb": round(memory.available / (1024 ** 3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024 ** 3), 2),
        },
    }

@app.post("/api/qa/test")
async def test_website(request: WebsiteTestRequest):
    url = str(request.url)
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP and HTTPS URLs are supported.")

    console_errors = []
    failed_requests = []
    page_errors = []
    broken_links = []

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)

            page = await browser.new_page()
            page.set_default_timeout(10000)

            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )

            page.on("pageerror", lambda error: page_errors.append(str(error)))

            page.on(
                "requestfailed",
                lambda req: failed_requests.append({
                    "url": req.url,
                    "error": req.failure,
                }),
            )

            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
            except PlaywrightTimeoutError:
                await browser.close()
                raise HTTPException(
                    status_code=504,
                    detail="Website navigation timed out.",
                )

            title = await page.title()
            final_url = page.url
            status_code = response.status if response else None

            links = await page.locator("a[href]").evaluate_all(
                """elements => elements
                    .map(a => a.href)
                    .filter(href => href.startsWith('http://') ||
                                    href.startsWith('https://'))
                """
            )

            unique_links = list(dict.fromkeys(links))[:15]

            for link in unique_links:
                try:
                    result = await page.request.get(
                        link,
                        timeout=7000,
                        fail_on_status_code=False,
                    )

                    if result.status >= 400:
                        broken_links.append({
                            "url": link,
                            "status": result.status,
                        })
                except Exception as error:
                    broken_links.append({
                        "url": link,
                        "error": str(error)[:180],
                    })

            await browser.close()

            return {
                "success": True,
                "tested_url": url,
                "final_url": final_url,
                "title": title,
                "http_status": status_code,
                "console_errors": console_errors[:30],
                "page_errors": page_errors[:30],
                "failed_requests": failed_requests[:30],
                "broken_links": broken_links,
                "links_checked": len(unique_links),
                "summary": {
                    "console_error_count": len(console_errors),
                    "page_error_count": len(page_errors),
                    "failed_request_count": len(failed_requests),
                    "broken_link_count": len(broken_links),
                },
                "note": "Detection only. No source files were modified.",
            }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Website test failed: {str(error)[:250]}",
        ) from error

# VANTEX Local File Access — initial restricted version

import os

AGENT_ROOT = (Path.home() / "Desktop" / "VANTEX").resolve()
MAX_READ_BYTES = 1_000_000
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}


def resolve_agent_path(raw_path: str | None = None) -> Path:
    """Allow access only inside the configured VANTEX project directory."""
    candidate = Path(raw_path).expanduser() if raw_path else AGENT_ROOT

    if not candidate.is_absolute():
        candidate = AGENT_ROOT / candidate

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(AGENT_ROOT)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path is outside the approved VANTEX folder or does not exist.",
        )

    return resolved


@app.get("/api/agent/files/list")
def list_agent_files(path: str | None = Query(default=None)):
    directory = resolve_agent_path(path)

    if not directory.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    entries = []

    try:
        for item in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            try:
                resolved_item = item.resolve(strict=True)
                resolved_item.relative_to(AGENT_ROOT)
                is_dir = resolved_item.is_dir()

                entries.append({
                    "name": item.name,
                    "type": "directory" if is_dir else "file",
                    "path": str(resolved_item),
                    "size_bytes": None if is_dir else resolved_item.stat().st_size,
                })
            except (OSError, ValueError, RuntimeError):
                continue

            if len(entries) >= 200:
                break
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.")

    return {
        "root": str(AGENT_ROOT),
        "directory": str(directory),
        "entries": entries,
        "count": len(entries),
    }


@app.get("/api/agent/files/search")
def search_agent_files(
    query: str = Query(min_length=1, max_length=200),
):
    needle = query.casefold()
    matches = []
    scanned = 0
    scan_limit = 10000

    for current, dirs, files in os.walk(AGENT_ROOT, followlinks=False):
        dirs[:] = [
            name for name in dirs
            if name not in SKIP_DIRS
            and not (Path(current) / name).is_symlink()
        ]

        for name in files:
            scanned += 1

            if needle in name.casefold():
                candidate = Path(current) / name

                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(AGENT_ROOT)

                    matches.append({
                        "name": name,
                        "path": str(resolved),
                    })
                except (OSError, ValueError, RuntimeError):
                    continue

                if len(matches) >= 100:
                    return {
                        "query": query,
                        "matches": matches,
                        "truncated": True,
                    }

            if scanned >= scan_limit:
                return {
                    "query": query,
                    "matches": matches,
                    "truncated": True,
                    "message": "Scan limit reached.",
                }

    return {
        "query": query,
        "matches": matches,
        "truncated": False,
    }


@app.get("/api/agent/files/read")
def read_agent_file(path: str = Query(min_length=1)):
    file_path = resolve_agent_path(path)

    if not file_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file.")

    if file_path.stat().st_size > MAX_READ_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 1 MB read limit.",
        )

    try:
        content = file_path.read_bytes()

        if b"\x00" in content:
            raise HTTPException(
                status_code=415,
                detail="Binary files are not supported by this text reader.",
            )

        text_content = content.decode("utf-8")

    except UnicodeDecodeError:
        raise HTTPException(
            status_code=415,
            detail="File is not valid UTF-8 text.",
        )
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.")

    return {
        "path": str(file_path),
        "size_bytes": len(content),
        "content": text_content,
        "read_only": True,
    }

# VANTEX controlled file editing

from pydantic import Field


class PrepareEditRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    new_content: str = Field(max_length=1_000_000)


class ApplyEditRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=100)
    approve: bool = False


# Prototype storage: pending proposals remain in memory until API restarts.
PENDING_EDITS = {}


@app.post("/api/agent/files/prepare-edit")
def prepare_file_edit(request: PrepareEditRequest):
    target = resolve_agent_path(request.path)

    if not target.is_file():
        raise HTTPException(status_code=400, detail="Target must be an existing file.")

    if target.is_symlink():
        raise HTTPException(status_code=403, detail="Symbolic links cannot be edited.")

    if target.stat().st_size > MAX_READ_BYTES:
        raise HTTPException(status_code=413, detail="Original file exceeds 1 MB.")

    try:
        original_content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        raise HTTPException(
            status_code=415,
            detail="Only readable UTF-8 text files can be edited.",
        )

    if "\x00" in original_content or "\x00" in request.new_content:
        raise HTTPException(status_code=415, detail="Binary content is not supported.")

    if original_content == request.new_content:
        return {"changed": False, "message": "File already has this content."}

    proposal_id = secrets.token_urlsafe(24)
    original_hash = hashlib.sha256(
        original_content.encode("utf-8")
    ).hexdigest()

    diff = list(difflib.unified_diff(
        original_content.splitlines(),
        request.new_content.splitlines(),
        fromfile=f"original/{target.name}",
        tofile=f"proposed/{target.name}",
        lineterm="",
    ))

    PENDING_EDITS[proposal_id] = {
        "path": str(target),
        "original_hash": original_hash,
        "new_content": request.new_content,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "proposal_id": proposal_id,
        "path": str(target),
        "changed": True,
        "diff": diff,
        "approval_required": True,
        "message": "Review the diff. The original file has not been changed.",
    }


@app.post("/api/agent/files/apply-edit")
def apply_file_edit(request: ApplyEditRequest):
    if not request.approve:
        raise HTTPException(
            status_code=400,
            detail="Explicit approval is required to apply this edit.",
        )

    proposal = PENDING_EDITS.get(request.proposal_id)
    if not proposal:
        raise HTTPException(
            status_code=404,
            detail="Proposal not found or expired after a server restart.",
        )

    target = resolve_agent_path(proposal["path"])

    if not target.is_file() or target.is_symlink():
        raise HTTPException(status_code=403, detail="Target is no longer a regular file.")

    current_content = target.read_text(encoding="utf-8")
    current_hash = hashlib.sha256(current_content.encode("utf-8")).hexdigest()

    if current_hash != proposal["original_hash"]:
        PENDING_EDITS.pop(request.proposal_id, None)
        raise HTTPException(
            status_code=409,
            detail="File changed after proposal creation. Prepare a fresh edit.",
        )

    new_content = proposal["new_content"]
    backup_dir = AGENT_ROOT / ".vantex_backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{target.name}.{timestamp}.bak"
    backup_path.write_text(current_content, encoding="utf-8")

    temp_path = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")

    try:
        temp_path.write_text(new_content, encoding="utf-8")
        os.replace(temp_path, target)

        verified_content = target.read_text(encoding="utf-8")
        if verified_content != new_content:
            raise OSError("Post-write verification failed.")

    except Exception as error:
        try:
            if backup_path.exists():
                os.replace(backup_path, target)
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail=f"Edit failed or verification failed: {str(error)[:200]}",
        ) from error
    finally:
        if temp_path.exists():
            temp_path.unlink()

    PENDING_EDITS.pop(request.proposal_id, None)

    return {
        "success": True,
        "path": str(target),
        "verified": True,
        "backup_path": str(backup_path),
        "message": "Approved edit applied and verified.",
    }

import re
from pydantic import Field


class AgentCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)


@app.post("/api/agent/command")
async def run_agent_command(request: AgentCommandRequest):
    command = request.command.strip()
    lowered = command.casefold()

    # 1. System status
    if lowered in {"system status", "pc status", "check system"}:
        return {
            "command": command,
            "action": "system_status",
            "result": get_system_status(),
        }

    # 2. List approved project files
    if lowered in {"list files", "show files", "list project files"}:
        return {
            "command": command,
            "action": "list_files",
            "result": list_agent_files(),
        }

    # 3. Search by filename
    match = re.fullmatch(
        r"(?:find|search)(?: file)?\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )
    if match:
        query = match.group(1).strip()
        return {
            "command": command,
            "action": "search_files",
            "result": search_agent_files(query),
        }

    # 4. Read a text file within the approved project root
    match = re.fullmatch(
        r"read file\s+(.+)",
        command,
        flags=re.IGNORECASE,
    )
    if match:
        path = match.group(1).strip()
        return {
            "command": command,
            "action": "read_file",
            "result": read_agent_file(path),
        }

    # 5. Website QA
    match = re.fullmatch(
        r"test website\s+(https?://\S+)",
        command,
        flags=re.IGNORECASE,
    )
    if match:
        url = match.group(1).strip()
        try:
            request_model = WebsiteTestRequest(url=url)
        except Exception as error:
            raise HTTPException(status_code=422, detail="Invalid website URL.") from error

        return {
            "command": command,
            "action": "website_qa",
            "result": await test_website(request_model),
        }

    raise HTTPException(
        status_code=400,
        detail=(
            "Command not supported yet. Try: system status, list files, "
            "find file Home.tsx, read file apps/web/src/App.tsx, "
            "or test website http://localhost:5173"
        ),
    )