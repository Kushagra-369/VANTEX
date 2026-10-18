#!/usr/bin/env python3
"""Extend VANTEX QA fixes to preview/propose overflow and contrast fixes safely."""
from pathlib import Path
import ast
import datetime
import shutil
import sys

ROOT = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else (Path.home() / "Desktop" / "VANTEX").resolve()
BACKEND = ROOT / "ai" / "main.py"
FRONTEND = ROOT / "apps" / "web" / "src" / "components" / "Home" / "Home.tsx"

if not BACKEND.is_file() or not FRONTEND.is_file():
    raise SystemExit(f"Could not find VANTEX source files under {ROOT}")

b = BACKEND.read_text(encoding="utf-8")
f = FRONTEND.read_text(encoding="utf-8")
if "VANTEX_MULTI_FIX_V1" in b or "VANTEX_MULTI_FIX_V1" in f:
    raise SystemExit("This fix patch is already applied; refusing to apply twice.")

start_marker = "class UIFixRequest(BaseModel):\n"
end_marker = "\n\nclass VisualPreviewRequest(BaseModel):"
if b.count(start_marker) != 1 or b.count(end_marker) != 1:
    raise SystemExit("Could not uniquely locate the UI-fix endpoint block; no files changed.")

new_ui_fix = r'''# VANTEX_MULTI_FIX_V1
class UIFixRequest(BaseModel):
    element: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=300)
    category: str = Field(default="Typography", max_length=80)
    fix_kind: str = Field(default="typography", max_length=30)


def _ui_fix_declarations(fix_kind: str) -> dict[str, str]:
    """Only return predefined CSS values; never accept CSS from the client."""
    if fix_kind == "typography":
        return {"font-size": "12px"}
    if fix_kind == "overflow":
        return {
            "max-width": "100%",
            "min-width": "0",
            "overflow-wrap": "anywhere",
            "white-space": "normal",
        }
    if fix_kind == "contrast":
        # Proposal for review, not a claim that mint suits every background.
        return {"color": "#e5fff0"}
    raise HTTPException(status_code=400, detail="Unsupported UI fix type.")


@app.post("/api/agent/qa/prepare-ui-fix")
def prepare_ui_fix(request: UIFixRequest):
    selector = request.element.strip()
    if not selector or len(selector) > 500 or any(char in selector for char in "{};"):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")

    fix_kind = request.fix_kind.strip().lower()
    evidence = request.evidence.strip()
    if fix_kind == "typography":
        match = re.fullmatch(
            r"Text is ([0-9]+(?:\.[0-9]+)?)px and contains [0-9]+ characters\.",
            evidence,
        )
        if request.category != "Typography" or not match or float(match.group(1)) >= 10:
            raise HTTPException(status_code=400, detail="Typography fixes require evidence of text smaller than 10px.")
    elif fix_kind == "overflow":
        if request.category != "Typography" or not evidence.startswith("Content width is "):
            raise HTTPException(status_code=400, detail="Overflow fixes require a measured content-width finding.")
    elif fix_kind == "contrast":
        if request.category != "Color & contrast" or not evidence.startswith("Estimated contrast is "):
            raise HTTPException(status_code=400, detail="Contrast fixes require a color-contrast finding.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported UI fix type.")

    declarations = _ui_fix_declarations(fix_kind)
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
                if candidate.stat().st_size > 1_000_000:
                    continue
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if tokens and any(
                re.search(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_-])", content)
                for token in tokens
            ):
                style_files.append(candidate.resolve())
                if len(style_files) >= 20:
                    break
        if scanned > 3000 or len(style_files) >= 20:
            break

    if style_files:
        target = style_files[0]
    else:
        fallbacks = [
            "src/index.css", "src/App.css", "src/globals.css", "src/style.css",
            "app/globals.css", "app/styles.css", "styles/globals.css",
            "index.css", "style.css", "apps/web/src/index.css", "apps/web/src/App.css",
        ]
        target = next((project_root / rel for rel in fallbacks if (project_root / rel).is_file()), None)
        if target is None:
            raise HTTPException(status_code=404, detail="No existing stylesheet could be mapped in selected project. No file changed.")
        target = target.resolve(strict=True)

    try:
        target.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Stylesheet is outside selected project.")
    original = target.read_text(encoding="utf-8")
    marker = f"/* VANTEX {fix_kind} proposal: {selector} */"
    if marker in original:
        raise HTTPException(status_code=409, detail="A proposal for this selector already exists in the selected stylesheet.")
    declaration_text = "\n".join(f"    {name}: {value} !important;" for name, value in declarations.items())
    proposed = original.rstrip() + "\n\n" + marker + "\n" + selector + " {\n" + declaration_text + "\n}\n"
    result = prepare_file_edit(PrepareEditRequest(path=str(target), new_content=proposed))
    if not result.get("changed"):
        raise HTTPException(status_code=409, detail="No CSS change was proposed.")
    result["fix_type"] = fix_kind
    result["project_root"] = str(project_root)
    result["relative_path"] = str(target.relative_to(project_root))
    result["source_mapping"] = "selector-token CSS match" if style_files else "stylesheet fallback"
    result["proposed_declarations"] = declarations
    result["caution"] = (
        "Review the before/after preview and diff. Contrast uses a light mint foreground proposal "
        "that may not suit every background; source remains unchanged until explicit approval."
    )
    return result
'''
b = b[:b.index(start_marker)] + new_ui_fix + b[b.index(end_marker):]

