#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path.home() / "Desktop" / "VANTEX"
HOME = ROOT / "apps/web/src/components/Home/Home.tsx"
BACKEND = ROOT / "ai/main.py"
if not HOME.is_file() or not BACKEND.is_file():
    print(f"STOP: VANTEX files not found under {ROOT}")
    sys.exit(1)

home, backend = HOME.read_text(), BACKEND.read_text()
old_copy = "`${API}/api/agent/files/read?path=${encodeURIComponent(path)}`"
new_copy = "`${API}/api/agent/pc-files/read?path=${encodeURIComponent(path)}`"
if home.count(old_copy) != 1:
    print(f"STOP: expected one Copy read endpoint, found {home.count(old_copy)}. No changes made.")
    sys.exit(1)

old_button = '''            <button type="button" className="qa-fix-button" disabled={projectBusy} onClick={async () => {
              setProjectBusy(true); setProjectMessage("Opening local folder picker…");
              try {
                const picked = asObject(await requestJSON(`${API}/api/projects/browse`));
                if (picked?.cancelled === true) { setProjectMessage("Folder selection cancelled."); return; }
                if (typeof picked?.path !== "string") throw new Error(getMessage(picked, "Could not choose folder."));
                setProjectPath(picked.path);
                const selected = asObject(await requestJSON(`${API}/api/projects/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: picked.path }) }));
                setProjectInfo(selected); setProjectMessage(String(selected?.message ?? "Project selected."));
              } catch (err) { setProjectMessage(err instanceof Error ? err.message : "Folder picker unavailable. Enter path manually."); }
              finally { setProjectBusy(false); }
            }}>{projectBusy ? "Working…" : "Browse folders"}</button>'''
new_button = old_button + '''
            <button type="button" className="qa-fix-button" disabled={projectBusy} onClick={async () => {
              setProjectBusy(true); setProjectMessage("Choose a folder to approve for file search and reading…");
              try {
                const picked = asObject(await requestJSON(`${API}/api/projects/browse`));
                if (picked?.cancelled === true) { setProjectMessage("Folder selection cancelled."); return; }
                if (typeof picked?.path !== "string") throw new Error(getMessage(picked, "Could not choose folder."));
                const approved = asObject(await requestJSON(`${API}/api/agent/pc-files/approve-folder`, {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ path: picked.path }),
                }));
                setProjectMessage(String(approved?.message ?? `Folder approved: ${picked.path}`));
              } catch (err) { setProjectMessage(err instanceof Error ? err.message : "Could not approve folder."); }
              finally { setProjectBusy(false); }
            }}>{projectBusy ? "Working…" : "Allow Folder"}</button>'''
if home.count(old_button) != 1:
    print(f"STOP: expected one Browse folders button block, found {home.count(old_button)}. No changes made.")
    sys.exit(1)

old_roots = '''PC_FILE_ROOTS = [
    (Path.home() / name).resolve()
    for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")
    if (Path.home() / name).is_dir()
]'''
new_roots = '''# File Operator roots: standard folders plus user-approved folders.
import json

PC_APPROVED_FOLDERS_FILE = Path.home() / ".config" / "vantex" / "approved_folders.json"

def load_pc_file_roots():
    roots = [
        (Path.home() / name).resolve()
        for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")
        if (Path.home() / name).is_dir()
    ]
    try:
        saved = json.loads(PC_APPROVED_FOLDERS_FILE.read_text(encoding="utf-8"))
        if isinstance(saved, list):
            for raw in saved:
                if not isinstance(raw, str):
                    continue
                try:
                    candidate = Path(raw).expanduser().resolve(strict=True)
                    if (candidate.is_dir()
                            and candidate != Path(candidate.anchor)
                            and candidate != Path.home().resolve()
                            and candidate not in roots):
                        roots.append(candidate)
                except (OSError, RuntimeError):
                    continue
    except (OSError, ValueError, TypeError):
        pass
    return roots

PC_FILE_ROOTS = load_pc_file_roots()

class ApproveFolderRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2000)

@app.post("/api/agent/pc-files/approve-folder")
def approve_pc_folder(request: ApproveFolderRequest):
    global PC_FILE_ROOTS
    candidate = Path(request.path).expanduser()
    try:
        if candidate.is_symlink():
            raise ValueError("Symlink folders cannot be approved.")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("Selected path is not a folder.")
        if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
            raise ValueError("Choose a specific folder, not the filesystem root or entire home folder.")
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc) or "Folder does not exist.") from exc

    if resolved not in PC_FILE_ROOTS:
        PC_FILE_ROOTS.append(resolved)

    try:
        PC_APPROVED_FOLDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        defaults = {
            (Path.home() / name).resolve()
            for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")
            if (Path.home() / name).is_dir()
        }
        custom_roots = [str(root) for root in PC_FILE_ROOTS if root not in defaults]
        PC_APPROVED_FOLDERS_FILE.write_text(
            json.dumps(sorted(set(custom_roots)), indent=2), encoding="utf-8"
        )
    except OSError as exc:
        PC_FILE_ROOTS = load_pc_file_roots()
        raise HTTPException(status_code=500, detail=f"Could not save folder approval: {exc}") from exc

    return {"approved": True, "path": str(resolved),
            "message": f"Folder approved for file search and read: {resolved}",
            "approved_roots": [str(root) for root in PC_FILE_ROOTS]}

@app.get("/api/agent/pc-files/read")
def read_pc_file(path: str = Query(min_length=1, max_length=2000)):
    safe_path = resolve_pc_file(path)
    if safe_path.stat().st_size > MAX_READ_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 1 MB read limit.")
    try:
        content = safe_path.read_bytes()
        if b"\\x00" in content:
            raise HTTPException(status_code=415, detail="Binary files cannot be copied as text.")
        text_content = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="File is not valid UTF-8 text; use a file attachment instead.") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied.") from exc
    return {"path": str(safe_path), "size_bytes": len(content),
            "content": text_content, "read_only": True}'''
if backend.count(old_roots) != 1:
    print(f"STOP: expected one PC_FILE_ROOTS block, found {backend.count(old_roots)}. No changes made.")
    sys.exit(1)
if "from pydantic import BaseModel, Field" not in backend:
    print("STOP: expected existing BaseModel, Field import. No changes made.")
    sys.exit(1)
if "MAX_READ_BYTES =" not in backend:
    print("STOP: MAX_READ_BYTES is missing; no changes made.")
    sys.exit(1)

# Insert routes after resolve_pc_file() and before scan_pc_files(), so the helper exists.
scan = "def scan_pc_files():"
if backend.count(scan) != 1:
    print("STOP: could not uniquely locate scan_pc_files. No changes made.")
    sys.exit(1)
new_backend = backend.replace(old_roots, new_roots, 1)
new_home = home.replace(old_copy, new_copy, 1).replace(old_button, new_button, 1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
hb = HOME.with_name(HOME.name + f".backup-allow-folder-{stamp}")
bb = BACKEND.with_name(BACKEND.name + f".backup-allow-folder-{stamp}")
shutil.copy2(HOME, hb)
shutil.copy2(BACKEND, bb)
HOME.write_text(new_home)
BACKEND.write_text(new_backend)
print("SUCCESS: Added persistent approved-folder support and approved-file text reading.")
print(f"Frontend backup: {hb}")
print(f"Backend backup: {bb}")
print("Restart FastAPI, run npm run build, then click Allow Folder and choose a specific folder.")
