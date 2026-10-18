#!/usr/bin/env python3
"""Add a cautious, approval-based accessible-name fix for simple JSX input controls."""
from pathlib import Path
from datetime import datetime
import ast, re, shutil, sys

ROOT = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
BACKEND = ROOT / 'ai' / 'main.py'
FRONTEND = ROOT / 'apps' / 'web' / 'src' / 'components' / 'Home' / 'Home.tsx'

if not BACKEND.is_file() or not FRONTEND.is_file():
    raise SystemExit(f'Expected files not found under {ROOT}: ai/main.py and apps/web/src/components/Home/Home.tsx')
b = BACKEND.read_text(encoding='utf-8')
f = FRONTEND.read_text(encoding='utf-8')
if 'VANTEX_ACCESSIBILITY_FIX_V1' in b and 'VANTEX_ACCESSIBILITY_FIX_V1' in f:
    raise SystemExit('Accessibility patch marker already exists; no files changed.')
if 'VANTEX_MULTI_FIX_V1' not in b or 'const fixKind =' not in f or 'fix_kind: fixKind' not in f:
    raise SystemExit('Expected the current multi-fix version. No files changed; send the current files for a compatible patch.')

# Add source-level JSX proposal helper before prepare_ui_fix.
anchor = '@app.post("/api/agent/qa/prepare-ui-fix")\ndef prepare_ui_fix(request: UIFixRequest):'
helper = r'''def _prepare_accessibility_input_edit(project_root: Path, selector: str):
    """Prepare an aria-label proposal only when exactly one matching JSX input is found."""
    tokens = list(dict.fromkeys(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", selector)))
    if not tokens:
        raise HTTPException(status_code=422, detail="Could not identify input classes from this finding. Use Find source file.")

    matches = []
    scanned = 0
    skip = set(PROJECT_SKIP_DIRS) | {"dist", "build", ".next", ".git", "coverage"}
    for current, dirs, files in os.walk(project_root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in skip and not (Path(current) / d).is_symlink()]
        for filename in files:
            candidate = Path(current) / filename
            if candidate.suffix.lower() not in {".tsx", ".jsx", ".html", ".vue", ".svelte"} or candidate.is_symlink():
                continue
            scanned += 1
            if scanned > 2500:
                break
            try:
                if candidate.stat().st_size > 1_000_000:
                    continue
                content = candidate.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for tag_match in re.finditer(r"<input\b[^>]*>", content, flags=re.IGNORECASE | re.DOTALL):
                tag = tag_match.group(0)
                class_match = re.search(r"(?:className|class)\s*=\s*(?:\{\s*)?['\"]([^'\"]*)['\"]", tag)
                if not class_match:
                    continue
                classes = set(class_match.group(1).split())
                if not set(tokens).issubset(classes):
                    continue
                if re.search(r"\b(?:aria-label|aria-labelledby)\s*=", tag):
                    continue
                # An associated explicit label may be outside this tag; the QA report says none,
                # but only propose if the control has a meaningful placeholder/name/type.
                placeholder = re.search(r"\bplaceholder\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                name = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                input_type = re.search(r"\btype\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                identifier = re.search(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", tag, re.I)
                label = placeholder.group(1).strip() if placeholder else ""
                if not label and name:
                    raw = name.group(1).replace("_", " ").replace("-", " ").strip()
                    label = raw[:1].upper() + raw[1:]
                if not label and identifier:
                    raw = identifier.group(1).replace("_", " ").replace("-", " ").strip()
                    label = raw[:1].upper() + raw[1:]
                if not label and input_type:
                    label = {"email": "Email address", "password": "Password", "search": "Search", "tel": "Phone number", "url": "Website address", "number": "Number"}.get(input_type.group(1).lower(), "")
                if not label:
                    continue
                matches.append((candidate.resolve(), content, tag_match.start(), tag_match.end(), tag, label))
        if scanned > 2500:
            break

    # De-duplicate the same physical source range and never guess between repeated controls.
    unique = {(str(item[0]), item[2], item[3]): item for item in matches}
    matches = list(unique.values())
    if len(matches) != 1:
        detail = "No safely identifiable input with a meaningful placeholder/name was found." if not matches else f"Found {len(matches)} matching inputs; refusing to guess which one to edit."
        raise HTTPException(status_code=422, detail=detail + " Use Find source file and add a visible label or aria-label manually.")

    target, original, start, end, tag, label = matches[0]
    try:
        target.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Input source is outside the selected project.")
    escaped = label.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    replacement = re.sub(r"\s*/?>$", lambda m: f' aria-label="{escaped}"{m.group(0)}', tag)
    proposed = original[:start] + replacement + original[end:]
    result = prepare_file_edit(PrepareEditRequest(path=str(target), new_content=proposed))
    if not result.get("changed"):
        raise HTTPException(status_code=409, detail="No accessibility change was proposed.")
    result["fix_type"] = "accessibility"
    result["proposed_declarations"] = {"aria-label": label}
    result["caution"] = "Review the source diff. This adds an accessible name based on the input's existing placeholder/name/id; a visible label is preferable when practical."
    return result


# VANTEX_ACCESSIBILITY_FIX_V1
'''
if b.count(anchor) != 1:
    raise SystemExit('Could not locate prepare-ui-fix anchor uniquely. No files changed.')
b = b.replace(anchor, helper + '\n' + anchor, 1)

