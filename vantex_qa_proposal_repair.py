#!/usr/bin/env python3
"""Repair VANTEX QA proposal flow for unlabeled inputs and Tailwind contrast selectors.
Creates backups, checks exact anchors, and never applies a proposal to project files itself.
"""
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
if 'VANTEX_QA_PROPOSAL_REPAIR_V1' in b and 'VANTEX_QA_PROPOSAL_REPAIR_V1' in f:
    raise SystemExit('This QA proposal repair is already applied; no files changed.')
if 'def _prepare_accessibility_input_edit' not in b or 'fix_kind: str = Field(default="typography"' not in b:
    raise SystemExit('Expected the existing multi-fix/accessibility backend. No files changed.')
if 'const fixKind =' not in f or "'accessibility'" not in f or 'async function requestPreview' not in f:
    raise SystemExit('Expected the current QA fix UI. No files changed.')

# 1) Allow a user-supplied accessible name when the source input has no meaningful placeholder/name/type.
old = '    fix_kind: str = Field(default="typography", max_length=30)\n'
new = old + '    accessibility_label: str = Field(default="", max_length=120)\n'
if b.count(old) < 1:
    raise SystemExit('Could not find UIFixRequest fix_kind field. No files changed.')
b = b.replace(old, new, 1)

old = 'def _prepare_accessibility_input_edit(project_root: Path, selector: str):'
new = 'def _prepare_accessibility_input_edit(project_root: Path, selector: str, requested_label: str = ""): '
if b.count(old) != 1:
    raise SystemExit('Could not find accessibility helper signature. No files changed.')
b = b.replace(old, new.rstrip(), 1)
old = '''                if not label:
                    continue
                matches.append((candidate.resolve(), content, tag_match.start(), tag_match.end(), tag, label))'''
new = '''                if not label:
                    label = requested_label.strip()
                if not label:
                    # Keep this input out of automatic edits unless the user supplies a meaningful label.
                    continue
                matches.append((candidate.resolve(), content, tag_match.start(), tag_match.end(), tag, label))'''
if b.count(old) != 1:
    raise SystemExit('Could not find input-label fallback block. No files changed.')
b = b.replace(old, new, 1)
old = '        return _prepare_accessibility_input_edit(project_root, selector)'
new = '        return _prepare_accessibility_input_edit(project_root, selector, request.accessibility_label)'
if b.count(old) != 1:
    raise SystemExit('Could not find accessibility helper call. No files changed.')
b = b.replace(old, new, 1)

# 2) Recursively locate a real source stylesheet when selector-token matching and common root paths fail.
old = '''        target = next((project_root / rel for rel in fallbacks if (project_root / rel).is_file()), None)
        if target is None:
            raise HTTPException(status_code=404, detail="No existing stylesheet could be mapped in selected project. No file changed.")
        target = target.resolve(strict=True)'''
new = '''        target = next((project_root / rel for rel in fallbacks if (project_root / rel).is_file()), None)
        if target is None:
            # Tailwind utility classes usually do not exist as selectors in source CSS.
            # Find an existing source stylesheet recursively; never use dist/build output.
            recursive_css = []
            skip_css_dirs = set(PROJECT_SKIP_DIRS) | {"dist", "build", ".next", ".git", "coverage"}
            for current, dirs, filenames in os.walk(project_root, followlinks=False):
                dirs[:] = [d for d in dirs if d not in skip_css_dirs and not (Path(current) / d).is_symlink()]
                for filename in filenames:
                    candidate = Path(current) / filename
                    if candidate.suffix.lower() not in {".css", ".scss", ".sass", ".less"} or candidate.is_symlink():
                        continue
                    try:
                        if candidate.stat().st_size <= 1_000_000:
                            recursive_css.append(candidate.resolve())
                    except OSError:
                        continue
                if len(recursive_css) >= 80:
                    break
            preferred = {"globals.css": 0, "global.css": 1, "index.css": 2, "app.css": 3, "home.css": 4, "style.css": 5, "styles.css": 6}
            recursive_css.sort(key=lambda p: (preferred.get(p.name.lower(), 20), len(p.parts), str(p)))
            target = recursive_css[0] if recursive_css else None
        if target is None:
            raise HTTPException(status_code=404, detail="No source stylesheet exists in the selected project. Select the actual frontend project folder; no file changed.")
        target = target.resolve(strict=True)'''
