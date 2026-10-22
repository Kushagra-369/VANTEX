import { useCallback, useEffect, useMemo, useState } from "react";

// This is VANTEX's backend address, not a user's Cloudinary account.
const API = import.meta.env.PROD
  ? "https://vantex-2d4l.onrender.com"
  : "http://localhost:8000";

type CloudImage = {
  asset_id?: string;
  public_id: string;
  display_name?: string;
  secure_url: string;
  format?: string;
  width?: number;
  height?: number;
  bytes?: number;
  created_at?: string;
};
type GalleryResponse = {
  resources: CloudImage[];
  next_cursor?: string | null;
  cloud_name?: string;
};
type Connection = { connected: boolean; cloud_name?: string | null };

const btn: React.CSSProperties = {
  border: "1px solid rgba(91,255,160,.28)",
  borderRadius: 9,
  padding: "10px 13px",
  background: "#123a24",
  color: "#aaffc4",
  fontWeight: 700,
  cursor: "pointer",
};

function getCloudName(): string {
  try {
    const value = JSON.parse(localStorage.getItem("vantex.cloudinary.config.v1") || "{}");
    return typeof value.cloudName === "string" ? value.cloudName.trim() : "";
  } catch {
    return "";
  }
}

export default function CloudinaryGallery() {
  const [images, setImages] = useState<CloudImage[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<CloudImage | null>(null);
  const [connection, setConnection] = useState<Connection>({ connected: false });

  const checkConnection = useCallback(async () => {
    try {
      const response = await fetch(`${API}/api/cloudinary/connection`, {
        credentials: "include",
      });
      if (!response.ok) throw new Error("Could not check Cloudinary connection.");
      const data = (await response.json()) as Connection;
      setConnection(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection check failed.");
    }
  }, []);

  const loadPage = useCallback(async (append: boolean) => {
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const params = new URLSearchParams({ limit: "30" });
      if (append && cursor) params.set("next_cursor", cursor);
      const response = await fetch(`${API}/api/cloudinary/images?${params}`, {
        credentials: "include",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : `Gallery request failed (${response.status}).`);
      }
      const data = body as GalleryResponse;
      const next = Array.isArray(data.resources) ? data.resources : [];
      setImages(previous => append ? [...previous, ...next] : next);
      setCursor(data.next_cursor || null);
      setConnection({ connected: true, cloud_name: data.cloud_name });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load Cloudinary images.");
    } finally {
      setLoading(false);
    }
  }, [cursor]);

  useEffect(() => {
    void checkConnection();
    const params = new URLSearchParams(window.location.search);
    if (params.get("cloudinary_oauth") === "connected") {
      setNotice("Cloudinary connected successfully.");
      window.history.replaceState({}, document.title, window.location.pathname);
      void loadPage(false);
    } else if (params.get("cloudinary_oauth") === "denied") {
      setError("Cloudinary connection was cancelled.");
      window.history.replaceState({}, document.title, window.location.pathname);
    } else {
      // On later visits, load the already-connected browser session's gallery too.
      void fetch(`${API}/api/cloudinary/connection`, { credentials: "include" })
        .then(response => response.ok ? response.json() : { connected: false })
        .then((data: Connection) => {
          if (data.connected) void loadPage(false);
        })
        .catch(() => undefined);
    }
  // Run only once on mount; loadPage changes when pagination cursor changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? images.filter(i => `${i.display_name || ""} ${i.public_id}`.toLowerCase().includes(q)) : images;
  }, [images, search]);

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setNotice("Image URL copied.");
    } catch {
      setNotice("Clipboard access failed. Open the image and copy the URL from the address bar.");
    }
  }

  function size(bytes?: number) {
    if (typeof bytes !== "number") return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }

  function connect() {
    const cloudName = getCloudName();
    if (!cloudName) {
      setError("First save your Cloud Name in the uploader, then connect Cloudinary.");
      return;
    }
    window.location.href = `${API}/api/cloudinary/oauth/start?cloud_name=${encodeURIComponent(cloudName)}`;
  }

  return (
    <section style={{ marginTop: 18, padding: 18, border: "1px solid rgba(91,255,160,.24)", borderRadius: 16, background: "linear-gradient(145deg, rgba(8,22,15,.98), rgba(8,13,12,.98))", color: "#e8fff0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ color: "#70ffa5", fontSize: 11, letterSpacing: 2, fontWeight: 800 }}>VANTEX · CLOUDINARY</div>
          <h3 style={{ margin: "5px 0", fontSize: 22 }}>My Cloud Images</h3>
          <p style={{ margin: 0, color: "#a6c6b2", fontSize: 12 }}>
            {connection.connected ? `Connected cloud: ${connection.cloud_name}` : "Connect your own Cloudinary account to browse your images."}
            {" · "}{images.length} loaded
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {!connection.connected && <button type="button" onClick={connect} style={btn}>Connect Cloudinary</button>}
          {connection.connected && <button type="button" onClick={() => void loadPage(false)} disabled={loading} style={btn}>{loading ? "Refreshing…" : "↻ Refresh"}</button>}
          {connection.connected && <button type="button" onClick={async () => {
            try {
              await fetch(`${API}/api/cloudinary/disconnect`, { method: "POST", credentials: "include" });
              setImages([]);
              setCursor(null);
              setConnection({ connected: false });
              setNotice("Cloudinary disconnected from this browser.");
            } catch {
              setError("Could not disconnect Cloudinary. Please try again.");
            }
          }} style={btn}>Disconnect</button>}
        </div>
      </div>

      {connection.connected && (
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search loaded images by filename or public ID…"
          aria-label="Search Cloudinary images"
          style={{ width: "100%", boxSizing: "border-box", margin: "16px 0", padding: "12px 14px", borderRadius: 10, border: "1px solid rgba(91,255,160,.25)", background: "#07100b", color: "#e8fff0" }}
        />
      )}

      {error && <div role="alert" style={{ padding: 12, borderRadius: 10, border: "1px solid rgba(255,110,110,.35)", color: "#ffb6b6", marginBottom: 14 }}>{error}</div>}
      {notice && <p role="status" style={{ color: "#83ffb0", fontSize: 13 }}>{notice}</p>}
      {connection.connected && !error && !loading && images.length === 0 && <p style={{ color: "#a6c6b2" }}>No images found in this Cloudinary account yet.</p>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(190px,1fr))", gap: 13 }}>
        {filtered.map(image => (
          <article key={image.asset_id || image.public_id} style={{ overflow: "hidden", borderRadius: 12, border: "1px solid rgba(91,255,160,.18)", background: "#0a1710", minWidth: 0 }}>
            <button type="button" onClick={() => setSelected(image)} aria-label={`Preview ${image.display_name || image.public_id}`} style={{ width: "100%", display: "block", padding: 0, border: 0, background: "#050a07", cursor: "zoom-in" }}>
              <img src={image.secure_url} alt={image.display_name || image.public_id} loading="lazy" style={{ width: "100%", height: 155, display: "block", objectFit: "cover" }} />
            </button>
            <div style={{ padding: 11 }}>
              <div title={image.public_id} style={{ fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{image.display_name || image.public_id}</div>
              <div style={{ color: "#8eaa98", fontSize: 11, marginTop: 5 }}>
                {image.width && image.height ? `${image.width} × ${image.height}` : "Image"}
                {image.format ? ` · ${image.format.toUpperCase()}` : ""}
                {image.bytes ? ` · ${size(image.bytes)}` : ""}
              </div>
              <div style={{ display: "flex", gap: 7, marginTop: 11 }}>
                <button type="button" onClick={() => void copyUrl(image.secure_url)} style={{ ...btn, flex: 1, padding: "8px 9px", fontSize: 12 }}>Copy URL</button>
                <button type="button" onClick={() => setSelected(image)} style={{ ...btn, padding: "8px 10px", fontSize: 12, background: "#14251b" }}>Preview</button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {images.length > 0 && filtered.length === 0 && <p style={{ color: "#a6c6b2" }}>No loaded images match “{search}”.</p>}
      {cursor && <div style={{ display: "flex", justifyContent: "center", marginTop: 18 }}><button type="button" onClick={() => void loadPage(true)} disabled={loading} style={btn}>{loading ? "Loading…" : "Load more images"}</button></div>}
      {!cursor && images.length > 0 && <p style={{ color: "#769984", textAlign: "center", fontSize: 12, marginTop: 16 }}>End of gallery results.</p>}

      {selected && (
        <div role="dialog" aria-modal="true" aria-label="Image preview" onClick={() => setSelected(null)} style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,.86)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
          <div onClick={e => e.stopPropagation()} style={{ width: "min(900px, 100%)", maxHeight: "90vh", overflow: "auto", border: "1px solid rgba(91,255,160,.35)", borderRadius: 16, background: "#08110b", padding: 16, color: "#e8fff0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 12 }}>
              <strong style={{ overflowWrap: "anywhere" }}>{selected.display_name || selected.public_id}</strong>
              <button type="button" onClick={() => setSelected(null)} style={btn}>Close ✕</button>
            </div>
            <img src={selected.secure_url} alt={selected.display_name || selected.public_id} style={{ maxWidth: "100%", maxHeight: "65vh", display: "block", margin: "0 auto", objectFit: "contain" }} />
            <p style={{ color: "#a6c6b2", fontSize: 12, overflowWrap: "anywhere" }}>{selected.secure_url}</p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" onClick={() => void copyUrl(selected.secure_url)} style={btn}>Copy image URL</button>
              <a href={selected.secure_url} target="_blank" rel="noreferrer" style={{ ...btn, textDecoration: "none", display: "inline-flex", alignItems: "center" }}>Open original ↗</a>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
