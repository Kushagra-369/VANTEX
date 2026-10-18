#!/usr/bin/env python3
from pathlib import Path
import ast
import datetime
import shutil
import sys

ROOT = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.home() / "Desktop" / "VANTEX"
BACKEND = ROOT / "ai" / "main.py"
FRONTEND = ROOT / "apps" / "web" / "src" / "components" / "Home" / "Home.tsx"

if not BACKEND.is_file() or not FRONTEND.is_file():
    sys.exit(f"Could not find VANTEX files under {ROOT}")

b = BACKEND.read_text(encoding="utf-8")
f = FRONTEND.read_text(encoding="utf-8")
if "/api/projects/select" in b or "project-manager-vantex" in f:
    sys.exit("Patch markers already exist; refusing to apply twice.")

root_anchor = 'AGENT_ROOT = (Path.home() / "Desktop" / "VANTEX").resolve()\n'
if b.count(root_anchor) != 1:
    sys.exit("Could not uniquely locate AGENT_ROOT; no changes made.")

project_api = r'''
SELECTED_PROJECT_ROOT = AGENT_ROOT
PROJECT_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".turbo"}
PROJECT_TEXT_EXTENSIONS = {".html", ".css", ".scss", ".sass", ".less", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".json", ".py", ".md", ".yaml", ".yml"}


class ProjectSelectRequest(BaseModel):
    path: str


def _describe_project(root: Path) -> dict:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise HTTPException(status_code=400, detail="Choose an existing, non-symlink project folder.")
    root = root.resolve(strict=True)
    indicators = {
        "package.json": (root / "package.json").is_file(),
        "index.html": (root / "index.html").is_file(),
        "pyproject.toml": (root / "pyproject.toml").is_file(),
        "requirements.txt": (root / "requirements.txt").is_file(),
        "src": (root / "src").is_dir(),
        "app": (root / "app").is_dir(),
        "pages": (root / "pages").is_dir(),
    }
    if not any(indicators.values()):
        raise HTTPException(status_code=400, detail="Folder does not look like a source project. Choose a folder containing package.json, src/, app/, pages/, index.html, or Python project files.")
    framework = "Project"
    if (root / "package.json").is_file():
        try:
            import json
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            framework = next((name for key, name in [("vite", "Vite"), ("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte")] if key in deps), "Node.js project")
        except Exception:
            framework = "Node.js project"
    elif (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file():
        framework = "Python project"
    elif (root / "index.html").is_file():
        framework = "Static HTML"
    return {"path": str(root), "name": root.name, "framework": framework, "indicators": indicators}


@app.get("/api/projects/current")
def current_project():
    return {**_describe_project(SELECTED_PROJECT_ROOT), "selected": True}


@app.post("/api/projects/select")
def select_project(request: ProjectSelectRequest):
    global SELECTED_PROJECT_ROOT
    candidate = Path(request.path).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(status_code=400, detail="Enter an absolute project folder path.")
    try:
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(status_code=400, detail="Project folder does not exist or cannot be accessed.")
    info = _describe_project(candidate)
    SELECTED_PROJECT_ROOT = candidate
    return {**info, "selected": True, "message": "Project selected. Project-fix operations are scoped to this folder."}


@app.get("/api/projects/browse")
def browse_project():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        chosen = filedialog.askdirectory(title="Choose a project folder", mustexist=True)
        root.destroy()
    except Exception as error:
        raise HTTPException(status_code=501, detail=f"Native folder picker unavailable ({str(error)[:100]}). Enter the absolute path manually.") from error
    if not chosen:
        return {"cancelled": True, "message": "Folder selection cancelled."}
    return {**_describe_project(Path(chosen)), "selected": False}


def resolve_selected_project_path(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = SELECTED_PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(SELECTED_PROJECT_ROOT.resolve(strict=True))
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=403, detail="Access denied: path is outside the selected project or does not exist.")
    return resolved


@app.get("/api/projects/map-source")
def map_project_source(selector: str = Query(min_length=1, max_length=500)):
    root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    tokens = []
    if "#" in selector:
        token = selector.split("#", 1)[1].split(".", 1)[0].split(":", 1)[0].split(" ", 1)[0]
        if token and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
            tokens.append(token)
    tokens.extend(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector))
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        raise HTTPException(status_code=400, detail="Selector has no safe class or id token to map.")
    matches = []
    scanned = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PROJECT_SKIP_DIRS and not (Path(current) / d).is_symlink()]
        for filename in files:
            path = Path(current) / filename
            if path.suffix.lower() not in PROJECT_TEXT_EXTENSIONS or path.is_symlink():
                continue
            scanned += 1
            if scanned > 6000:
                break
            try:
                if path.stat().st_size > 1000000:
                    continue
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            found = [token for token in tokens if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_-])", content)]
            if found:
                matches.append({"path": str(path.resolve()), "relative_path": str(path.resolve().relative_to(root)), "type": "style" if path.suffix.lower() in {".css", ".scss", ".sass", ".less"} else "source", "matched_tokens": found})
                if len(matches) >= 40:
                    break
        if scanned > 6000 or len(matches) >= 40:
            break
    return {"project": str(root), "selector": selector, "tokens": tokens, "matches": matches, "message": "These are heuristic source candidates, not guaranteed ownership of the rendered element."}


'''
b = b.replace(root_anchor, root_anchor + project_api, 1)