if b.count(old) != 1:
    raise SystemExit('Could not find stylesheet fallback block. No files changed.')
b = b.replace(old, new, 1)

# Escape Tailwind variant colons in a CSS selector before writing it into a stylesheet.
old = '''    declaration_text = "\\n".join(f"    {name}: {value} !important;" for name, value in declarations.items())
    proposed = original.rstrip() + "\\n\\n" + marker + "\\n" + selector + " {\\n" + declaration_text + "\\n}\\n"'''
new = '''    declaration_text = "\\n".join(f"    {name}: {value} !important;" for name, value in declarations.items())
    # VANTEX_QA_PROPOSAL_REPAIR_V1: escape Tailwind variant colons in class selectors.
    css_selector = re.sub(
        r"\\.([A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)+)",
        lambda m: "." + m.group(1).replace(":", r"\\:"),
        selector,
    )
    proposed = original.rstrip() + "\\n\\n" + marker + "\\n" + css_selector + " {\\n" + declaration_text + "\\n}\\n"'''
if b.count(old) != 1:
    raise SystemExit('Could not find CSS proposal generation block. No files changed.')
b = b.replace(old, new, 1)
# marker currently only prevents duplicate exact marker; improve message to identify existing proposal.

# 3) Frontend: manual accessible-name input and a button to prepare a source-code diff after preview.
old = "  const [message, setMessage] = useState('');\n"
new = old + "  const [accessibilityLabel, setAccessibilityLabel] = useState('');\n"
if f.count(old) != 1:
    raise SystemExit('Could not find frontend message state. No files changed.')
f = f.replace(old, new, 1)

# Include user-provided label in initial proposal request (empty is okay; backend will ask for one via error).
old = 'body: JSON.stringify({ element: visualData.unique_selector, evidence, category, fix_kind: fixKind }),'
new = 'body: JSON.stringify({ element: visualData.unique_selector, evidence, category, fix_kind: fixKind, accessibility_label: accessibilityLabel.trim() }),'
if f.count(old) != 1:
    raise SystemExit('Could not find prepare-ui-fix request body. No files changed.')
f = f.replace(old, new, 1)

# Add a dedicated manual proposal function after requestPreview.
anchor = '''    setProposal(proposalObject);
    setMessage('Preview ready. The CSS proposal targets this exact element; source is unchanged.');
  }

  async function prepareFix() {'''
insert = '''    setProposal(proposalObject);
    setMessage('Preview ready. Review the proposed source change before applying.');
  }

  async function prepareAccessibilityProposal() {
    const label = accessibilityLabel.trim();
    if (!label) {
      setMessage('Enter a meaningful name for this input, such as “Email address” or “Search destinations”.');
      return;
    }
    if (!visualPreview || typeof visualPreview.unique_selector !== 'string') {
      setMessage('Generate the browser preview first.');
      return;
    }
    setBusy(true);
    setMessage('Preparing source-code proposal…');
    try {
      const proposalData = await requestJSON(`${API}/api/agent/qa/prepare-ui-fix`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          element: String(visualPreview.unique_selector), evidence, category, fix_kind: 'accessibility',
          accessibility_label: label,
        }),
      });
      const proposalObject = asObject(proposalData);
      if (!proposalObject || typeof proposalObject.proposal_id !== 'string') {
        throw new Error(getResultMessage(proposalData, 'Could not prepare the source-code proposal.'));
      }
      setProposal(proposalObject);
      setMessage('Source-code proposal ready. Review the diff before applying.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not prepare the accessibility proposal.');
    } finally {
      setBusy(false);
    }
  }

  async function prepareFix() {'''
if f.count(anchor) != 1:
    raise SystemExit('Could not find requestPreview end anchor. No files changed.')
f = f.replace(anchor, insert, 1)

