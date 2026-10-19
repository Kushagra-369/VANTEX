import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import './Home.css';

let kokoroPromise: Promise<any> | null = null;

function getKokoro() {
  if (!kokoroPromise) {
    kokoroPromise = import('kokoro-js')
      .then(({ KokoroTTS }) =>
        KokoroTTS.from_pretrained(
          'onnx-community/Kokoro-82M-v1.0-ONNX',
          {
            dtype: 'q8',
            device: 'wasm',
          },
        ),
      )
      .catch((error) => {
        kokoroPromise = null;
        throw error;
      });
  }

  return kokoroPromise;
}

const API = import.meta.env.PROD
  ? 'https://vantex-2d4l.onrender.com'
  : 'http://127.0.0.1:8000';

type FileItem = {
  name: string;
  path: string;
  type?: string;
  preview?: string;
};

type ResultData = {
  title: string;
  message: string;
  details?: string;
  files?: FileItem[];
  data?: unknown;
};

type HomeProps = {
  onOpenIntelligence?: () => void;
};

function asObject(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }

  return null;
}

function getMessage(value: unknown, fallback = 'Request completed.'): string {
  const obj = asObject(value);

  if (!obj) {
    return typeof value === 'string' ? value : fallback;
  }

  const message =
    obj.message ??
    obj.detail ??
    obj.output ??
    obj.result ??
    obj.status ??
    obj.description;

  if (typeof message === 'string') {
    return message;
  }

  if (message && typeof message === 'object') {
    return getMessage(message, fallback);
  }

  return fallback;
}

function findFileItems(value: unknown, depth = 0): FileItem[] {
  if (depth > 5 || value == null) {
    return [];
  }

  if (Array.isArray(value)) {
    return value
      .map((item): FileItem | null => {
        if (typeof item === 'string') {
          return {
            name: item.split('/').pop() || item,
            path: item,
          };
        }

        const obj = asObject(item);

        if (!obj) {
          return null;
        }

        const path = [
          obj.path,
          obj.full_path,
          obj.absolute_path,
          obj.file_path,
          obj.location,
        ].find((entry): entry is string => typeof entry === 'string');

        const name = [
          obj.name,
          obj.filename,
          obj.file_name,
        ].find((entry): entry is string => typeof entry === 'string');

        if (!path && !name) {
          return null;
        }

        const finalPath = path || name || '';

        return {
          name: name || finalPath.split('/').pop() || finalPath,
          path: finalPath,
          type:
            typeof obj.type === 'string'
              ? obj.type
              : typeof obj.kind === 'string'
                ? obj.kind
                : undefined,
          preview:
            typeof obj.preview === 'string'
              ? obj.preview
              : typeof obj.snippet === 'string'
                ? obj.snippet
                : typeof obj.content_preview === 'string'
                  ? obj.content_preview
                  : undefined,
        };
      })
      .filter((item): item is FileItem => item !== null);
  }

  const obj = asObject(value);

  if (!obj) {
    return [];
  }

  for (const key of [
    'matches',
    'files',
    'items',
    'results',
    'entries',
    'data',
    'result',
  ]) {
    if (obj[key] !== undefined) {
      const found = findFileItems(obj[key], depth + 1);

      if (found.length) {
        return found;
      }
    }
  }

  return [];
}

function getHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function normalizeUrl(text: string): string | null {
  const match = text.match(
    /https?:\/\/[^\s"'<>]+|(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?:\/[^\s"'<>]*)?/i,
  );

  if (!match) {
    return null;
  }

  let url = match[0].replace(/[.,!?;]+$/, '');

  if (!/^https?:\/\//i.test(url)) {
    url = `https://${url}`;
  }

  try {
    return new URL(url).toString();
  } catch {
    return null;
  }
}



function detectIntent(input: string) {
  const text = input.trim();
  const url = normalizeUrl(text);

  // Navigate directly to PC Intelligence.
  if (
    /\b(pc intelligence|computer intelligence|system intelligence|open intelligence)\b/i.test(text)
  ) {
    return { type: 'intelligence' as const };
  }

  // Website testing, with or without a URL.
  if (
    /\b(test|check|qa|audit|inspect)\b/i.test(text) &&
    /\b(website|web site|webpage|web page|site|url)\b/i.test(text)
  ) {
    return {
      type: 'website' as const,
      url: url || '',
    };
  }

  // Also support a URL with a test/check command.
  if (/\b(test|check|qa|audit|inspect)\b/i.test(text) && url) {
    return { type: 'website' as const, url };
  }

  // PC/system information and hardware usage questions.
  if (
    /\b(pc status|system status|system info|system information|pc info|computer status|hardware status|show my pc|my system|cpu|processor|ram|memory usage|disk usage|disk space|storage space|free space|operating system|linux version|os version)\b/i.test(text)
  ) {
    return { type: 'system' as const };
  }

  // Explicit searches inside file contents.
  const contentPatterns = [
    /^(?:please\s+)?(?:search|find|look for)\s+(?:all\s+)?files?\s+(?:with|containing|that contain|mentioning)\s+(.+)$/i,
    /^(?:please\s+)?(?:search|find|look for)\s+(.+?)\s+files?\s+for\s+(.+)$/i,
    /^(?:please\s+)?(?:search|find|look for)\s+(?:the\s+)?(resumes?|cvs?)\s+for\s+(.+)$/i,
    /^(?:please\s+)?(?:search inside|search within|search content|find text)\s+(.+)$/i,
    /^(?:please\s+)?find text\s+(.+?)\s+inside files?$/i,
    /^(?:please\s+)?(?:find|search for)\s+(.+?)\s+in\s+(?:the\s+)?(?:file contents|file content|documents?)$/i,
  ];

  for (const pattern of contentPatterns) {
    if (pattern.test(text)) {
      return { type: 'content' as const, query: text };
    }
  }

  // Open/launch a file or folder.
  const isOpen =
    /^(?:please\s+)?(?:open|launch|show|khol|kholo|khul)\b/i.test(text) ||
    /\b(?:open|kholo|khol|khul)\s+(?:the\s+)?(?:file|folder)\b/i.test(text);

  if (isOpen) {
    const query = text
      .replace(/\b(open|launch|show|khol|kholo|khul)\b/gi, ' ')
      .replace(/\b(please|the|file|folder|kar|do|latest|last|newest|recent)\b/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    return { type: 'open' as const, query: query || text };
  }

  // General file-content search.
  if (
    /\b(search inside|search within|inside files|in file contents|search content|find text|find function|find code|search for|where is|look for)\b/i.test(text)
  ) {
    const query = text
      .replace(
        /^(please\s+)?(search inside|search within|inside files|in file contents|search content|find text|find function|find code|search for|find|where is|look for)\s*/i,
        '',
      )
      .replace(/\b(in my project|in the project|inside my project|inside the project|in files|inside files)\b/gi, '')
      .trim();

    return { type: 'content' as const, query: query || text };
  }


  // Filename/folder search, including Hindi and Hinglish.
  const isFileSearch =
    /\b(find|search|locate|list|show|dikha|dikhao|dikhaye|bata|batao|dhoondh|dhundh|dhundho|khoj|nikaal|nikal)\b/i.test(text) &&
    /\b(file|files|folder|folders|document|documents|resume|resumes|cv|cvs|pdf|python|javascript|typescript|css|html|json|tsx|ts|jsx|js|py|md)\b/i.test(text);

  if (isFileSearch) {
    const folderMatch = text.match(
      /\b(desktop|downloads|documents|pictures|videos)\b/i,
    );

    const typeMatch = text.match(
      /\b(python|javascript|typescript|css|html|json|pdf|markdown|text)\b/i,
    );

    const cleanedQuery = text
      .replace(
        /\b(please|bhai|mujhe|mera|meri|mere|saari|saare|sari|sare|sabhi|sab|all|my|the|for|find|search|locate|list|show|give|me|de|do|dikha|dikhao|dikhaye|bata|batao|dhoondh|dhundh|dhundho|khoj|nikaal|nikal|files|file|folders|folder|documents|document|desktop|downloads|pictures|videos|in|inside|from|on|my|pc|computer|laptop|wali|wala|wale|waali|waala|waale|please)\b/gi,
        ' ',
      )
      .replace(/\s+/g, ' ')
      .trim();

    const query = typeMatch
      ? typeMatch[1].toLowerCase()
      : cleanedQuery;

    return {
      type: 'files' as const,
      query: query || cleanedQuery || text,
      folder: folderMatch
        ? folderMatch[1].toLowerCase()
        : undefined,
    };
  }

  // Keep unsupported/other requests available to the local command handler.
  return { type: 'command' as const, command: text };
}



async function requestJSON(
  url: string,
  options?: RequestInit,
): Promise<unknown> {
  const response = await fetch(url, options);
  const text = await response.text();

  let body: unknown;

  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = text;
  }

  if (!response.ok) {
    throw new Error(
      getMessage(body, `Request failed (${response.status})`),
    );
  }

  return body;
}

function getResultMessage(value: unknown, fallback: string): string {
  const obj = asObject(value);

  if (!obj) {
    return typeof value === 'string' ? value : fallback;
  }

  const candidates = [
    obj.message,
    obj.detail,
    obj.output,
    obj.description,
    obj.status,
  ];

  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim()) {
      return candidate;
    }
  }

  return fallback;
}

