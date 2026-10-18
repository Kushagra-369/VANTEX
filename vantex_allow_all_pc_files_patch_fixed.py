#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path.home() / "Desktop" / "VANTEX"
HOME = ROOT / "apps/web/src/components/Home/Home.tsx"
BACKEND = ROOT / "ai/main.py"

if not HOME.is_file() or not BACKEND.is_file():
    sys.exit(f"STOP: VANTEX source files not found under {ROOT}")

home = HOME.read_text(encoding="utf-8")
backend = BACKEND.read_text(encoding="utf-8")

if "Allow All PC Files" in home or "/api/agent/pc-files/allow-all" in backend:
    sys.exit("STOP: Allow All patch already appears to be installed.")

browse_end = '>{projectBusy ? "Working…" : "Allow Folder"}</button>'
if home.count(browse_end) != 1:
    sys.exit(f"STOP: expected one Allow Folder button, found {home.count(browse_end)}. No changes made.")

allow_button = '''>{projectBusy ? "Working…" : "Allow Folder"}</button>
            <button type="button" className="qa-fix-button" disabled={projectBusy} onClick={async () => {
              const confirmed = window.confirm("Allow VANTEX to search and read files throughout your home folder (including Desktop, Documents, Downloads and other user folders)? This does not grant root access or enable file editing/deletion.");
              if (!confirmed || projectBusy) return;
              setProjectBusy(true); setProjectMessage("Enabling full user-folder access…");
              try {
                const approved = asObject(await requestJSON(`${API}/api/agent/pc-files/allow-all`, {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ confirm: true }),
                }));
                setProjectMessage(String(approved?.message ?? "Full user-folder access enabled."));
              } catch (err) { setProjectMessage(err instanceof Error ? err.message : "Could not enable full access."); }
              finally { setProjectBusy(false); }
            }}>{projectBusy ? "Working…" : "Allow All PC Files"}</button>'''
home = home.replace(browse_end, allow_button, 1)

loader_anchor = "def load_pc_file_roots():\n    roots = ["
if backend.count(loader_anchor) != 1:
    sys.exit(f"STOP: expected one load_pc_file_roots function anchor, found {backend.count(loader_anchor)}. No changes made.")

backend = backend.replace(
    loader_anchor,
    '''PC_FULL_ACCESS_FILE = Path.home() / ".config" / "vantex" / "full_pc_access.json"

def load_pc_file_roots():
    try:
        access_state = json.loads(PC_FULL_ACCESS_FILE.read_text(encoding="utf-8"))
        if isinstance(access_state, dict) and access_state.get("enabled") is True:
            return [Path.home().resolve()]
    except (OSError, ValueError, TypeError):
        pass

    roots = [''',
    1,
)

roots_anchor = "PC_FILE_ROOTS = load_pc_file_roots()"
if roots_anchor not in backend:
    sys.exit("STOP: PC_FILE_ROOTS initializer not found. No changes made.")

route = '''

class AllowAllPcFilesRequest(BaseModel):
    confirm: bool = False

@app.post("/api/agent/pc-files/allow-all")
def allow_all_pc_files(request: AllowAllPcFilesRequest):
    global PC_FILE_ROOTS
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required.")

    try:
        PC_FULL_ACCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PC_FULL_ACCESS_FILE.write_text(
            json.dumps({"enabled": True, "enabled_at": datetime.now().astimezone().isoformat()}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save access setting: {exc}") from exc

    PC_FILE_ROOTS = [Path.home().resolve()]
    return {
        "enabled": True,
        "mode": "user-home",
        "roots": [str(PC_FILE_ROOTS[0])],
        "message": "Full user-folder search/read access enabled. Restart is not required.",
    }
'''
backend = backend.replace(roots_anchor, roots_anchor + route, 1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
home_backup = HOME.with_name(HOME.name + f".backup-allow-all-{stamp}")
backend_backup = BACKEND.with_name(BACKEND.name + f".backup-allow-all-{stamp}")
shutil.copy2(HOME, home_backup)
shutil.copy2(BACKEND, backend_backup)
try:
    HOME.write_text(home, encoding="utf-8")
    BACKEND.write_text(backend, encoding="utf-8")
except Exception:
    shutil.copy2(home_backup, HOME)
    shutil.copy2(backend_backup, BACKEND)
    raise

print("PATCH APPLIED")
print(f"Frontend backup: {home_backup}")
print(f"Backend backup: {backend_backup}")
print("Added a separate Allow All PC Files button; Allow Folder behavior is unchanged.")
print("Scope: files under your home folder for search/read only; no OS root access, editing, or deletion.")
print("Next: python3 -m py_compile ai/main.py")
print("Then: cd apps/web && npm run build")