# CSS proposal targets selected project's stylesheet instead of VANTEX's own Home.css.
start = b.index('@app.post("/api/agent/qa/prepare-ui-fix")')
end = b.index("\n\nclass VisualPreviewRequest", start)
new_fix = r'''@app.post("/api/agent/qa/prepare-ui-fix")
def prepare_ui_fix(request: UIFixRequest):
    match = re.fullmatch(
        r"Text is ([0-9]+(?:\.[0-9]+)?)px and contains [0-9]+ characters\.",
        request.evidence.strip(),
    )
    if not match or float(match.group(1)) >= 10:
        raise HTTPException(status_code=400, detail="Only detected text smaller than 10px is supported.")

    selector = request.element.strip()
    if not selector or len(selector) > 500 or any(char in selector for char in "{};"):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")

    project_root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    tokens = []
    if "#" in selector:
        token = selector.split("#", 1)[1].split(".", 1)[0].split(":", 1)[0].split(" ", 1)[0]
        if token and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", token):
            tokens.append(token)
    tokens.extend(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector))
    tokens = list(dict.fromkeys(tokens))

    style_files = []
    scanned = 0
    for current, dirs, files in os.walk(project_root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PROJECT_SKIP_DIRS and not (Path(current) / d).is_symlink()]
        for filename in files:
            candidate = Path(current) / filename
            if candidate.suffix.lower() not in {".css", ".scss", ".sass", ".less"} or candidate.is_symlink():
                continue
            scanned += 1
            if scanned > 3000:
                break
            try:
                if candidate.stat().st_size > 1000000:
                    continue
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if tokens and any(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_-])", content) for token in tokens):
                style_files.append(candidate.resolve())
                if len(style_files) >= 20:
                    break
        if scanned > 3000 or len(style_files) >= 20:
            break

    if style_files:
        target = style_files[0]
    else:
        fallbacks = ["src/index.css", "src/App.css", "src/globals.css", "src/style.css", "app/globals.css", "app/styles.css", "styles/globals.css", "index.css", "style.css"]
        target = next((project_root / rel for rel in fallbacks if (project_root / rel).is_file()), None)
        if target is None:
            raise HTTPException(status_code=404, detail="No existing stylesheet could be mapped in selected project. No file changed.")
        target = target.resolve(strict=True)

    try:
        target.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Stylesheet is outside selected project.")
    original = target.read_text(encoding="utf-8")
    marker = f"/* VANTEX typography proposal: {selector} */"
    if marker in original:
        raise HTTPException(status_code=409, detail="A proposal for this selector already exists in the selected stylesheet.")
    proposed = original.rstrip() + "\n\n" + marker + "\n" + selector + " {\n    font-size: 12px !important;\n}\n"
    result = prepare_file_edit(PrepareEditRequest(path=str(target), new_content=proposed))
    if not result.get("changed"):
        raise HTTPException(status_code=409, detail="No CSS change was proposed.")
    result["fix_type"] = "typography_minimum_size"
    result["project_root"] = str(project_root)
    result["relative_path"] = str(target.relative_to(project_root))
    result["source_mapping"] = "selector-token CSS match" if style_files else "global stylesheet fallback"
    result["caution"] = "Review the selected project's stylesheet and selector. Source remains unchanged until explicit approval."
    return result
'''
b = b[:start] + new_fix + b[end:]

