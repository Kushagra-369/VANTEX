#!/usr/bin/env python3
"""Safely add plain-English explanations to VANTEX UI audit findings."""
from pathlib import Path
from datetime import datetime
import shutil
import sys

project = Path.home() / "Desktop/VANTEX"
target = project / "apps/web/src/components/Home/Home.tsx"
if not target.exists():
    print(f"Could not find project file: {target}")
    sys.exit(1)
source = target.read_text(encoding="utf-8")
marker = "// VANTEX_QA_PLAIN_ENGLISH_V1"
component_anchor = "// VANTEX_QA_PROPOSAL_REPAIR_V1\nfunction AuditFixAction"
render_anchor = "                                        <AuditFixAction\n"
if marker in source:
    print("Patch already installed. No files changed.")
    sys.exit(0)
if source.count(component_anchor) != 1 or source.count(render_anchor) != 1:
    print(f"Expected component anchor={1}, found {source.count(component_anchor)}; render anchor={1}, found {source.count(render_anchor)}. No files changed.")
    sys.exit(1)

helper = '''// VANTEX_QA_PLAIN_ENGLISH_V1
function getPlainEnglishQA(issue: Record<string, unknown>) {
  const category = String(issue.category ?? '').toLowerCase();
  const evidence = String(issue.evidence ?? '').toLowerCase();
  const recommendation = String(issue.recommendation ?? '').trim();
  const element = String(issue.element ?? '').toLowerCase();

  if ((evidence.includes('accessible name') || evidence.includes('associated label') || evidence.includes('aria naming')) && element.startsWith('input')) {
    return {
      title: 'The input field needs a clear name',
      what: 'A screen reader may not be able to tell users what this field is for.',
      why: 'People using assistive technology need a label such as Email address or Search.',
      change: 'Add a visible label, or give the field an appropriate accessible name.',
      before: 'The field may be announced without a useful name.',
      after: 'The field is announced with a clear purpose.'
    };
  }
  if (category.includes('color') && (evidence.includes('contrast') || evidence.includes('readability'))) {
    return {
      title: 'The text may be difficult to read',
      what: 'The text colour and background colour may be too similar.',
      why: 'Low contrast makes text harder to read, especially for people with low vision or on dim screens.',
      change: recommendation || 'Choose a text colour that stands out more clearly from the background.',
      before: 'Text blends into the background.',
      after: 'Text stands out clearly against the background.'
    };
  }
  if (category.includes('typography') && (evidence.includes('content width') || evidence.includes('overflow'))) {
    return {
      title: 'The content may not fit its space',
      what: 'Text or an element may be wider than the area available to it.',
      why: 'This can cause awkward wrapping, clipping, or horizontal scrolling on smaller screens.',
      change: recommendation || 'Adjust the width or responsive layout so the content fits its container.',
      before: 'Content may spill outside its intended area.',
      after: 'Content fits the available space at the checked screen size.'
    };
  }
  if (category.includes('typography') && (evidence.includes('px') || evidence.includes('font size'))) {
    return {
      title: 'The text size may be too small',
      what: 'Some text may be difficult to read at its current size.',
      why: 'Small text can strain readers and be especially difficult on phones or for people with low vision.',
      change: recommendation || 'Increase the text size where needed while keeping the layout readable.',
      before: 'Text may be too small to read comfortably.',
      after: 'Text is easier to read without breaking the layout.'
    };
  }
  return {
    title: 'Review this possible issue',
    what: recommendation || 'The automated check found something that may need attention.',
    why: 'Automated checks can flag potential problems, so confirm the issue on the actual page before editing.',
    change: recommendation || 'Inspect the affected part of the page and decide whether a change is needed.',
    before: 'The current page state; the check alone has not confirmed a defect.',
    after: 'The expected improvement after a suitable change; verify it by retesting.'
  };
}

'''
render = '''                                        {(() => {
                                          const explanation = getPlainEnglishQA(issue);
                                          return (
                                            <div className="qa-plain-english" aria-label="Plain-English explanation">
                                              <h5>In plain English: {explanation.title}</h5>
                                              <p><strong>What this means:</strong> {explanation.what}</p>
                                              <p><strong>Why it matters:</strong> {explanation.why}</p>
                                              <p><strong>What to change:</strong> {explanation.change}</p>
                                              <div className="qa-plain-english-before-after">
                                                <p><strong>Before:</strong> {explanation.before}</p>
                                                <p><strong>Expected after:</strong> {explanation.after}</p>
                                              </div>
                                              <p className="qa-plain-english-status"><strong>Status:</strong> A recommendation is not proof that a change was applied. Approve a supported fix, then retest and review the new report to verify it.</p>
                                            </div>
                                          );
                                        })()}

'''
source = source.replace(component_anchor, helper + component_anchor, 1)
source = source.replace(render_anchor, render + render_anchor, 1)
backup = target.with_name(target.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
shutil.copy2(target, backup)
target.write_text(source, encoding="utf-8")
print("Patch applied successfully.")
print(f"Updated: {target}")
print(f"Backup:  {backup}")
print("Next: cd ~/Desktop/VANTEX/apps/web && npm run build")
