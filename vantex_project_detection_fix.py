#!/usr/bin/env python3
"""Repair VANTEX project detection to recognize monorepo roots."""
from pathlib import Path
import ast
import datetime
import shutil
import sys

root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else (Path.home() / "Desktop" / "VANTEX").resolve()
backend = root / "ai" / "main.py"
if not backend.is_file():
    raise SystemExit(f"Could not find backend file: {backend}")

source = backend.read_text(encoding="utf-8")
start_marker = "def _describe_project(root: Path) -> dict:\n"
end_marker = '\n\n@app.get("/api/projects/current")'
if source.count(start_marker) != 1 or source.count(end_marker) != 1:
    raise SystemExit("Could not uniquely locate _describe_project(); no files changed.")

start = source.index(start_marker)
end = source.index(end_marker, start)
replacement = r'''def _describe_project(root: Path) -> dict:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        raise HTTPException(status_code=400, detail="Choose an existing, non-symlink project folder.")
    root = root.resolve(strict=True)

    # Recognize ordinary projects and monorepo roots; never scan dependencies/build output.
    direct = {
        "package.json": (root / "package.json").is_file(),
        "index.html": (root / "index.html").is_file(),
        "pyproject.toml": (root / "pyproject.toml").is_file(),
        "requirements.txt": (root / "requirements.txt").is_file(),
        "src": (root / "src").is_dir(),
        "app": (root / "app").is_dir(),
        "pages": (root / "pages").is_dir(),
        "main.py": (root / "main.py").is_file(),
        "manage.py": (root / "manage.py").is_file(),
    }
    nested_markers = []
    skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".turbo"}
    for base, dirs, files in os.walk(root, followlinks=False):
        relative = Path(base).relative_to(root)
        depth = len(relative.parts)
        dirs[:] = [d for d in dirs if d not in skip_dirs and not (Path(base) / d).is_symlink()]
        if depth >= 3:
            dirs[:] = []
            continue
        if any(name in files for name in ("package.json", "index.html", "pyproject.toml", "requirements.txt", "main.py", "manage.py")):
            nested_markers.append(Path(base))
    has_monorepo_layout = any((root / name).is_dir() for name in ("apps", "packages", "frontend", "backend", "client", "server", "web", "api", "ai"))
    if not any(direct.values()) and not nested_markers and not has_monorepo_layout:
        raise HTTPException(status_code=400, detail="Folder does not look like a source project. Choose a project folder containing source files, or a monorepo root with apps/, packages/, frontend/, backend/, client/, server/, web/, api/, or ai/.")

    package_file = root / "package.json"
    if not package_file.is_file():
        package_file = next((p / "package.json" for p in nested_markers if (p / "package.json").is_file()), None)
    indicators = {**direct, "nested_project_files": bool(nested_markers), "monorepo_layout": has_monorepo_layout}
    framework = "Project / monorepo"
    if package_file and package_file.is_file():
        try:
            import json
            pkg = json.loads(package_file.read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            framework = next((name for key, name in [("vite", "Vite"), ("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte")] if key in deps), "Node.js project")
            if package_file.parent != root:
                framework += " monorepo"
        except Exception:
            framework = "Node.js project / monorepo"
    elif direct["pyproject.toml"] or direct["requirements.txt"] or direct["main.py"] or direct["manage.py"] or any((p / "main.py").is_file() for p in nested_markers):
        framework = "Python project / monorepo"
    elif direct["index.html"]:
        framework = "Static HTML"
    return {"path": str(root), "name": root.name, "framework": framework, "indicators": indicators}
'''
updated = source[:start] + replacement + source[end:]
ast.parse(updated)
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
backup = backend.with_name(f"main.py.before_project_detection_fix_{stamp}")
shutil.copy2(backend, backup)
backend.write_text(updated, encoding="utf-8")
print("Project detection updated.")
print(f"Backup: {backup}")
print("Python syntax check: PASSED")