function Icon({
  name,
  size = 20,
}: {
  name: 'spark' | 'search' | 'file' | 'external' | 'check' | 'monitor';
  size?: number;
}) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.7,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true as const,
  };

  const paths: Record<string, ReactNode> = {
    spark: (
      <>
        <path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-2-5.8L4 11l6-2.2L12 3Z" />
        <path d="m19 14 1.1 2.9L23 18l-2.9 1.1L19 22l-1.1-2.9L15 18l2.9-1.1L19 14Z" />
      </>
    ),
    search: (
      <>
        <circle cx="10.8" cy="10.8" r="6.8" />
        <path d="m16 16 4.5 4.5" />
      </>
    ),
    file: (
      <>
        <path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10Z" />
        <path d="M13 3v7h7M8 15h8M8 18h6" />
      </>
    ),
    external: (
      <>
        <path d="M14 4h6v6M20 4l-9 9" />
        <path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    monitor: (
      <>
        <rect x="3" y="4" width="18" height="13" rx="2" />
        <path d="M8 21h8M12 17v4" />
      </>
    ),
  };

  return <svg {...common}>{paths[name]}</svg>;
}


type ResponsiveCheck = {
  name: string;
  width: number;
  height: number;
  passed: boolean;
  horizontal_overflow: boolean;
  viewport_width: number;
  document_width: number;
  overflowing_elements: {
    element: string;
    left: number;
    right: number;
    width: number;
  }[];
};


// VANTEX_QA_PLAIN_ENGLISH_V1
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