# Add accessible-name editor when an input preview exists but proposal has not been made.
anchor = '''          <div className="qa-visual-grid">
            <div><strong>Before</strong><img src={String(visualPreview.before_image)} alt="Website before the proposed fix" /></div>
            <div><strong>After</strong><img src={String(visualPreview.after_image)} alt={fixKind === 'accessibility' ? "Website after temporary accessibility preview; visual appearance may be unchanged" : `Website after temporary ${fixKind} preview`} /></div>
          </div>
          {proposal && ('''
insert = '''          <div className="qa-visual-grid">
            <div><strong>Before</strong><img src={String(visualPreview.before_image)} alt="Website before the proposed fix" /></div>
            <div><strong>After</strong><img src={String(visualPreview.after_image)} alt={fixKind === 'accessibility' ? "Website after temporary accessibility preview; visual appearance may be unchanged" : `Website after temporary ${fixKind} preview`} /></div>
          </div>
          {fixKind === 'accessibility' && !proposal && (
            <div className="qa-fix-preview">
              <label htmlFor={`qa-accessible-name-${String(issue.element ?? 'input').replace(/[^a-zA-Z0-9_-]/g, '-')}`}>
                Accessible name for this input
              </label>
              <input
                id={`qa-accessible-name-${String(issue.element ?? 'input').replace(/[^a-zA-Z0-9_-]/g, '-')}`}
                type="text"
                value={accessibilityLabel}
                onChange={(event) => setAccessibilityLabel(event.target.value)}
                placeholder="e.g. Email address"
                maxLength={120}
              />
              <p>Use the input’s real purpose. This creates a source-code diff; it does not change the source until you approve it.</p>
              <button type="button" className="qa-fix-button" onClick={prepareAccessibilityProposal} disabled={busy || !accessibilityLabel.trim()}>
                {busy ? 'Preparing…' : 'Prepare code change'}
              </button>
            </div>
          )}
          {proposal && ('''
if f.count(anchor) != 1:
    raise SystemExit('Could not find preview render anchor. No files changed.')
f = f.replace(anchor, insert, 1)
# Show a generic source proposal heading instead of implying every proposal is CSS.
f = f.replace('<strong>Proposed CSS change</strong>', '<strong>{fixKind === \'accessibility\' ? \'Proposed source-code change\' : \'Proposed CSS change\'}</strong>')
f = f.replace('The proposal uses the unique selector returned for the element shown in this preview. Review the diff before applying.', 'Review the source diff and confirm it targets the intended element before applying.')

# marker for idempotence
b = b.replace('# VANTEX_ACCESSIBILITY_FIX_V1', '# VANTEX_ACCESSIBILITY_FIX_V1\n# VANTEX_QA_PROPOSAL_REPAIR_V1', 1)
f = f.replace('function AuditFixAction({', '// VANTEX_QA_PROPOSAL_REPAIR_V1\nfunction AuditFixAction({', 1)

# Create backups only after all anchors pass; validate Python syntax before writes.
ts = datetime.now().strftime('%Y%m%d-%H%M%S')
bak_b = BACKEND.with_name(BACKEND.name + f'.before_qa_proposal_repair_{ts}')
bak_f = FRONTEND.with_name(FRONTEND.name + f'.before_qa_proposal_repair_{ts}')
shutil.copy2(BACKEND, bak_b)
shutil.copy2(FRONTEND, bak_f)
try:
    ast.parse(b)
    BACKEND.write_text(b, encoding='utf-8')
    FRONTEND.write_text(f, encoding='utf-8')
    ast.parse(BACKEND.read_text(encoding='utf-8'))
except Exception:
    shutil.copy2(bak_b, BACKEND)
    shutil.copy2(bak_f, FRONTEND)
    raise
print('VANTEX QA proposal repair applied.')
print(f'Backend backup: {bak_b}')
print(f'Frontend backup: {bak_f}')
print('Python syntax check: PASSED')
print('Added: manual accessible-name input + source proposal button; recursive stylesheet fallback; escaped Tailwind variant selectors.')
print('Next: restart FastAPI, then run npm run build.')
