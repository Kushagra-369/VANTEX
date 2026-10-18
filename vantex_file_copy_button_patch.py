#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import shutil
import sys

target = Path.home() / "Desktop/VANTEX/apps/web/src/components/Home/Home.tsx"
if not target.exists():
    print(f"ERROR: File not found: {target}")
    sys.exit(1)

source = target.read_text(encoding="utf-8")

state_anchor = """}: {
  files: FileItem[];
  onOpen: (file: FileItem) => void;
  openingPath: string;
}) {
  if (!files.length) {"""

state_replacement = """}: {
  files: FileItem[];
  onOpen: (file: FileItem) => void;
  openingPath: string;
}) {
  const [copiedPath, setCopiedPath] = useState('');

  async function copyFilePath(path: string) {
    try {
      await navigator.clipboard.writeText(path);
      setCopiedPath(path);
      window.setTimeout(() => {
        setCopiedPath(current => current === path ? '' : current);
      }, 1800);
    } catch {
      // Clipboard access can be blocked by browser permissions.
      setCopiedPath('');
    }
  }

  if (!files.length) {"""

button_anchor = """          <button
            className="file-open-button"
            type="button"
            onClick={() => onOpen(file)}
            disabled={openingPath === file.path}
          >
            {openingPath === file.path ? 'Opening…' : 'Open'}
            {openingPath !== file.path && (
              <Icon name="external" size={15} />
            )}
          </button>"""

button_replacement = """          <div className="file-result-actions">
            <button
              className="file-open-button"
              type="button"
              onClick={() => onOpen(file)}
              disabled={openingPath === file.path}
            >
              {openingPath === file.path ? 'Opening…' : 'Open'}
              {openingPath !== file.path && (
                <Icon name="external" size={15} />
              )}
            </button>
            <button
              className="file-copy-button"
              type="button"
              onClick={() => void copyFilePath(file.path)}
              aria-label={`Copy path for ${file.name}`}
              title="Copy full file path"
            >
              {copiedPath === file.path ? 'Copied!' : 'Copy'}
            </button>
          </div>"""

if "const [copiedPath, setCopiedPath] = useState('');" in source:
    print("Already patched: Copy button is already present. No files changed.")
    sys.exit(0)

if source.count(state_anchor) != 1:
    print(f"ERROR: Expected one FileResults state anchor, found {source.count(state_anchor)}. No files changed.")
    sys.exit(1)

if source.count(button_anchor) != 1:
    print(f"ERROR: Expected one Open button block, found {source.count(button_anchor)}. No files changed.")
    sys.exit(1)

backup = target.with_name(f"{target.name}.backup-copy-button-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
shutil.copy2(target, backup)
updated = source.replace(state_anchor, state_replacement, 1).replace(button_anchor, button_replacement, 1)
target.write_text(updated, encoding="utf-8")
print("SUCCESS: Added a Copy button beside Open. It copies the full file path.")
print(f"Backup: {backup}")
print("Note: If clipboard permission is blocked by the browser, Copy may not work until clipboard access is allowed.")