// VANTEX_QA_PROPOSAL_REPAIR_V1
function AuditFixAction({
  issue,
  url,
}: {
  issue: Record<string, unknown>;
  url: string;
}) {
  const [proposal, setProposal] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(false);
  const [message, setMessage] = useState('');
  const [accessibilityLabel, setAccessibilityLabel] = useState('');
  const [visualCandidates, setVisualCandidates] = useState<Array<Record<string, unknown>>>([]);
  const [visualPreview, setVisualPreview] = useState<Record<string, unknown> | null>(null);
  const evidence = String(issue.evidence ?? '');
  const category = String(issue.category ?? '');
  const match = evidence.match(/Text is ([\d.]+)px/);
  const evidenceLower = evidence.toLowerCase();
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
  const supported = fixKind !== '';

  async function requestPreview(candidateIndex?: number) {
    const data = await requestJSON(`${API}/api/agent/qa/visual-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url,
        selector: String(issue.element ?? ''),
        font_size: 12,
        fix_kind: fixKind,
        ...(candidateIndex === undefined ? {} : { candidate_index: candidateIndex }),
      }),
    });
    const visualData = asObject(data);
    if (!visualData) throw new Error('Invalid visual preview response.');
    if (visualData.needs_selection === true && Array.isArray(visualData.candidates)) {
      setVisualCandidates(visualData.candidates.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object'));
      setVisualPreview(null);
      setProposal(null);
      setMessage(String(visualData.message ?? 'Choose the exact element to preview.'));
      return;
    }
    if (typeof visualData.before_image !== 'string' || typeof visualData.after_image !== 'string' || typeof visualData.unique_selector !== 'string') {
      throw new Error(String(visualData.detail ?? visualData.message ?? 'Could not generate a unique visual preview.'));
    }
    setVisualCandidates([]);
    setVisualPreview(visualData);
    // Prepare the actual CSS proposal only after the selected element has a unique preview selector.
    const proposalData = await requestJSON(`${API}/api/agent/qa/prepare-ui-fix`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ element: visualData.unique_selector, evidence, category, fix_kind: fixKind, accessibility_label: accessibilityLabel.trim(), contrast_color: visualData.contrast_color === "#111827" ? "#111827" : "#ffffff" }),
    });
    const proposalObject = asObject(proposalData);
    if (!proposalObject || typeof proposalObject.proposal_id !== 'string') {
      throw new Error(getResultMessage(proposalData, 'Could not prepare the CSS proposal.'));
    }
    setProposal(proposalObject);
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

  async function prepareFix() {
    if (!supported) {
      setMessage("This finding type is not supported for a proposed edit yet. No source was changed.");
      return;
    }
    setBusy(true);
    setMessage('');
    setVisualCandidates([]);
    setVisualPreview(null);
    setProposal(null);
    try {
      await requestPreview();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not prepare fix.');
    } finally {
      setBusy(false);
    }
  }

  async function chooseCandidate(index: number) {
    setBusy(true);
    setMessage('Generating preview for the selected element…');
    setProposal(null);
    setVisualPreview(null);
    try {
      await requestPreview(index);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not preview selected element.');
    } finally {
      setBusy(false);
    }
  }

  async function approveFix() {
    if (!proposal || typeof proposal.proposal_id !== 'string' || !visualPreview) return;
    setBusy(true);
    setMessage('');
    try {
      await requestJSON(`${API}/api/agent/files/apply-edit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: proposal.proposal_id, approve: true }),
      });
      setApplied(true);
      setMessage('Fix applied. Running website QA again…');
      if (url && /^https?:\/\//i.test(url)) {
        const retest = await requestJSON(`${API}/api/qa/test`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        const summary = asObject(asObject(retest)?.summary);
        setMessage(`Fix applied. Retest complete: ${String(summary?.ui_issue_count ?? 'unknown')} UI finding(s) reported. Review the new QA report.`);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Fix or retest failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="qa-fix-actions">
      {!proposal && !visualCandidates.length && !visualPreview && (
        <button type="button" className="qa-fix-button" onClick={() => {
          if (!supported) {
            setMessage("This finding type is not supported for a proposed edit yet. Use Find source file to locate likely project files. No source was changed.");
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
      {visualCandidates.length > 0 && !applied && (
        <div className="qa-fix-preview">
          <strong>Choose the exact element</strong>
          {visualCandidates.map((candidate) => {
            const index = Number(candidate.index);
            return (
              <button key={index} type="button" className="qa-fix-button" onClick={() => chooseCandidate(index)} disabled={busy}>
                {`Element ${index + 1}: ${String(candidate.text ?? '(no text)')}${candidate.visible ? '' : ' (hidden)'}`}
              </button>
            );
          })}
          <p>Selection only creates a temporary browser preview. It does not edit source files.</p>
        </div>
      )}
      {visualPreview && !applied && (
        <div className="qa-visual-comparison">
          <h4>Actual browser preview</h4>
          <p>{fixKind === 'accessibility' ? 'Temporary accessible-name preview · Original source unchanged' : fixKind === 'overflow' ? 'Temporary text-wrapping preview · Original source unchanged' : fixKind === 'contrast' ? 'Temporary contrast preview · Original source unchanged' : 'Temporary 12px typography preview · Original source unchanged'}</p>
          <div className="qa-visual-grid">
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
          {proposal && (
            <>
              <strong>{fixKind === 'accessibility' ? 'Proposed source-code change' : 'Proposed CSS change'}</strong>
              <p>{String(proposal.path ?? '')}</p>
              <pre>{Array.isArray(proposal.diff) ? proposal.diff.map(String).join('\n') : 'Diff unavailable'}</pre>
              <p className="qa-fix-caution">Review the source diff and confirm it targets the intended element before applying.</p>
              <button type="button" className="qa-fix-button" onClick={approveFix} disabled={busy || !visualPreview}>
                {busy ? 'Applying / retesting…' : 'Approve & apply fix'}
              </button>
            </>
          )}
        </div>
      )}
      {message && <p role="status">{message}</p>}
      {applied && <p>Fix applied. Review the updated QA report before applying another change.</p>}
    </div>
  );
}


function WebsiteQAReport({ data }: { data: unknown }) {
  const report = asObject(data);
  if (!report) return null;

  const summary = asObject(report.summary);

  const count = (key: string) =>
    typeof summary?.[key] === 'number' ? summary[key] as number : 0;

  const checks = Array.isArray(report.responsive_checks)
    ? report.responsive_checks.filter((item) => {
      const check = asObject(item);
      return check !== null &&
        typeof check.name === 'string' &&
        typeof check.passed === 'boolean';
    }) as ResponsiveCheck[]
    : [];

  const pages = Array.isArray(report.pages)
    ? report.pages.map(asObject).filter(
      (page): page is Record<string, unknown> => page !== null,
    )
    : [];

  const externalLinks = Array.isArray(report.external_links)
    ? report.external_links.map(asObject).filter(
      (item): item is Record<string, unknown> => item !== null,
    )
    : [];

  const success = report.success === true;
  const metrics = [
    { label: 'Pages tested', value: count('pages_tested') },
    { label: 'Pages failed', value: count('pages_failed') },
    { label: 'Console errors', value: count('console_error_count') },
    { label: 'JavaScript errors', value: count('page_error_count') },
    { label: 'Failed requests', value: count('failed_request_count') },
    {
      label: 'Broken external links',
      value: count('external_broken_link_count'),
    },
  ];

  function renderResponsive(items: unknown) {
    if (!Array.isArray(items) || items.length === 0) {
      return <p className="qa-no-results">No responsive results available.</p>;
    }

    return (
      <div className="qa-viewport-grid">
        {items.map((item, index) => {
          const check = asObject(item);
          if (!check) return null;

          const name = typeof check.name === 'string' ? check.name : 'Viewport';
          const passed = check.passed === true;

          return (
            <article className="qa-viewport" key={`${name}-${index}`}>
              <div className="qa-viewport-top">
                <span className="qa-device-icon">
                  {name === 'mobile' ? '▯' : name === 'tablet' ? '▤' : '▭'}
                </span>
                <span className={`qa-mini-status ${passed ? 'is-pass' : 'is-fail'}`}>
                  {passed ? 'PASS' : 'FAIL'}
                </span>
              </div>
              <h4>{name.charAt(0).toUpperCase() + name.slice(1)}</h4>
              <p>{String(check.width ?? '?')} × {String(check.height ?? '?')}</p>
              <div className="qa-width-detail">
                <span>Viewport width</span>
                <strong>{String(check.viewport_width ?? '?')}px</strong>
              </div>
              <div className="qa-width-detail">
                <span>Document width</span>
                <strong>{String(check.document_width ?? '?')}px</strong>
              </div>
              {check.horizontal_overflow === true && (
                <details className="qa-overflow-details">
                  <summary>View overflowing elements</summary>
                  <pre>{JSON.stringify(check.overflowing_elements ?? [], null, 2)}</pre>
                </details>
              )}
            </article>
          );
        })}
      </div>
    );
  }

  return (
    <section className="qa-report" aria-label="Website QA report">
      <div className="qa-report-heading">
        <div>
          <span className="qa-eyebrow">AUTOMATED WEBSITE AUDIT</span>
          <h3>Test overview</h3>
          <p>{String(report.tested_url ?? '')}</p>
        </div>
        <span className={`qa-status ${success ? 'is-pass' : 'is-fail'}`}>
          <span className="qa-status-dot" />
          {success ? 'TEST COMPLETED' : 'CHECK RESULTS'}
        </span>
      </div>

      <div className="qa-metrics">
        {metrics.map((metric) => (
          <article className="qa-metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong className={metric.value > 0 && metric.label !== 'Pages tested'
              ? 'has-issues' : ''}>
              {metric.value}
            </strong>
          </article>
        ))}
      </div>

      {pages.length > 0 ? (
        <div className="qa-responsive">
          <div className="qa-section-heading">
            <div>
              <h3>Pages tested</h3>
              <p>
                {pages.length} page(s) tested · Maximum crawl limit: {String(report.crawl_limit ?? 50)}
              </p>
            </div>
          </div>

          <div className="qa-page-list">
            {pages.map((page, index) => {
              const pageSummary = asObject(page.summary);
              const status = typeof page.http_status === 'number'
                ? page.http_status : null;
              const pageSuccess = page.success === true;
              const pageChecks = Array.isArray(page.responsive_checks)
                ? page.responsive_checks : [];

              return (
                <details className="qa-page-item" key={`${String(page.url ?? index)}-${index}`}>
                  <summary className="qa-page-summary">
                    <span className={`qa-mini-status ${pageSuccess ? 'is-pass' : 'is-fail'}`}>
                      {status ?? 'ERR'}
                    </span>
                    <span className="qa-page-title">
                      <strong>{String(page.title || page.url || `Page ${index + 1}`)}</strong>
                      <small>{String(page.url ?? '')}</small>
                    </span>
                    <span className={`qa-status ${pageSuccess ? 'is-pass' : 'is-fail'}`}>
                      {pageSuccess ? 'PASS' : 'ISSUES'}
                    </span>
                  </summary>

                  {typeof page.navigation_error === 'string' && (
                    <p className="qa-no-results">{page.navigation_error}</p>
                  )}
                  {typeof page.page_test_error === 'string' && (
                    <p className="qa-no-results">{page.page_test_error}</p>
                  )}

                  <div className="qa-metrics">
                    {[
                      ['Console errors', pageSummary?.console_error_count],
                      ['JS errors', pageSummary?.page_error_count],
                      ['Failed requests', pageSummary?.failed_request_count],
                      ['Responsive failures', pageSummary?.responsive_viewports_failed],
                    ].map(([label, value]) => (
                      <article className="qa-metric" key={String(label)}>
                        <span>{String(label)}</span>
                        <strong>{typeof value === 'number' ? value : 0}</strong>
                      </article>
                    ))}
                  </div>

                  <h4>Responsive checks</h4>
                  {renderResponsive(pageChecks)}

                  {Array.isArray(page.ui_audit) && (() => {
                    type AuditIssue = Record<string, unknown> & {
                      viewports: string[];
                    };

                    const audits = page.ui_audit
                      .map(asObject)
                      .filter((item): item is Record<string, unknown> => item !== null);

                    const grouped = new Map<string, AuditIssue>();

                    for (const audit of audits) {
                      const viewport = String(audit.name ?? 'Unknown viewport');
                      const issues = Array.isArray(audit.issues)
                        ? audit.issues.map(asObject).filter(
                          (item): item is Record<string, unknown> => item !== null,
                        )
                        : [];

                      for (const issue of issues) {
                        const key = [
                          issue.category,
                          issue.element,
                          issue.evidence,
                          issue.recommendation,
                        ].map(value => String(value ?? '')).join('|');

                        const existing = grouped.get(key);

                        if (existing) {
                          if (!existing.viewports.includes(viewport)) {
                            existing.viewports.push(viewport);
                          }
                        } else {
                          grouped.set(key, {
                            ...issue,
                            viewports: [viewport],
                          });
                        }
                      }
                    }

                    const allIssues = [...grouped.values()];
                    const severityRank: Record<string, number> = {
                      high: 0,
                      medium: 1,
                      low: 2,
                    };

                    allIssues.sort((a, b) =>
                      (severityRank[String(a.severity).toLowerCase()] ?? 3) -
                      (severityRank[String(b.severity).toLowerCase()] ?? 3)
                    );

                    const categories = [...new Set(
                      allIssues.map(issue => String(issue.category ?? 'Other'))
                    )];

                    return (
                      <section className="qa-ui-audit">
                        <div className="qa-section-heading">
                          <div>
                            <h4>UI quality audit</h4>
                            <p>
                              {allIssues.length} unique finding(s) across{' '}
                              {audits.length} viewport checks
                            </p>
                          </div>
                          <span className={`qa-status ${allIssues.some(issue =>
                            String(issue.severity).toLowerCase() === 'high'
                          ) ? 'is-fail' : 'is-neutral'
                            }`}>
                            {allIssues.length === 0 ? 'NO FINDINGS' : 'REVIEW FINDINGS'}
                          </span>
                        </div>

                        {allIssues.length === 0 ? (
                          <p className="qa-no-results">
                            No findings from the current automated UI rules.
                            This does not guarantee a visually perfect page.
                          </p>
                        ) : (
                          <div className="qa-ui-issues">
                            {categories.map(category => (
                              <section className="qa-ui-category" key={category}>
                                <h5>{category}</h5>
                                {allIssues
                                  .filter(issue => String(issue.category ?? 'Other') === category)
                                  .map((issue, index) => {
                                    const severity = String(issue.severity ?? 'low').toLowerCase();
                                    const confidence = String(issue.confidence ?? 'medium');
                                    const elementText = String(issue.element_text ?? '').trim();

                                    return (
                                      <article
                                        className={`qa-ui-finding severity-${severity}`}
                                        key={`${category}-${String(issue.element)}-${index}`}
                                      >
                                        <div className="qa-ui-finding-top">
                                          <span className={`qa-ui-severity severity-${severity}`}>
                                            {severity.toUpperCase()}
                                          </span>
                                          <span className="qa-ui-confidence">
                                            {confidence} confidence
                                          </span>
                                        </div>

                                        <code className="qa-ui-selector">
                                          {String(issue.element ?? 'Unknown element')}
                                        </code>

                                        {elementText && (
                                          <p className="qa-ui-snippet">
                                            Text: “{elementText}”
                                          </p>
                                        )}

                                        <p className="qa-ui-evidence">
                                          {String(issue.evidence ?? '')}
                                        </p>

                                        <div className="qa-ui-recommendation">
                                          <strong>Recommended action</strong>
                                          <p>{String(issue.recommendation ?? '')}</p>
                                        </div>


                                        {(() => {
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

                                        <AuditFixAction
                                          issue={issue}
                                          url={String(page.url ?? report.tested_url ?? '')}
                                        />
                                        <div className="qa-ui-viewports">
                                          {issue.viewports.map(viewport => (
                                            <span key={viewport}>{viewport}</span>
                                          ))}
                                        </div>
                                      </article>
                                    );
                                  })}
                              </section>
                            ))}
                          </div>
                        )}
                        <p className="qa-ui-disclaimer">
                          Automated findings are suggestions, not guaranteed defects.
                          Verify the rendered page before changing styles.
                        </p>
                      </section>
                    );
                  })()}

                  {[
                    ['Console errors', page.console_errors],
                    ['JavaScript errors', page.page_errors],
                    ['Failed requests', page.failed_requests],
                  ].map(([label, value]) => (
                    Array.isArray(value) && value.length > 0 ? (
                      <details className="technical-details" key={String(label)}>
                        <summary>{String(label)} ({value.length})</summary>
                        <pre>{JSON.stringify(value, null, 2)}</pre>
                      </details>
                    ) : null
                  ))}
                </details>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="qa-responsive">
          <div className="qa-section-heading">
            <div>
              <h3>Responsive checks</h3>
              <p>Horizontal overflow detection</p>
            </div>
            <span className="qa-status is-neutral">
              {checks.length > 0
                ? `${checks.filter((check) => check.passed).length}/${checks.length} PASSED`
                : 'NOT AVAILABLE'}
            </span>
          </div>
          {renderResponsive(checks)}
        </div>
      )}

      {externalLinks.length > 0 && (
        <details className="technical-details">
          <summary>External links checked ({externalLinks.length})</summary>
          <ul>
            {externalLinks.map((item, index) => {
              const broken = item.broken === true;
              return (
                <li key={`${String(item.url ?? index)}-${index}`}>
                  <span className={`qa-mini-status ${broken ? 'is-fail' : 'is-pass'}`}>
                    {broken ? 'FAIL' : String(item.status ?? 'OK')}
                  </span>{' '}
                  <code>{String(item.url ?? '')}</code>
                  {typeof item.error === 'string' && ` — ${item.error}`}
                </li>
              );
            })}
          </ul>
        </details>
      )}

      <details className="technical-details qa-raw-details">
        <summary>Full QA response</summary>
        <pre>{JSON.stringify(data, null, 2)}</pre>
      </details>
    </section>
  );
}

function ResultCard({
  title,
  message,
  children,
  onClear,
}: {
  title: string;
  message: string;
  children?: ReactNode;
  onClear: () => void;
}) {
  return (
    <section className="result-panel">
      <div className="result-heading">
        <div className="result-icon">
          <Icon name="spark" size={18} />
        </div>

        <div className="result-heading-text">
          <span className="result-eyebrow">VANTEX RESPONSE</span>
          <h2>{title}</h2>
        </div>

        <button
          type="button"
          className="result-close"
          onClick={onClear}
          aria-label="Clear result"
        >
          ×
        </button>
      </div>

      <p className="result-message">{message}</p>
      {children}
    </section>
  );
}

function FileResults({
  files,
  onOpen,
  openingPath,
}: {
  files: FileItem[];
  onOpen: (file: FileItem) => void;
  openingPath: string;
}) {
  const [copiedPath, setCopiedPath] = useState('');


  async function copyFilePath(path: string) {
    try {
      const data = await requestJSON(
        `${API}/api/agent/pc-files/copy`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        },
      ) as { copied?: boolean; message?: string };

      if (data.copied !== true) {
        throw new Error(data.message || 'Could not copy the original file.');
      }

      setCopiedPath(path);
      window.setTimeout(() => {
        setCopiedPath(current => current === path ? '' : current);
      }, 1800);
    } catch (err) {
      console.error('[VANTEX] Copy original file failed:', err);
      setCopiedPath('');
      alert(
        err instanceof Error
          ? err.message
          : 'Could not copy file. Check file access and Linux clipboard support.',
      );
    }
  }

  if (!files.length) {
    return (
      <div className="empty-results">
        <Icon name="search" size={24} />
        <p>No matching files found.</p>
        <span>
          Try a filename, extension, or a more specific description.
        </span>
      </div>
    );
  }

  return (
    <div className="file-results">
      {files.map((file, index) => (
        <article
          className="file-result"
          key={`${file.path}-${index}`}
        >
          <div className="file-result-icon">
            <Icon name="file" size={21} />
          </div>

          <div className="file-result-info">
            <h3>{file.name}</h3>
            <p className="file-path" title={file.path}>
              {file.path}
            </p>

            {file.preview && (
              <p className="file-preview">{file.preview}</p>
            )}
          </div>

          <div className="file-result-actions">
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
              aria-label={`Copy original file ${file.name}`}
              title="Copy original file for pasting in a compatible file manager"
            >
              {copiedPath === file.path ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}

export default function Home({ onOpenIntelligence }: HomeProps) {
  const [command, setCommand] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<ResultData | null>(null);
  const [openingPath, setOpeningPath] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [projectPath, setProjectPath] = useState('');
  const [projectInfo, setProjectInfo] = useState<Record<string, unknown> | null>(null);
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectMessage, setProjectMessage] = useState('');

  const [showWebsitePanel, setShowWebsitePanel] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [websiteUrl, setWebsiteUrl] = useState('');

  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(false);
  const recognitionRef = useRef<any>(null);
  const lastSpokenRef = useRef('');
  const voiceModeRef = useRef(false);
  const speakingRef = useRef(false);
  const restartingRef = useRef(false);

  function startVoiceCapture() {
    if (voiceModeRef.current) {
      voiceModeRef.current = false;
      speakingRef.current = false;
      window.speechSynthesis?.cancel();
      recognitionRef.current?.stop();
      setVoiceListening(false);
      setVoiceReplyEnabled(false);
      return;
    }

    const w = window as any;
    const Recognition = w.SpeechRecognition || w.webkitSpeechRecognition;

    if (!Recognition) {
      setError('Speech recognition is unavailable. Try the latest Chrome or Brave.');
      return;
    }

    setError('');
    voiceModeRef.current = true;
    speakingRef.current = false;
    setVoiceReplyEnabled(true);

    try {
      const recognition = new Recognition();
      recognitionRef.current = recognition;
      recognition.lang = 'en-IN';
      recognition.continuous = false;
      recognition.interimResults = false;

      recognition.onstart = () => {
        restartingRef.current = false;
        setVoiceListening(true);
      };

      recognition.onend = () => {
        setVoiceListening(false);
        if (voiceModeRef.current && !speakingRef.current) {
          window.setTimeout(() => {
            if (!voiceModeRef.current || speakingRef.current || restartingRef.current) return;
            try {
              restartingRef.current = true;
              recognition.start();
            } catch {
              restartingRef.current = false;
            }
          }, 450);
        }
      };

      recognition.onerror = (event: any) => {
        setVoiceListening(false);
        restartingRef.current = false;
        if (event.error !== 'aborted' && event.error !== 'no-speech') {
          setError('Microphone error: ' + event.error + '. Check browser microphone permissions.');
        }
      };

      recognition.onresult = (event: any) => {
        const transcript = String(event.results?.[0]?.[0]?.transcript ?? '').trim();
        if (!transcript) return;

        // Avoid restarting the microphone while the command is being processed.
        speakingRef.current = true;
        setCommand(transcript);
        window.setTimeout(() => {
          document.querySelector<HTMLFormElement>('.command-form')?.requestSubmit();
        }, 250);
      };

      recognition.start();
    } catch (err) {
      setVoiceListening(false);
      setError(err instanceof Error ? err.message : 'Could not start voice recognition.');
    }
  }

  // Preload Kokoro in the background instead of waiting for a reply.
  useEffect(() => {
    let active = true;

    getKokoro()
      .then(() => {
        if (active) {
          console.info('Kokoro TTS ready');
        }
      })
      .catch((err) => {
        console.error('Kokoro preload failed:', err);
      });

    return () => {
      active = false;
    };
  }, []);

  const spokenText = error || result?.message || '';



  useEffect(() => {
    if (!voiceReplyEnabled || !spokenText.trim()) return;
    if (lastSpokenRef.current === spokenText) return;

    let cancelled = false;

    const resumeListening = () => {
      speakingRef.current = false;

      if (!voiceModeRef.current || cancelled) return;

      window.setTimeout(() => {
        if (
          cancelled ||
          !voiceModeRef.current ||
          speakingRef.current
        ) {
          return;
        }

        try {
          restartingRef.current = true;
          recognitionRef.current?.start();
        } catch {
          restartingRef.current = false;
        }
      }, 500);
    };

    const speak = () => {
      if (cancelled) return;

      const voices = window.speechSynthesis.getVoices();

      const femaleVoice = voices.find((voice) =>
        /female|samantha|zira|aria|jenny|google us english/i.test(
          voice.name,
        ),
      );

      const englishVoice =
        femaleVoice ??
        voices.find((voice) => /^en(-|_)/i.test(voice.lang));

      const utterance = new SpeechSynthesisUtterance(spokenText);

      if (englishVoice) {
        utterance.voice = englishVoice;
      }

      utterance.lang = englishVoice?.lang || 'en-US';
      utterance.rate = 0.95;
      utterance.pitch = 1.05;
      utterance.volume = 1;

      utterance.onstart = () => {
        console.log('[VANTEX TTS] Browser voice started');
      };

      utterance.onend = () => {
        if (cancelled) return;

        lastSpokenRef.current = spokenText;
        resumeListening();
      };

      utterance.onerror = (event) => {
        console.error('[VANTEX TTS] Browser voice error:', event.error);
        resumeListening();
      };

      window.speechSynthesis.speak(utterance);
    };

    speakingRef.current = true;
    recognitionRef.current?.stop();
    setVoiceListening(false);

    window.speechSynthesis.cancel();

    // Wait briefly for the browser's voice list to initialize.
    if (window.speechSynthesis.getVoices().length > 0) {
      speak();
    } else {
      const onVoicesChanged = () => {
        window.speechSynthesis.removeEventListener(
          'voiceschanged',
          onVoicesChanged,
        );
        speak();
      };

      window.speechSynthesis.addEventListener(
        'voiceschanged',
        onVoicesChanged,
      );

      // Avoid waiting forever if the browser never fires voiceschanged.
      window.setTimeout(() => {
        window.speechSynthesis.removeEventListener(
          'voiceschanged',
          onVoicesChanged,
        );
        speak();
      }, 1000);
    }

    return () => {
      cancelled = true;
      window.speechSynthesis.cancel();
    };
  }, [spokenText, voiceReplyEnabled]);



  useEffect(() => {
    return () => {
      speakingRef.current = false;
      window.speechSynthesis?.cancel();
      document.querySelectorAll('audio').forEach((audio) => {
        audio.pause();
        audio.currentTime = 0;
      });
    };
  }, []);

  function clearResult() {
    setResult(null);
    setError('');
  }


  async function searchFiles(
    query: string,
    contentSearch = false,
    folder?: string,
  ) {
    console.log('[VANTEX] Search query:', query);
    console.log('[VANTEX] Search folder:', folder ?? 'all folders');
    console.log('[VANTEX] Content search:', contentSearch);

    const endpoint = contentSearch
      ? '/api/agent/pc-files/search-content'
      : '/api/agent/pc-files/search';

    const params = new URLSearchParams({ query });

    if (folder) {
      params.set('folder', folder.charAt(0).toUpperCase() + folder.slice(1));
    }

    const data = await requestJSON(
      `${API}${endpoint}?${params.toString()}`,
    );

    const files = findFileItems(data);

    setResult({
      title: contentSearch
        ? 'Content search results'
        : 'File search results',
      message: files.length
        ? `Found ${files.length} matching ${files.length === 1 ? 'result' : 'results'
        }.`
        : getResultMessage(data, 'No matching files were found.'),
      files,
      data,
    });
  }


  async function openFile(file: FileItem) {
    setOpeningPath(file.path);
    setError('');

    try {
      const data = await requestJSON(`${API}/api/agent/pc-files/open`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: file.path }),
      });

      setResult({
        title: 'Open file',
        message: getResultMessage(
          data,
          `Open request sent for ${file.name}.`,
        ),
        details: file.path,
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Could not open this file.',
      );
    } finally {
      setOpeningPath('');
    }
  }




  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const input = command.trim();

    if (!input || loading) return;

    setLoading(true);
    setError('');
    setResult(null);

    setHistory((previous) =>
      [input, ...previous.filter((item) => item !== input)].slice(0, 4),
    );

    try {
      const intent = detectIntent(input);

      console.log('[VANTEX] Input:', input);
      console.log('[VANTEX] Detected intent:', intent);

      // PC Intelligence: navigate directly.
      if (intent.type === 'intelligence') {
        setShowTools(true);
        onOpenIntelligence?.();
        return;
      }

      // Website test requested without a URL: show the URL form.
      if (intent.type === 'website' && !intent.url) {
        setWebsiteUrl('');
        setShowWebsitePanel(true);
        setShowTools(true);
        return;
      }

      // Website QA.
      if (intent.type === 'website' && intent.url) {
        const url = intent.url;
        setWebsiteUrl(url);
        setShowWebsitePanel(true);

        const data = await requestJSON(`${API}/api/qa/test`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });

        const obj = asObject(data);

        const title =
          typeof obj?.title === 'string'
            ? obj.title
            : getHostname(url);

        const status =
          typeof obj?.http_status === 'number'
            ? `HTTP status: ${obj.http_status}`
            : '';

        setResult({
          title: 'Website test complete',
          message: getResultMessage(
            data,
            `The website test request completed for ${title}.`,
          ),
          details: [url, status].filter(Boolean).join('\n'),
          data,
        });

        return;
      }

      // Route filename searches and searches inside file contents separately.
      if (intent.type === 'files') {
        const wantsContent = /\b(with|containing|contains|inside|mentioning|mentions|whose content|text contains)\b/i.test(input)
          && /\b(resume|resumes|cv|cvs|file|files|pdf|document|documents)\b/i.test(input);

        const contentQuery = wantsContent
          ? input
            .replace(/\b(find|search|locate|list|show|please|bhai|mujhe|mera|meri|mere|all|my|the|files|file|documents|document|resumes|resume|cvs|cv|pdf|with|containing|contains|inside|mentioning|mentions|whose|content|text|in|inside|from|on|my|pc|computer|laptop|desktop|downloads|pictures|videos)\b/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim()
          : intent.query;

        await searchFiles(
          wantsContent && contentQuery ? contentQuery : intent.query,
          wantsContent,
          intent.folder,
        );
        return;
      }

      // Send a command to the existing PC command handler.
      // The backend decides which supported action to execute.
      const data = await requestJSON(`${API}/api/agent/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: input }),
      });

      const obj = asObject(data);
      const resultData = asObject(obj?.result);

      const action =
        typeof obj?.action === 'string' ? obj.action : '';

      const backendMessage =
        typeof obj?.message === 'string'
          ? obj.message
          : typeof obj?.detail === 'string'
            ? obj.detail
            : typeof resultData?.message === 'string'
              ? resultData.message
              : '';

      // Content search results.
      // Handle content searches identified by either frontend intent or backend action.
      if (intent.type === 'content' || action === 'search_file_content') {
        const rawResults = Array.isArray(obj?.results)
          ? obj.results
          : Array.isArray(resultData?.results)
            ? resultData.results
            : Array.isArray(resultData?.matches)
              ? resultData.matches
              : [];

        const files = rawResults
          .filter(
            (item): item is Record<string, unknown> =>
              item !== null && typeof item === 'object',
          )
          .map((item) => ({
            name: String(item.name ?? ''),
            path: String(item.path ?? ''),
          }))
          .filter((file) => file.name && file.path);

        setResult({
          title: 'Content search results',
          message:
            files.length > 0
              ? `Found ${files.length} matching files.`
              : backendMessage ||
              getResultMessage(
                data,
                'No files matched the requested content.',
              ),
          files,
          data,
        });

        return;
      }

      // Open a file or folder.
      if (intent.type === 'open') {
        const selection = asObject(obj?.selection);

        const openedActions = [
          'open_file_by_content',
          'open_pc_file',
          'open_latest_resume',
          'open_latest_screenshot',
        ];

        if (openedActions.includes(action)) {
          setResult({
            title: 'File opened',
            message:
              backendMessage ||
              getResultMessage(
                data,
                'Open request sent to the default application.',
              ),
            details:
              typeof selection?.path === 'string'
                ? selection.path
                : typeof resultData?.path === 'string'
                  ? resultData.path
                  : undefined,
            data,
          });
        } else {
          const rawResults = Array.isArray(obj?.results)
            ? obj.results
            : Array.isArray(resultData?.results)
              ? resultData.results
              : Array.isArray(resultData?.matches)
                ? resultData.matches
                : [];

          const files = rawResults
            .filter(
              (item): item is Record<string, unknown> =>
                item !== null && typeof item === 'object',
            )
            .map((item) => ({
              name: String(item.name ?? ''),
              path: String(item.path ?? ''),
            }))
            .filter((file) => file.name && file.path);

          setResult({
            title: files.length
              ? 'Select a file'
              : 'Open file result',
            message:
              backendMessage ||
              (files.length > 0
                ? 'Multiple files matched. Review the results before opening one.'
                : getResultMessage(
                  data,
                  'No matching file was found. Try a more specific filename.',
                )),
            files,
            data,
          });
        }

        return;
      }

      // PC status: support the existing dedicated endpoint.
      if (intent.type === 'system') {
        setResult({
          title: 'PC status',
          message:
            backendMessage ||
            getResultMessage(data, 'System information retrieved.'),
          data,
        });

        return;
      }

      // All other requests: show the action or conversational response
      // returned by the command handler.
      setResult({
        title:
          action === 'clarify'
            ? 'Need more details'
            : action === 'chat'
              ? 'VANTEX'
              : 'VANTEX command result',
        message:
          backendMessage ||
          getResultMessage(
            data,
            'Command processed. Check the result below.',
          ),
        data,
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Something went wrong. Check that the VANTEX backend is running.',
      );
    } finally {
      setLoading(false);
    }
  }




  const systemData = asObject(result?.data);
  const metricsData = asObject(asObject(systemData?.result)?.system) ?? asObject(systemData?.system);

  const systemEntries = metricsData
    ? Object.entries(metricsData).filter(
      ([, value]) =>
        typeof value === 'string' ||
        typeof value === 'number' ||
        typeof value === 'boolean',
    )
    : [];

  return (
    <main className="home-shell">
      <div className="home-noise" aria-hidden="true" />

      <header className="home-topbar">
        <a href="/" className="brand" aria-label="VANTEX home">
          <span className="brand-mark">
            <Icon name="spark" size={23} />
          </span>
          <span className="brand-name">VANTEX</span>
          <span className="brand-ai">AI</span>
        </a>

        <div className="connection-status">
          <span className="status-dot" />
          <span>LOCAL AGENT</span>
        </div>
      </header>

      <section className="command-main">
        <div className="hero-badge">
          <span className="hero-badge-dot" />
          YOUR PERSONAL AI WORKSPACE
        </div>

        <div className="hero-orb" aria-hidden="true">
          <div className="orb-ring orb-ring-one" />
          <div className="orb-ring orb-ring-two" />
          <div className="orb-core">
            <Icon name="spark" size={37} />
          </div>
          <div className="orb-glow" />
        </div>

        <h1 className="hero-title">
          Your PC.
          <br />
          <span>Your commands.</span>
        </h1>

        <p className="hero-description">
          Search files, open projects, test websites, and interact with your
          system — all from one place.
        </p>

        {showTools && (
          <section className="project-manager-vantex" aria-label="Project manager" style={{ width: "min(760px, 100%)", margin: "0 auto 24px", padding: "18px", border: "1px solid rgba(100,255,170,.22)", borderRadius: "16px", background: "rgba(8,20,16,.72)", textAlign: "left" }}>
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
              <button type="button" className="qa-fix-button" disabled={projectBusy} onClick={async () => {
                setProjectBusy(true); setProjectMessage("Choose a folder to approve for file search and reading…");
                try {
                  const picked = asObject(await requestJSON(`${API}/api/projects/browse`));
                  if (picked?.cancelled === true) { setProjectMessage("Folder selection cancelled."); return; }
                  if (typeof picked?.path !== "string") throw new Error(getMessage(picked, "Could not choose folder."));
                  const approved = asObject(await requestJSON(`${API}/api/agent/pc-files/approve-folder`, {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: picked.path }),
                  }));
                  setProjectMessage(String(approved?.message ?? `Folder approved: ${picked.path}`));
                } catch (err) { setProjectMessage(err instanceof Error ? err.message : "Could not approve folder."); }
                finally { setProjectBusy(false); }
              }}>{projectBusy ? "Working…" : "Allow Folder"}</button>
              <button type="button" className="qa-fix-button" disabled={projectBusy} onClick={async () => {
                const confirmed = window.confirm("Allow VANTEX to search and read files throughout your home folder (including Desktop, Documents, Downloads and other user folders)? This does not grant root access or enable file editing/deletion.");
                if (!confirmed || projectBusy) return;
                setProjectBusy(true); setProjectMessage("Enabling full user-folder access…");
                try {
                  const approved = asObject(await requestJSON(`${API}/api/agent/pc-files/allow-all`, {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ confirm: true }),
                  }));
                  setProjectMessage(String(approved?.message ?? "Full user-folder access enabled."));
                } catch (err) { setProjectMessage(err instanceof Error ? err.message : "Could not enable full access."); }
                finally { setProjectBusy(false); }
              }}>{projectBusy ? "Working…" : "Allow All PC Files"}</button>
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
        )}
        <form className="command-form voice-first-form" onSubmit={handleSubmit}>
          <div className="voice-stage">
            <div className={`voice-stage-orb${voiceListening ? " voice-stage-orb-active" : ""}${loading ? " voice-stage-orb-thinking" : ""}`}>
              <span className="voice-stage-core">V</span>
            </div>

            <p className="voice-stage-status" aria-live="polite">
              {loading ? "Thinking…" : voiceListening ? "I'm listening…" : "Talk to VANTEX"}
            </p>

            <p className="voice-stage-hint">
              {voiceListening
                ? "Speak naturally. I'm listening to your request."
                : "Tap the microphone and tell me what's on your mind."}
            </p>

            <button
              type="button"
              className={`voice-toggle${voiceListening ? " is-listening" : ""}`}
              onClick={startVoiceCapture}
              aria-label={voiceListening ? "Stop listening" : "Talk to VANTEX"}
            >
              {voiceListening ? "■" : "🎙"}
            </button>

            <span className="voice-stage-footnote">
              VOICE INTERACTION · LOCAL PC AGENT
            </span>
          </div>

          <div className="voice-text-input">
            <span className="voice-text-label">OR TYPE YOUR COMMAND</span>

            <div className="voice-text-row">
              <input
                type="text"
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                placeholder="Ask VANTEX anything..."
                aria-label="Type a command for VANTEX"
                disabled={loading}
              />

              <button
                type="submit"
                className="voice-text-send"
                disabled={loading || !command.trim()}
                aria-label="Send command"
              >
                {loading ? "…" : "➤"}
              </button>
            </div>
          </div>

        </form>

        <button
          type="button"
          className="qa-fix-button"
          onClick={() => setShowTools((visible) => !visible)}
        >
          {showTools ? 'Hide tools' : 'File tools & permissions'}
        </button>

        {showWebsitePanel && (
          <section className="vantex-action-panel">
            <h3>Test a website</h3>
            <p>Enter the website URL. VANTEX will run the website QA check.</p>

            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!websiteUrl.trim() || loading) return;

                setCommand(`Test ${websiteUrl.trim()}`);

                window.setTimeout(() => {
                  document
                    .querySelector<HTMLFormElement>('.voice-first-form')
                    ?.requestSubmit();
                }, 0);
              }}
            >
              <input
                type="url"
                value={websiteUrl}
                onChange={(event) => setWebsiteUrl(event.target.value)}
                placeholder="http://localhost:5173"
                aria-label="Website URL"
                required
              />

              <button type="submit" disabled={loading || !websiteUrl.trim()}>
                {loading ? 'Testing…' : 'Test website'}
              </button>

              <button
                type="button"
                onClick={() => setShowWebsitePanel(false)}
              >
                Cancel
              </button>
            </form>
          </section>
        )}

        {showTools && (
          <div className="quick-actions">
            <span className="section-label">TRY A COMMAND</span>

            <div className="quick-action-list">
              <button
                type="button"
                className="quick-action"
                onClick={() => setCommand('Find Home.tsx')}
              >
                <Icon name="file" size={17} />
                <span>Find a file</span>
                <span className="quick-action-arrow">↗</span>
              </button>

              <button
                type="button"
                className="quick-action"
                onClick={() => setCommand('Test http://127.0.0.1:5173')}
              >
                <Icon name="check" size={17} />
                <span>Test a website</span>
                <span className="quick-action-arrow">↗</span>
              </button>

              <button
                type="button"
                className="quick-action"
                onClick={() => onOpenIntelligence?.()}
              >
                <Icon name="monitor" size={17} />
                <span>PC Intelligence</span>
                <span className="quick-action-arrow">↗</span>
              </button>
            </div>
          </div>
        )}

        {showTools && history.length > 0 && !result && !error && (
          <div className="recent-commands">
            <span className="section-label">RECENT COMMANDS</span>
            <div className="recent-command-list">
              {history.map((item) => (
                <button
                  type="button"
                  key={item}
                  onClick={() => setCommand(item)}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>
        )}

        {loading && (
          <div className="working-indicator">
            <span className="working-pulse" />
            <span>VANTEX is working on your request…</span>
          </div>
        )}

        {error && (
          <section className="error-panel" role="alert">
            <div className="error-symbol">!</div>
            <div>
              <h2>Something went wrong</h2>
              <p>{error}</p>
              <button
                type="button"
                className="retry-button"
                onClick={() => {
                  const previousCommand = command;
                  setError('');

                  if (previousCommand.trim()) {
                    const form = document.querySelector<HTMLFormElement>(
                      '.command-form',
                    );
                    form?.requestSubmit();
                  }
                }}
              >
                Try again
              </button>
            </div>
          </section>
        )}

        {result && (
          <ResultCard
            title={result.title}
            message={result.message}
            onClear={clearResult}
          >
            {result.details && (
              <div className="result-details">{result.details}</div>
            )}

            {result.title === 'Website test complete' && result.data != null && (
              <WebsiteQAReport data={result.data} />
            )}

            {result.files && (
              <FileResults
                files={result.files}
                onOpen={openFile}
                openingPath={openingPath}
              />
            )}

            {result.title === 'PC status' && systemEntries.length > 0 && (
              <div className="system-result-grid">
                {systemEntries.map(([key, value]) => (
                  <div className="system-result-item" key={key}>
                    <span>{key.replaceAll('_', ' ')}</span>
                    <strong>{String(value)}</strong>
                  </div>
                ))}
              </div>
            )}

            {result.title === 'Website test complete' &&
              systemEntries.length > 0 && (
                <div className="system-result-grid">
                  {systemEntries
                    .filter(([key]) =>
                      ['title', 'http_status', 'success', 'url'].includes(
                        key.toLowerCase(),
                      ),
                    )
                    .map(([key, value]) => (
                      <div className="system-result-item" key={key}>
                        <span>{key.replaceAll('_', ' ')}</span>
                        <strong>{String(value)}</strong>
                      </div>
                    ))}
                </div>
              )}

            {result.data != null &&
              !result.files &&
              systemEntries.length === 0 && (
                <details className="technical-details">
                  <summary>Technical details</summary>
                  <pre>{JSON.stringify(result.data, null, 2)}</pre>
                </details>
              )}
          </ResultCard>
        )}
      </section>


      <footer className="home-footer">
        <div className="footer-line" />
        <span>VANTEX AI</span>
        <span className="footer-separator">/</span>
        <span>LOCAL-FIRST INTELLIGENCE</span>
        <span className="footer-right">
          BUILT FOR YOUR WORKFLOW
        </span>
      </footer>
    </main>
  );
}
