import { useCallback, useEffect, useMemo, useState } from 'react';

const API = import.meta.env.PROD ? 'https://vantex-2d4l.onrender.com' : 'http://127.0.0.1:8000';
type CloudImage = { asset_id?: string; public_id: string; display_name?: string; secure_url: string; format?: string; width?: number; height?: number; bytes?: number; created_at?: string };
type GalleryResponse = { resources: CloudImage[]; next_cursor?: string | null };
function readCloudName(): string { try { const value = JSON.parse(localStorage.getItem('vantex.cloudinary.config.v1') || '{}'); return typeof value.cloudName === 'string' ? value.cloudName.trim() : ''; } catch { return ''; } }
function readGalleryToken(): string { try { return localStorage.getItem('vantex.cloudinary.galleryToken') || ''; } catch { return ''; } }
const buttonStyle: React.CSSProperties = { border: '1px solid rgba(91,255,160,.28)', borderRadius: 9, padding: '10px 13px', background: '#123a24', color: '#aaffc4', fontWeight: 700, cursor: 'pointer' };

export default function CloudinaryGallery() {
  const [images, setImages] = useState<CloudImage[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<CloudImage | null>(null);
  const [cloudName, setCloudName] = useState(readCloudName);
  const [galleryToken, setGalleryToken] = useState(readGalleryToken);
  const [tokenDraft, setTokenDraft] = useState(readGalleryToken);

  const loadPage = useCallback(async (append: boolean) => {
    setLoading(true); setError(''); setNotice('');
    try {
      const current = readCloudName(); setCloudName(current);
      if (!current) throw new Error('Save your Cloud Name in the Cloudinary uploader first.');
      const token = readGalleryToken();
      if (!token) throw new Error('Enter the VANTEX gallery access token below first.');
      const params = new URLSearchParams({ limit: '30' });
      if (append && cursor) params.set('next_cursor', cursor);
      const response = await fetch(`${API}/api/cloudinary/images?${params.toString()}`, { headers: { 'X-VANTEX-Gallery-Token': token } });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Gallery request failed (${response.status}).`);
      const data = body as GalleryResponse; const next = Array.isArray(data.resources) ? data.resources : [];
      setImages(previous => append ? [...previous, ...next] : next); setCursor(data.next_cursor || null);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not load Cloudinary images.'); }
    finally { setLoading(false); }
  }, [cursor]);
  useEffect(() => { void loadPage(false); }, []); // Loads once when the gallery opens.
  const filtered = useMemo(() => { const q = search.trim().toLowerCase(); return q ? images.filter(i => `${i.display_name || ''} ${i.public_id}`.toLowerCase().includes(q)) : images; }, [images, search]);
  async function copyUrl(url: string) { try { await navigator.clipboard.writeText(url); setNotice('Image URL copied.'); } catch { setNotice('Clipboard access failed. Open the image and copy the URL from the address bar.'); } }
  function size(bytes?: number) { if (typeof bytes !== 'number') return ''; if (bytes < 1024) return `${bytes} B`; if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / 1048576).toFixed(1)} MB`; }

  return <section style={{ marginTop: 18, padding: 18, border: '1px solid rgba(91,255,160,.24)', borderRadius: 16, background: 'linear-gradient(145deg, rgba(8,22,15,.98), rgba(8,13,12,.98))', color: '#e8fff0' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}><div><div style={{ color: '#70ffa5', fontSize: 11, letterSpacing: 2, fontWeight: 800 }}>VANTEX · CLOUDINARY</div><h3 style={{ margin: '5px 0', fontSize: 22 }}>My Cloud Images</h3><p style={{ margin: 0, color: '#a6c6b2', fontSize: 12 }}>{cloudName ? `Cloud: ${cloudName}` : 'Connect Cloudinary in the uploader.'} · {images.length} loaded</p></div><button type="button" onClick={() => void loadPage(false)} disabled={loading} style={buttonStyle}>{loading ? 'Refreshing…' : '↻ Refresh'}</button></div>
    <form onSubmit={e => { e.preventDefault(); try { localStorage.setItem('vantex.cloudinary.galleryToken', tokenDraft.trim()); setGalleryToken(tokenDraft.trim()); setImages([]); setCursor(null); setNotice('Gallery access token saved in this browser.'); } catch { setError('Could not save the gallery token in browser storage.'); } }} style={{ display: 'flex', gap: 8, marginTop: 14 }}><input value={tokenDraft} onChange={e => setTokenDraft(e.target.value)} type="password" autoComplete="current-password" placeholder="VANTEX gallery access token" aria-label="VANTEX gallery access token" style={{ flex: 1, minWidth: 0, padding: '11px 12px', borderRadius: 9, border: '1px solid rgba(91,255,160,.25)', background: '#07100b', color: '#e8fff0' }} /><button type="submit" style={buttonStyle}>Save token</button><button type="button" onClick={() => { try { localStorage.removeItem('vantex.cloudinary.galleryToken'); } catch {} setGalleryToken(''); setTokenDraft(''); setImages([]); setCursor(null); setNotice('Gallery token removed from this browser.'); }} style={buttonStyle}>Forget</button></form>
    <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search loaded images by filename or public ID…" aria-label="Search Cloudinary images" style={{ width: '100%', boxSizing: 'border-box', margin: '16px 0', padding: '12px 14px', borderRadius: 10, border: '1px solid rgba(91,255,160,.25)', background: '#07100b', color: '#e8fff0' }} />
    {galleryToken && <p style={{ color: '#8eaa98', fontSize: 11 }}>Gallery access token is stored in this browser only; it is not the Cloudinary API secret.</p>}
    {error && <div role="alert" style={{ padding: 12, borderRadius: 10, border: '1px solid rgba(255,110,110,.35)', color: '#ffb6b6', marginBottom: 14 }}>{error}</div>}{notice && <p role="status" style={{ color: '#83ffb0', fontSize: 13 }}>{notice}</p>}
    {!error && !loading && images.length === 0 && <p style={{ color: '#a6c6b2' }}>No images found in this Cloudinary account yet.</p>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 13 }}>{filtered.map(image => <article key={image.asset_id || image.public_id} style={{ overflow: 'hidden', borderRadius: 12, border: '1px solid rgba(91,255,160,.18)', background: '#0a1710', minWidth: 0 }}><button type="button" onClick={() => setSelected(image)} aria-label={`Preview ${image.display_name || image.public_id}`} style={{ width: '100%', display: 'block', padding: 0, border: 0, background: '#050a07', cursor: 'zoom-in' }}><img src={image.secure_url} alt={image.display_name || image.public_id} loading="lazy" style={{ width: '100%', height: 155, display: 'block', objectFit: 'cover' }} /></button><div style={{ padding: 11 }}><div title={image.public_id} style={{ fontSize: 12, fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{image.display_name || image.public_id}</div><div style={{ color: '#8eaa98', fontSize: 11, marginTop: 5 }}>{image.width && image.height ? `${image.width} × ${image.height}` : 'Image'}{image.format ? ` · ${image.format.toUpperCase()}` : ''}{image.bytes ? ` · ${size(image.bytes)}` : ''}</div><div style={{ display: 'flex', gap: 7, marginTop: 11 }}><button type="button" onClick={() => void copyUrl(image.secure_url)} style={{ ...buttonStyle, flex: 1, padding: '8px 9px', fontSize: 12 }}>Copy URL</button><button type="button" onClick={() => setSelected(image)} style={{ ...buttonStyle, padding: '8px 10px', fontSize: 12, background: '#14251b' }}>Preview</button></div></div></article>)}</div>
    {images.length > 0 && filtered.length === 0 && <p style={{ color: '#a6c6b2' }}>No loaded images match “{search}”.</p>}{cursor && <div style={{ display: 'flex', justifyContent: 'center', marginTop: 18 }}><button type="button" onClick={() => void loadPage(true)} disabled={loading} style={buttonStyle}>{loading ? 'Loading…' : 'Load more images'}</button></div>}{!cursor && images.length > 0 && <p style={{ color: '#769984', textAlign: 'center', fontSize: 12, marginTop: 16 }}>End of gallery results.</p>}
    {selected && <div role="dialog" aria-modal="true" aria-label="Image preview" onClick={() => setSelected(null)} style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,.86)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}><div onClick={e => e.stopPropagation()} style={{ width: 'min(900px, 100%)', maxHeight: '90vh', overflow: 'auto', border: '1px solid rgba(91,255,160,.35)', borderRadius: 16, background: '#08110b', padding: 16, color: '#e8fff0' }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 12 }}><strong style={{ overflowWrap: 'anywhere' }}>{selected.display_name || selected.public_id}</strong><button type="button" onClick={() => setSelected(null)} style={buttonStyle}>Close ✕</button></div><img src={selected.secure_url} alt={selected.display_name || selected.public_id} style={{ maxWidth: '100%', maxHeight: '65vh', display: 'block', margin: '0 auto', objectFit: 'contain' }} /><p style={{ color: '#a6c6b2', fontSize: 12, overflowWrap: 'anywhere' }}>{selected.secure_url}</p><div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><button type="button" onClick={() => void copyUrl(selected.secure_url)} style={buttonStyle}>Copy image URL</button><a href={selected.secure_url} target="_blank" rel="noreferrer" style={{ ...buttonStyle, textDecoration: 'none', display: 'inline-flex', alignItems: 'center' }}>Open original ↗</a></div></div></div>}
  </section>;
}
