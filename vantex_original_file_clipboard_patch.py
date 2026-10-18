#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path.home() / "Desktop" / "VANTEX"
HOME = ROOT / "apps/web/src/components/Home/Home.tsx"
BACKEND = ROOT / "ai/main.py"

for path in (HOME, BACKEND):
    if not path.is_file():
        sys.exit(f"STOP: required source file not found: {path}")

home = HOME.read_text(encoding="utf-8")
backend = BACKEND.read_text(encoding="utf-8")

old_copy_function = '''  async function copyFilePath(path: string) {
    try {
      const data: { content: string } = await requestJSON(
        `${API}/api/agent/pc-files/read?path=${encodeURIComponent(path)}`,
        { method: 'GET' },
      ) as { content: string };

      if (typeof data.content !== 'string') {
        throw new Error('File content was not returned.');
      }

      await navigator.clipboard.writeText(data.content);
      setCopiedPath(path);
      window.setTimeout(() => {
        setCopiedPath(current => current === path ? '' : current);
      }, 1800);
    } catch (err) {
      console.error('[VANTEX] Copy file content failed:', err);
      setCopiedPath('');
      alert(
        err instanceof Error
          ? err.message
          : 'Could not copy file content. Check file type and permissions.',
      );
    }
  }'''

new_copy_function = '''  async function copyFilePath(path: string) {
    try {
      const data = await requestJSON(
        `${API}/api/agent/pc-files/copy`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        },
      ) as { copied?: boolean; message?: string };

      if (data.copied !== true) {
        throw new Error(data.message || 'Could not copy the original file.');
      }

      setCopiedPath(path);
      window.setTimeout(() => {
        setCopiedPath(current => current === path ? '' : current);
      }, 1800);
    } catch (err) {
      console.error('[VANTEX] Copy original file failed:', err);
      setCopiedPath('');
      alert(
        err instanceof Error
          ? err.message
          : 'Could not copy file. Check file access and Linux clipboard support.',
      );
    }
  }'''

if home.count(old_copy_function) != 1:
    sys.exit(
        "STOP: expected exactly one known text-copy function in Home.tsx, "
        f"found {home.count(old_copy_function)}. No changes made."
    )

if '@app.post("/api/agent/pc-files/copy")' in backend:
    sys.exit("STOP: backend copy endpoint already exists. No changes made.")

home = home.replace(old_copy_function, new_copy_function, 1)
home = home.replace(
    "aria-label={`Copy path for ${file.name}`}\n              title=\"Copy full file path\"",
    "aria-label={`Copy original file ${file.name}`}\n              title=\"Copy original file for pasting in a compatible file manager\"",
    1,
)

backend_anchor = '''@app.get("/api/agent/pc-files/read")
def read_pc_file(path: str = Query(min_length=1, max_length=2000)):'''
if backend.count(backend_anchor) != 1:
    sys.exit(
        "STOP: expected exactly one PC file read endpoint anchor, "
        f"found {backend.count(backend_anchor)}. No changes made."
    )

copy_endpoint = '''@app.post("/api/agent/pc-files/copy")
def copy_pc_file(request: ApproveFolderRequest):
    # Put the original file URI on the Linux file clipboard; do not read or convert its bytes.
    safe_path = resolve_pc_file(request.path)
    clipboard_payload = ("copy\\n" + safe_path.as_uri() + "\\n").encode("utf-8")

    import os
    import shutil as _shutil

    if os.environ.get("WAYLAND_DISPLAY") and _shutil.which("wl-copy"):
        command = [_shutil.which("wl-copy"), "--type", "x-special/gnome-copied-files"]
    elif _shutil.which("xclip"):
        command = [_shutil.which("xclip"), "-selection", "clipboard",
                   "-t", "x-special/gnome-copied-files", "-i"]
    elif _shutil.which("wl-copy"):
        command = [_shutil.which("wl-copy"), "--type", "x-special/gnome-copied-files"]
    else:
        raise HTTPException(
            status_code=503,
            detail="Linux file clipboard tool missing. Install xclip (X11) or wl-clipboard (Wayland), then restart VANTEX.",
        )

    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        assert process.stdin is not None
        process.stdin.write(clipboard_payload)
        process.stdin.close()
    except (OSError, BrokenPipeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not place file on the system clipboard: {exc}",
        ) from exc

    return {
        "copied": True,
        "path": str(safe_path),
        "message": "Original file copied to the Linux file clipboard. Paste into a compatible file manager with Ctrl+V.",
    }


'''
backend = backend.replace(backend_anchor, copy_endpoint + backend_anchor, 1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
home_backup = HOME.with_name(HOME.name + f".backup-file-clipboard-{stamp}")
backend_backup = BACKEND.with_name(BACKEND.name + f".backup-file-clipboard-{stamp}")

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
print("Copy now places the original file URI on the Linux file clipboard; it does not convert files to text.")
print("This is intended for pasting files into compatible Linux file managers. Browser/app paste support varies.")
print("Next: python3 -m py_compile ai/main.py")
print("Then: cd apps/web && npm run build")