# prepare_file_edit may accept an absolute path in either VANTEX or selected root.
old = "    target = resolve_agent_path(request.path)\n"
if b.count(old) != 1:
    sys.exit("Could not uniquely locate prepare_file_edit path resolver. No files changed.")
b = b.replace(old, '''    try:
        target = resolve_agent_path(request.path)
    except HTTPException:
        target = resolve_selected_project_path(request.path)
''', 1)

# apply-edit must permit only VANTEX legacy paths or currently selected project paths.
old = '    target = resolve_agent_path(proposal["path"])\n'
if b.count(old) != 1:
    sys.exit("Could not uniquely locate apply-edit path resolver. No files changed.")
b = b.replace(old, '''    try:
        target = resolve_agent_path(proposal["path"])
    except HTTPException:
        target = resolve_selected_project_path(proposal["path"])
''', 1)

old = '    backup_dir = AGENT_ROOT / ".vantex_backups"\n'
if b.count(old) != 1:
    sys.exit("Could not uniquely locate backup path. No files changed.")
b = b.replace(old, '''    try:
        target.relative_to(AGENT_ROOT)
        backup_root = AGENT_ROOT
    except ValueError:
        target.relative_to(SELECTED_PROJECT_ROOT.resolve(strict=True))
        backup_root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    backup_dir = backup_root / ".vantex_backups"
''', 1)

# Frontend project picker + path field
state_anchor = "  const [history, setHistory] = useState<string[]>([]);\n"
if f.count(state_anchor) != 1:
    sys.exit("Could not uniquely locate frontend state. No files changed.")
f = f.replace(state_anchor, state_anchor + '''  const [projectPath, setProjectPath] = useState('');
  const [projectInfo, setProjectInfo] = useState<Record<string, unknown> | null>(null);
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectMessage, setProjectMessage] = useState('');
''', 1)

form_anchor = '        <form className="command-form" onSubmit={handleSubmit}>\n'
if f.count(form_anchor) != 1:
    sys.exit("Could not uniquely locate command form. No files changed.")
project_ui = r'''        <section className="project-manager-vantex" aria-label="Project manager" style={{ width: "min(760px, 100%)", margin: "0 auto 24px", padding: "18px", border: "1px solid rgba(100,255,170,.22)", borderRadius: "16px", background: "rgba(8,20,16,.72)", textAlign: "left" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", alignItems: "center", flexWrap: "wrap" }}>
            <div><strong style={{ display: "block", color: "#d7ffe7" }}>Choose Project</strong><span style={{ color: "#9ab5a5", fontSize: "13px" }}>Select the local source folder VANTEX may inspect.</span></div>
            <button type="button" className="qa-fix-button" disabled={projectBusy} onClick={async () => {
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
            }}>{projectBusy ? "Working…" : "Browse folders"}</button>
          </div>
          <form onSubmit={async (event) => {
            event.preventDefault();
            if (!projectPath.trim() || projectBusy) return;
            setProjectBusy(true); setProjectMessage("");
            try {
              const selected = asObject(await requestJSON(`${API}/api/projects/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: projectPath.trim() }) }));
              setProjectInfo(selected); setProjectMessage(String(selected?.message ?? "Project selected."));
            } catch (err) { setProjectMessage(err instanceof Error ? err.message : "Could not select project."); }
            finally { setProjectBusy(false); }
          }} style={{ display: "flex", gap: "8px", marginTop: "14px", flexWrap: "wrap" }}>
            <input value={projectPath} onChange={(event) => setProjectPath(event.target.value)} placeholder="/home/user/projects/my-app" aria-label="Absolute project folder path" style={{ flex: "1 1 320px", minWidth: 0, padding: "12px", borderRadius: "9px", border: "1px solid rgba(100,255,170,.2)", background: "#07110d", color: "#e5fff0" }} />
            <button type="submit" className="qa-fix-button" disabled={projectBusy || !projectPath.trim()}>{projectBusy ? "Selecting…" : "Select project"}</button>
          </form>
          {projectInfo && <div style={{ marginTop: "12px", color: "#b8e9ca", fontSize: "13px" }}><strong>{String(projectInfo.name ?? "Selected project")}</strong> · {String(projectInfo.framework ?? "Project detected")}<div style={{ overflowWrap: "anywhere", color: "#91ad9d" }}>{String(projectInfo.path ?? projectPath)}</div></div>}
          {projectMessage && <p role="status" style={{ margin: "10px 0 0", color: "#b8e9ca", fontSize: "13px" }}>{projectMessage}</p>}
        </section>

'''
f = f.replace(form_anchor, project_ui + form_anchor, 1)