# Extend validation and route accessibility edits before CSS-only declarations.
old = '''    elif fix_kind == "contrast":
        if request.category != "Color & contrast" or not evidence.startswith("Estimated contrast is "):
            raise HTTPException(status_code=400, detail="Contrast fixes require a color-contrast finding.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported UI fix type.")

    declarations = _ui_fix_declarations(fix_kind)
    project_root = SELECTED_PROJECT_ROOT.resolve(strict=True)
'''
new = '''    elif fix_kind == "contrast":
        if request.category != "Color & contrast" or not evidence.startswith("Estimated contrast is "):
            raise HTTPException(status_code=400, detail="Contrast fixes require a color-contrast finding.")
    elif fix_kind == "accessibility":
        evidence_lower = evidence.lower()
        if not ("accessible name" in evidence_lower or "associated label" in evidence_lower or "aria naming attribute" in evidence_lower):
            raise HTTPException(status_code=400, detail="Accessibility fixes require a missing input-name/label finding.")
    else:
        raise HTTPException(status_code=400, detail="Unsupported UI fix type.")

    project_root = SELECTED_PROJECT_ROOT.resolve(strict=True)
    if fix_kind == "accessibility":
        return _prepare_accessibility_input_edit(project_root, selector)

    declarations = _ui_fix_declarations(fix_kind)
'''
if b.count(old) != 1:
    raise SystemExit('Could not locate fix-kind validation block uniquely. No files changed.')
b = b.replace(old, new, 1)

# Preview supports semantic accessibility preview; screenshots may look identical, which is expected.
old = '''            preview_declarations = _ui_fix_declarations(request.fix_kind)
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
'''
new = '''            if request.fix_kind == "accessibility":
                preview_label = await chosen.evaluate("""el => {
                  const placeholder = (el.getAttribute('placeholder') || '').trim();
                  const name = (el.getAttribute('name') || el.id || '').replace(/[_-]+/g, ' ').trim();
                  const type = (el.getAttribute('type') || '').toLowerCase();
                  const typeNames = {email:'Email address', password:'Password', search:'Search', tel:'Phone number', url:'Website address', number:'Number'};
                  return placeholder || (name ? name.charAt(0).toUpperCase() + name.slice(1) : '') || typeNames[type] || 'Input field';
                }""")
                preview_declarations = {"aria-label": preview_label}
                await chosen.evaluate("(el, label) => el.setAttribute('aria-label', label)", preview_label)
            else:
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
'''
if b.count(old) != 1:
    raise SystemExit('Could not locate preview style application uniquely. No files changed.')
b = b.replace(old, new, 1)

# Add frontend classification for accessibility findings.
old = '''  const fixKind =
    category === 'Color & contrast' && evidence.startsWith('Estimated contrast is ')
      ? 'contrast'
      : category === 'Typography' && evidence.startsWith('Content width is ')
        ? 'overflow'
        : category === 'Typography' && match !== null && Number(match[1]) < 10
          ? 'typography'
          : '';
'''
new = '''  const evidenceLower = evidence.toLowerCase();
  const isMissingInputName =
    (evidenceLower.includes('accessible name') ||
      evidenceLower.includes('associated label') ||
      evidenceLower.includes('aria naming attribute')) &&
    String(issue.element ?? '').toLowerCase().startsWith('input');
  const fixKind =
    isMissingInputName
      ? 'accessibility'
      : category === 'Color & contrast' && evidence.startsWith('Estimated contrast is ')
        ? 'contrast'
        : category === 'Typography' && evidence.startsWith('Content width is ')
          ? 'overflow'
          : category === 'Typography' && match !== null && Number(match[1]) < 10
            ? 'typography'
            : '';
'''
if f.count(old) != 1:
    raise SystemExit('Could not locate frontend fixKind block uniquely. No files changed.')
f = f.replace(old, new, 1)

# Show accurate preview copy for semantic vs visual fixes.
old = '<p>Temporary 12px preview · Original source unchanged</p>'
new = '''<p>{fixKind === 'accessibility' ? 'Temporary accessible-name preview · Original source unchanged' : fixKind === 'overflow' ? 'Temporary text-wrapping preview · Original source unchanged' : fixKind === 'contrast' ? 'Temporary contrast preview · Original source unchanged' : 'Temporary 12px typography preview · Original source unchanged'}</p>'''
if f.count(old) != 1:
    raise SystemExit('Could not locate preview label uniquely. No files changed.')
f = f.replace(old, new, 1)
f = f.replace('alt="Website after temporary typography preview"', 'alt={fixKind === \'accessibility\' ? "Website after temporary accessibility preview; visual appearance may be unchanged" : `Website after temporary ${fixKind} preview`}')

# Create backups and write atomically-ish only after all anchor checks passed.
ts = datetime.now().strftime('%Y%m%d-%H%M%S')
bak_b = BACKEND.with_name(BACKEND.name + f'.before_accessibility_{ts}')
bak_f = FRONTEND.with_name(FRONTEND.name + f'.before_accessibility_{ts}')
shutil.copy2(BACKEND, bak_b); shutil.copy2(FRONTEND, bak_f)
try:
    ast.parse(b)
    BACKEND.write_text(b, encoding='utf-8')
    FRONTEND.write_text(f, encoding='utf-8')
    ast.parse(BACKEND.read_text(encoding='utf-8'))
except Exception:
    shutil.copy2(bak_b, BACKEND); shutil.copy2(bak_f, FRONTEND)
    raise
print('VANTEX accessibility fix patch applied.')
print(f'Backend backup: {bak_b}')
print(f'Frontend backup: {bak_f}')
print('Python syntax check: PASSED')
print('Next: cd apps/web && npm run build')