old = '''class VisualPreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    selector: str = Field(min_length=1, max_length=500)
    font_size: int = Field(default=12, ge=10, le=32)
    candidate_index: int | None = Field(default=None, ge=0, le=9)
'''
new = '''class VisualPreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    selector: str = Field(min_length=1, max_length=500)
    font_size: int = Field(default=12, ge=10, le=32)
    fix_kind: str = Field(default="typography", max_length=30)
    candidate_index: int | None = Field(default=None, ge=0, le=9)
'''
if b.count(old) != 1:
    raise SystemExit("Could not uniquely locate visual preview request model; no files changed.")
b = b.replace(old, new, 1)

old = '''            before_png = await page.screenshot(type="png", full_page=False)
            await chosen.evaluate("(el, size) => { el.style.setProperty('font-size', size + 'px', 'important'); }", request.font_size)
            await page.wait_for_timeout(300)
            after_png = await page.screenshot(type="png", full_page=False)
'''
new = '''            before_png = await page.screenshot(type="png", full_page=False)
            preview_declarations = _ui_fix_declarations(request.fix_kind)
            if request.fix_kind == "typography":
                preview_declarations = {"font-size": f"{request.font_size}px"}
            await chosen.evaluate(
                """(el, declarations) => {
                    for (const [property, value] of Object.entries(declarations)) {
                        el.style.setProperty(property, value, 'important');
                    }
                }""",
                preview_declarations,
            )
            await page.wait_for_timeout(300)
            after_png = await page.screenshot(type="png", full_page=False)
'''
if b.count(old) != 1:
    raise SystemExit("Could not uniquely locate preview style application; no files changed.")
b = b.replace(old, new, 1)
old = '''                "font_size": request.font_size,
                "before_image": "data:image/png;base64," + base64.b64encode(before_png).decode("ascii"),
'''
new = '''                "font_size": request.font_size,
                "fix_kind": request.fix_kind,
                "preview_declarations": preview_declarations,
                "before_image": "data:image/png;base64," + base64.b64encode(before_png).decode("ascii"),
'''
if b.count(old) != 1:
    raise SystemExit("Could not uniquely locate visual preview response; no files changed.")
b = b.replace(old, new, 1)

old = '''  const evidence = String(issue.evidence ?? '');
  const match = evidence.match(/Text is ([\\d.]+)px/);
  const supported = String(issue.category ?? '') === 'Typography' && match !== null && Number(match[1]) < 10;
'''
new = '''  const evidence = String(issue.evidence ?? '');
  const category = String(issue.category ?? '');
  const match = evidence.match(/Text is ([\\d.]+)px/);
  const fixKind =
    category === 'Color & contrast' && evidence.startsWith('Estimated contrast is ')
      ? 'contrast'
      : category === 'Typography' && evidence.startsWith('Content width is ')
        ? 'overflow'
        : category === 'Typography' && match !== null && Number(match[1]) < 10
          ? 'typography'
          : '';
  const supported = fixKind !== '';
'''
if f.count(old) != 1:
    raise SystemExit("Could not uniquely locate frontend finding classifier; no files changed.")
f = f.replace(old, new, 1)
old = '''        selector: String(issue.element ?? ''),
        font_size: 12,
        ...(candidateIndex === undefined ? {} : { candidate_index: candidateIndex }),
'''
new = '''        selector: String(issue.element ?? ''),
        font_size: 12,
        fix_kind: fixKind,
        ...(candidateIndex === undefined ? {} : { candidate_index: candidateIndex }),
'''
if f.count(old) != 1:
    raise SystemExit("Could not uniquely locate visual preview request body; no files changed.")
f = f.replace(old, new, 1)
old = '''      body: JSON.stringify({ element: visualData.unique_selector, evidence }),
'''
new = '''      body: JSON.stringify({ element: visualData.unique_selector, evidence, category, fix_kind: fixKind }),
'''
if f.count(old) != 1:
    raise SystemExit("Could not uniquely locate prepare-fix request body; no files changed.")
f = f.replace(old, new, 1)
old = '''            setMessage("Automatic edit is currently supported only for Typography findings with evidence below 10px. Use Find source file to locate likely project files. No source was changed.");
'''
new = '''            setMessage("This finding type is not supported for a proposed edit yet. Use Find source file to locate likely project files. No source was changed.");
'''
if f.count(old) != 1:
    raise SystemExit("Could not uniquely locate unsupported-fix message; no files changed.")
f = f.replace(old, new, 1)
old = '''  async function prepareFix() {
    setBusy(true);
'''
new = '''  async function prepareFix() {
    if (!supported) {
      setMessage("This finding type is not supported for a proposed edit yet. No source was changed.");
      return;
    }
    setBusy(true);
'''
if f.count(old) != 1:
    raise SystemExit("Could not uniquely locate prepareFix guard; no files changed.")
f = f.replace(old, new, 1)

try:
    ast.parse(b)
except SyntaxError as exc:
    raise SystemExit(f"Backend Python syntax check failed at line {exc.lineno}: {exc.msg}; no files changed.")
if "VANTEX_MULTI_FIX_V1" not in b or "fix_kind: fixKind" not in f:
    raise SystemExit("Internal patch validation failed; no files changed.")

stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
b_backup = BACKEND.with_name(f"main.py.before_multi_fix_{stamp}")
f_backup = FRONTEND.with_name(f"Home.tsx.before_multi_fix_{stamp}")
shutil.copy2(BACKEND, b_backup)
shutil.copy2(FRONTEND, f_backup)
try:
    BACKEND.write_text(b, encoding="utf-8")
    FRONTEND.write_text(f, encoding="utf-8")
except Exception:
    shutil.copy2(b_backup, BACKEND)
    shutil.copy2(f_backup, FRONTEND)
    raise
print("VANTEX multi-fix patch applied.")
print(f"Backend backup: {b_backup}")
print(f"Frontend backup: {f_backup}")
print("Python syntax check: PASSED")
print("Next: cd ~/Desktop/VANTEX/apps/web && npm run build")
