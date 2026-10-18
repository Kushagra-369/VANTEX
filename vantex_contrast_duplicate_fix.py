#!/usr/bin/env python3
"""Patch VANTEX contrast proposals: replace duplicate proposal and choose a readable text color."""
from pathlib import Path
import re
import shutil
import py_compile
from datetime import datetime

ROOT = Path.home() / "Desktop" / "VANTEX"
BACKEND = ROOT / "ai" / "main.py"
FRONTEND = ROOT / "apps" / "web" / "src" / "components" / "Home" / "Home.tsx"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}. No files changed.")
    return text.replace(old, new, 1)

def main():
    if not BACKEND.is_file() or not FRONTEND.is_file():
        raise SystemExit(f"Could not find expected files under {ROOT}. No files changed.")

    backend = BACKEND.read_text(encoding="utf-8")
    frontend = FRONTEND.read_text(encoding="utf-8")

    # Validate all anchors before writing anything.
    backend_new = backend
    frontend_new = frontend

    backend_new = replace_once(
        backend_new,
        '    accessibility_label: str = Field(default="", max_length=120)\n',
        '    accessibility_label: str = Field(default="", max_length=120)\n'
        '    contrast_color: str = Field(default="#ffffff", max_length=20)\n',
        "UIFixRequest contrast_color field",
    )
    backend_new = replace_once(
        backend_new,
        'def _ui_fix_declarations(fix_kind: str) -> dict[str, str]:\n'
        '    """Only return predefined CSS values; never accept CSS from the client."""\n',
        'def _ui_fix_declarations(fix_kind: str, contrast_color: str = "#ffffff") -> dict[str, str]:\n'
        '    """Only return predefined CSS values; never accept arbitrary CSS from the client."""\n',
        "declaration helper signature",
    )
    backend_new = replace_once(
        backend_new,
        '    if fix_kind == "contrast":\n'
        '        # Proposal for review, not a claim that mint suits every background.\n'
        '        return {"color": "#e5fff0"}\n',
        '    if fix_kind == "contrast":\n'
        '        # Only accept one of two predefined high-contrast foreground choices.\n'
        '        color = contrast_color.lower()\n'
        '        if color not in {"#ffffff", "#111827"}:\n'
        '            color = "#ffffff"\n'
        '        return {"color": color}\n',
        "contrast declaration",
    )
    backend_new = replace_once(
        backend_new,
        '    declarations = _ui_fix_declarations(fix_kind)\n',
        '    declarations = _ui_fix_declarations(\n'
        '        fix_kind,\n'
        '        request.contrast_color if request.contrast_color in {"#ffffff", "#111827"} else "#ffffff",\n'
        '    )\n',
        "proposal declarations call",
    )
    backend_new = replace_once(
        backend_new,
        '    marker = f"/* VANTEX {fix_kind} proposal: {selector} */"\n'
        '    if marker in original:\n'
        '        raise HTTPException(status_code=409, detail="A proposal for this selector already exists in the selected stylesheet.")\n'
        '    declaration_text = "\\n".join(f"    {name}: {value} !important;" for name, value in declarations.items())\n',
        '    marker = f"/* VANTEX {fix_kind} proposal: {selector} */"\n'
        '    declaration_text = "\\n".join(f"    {name}: {value} !important;" for name, value in declarations.items())\n',
        "duplicate proposal guard",
    )
    backend_new = replace_once(
        backend_new,
        '    proposed = original.rstrip() + "\\n\\n" + marker + "\\n" + css_selector + " {\\n" + declaration_text + "\\n}\\n"\n',
        '    new_block = marker + "\\n" + css_selector + " {\\n" + declaration_text + "\\n}"\n'
        '    if marker in original:\n'
        '        # Update the existing VANTEX proposal in-place instead of blocking the user.\n'
        '        start = original.index(marker)\n'
        '        close = original.find("\\n}", start)\n'
        '        if close < 0:\n'
        '            raise HTTPException(status_code=409, detail="Existing VANTEX proposal is malformed; no file changed.")\n'
        '        end = close + 2\n'
        '        proposed = original[:start] + new_block + original[end:]\n'
        '    else:\n'
        '        proposed = original.rstrip() + "\\n\\n" + new_block + "\\n"\n',
        "replace-or-append proposal block",
    )

    # The preview computes which of pure white or near-black contrasts better
    # with the nearest solid ancestor background, then passes that choice to the proposal endpoint.
    backend_new = replace_once(
        backend_new,
        '            before_png = await page.screenshot(type="png", full_page=False)\n'
        '            if request.fix_kind == "accessibility":\n',
        '            before_png = await page.screenshot(type="png", full_page=False)\n'
        '            contrast_color = "#ffffff"\n'
        '            if request.fix_kind == "contrast":\n'
        '                contrast_color = await chosen.evaluate("""el => {\n'
        '                  const lum = rgb => {\n'
        '                    const c = rgb.map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });\n'
        '                    return 0.2126*c[0] + 0.7152*c[1] + 0.0722*c[2];\n'
        '                  };\n'
        '                  let node = el, bg = [255,255,255];\n'
        '                  while (node && node.nodeType === 1) {\n'
        '                    const s = getComputedStyle(node), m = s.backgroundColor.match(/rgba?\\((\\d+)[, ]+\\s*(\\d+)[, ]+\\s*(\\d+)/i);\n'
        '                    if (m && !(s.backgroundColor.includes("0)") || s.backgroundColor.includes("/ 0)"))) { bg = [+m[1],+m[2],+m[3]]; break; }\n'
        '                    node = node.parentElement;\n'
        '                  }\n'
        '                  const l = lum(bg), white = 1.05/(l+0.05), dark = (l+0.05)/(0.006+0.05);\n'
        '                  return white >= dark ? "#ffffff" : "#111827";\n'
        '                }""")\n'
        '            if request.fix_kind == "accessibility":\n',
        "preview contrast color calculation",
    )
    backend_new = replace_once(
        backend_new,
        '                "preview_declarations": preview_declarations,\n'
        '                "before_image": "data:image/png;base64," + base64.b64encode(before_png).decode("ascii"),\n',
        '                "preview_declarations": preview_declarations,\n'
        '                "contrast_color": contrast_color,\n'
        '                "before_image": "data:image/png;base64," + base64.b64encode(before_png).decode("ascii"),\n',
        "preview response contrast color",
    )

    frontend_new = replace_once(
        frontend_new,
        'body: JSON.stringify({ element: visualData.unique_selector, evidence, category, fix_kind: fixKind, accessibility_label: accessibilityLabel.trim() }),',
        'body: JSON.stringify({ element: visualData.unique_selector, evidence, category, fix_kind: fixKind, accessibility_label: accessibilityLabel.trim(), contrast_color: visualData.contrast_color === "#111827" ? "#111827" : "#ffffff" }),',
        "frontend proposal request",
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backend_backup = BACKEND.with_suffix(f".py.bak-contrast-{stamp}")
    frontend_backup = FRONTEND.with_suffix(f".tsx.bak-contrast-{stamp}")
    shutil.copy2(BACKEND, backend_backup)
    shutil.copy2(FRONTEND, frontend_backup)

    try:
        BACKEND.write_text(backend_new, encoding="utf-8")
        FRONTEND.write_text(frontend_new, encoding="utf-8")
        py_compile.compile(str(BACKEND), doraise=True)
    except Exception:
        BACKEND.write_text(backend, encoding="utf-8")
        FRONTEND.write_text(frontend, encoding="utf-8")
        raise

    print("VANTEX contrast proposal patch applied.")
    print(f"Backend backup: {backend_backup}")
    print(f"Frontend backup: {frontend_backup}")
    print("Python syntax check passed. Frontend build has NOT been run by this script.")
    print("Next: restart FastAPI, run `cd ~/Desktop/VANTEX/apps/web && npm run build`, then rerun Website QA.")

if __name__ == "__main__":
    main()
