
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type DragEvent,
  type ClipboardEvent,
} from 'react';
import './CloudinaryUploader.css';

type CloudinaryConfig = {
  cloudName: string;
  uploadPreset: string;
};

type CloudinaryResponse = {
  secure_url?: string;
  public_id?: string;
  original_filename?: string;
  bytes?: number;
  format?: string;
  error?: { message?: string };
};

type GalleryImage = {
  id: string;
  url: string;
  name: string;
  publicId: string;
  bytes: number;
  format: string;
  uploadedAt: string;
};

const STORAGE_KEY = 'vantex.cloudinary.config.v1';
const GALLERY_KEY = 'vantex.cloudinary.gallery.v1';
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_GALLERY_ITEMS = 100;

function readConfig(): CloudinaryConfig {
  try {
    const parsed = JSON.parse(
      localStorage.getItem(STORAGE_KEY) || '{}',
    ) as Partial<CloudinaryConfig>;

    return {
      cloudName: parsed.cloudName || '',
      uploadPreset: parsed.uploadPreset || '',
    };
  } catch {
    return { cloudName: '', uploadPreset: '' };
  }
}

function readGallery(): GalleryImage[] {
  try {
    const parsed: unknown = JSON.parse(
      localStorage.getItem(GALLERY_KEY) || '[]',
    );

    if (!Array.isArray(parsed)) return [];

    return parsed.filter(
      (item): item is GalleryImage =>
        !!item &&
        typeof item.id === 'string' &&
        typeof item.url === 'string' &&
        /^https:\/\/res\.cloudinary\.com\//i.test(item.url) &&
        typeof item.name === 'string' &&
        typeof item.uploadedAt === 'string',
    );
  } catch {
    return [];
  }
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return 'Unknown size';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function CloudinaryUploader() {
  const [config, setConfig] = useState<CloudinaryConfig>({
    cloudName: '',
    uploadPreset: '',
  });
  const [draft, setDraft] = useState<CloudinaryConfig>({
    cloudName: '',
    uploadPreset: '',
  });
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [imageUrl, setImageUrl] = useState('');
  const [dragging, setDragging] = useState(false);
  const [gallery, setGallery] = useState<GalleryImage[]>(readGallery);
  const [gallerySearch, setGallerySearch] = useState('');
  const [galleryError, setGalleryError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const saved = readConfig();
    setConfig(saved);
    setDraft(saved);
  }, []);

  useEffect(() => {
    if (!file) {
      setPreview('');
      return;
    }

    const url = URL.createObjectURL(file);
    setPreview(url);

    return () => URL.revokeObjectURL(url);
  }, [file]);

  function persistGallery(next: GalleryImage[]): boolean {
    try {
      localStorage.setItem(GALLERY_KEY, JSON.stringify(next));
      setGallery(next);
      setGalleryError('');
      return true;
    } catch {
      setGalleryError(
        'Gallery could not be saved in this browser. Your Cloudinary upload may still be available through its URL.',
      );
      return false;
    }
  }

  function saveConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const next = {
      cloudName: draft.cloudName.trim(),
      uploadPreset: draft.uploadPreset.trim(),
    };

    if (!/^[a-zA-Z0-9_-]+$/.test(next.cloudName)) {
      setMessage('Enter a valid Cloudinary Cloud Name.');
      return;
    }

    if (!/^[a-zA-Z0-9_-]+$/.test(next.uploadPreset)) {
      setMessage('Enter a valid Upload Preset name.');
      return;
    }

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      setConfig(next);
      setMessage('Cloudinary settings saved in this browser.');
    } catch {
      setMessage('Browser storage is unavailable. Enable site storage and try again.');
    }
  }

  function chooseFile(next: File | undefined) {
    if (!next) return;

    if (!next.type.startsWith('image/')) {
      setMessage('Please choose an image file.');
      return;
    }

    if (next.size > MAX_FILE_BYTES) {
      setMessage('Image must be 10 MB or smaller.');
      return;
    }

    setFile(next);
    setImageUrl('');
    setMessage(`${next.name} ready to upload.`);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0]);
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    const pastedImage = Array.from(event.clipboardData.items).find(
      item => item.type.startsWith('image/'),
    );
    const pastedFile = pastedImage?.getAsFile();

    if (pastedFile) {
      event.preventDefault();
      chooseFile(pastedFile);
    }
  }

  async function uploadImage() {
    if (!config.cloudName || !config.uploadPreset) {
      setMessage('First add and save your own Cloud Name and unsigned Upload Preset.');
      return;
    }

    if (!file) {
      setMessage('Choose, drop, or paste an image first.');
      return;
    }

    setBusy(true);
    setMessage('Uploading to your Cloudinary account…');
    setImageUrl('');

    try {
      const form = new FormData();
      form.append('file', file);
      form.append('upload_preset', config.uploadPreset);

      const response = await fetch(
        `https://api.cloudinary.com/v1_1/${encodeURIComponent(config.cloudName)}/image/upload`,
        { method: 'POST', body: form },
      );

      const data = (await response.json()) as CloudinaryResponse;

      if (!response.ok || !data.secure_url) {
        throw new Error(
          data.error?.message ||
            `Upload failed (${response.status}). Check your Cloud Name and unsigned preset.`,
        );
      }

      setImageUrl(data.secure_url);

      const item: GalleryImage = {
        id: `${data.public_id || data.secure_url}-${Date.now()}`,
        url: data.secure_url,
        name: data.original_filename || file.name,
        publicId: data.public_id || '',
        bytes: data.bytes ?? file.size,
        format: data.format || file.type.split('/')[1] || 'image',
        uploadedAt: new Date().toISOString(),
      };

      const currentGallery = readGallery();
      const nextGallery = [
        item,
        ...currentGallery.filter(existing => existing.url !== item.url),
      ].slice(0, MAX_GALLERY_ITEMS);

      persistGallery(nextGallery);
      setMessage('Upload complete — image added to your VANTEX gallery.');
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Upload failed. Please try again.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function copyUrl(url: string, successMessage = 'Image URL copied.') {
    try {
      await navigator.clipboard.writeText(url);
      setMessage(successMessage);
    } catch {
      setMessage('Copy was blocked by the browser. Select the URL and copy it manually.');
    }
  }

  function removeFromGallery(id: string) {
    const next = gallery.filter(item => item.id !== id);

    if (persistGallery(next)) {
      setMessage('Image removed from this browser gallery. The Cloudinary image was not deleted.');
    }
  }

  function disconnect() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      setMessage('Could not clear browser storage. Check browser privacy settings.');
      return;
    }

    setConfig({ cloudName: '', uploadPreset: '' });
    setDraft({ cloudName: '', uploadPreset: '' });
    setMessage('Cloudinary settings removed from this browser. Your gallery is unchanged.');
  }

  const filteredGallery = gallery.filter(item =>
    `${item.name} ${item.publicId} ${item.format}`
      .toLowerCase()
      .includes(gallerySearch.toLowerCase().trim()),
  );

  return (
    <section className="vtx-cloud-panel" aria-label="Cloudinary image uploader">
      <div className="vtx-cloud-heading">
        <div>
          <span className="vtx-cloud-eyebrow">PERSONAL CLOUD CONNECTION</span>
          <h2>Image to Cloud</h2>
          <p>Upload directly to your own Cloudinary account and get a shareable URL.</p>
        </div>

        <span
          className={`vtx-cloud-status${
            config.cloudName && config.uploadPreset ? ' is-connected' : ''
          }`}
        >
          {config.cloudName && config.uploadPreset ? 'CONFIGURED' : 'NOT CONNECTED'}
        </span>
      </div>

      <details
        className="vtx-cloud-settings"
        open={!config.cloudName || !config.uploadPreset}
      >
        <summary>
          {config.cloudName && config.uploadPreset
            ? 'Cloudinary settings'
            : 'Connect your Cloudinary account'}
        </summary>

        <form onSubmit={saveConfig} className="vtx-cloud-config-form">
          <label>
            Cloud Name
            <input
              value={draft.cloudName}
              onChange={e =>
                setDraft(v => ({ ...v, cloudName: e.target.value }))
              }
              placeholder="your-cloud-name"
              autoComplete="off"
              required
            />
          </label>

          <label>
            Unsigned Upload Preset
            <input
              value={draft.uploadPreset}
              onChange={e =>
                setDraft(v => ({ ...v, uploadPreset: e.target.value }))
              }
              placeholder="your_upload_preset"
              autoComplete="off"
              required
            />
          </label>

          <p className="vtx-cloud-note">
            Create an unsigned preset in Cloudinary → Settings → Upload → Upload
            presets. Settings are saved only in this browser.
          </p>

          <div className="vtx-cloud-actions">
            <button type="submit" className="vtx-cloud-primary">
              Save connection
            </button>
            {config.cloudName && (
              <button
                type="button"
                className="vtx-cloud-secondary"
                onClick={disconnect}
              >
                Disconnect
              </button>
            )}
          </div>
        </form>
      </details>

      <div
        className={`vtx-cloud-dropzone${dragging ? ' is-dragging' : ''}`}
        tabIndex={0}
        role="button"
        aria-label="Drop an image here, paste an image, or choose a file"
        onClick={() => inputRef.current?.click()}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={e => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onPaste={onPaste}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={e => {
            chooseFile(e.target.files?.[0]);
            e.currentTarget.value = '';
          }}
        />

        {preview ? (
          <img className="vtx-cloud-preview" src={preview} alt="Selected image preview" />
        ) : (
          <span className="vtx-cloud-upload-icon">↑</span>
        )}

        <strong>{file ? file.name : 'Drop an image here'}</strong>
        <span>
          {file
            ? `${(file.size / 1024 / 1024).toFixed(2)} MB · Click to change`
            : 'or click to browse · paste an image with Ctrl+V while this area is focused'}
        </span>
      </div>

      <div className="vtx-cloud-actions vtx-cloud-upload-actions">
        <button
          type="button"
          className="vtx-cloud-primary"
          onClick={() => void uploadImage()}
          disabled={busy || !file}
        >
          {busy ? 'Uploading…' : 'Upload to my Cloudinary'}
        </button>

        {file && (
          <button
            type="button"
            className="vtx-cloud-secondary"
            onClick={() => {
              setFile(null);
              setImageUrl('');
              setMessage('Image removed from the upload selection.');
            }}
          >
            Remove image
          </button>
        )}
      </div>

      {imageUrl && (
        <div className="vtx-cloud-result">
          <img src={imageUrl} alt="Recently uploaded image" />

          <label>
            Uploaded image URL
            <input
              readOnly
              value={imageUrl}
              onFocus={e => e.currentTarget.select()}
            />
          </label>

          <div className="vtx-cloud-actions">
            <button
              type="button"
              className="vtx-cloud-primary"
              onClick={() => void copyUrl(imageUrl)}
            >
              Copy link
            </button>

            <a
              className="vtx-cloud-secondary vtx-cloud-open-link"
              href={imageUrl}
              target="_blank"
              rel="noreferrer"
            >
              Open image ↗
            </a>
          </div>
        </div>
      )}

      {message && (
        <p className="vtx-cloud-message" role="status">
          {message}
        </p>
      )}

      <section className="vtx-cloud-gallery" aria-label="Uploaded image gallery">
        <div className="vtx-cloud-gallery-heading">
          <div>
            <span className="vtx-cloud-eyebrow">YOUR UPLOADS</span>
            <h3>Image Gallery</h3>
            <p>
              Images uploaded through VANTEX are saved here in this browser.
            </p>
          </div>
          <span className="vtx-cloud-gallery-count">{gallery.length} / {MAX_GALLERY_ITEMS}</span>
        </div>

        {gallery.length > 0 && (
          <input
            className="vtx-cloud-gallery-search"
            type="search"
            value={gallerySearch}
            onChange={e => setGallerySearch(e.target.value)}
            placeholder="Search your images..."
            aria-label="Search uploaded images"
          />
        )}

        {galleryError && (
          <p className="vtx-cloud-message" role="alert">
            {galleryError}
          </p>
        )}

        {filteredGallery.length === 0 ? (
          <div className="vtx-cloud-gallery-empty">
            <span aria-hidden="true">▧</span>
            <strong>{gallery.length ? 'No matching images' : 'Your gallery is empty'}</strong>
            <p>
              {gallery.length
                ? 'Try another search term.'
                : 'Upload your first image above. It will appear here automatically.'}
            </p>
          </div>
        ) : (
          <div className="vtx-cloud-gallery-grid">
            {filteredGallery.map(item => (
              <article className="vtx-cloud-gallery-card" key={item.id}>
                <a
                  className="vtx-cloud-gallery-image-link"
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={`Open ${item.name}`}
                >
                  <img src={item.url} alt={item.name} loading="lazy" />
                </a>

                <div className="vtx-cloud-gallery-card-content">
                  <strong className="vtx-cloud-gallery-name" title={item.name}>
                    {item.name}
                  </strong>

                  <span className="vtx-cloud-gallery-meta">
                    {formatBytes(item.bytes)} · {item.format.toUpperCase()}
                  </span>

                  <time
                    className="vtx-cloud-gallery-date"
                    dateTime={item.uploadedAt}
                  >
                    {new Date(item.uploadedAt).toLocaleString()}
                  </time>

                  <div className="vtx-cloud-gallery-actions">
                    <button
                      type="button"
                      className="vtx-cloud-primary"
                      onClick={() =>
                        void copyUrl(item.url, `URL copied for ${item.name}.`)
                      }
                    >
                      Copy URL
                    </button>

                    <button
                      type="button"
                      className="vtx-cloud-secondary"
                      onClick={() => removeFromGallery(item.id)}
                      aria-label={`Remove ${item.name} from gallery`}
                    >
                      Remove
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}

        {gallery.length > 0 && (
          <p className="vtx-cloud-gallery-footnote">
            Removing an item here only removes its gallery entry. It does not
            delete the image from Cloudinary.
          </p>
        )}
      </section>
    </section>
  );
}