# Keep button visible for all findings; only known typography issue is automatically editable.
old = '''  const evidence = String(issue.evidence ?? '');
  const match = evidence.match(/Text is ([\\d.]+)px/);
  const supported = String(issue.category ?? '') === 'Typography' && match !== null && Number(match[1]) < 10;

  if (!supported) return null;
'''
new = '''  const evidence = String(issue.evidence ?? '');
  const match = evidence.match(/Text is ([\\d.]+)px/);
  const supported = String(issue.category ?? '') === 'Typography' && match !== null && Number(match[1]) < 10;
'''
if f.count(old) != 1:
    sys.exit("Could not uniquely locate fix-button category guard. No files changed.")
f = f.replace(old, new, 1)

old = '''      {!proposal && !visualCandidates.length && !visualPreview && (
        <button type="button" className="qa-fix-button" onClick={prepareFix} disabled={busy}>
          {busy ? 'Preparing…' : 'Fix this issue'}
        </button>
      )}
'''
new = '''      {!proposal && !visualCandidates.length && !visualPreview && (
        <button type="button" className="qa-fix-button" onClick={() => {
          if (!supported) {
            setMessage("Automatic edit is currently supported only for Typography findings with evidence below 10px. Use Find source file to locate likely project files. No source was changed.");
            return;
          }
          void prepareFix();
        }} disabled={busy}>
          {busy ? 'Preparing…' : 'Fix this issue'}
        </button>
      )}
      <button type="button" className="qa-fix-button" disabled={busy} onClick={async () => {
        setBusy(true); setMessage("Searching selected project files…");
        try {
          const mapped = await requestJSON(`${API}/api/projects/map-source?${new URLSearchParams({ selector: String(issue.element ?? "") })}`);
          const obj = asObject(mapped);
          const matches = Array.isArray(obj?.matches) ? obj.matches : [];
          const paths = matches.slice(0, 8).map((item) => { const entry = asObject(item); return String(entry?.relative_path ?? entry?.path ?? ""); });
          setMessage(paths.length ? `Likely source candidates: ${paths.join(" · ")}. These are heuristic matches; review before editing.` : getMessage(mapped, "No source candidates found."));
        } catch (err) { setMessage(err instanceof Error ? err.message : "Source mapping failed."); }
        finally { setBusy(false); }
      }}>Find source file</button>
'''
if f.count(old) != 1:
    sys.exit("Could not uniquely locate fix button block. No files changed.")
f = f.replace(old, new, 1)

# Validate the candidate backend before touching disk.
try:
    ast.parse(b)
except SyntaxError as exc:
    sys.exit(f"Backend syntax check failed at line {exc.lineno}: {exc.msg}. No files changed.")

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
bbak = BACKEND.with_name(f"main.py.before_project_selection_{stamp}")
fbak = FRONTEND.with_name(f"Home.tsx.before_project_selection_{stamp}")
shutil.copy2(BACKEND, bbak)
shutil.copy2(FRONTEND, fbak)
try:
    BACKEND.write_text(b, encoding="utf-8")
    FRONTEND.write_text(f, encoding="utf-8")
except Exception:
    shutil.copy2(bbak, BACKEND)
    shutil.copy2(fbak, FRONTEND)
    raise

print("Project-selection patch applied.")
print(f"Backend backup: {bbak}")
print(f"Frontend backup: {fbak}")
print("Python syntax check: PASSED")
print("Next: cd ~/Desktop/VANTEX/apps/web && npm run build")
print("Important: source mapping is heuristic. Auto-edit remains limited to small Typography findings; other findings show the fix control and a source-mapping option, but are not automatically edited.")
