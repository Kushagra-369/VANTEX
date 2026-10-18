#!/usr/bin/env python3
"""Add plain-English explanations to VANTEX Website QA fix cards.
Creates a timestamped backup and refuses to patch if expected code anchors differ.
"""
from pathlib import Path
from datetime import datetime
import shutil, sys, re

ROOT = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.home() / "Desktop" / "VANTEX"
FILE = ROOT / "apps/web/src/components/Home/Home.tsx"
if not FILE.is_file():
    raise SystemExit(f"File not found: {FILE}. No files changed.")
s = FILE.read_text(encoding="utf-8")
MARK = "VANTEX_PLAIN_ENGLISH_QA_V1"
if MARK in s:
    raise SystemExit("Plain-English QA patch is already present. No files changed.")

# Add a helper before AuditFixAction.
anchor = "function AuditFixAction({"
helper = r'''// VANTEX_PLAIN_ENGLISH_QA_V1
function getPlainEnglishQA(issue: Record<string, unknown>, fixKind: string) {
  const category = String(issue.category ?? 'Website quality');
  const evidence = String(issue.evidence ?? '').toLowerCase();
  const element = String(issue.element ?? 'the affected element');

  if (category.toLowerCase().includes('accessibility') || evidence.includes('accessible name') || evidence.includes('associated label')) {
    return {
      title: 'Give this field a clear name',
      what: 'This input field does not have a name that assistive technology can reliably read.',
      change: 'Add a meaningful label or aria-label that describes what the user should enter. The field design and behaviour should stay the same.',
      why: 'Screen readers need a name to explain the purpose of the field to people who cannot see the screen.',
      from: 'An input field with no accessible name',
      to: 'The same input field with a meaningful accessible name',
    };
  }
  if (category.toLowerCase().includes('contrast') || evidence.includes('contrast')) {
    return {
      title: 'Make the text easier to read',
      what: 'The text and its background appear too similar in colour.',
      change: 'Adjust the text colour to improve readability while keeping the existing layout and wording.',
      why: 'Stronger contrast helps more people read the text, including people with low vision.',
      from: 'Text with low contrast against its background',
      to: 'Text with a more readable foreground colour',
    };
  }
  if (fixKind === 'overflow' || evidence.includes('content width')) {
    return {
      title: 'Keep content inside the screen',
      what: 'This element may extend beyond the visible page width.',
      change: 'Adjust the element sizing so it fits the viewport without introducing horizontal scrolling.',
      why: 'People should be able to read and use the page on mobile, tablet, and desktop.',
      from: 'Content extending past the viewport',
      to: 'Content fitting within the viewport',
    };
  }
  if (fixKind === 'typography' || evidence.includes('text is')) {
    return {
      title: 'Make the text readable',
      what: 'The detected text is unusually small.',
      change: 'Increase the text size for the affected element. Review the preview to make sure it still fits the design.',
      why: 'Readable text is easier to scan and use, especially on smaller screens.',
      from: 'Very small text',
      to: 'Larger, easier-to-read text',
    };
  }
  return {
    title: 'Review this website issue',
    what: String(issue.recommendation ?? issue.message ?? 'VANTEX detected a possible website quality issue.'),
    change: 'Review the proposed code diff before applying it. Only apply the change if it matches the intended design and behaviour.',
    why: 'This explains the likely user impact without claiming that a fix has already been verified.',
    from: 'Current website behaviour',
    to: 'The behaviour shown in the proposed change preview',
  };
}

'''
if s.count(anchor) != 1:
    raise SystemExit(f"Expected one AuditFixAction anchor, found {s.count(anchor)}. No files changed.")
s = s.replace(anchor, helper + anchor, 1)

# Add a plain-English summary inside the fix action component.
anchor2 = "  const supported = fixKind !== '';\n"
insert2 = anchor2 + "  const plainEnglish = getPlainEnglishQA(issue, fixKind);\n"
if s.count(anchor2) != 1:
    raise SystemExit(f"Expected one supported flag anchor, found {s.count(anchor2)}. No files changed.")
s = s.replace(anchor2, insert2, 1)

# Insert UI after the component's outer return wrapper, using a stable unique class anchor.
anchor3 = '    <div className="qa-fix-action">\n'
ui = '''    <div className="qa-fix-action">\n      <section className="qa-plain-english" aria-label="Plain-English explanation">\n        <h4>{plainEnglish.title}</h4>\n        <p><strong>What needs attention:</strong> {plainEnglish.what}</p>\n        <p><strong>What would change:</strong> {plainEnglish.change}</p>\n        <p><strong>Why it matters:</strong> {plainEnglish.why}</p>\n        <div className="qa-plain-english-diff">\n          <div><strong>Before</strong><p>{plainEnglish.from}</p></div>\n          <div><strong>After</strong><p>{plainEnglish.to}</p></div>\n        </div>\n        <p className="qa-fix-caution">Status: {applied ? 'Applied — run QA again to verify the result.' : proposal ? 'Proposed only — the original source is unchanged until you approve it.' : 'Not applied — no source files have been changed.'}</p>\n        {proposal && Array.isArray(proposal.diff) && (\n          <details className="qa-plain-english-code">\n            <summary>View exact code changes</summary>\n            <pre>{proposal.diff.map(String).join('\\n')}</pre>\n          </details>\n        )}\n      </section>\n'''
if s.count(anchor3) != 1:
    raise SystemExit(f"Expected one qa-fix-action wrapper anchor, found {s.count(anchor3)}. No files changed.")
s = s.replace(anchor3, ui, 1)

# Add minimal styles in Home.css if it exists, otherwise use existing classes with no CSS edits.
css = ROOT / "apps/web/src/components/Home/Home.css"
css_new = None
if css.is_file():
    c = css.read_text(encoding="utf-8")
    css_mark = "/* VANTEX_PLAIN_ENGLISH_QA_V1 */"
    if css_mark not in c:
        css_new = c.rstrip() + '''\n\n/* VANTEX_PLAIN_ENGLISH_QA_V1 */\n.qa-plain-english { margin: 1rem 0; padding: 1rem; border: 1px solid rgba(128, 128, 128, .35); border-radius: 14px; }\n.qa-plain-english h4 { margin: 0 0 .75rem; }\n.qa-plain-english p { margin: .5rem 0; line-height: 1.55; }\n.qa-plain-english-diff { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; margin-top: .8rem; }\n.qa-plain-english-diff > div { padding: .75rem; border-radius: 10px; background: rgba(128, 128, 128, .09); }\n.qa-plain-english-diff p { margin-bottom: 0; }\n.qa-plain-english-code { margin-top: .75rem; }\n.qa-plain-english-code pre { max-width: 100%; overflow: auto; }\n@media (max-width: 600px) { .qa-plain-english-diff { grid-template-columns: 1fr; } }\n'''

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_tsx = FILE.with_name(FILE.name + f".bak-plain-english-{stamp}")
shutil.copy2(FILE, backup_tsx)
backup_css = None
if css_new is not None:
    backup_css = css.with_name(css.name + f".bak-plain-english-{stamp}")
    shutil.copy2(css, backup_css)
try:
    FILE.write_text(s, encoding="utf-8")
    if css_new is not None:
        css.write_text(css_new, encoding="utf-8")
except Exception:
    shutil.copy2(backup_tsx, FILE)
    if backup_css and backup_css.exists():
        shutil.copy2(backup_css, css)
    raise
print("Plain-English QA explanations added.")
print(f"Frontend backup: {backup_tsx}")
if backup_css:
    print(f"CSS backup: {backup_css}")
print("Next: cd ~/Desktop/VANTEX/apps/web && npm run build")
