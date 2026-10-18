#!/usr/bin/env python3
"""Repair VANTEX QA selector handling for Tailwind variants; preserves backups."""
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
if 'VANTEX_SELECTOR_ESCAPE_V1' in b:
    raise SystemExit('Selector escape repair already applied; no files changed.')
anchor = '    selector = request.selector.strip()\n    if (not selector or len(selector) > 500 or\n        not re.fullmatch(r"[A-Za-z0-9_.*#:\\-\\[\\]=\\\"\' >+~(),]+", selector)):'
if b.count(anchor) != 1:
    raise SystemExit('Could not find the expected visual_preview selector validation block. No files changed.')
replacement = '''    selector = request.selector.strip()
    if (not selector or len(selector) > 500 or
        not re.fullmatch(r"[A-Za-z0-9_.*#:\\-\\[\\]=\\\"' >+~(),]+", selector)):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")

    # VANTEX_SELECTOR_ESCAPE_V1: Tailwind variant colons inside class names
    # must be escaped for querySelectorAll (e.g. .md:text-5xl -> .md\\:text-5xl).
    # Only escape colons that appear in a dot-prefixed class token, not pseudo-selectors.
    selector = re.sub(
        r"\\.([A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)+)",
        lambda match: "." + match.group(1).replace(":", r"\\:"),
        selector,
    )'''
# anchor includes validation's first line but not the HTTPException line; replace carefully through exact known block
old = '''    selector = request.selector.strip()
    if (not selector or len(selector) > 500 or
        not re.fullmatch(r"[A-Za-z0-9_.*#:\\-\\[\\]=\\\"' >+~(),]+", selector)):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")'''
if b.count(old) != 1:
    raise SystemExit('Could not locate the complete selector validation block. No files changed.')
new = '''    selector = request.selector.strip()
    if (not selector or len(selector) > 500 or
        not re.fullmatch(r"[A-Za-z0-9_.*#:\\-\\[\\]=\\\"' >+~(),]+", selector)):
        raise HTTPException(status_code=400, detail="Unsupported CSS selector.")

    # VANTEX_SELECTOR_ESCAPE_V1: Tailwind variant colons inside class names
    # must be escaped for querySelectorAll (e.g. .md:text-5xl -> .md\\:text-5xl).
    # Only escape colons that appear in a dot-prefixed class token, not pseudo-selectors.
    selector = re.sub(
        r"\\.([A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)+)",
        lambda match: "." + match.group(1).replace(":", r"\\:"),
        selector,
    )'''
b = b.replace(old, new, 1)
# Validate the frontend still includes the multi-fix classification and accessible-name route.
if 'isMissingInputName' not in f or "'accessibility'" not in f:
    raise SystemExit('Frontend accessibility classification is missing; no files changed. Reapply the accessibility patch and restart backend.')
ts = datetime.now().strftime('%Y%m%d-%H%M%S')
bak = BACKEND.with_name(BACKEND.name + f'.before_selector_repair_{ts}')
shutil.copy2(BACKEND, bak)
try:
    ast.parse(b)
    BACKEND.write_text(b, encoding='utf-8')
    ast.parse(BACKEND.read_text(encoding='utf-8'))
except Exception:
    shutil.copy2(bak, BACKEND)
    raise
print('VANTEX selector repair applied.')
print(f'Backend backup: {bak}')
print('Python syntax check: PASSED')
print('Next: restart FastAPI backend, then test the contrast finding again.')
