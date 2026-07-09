import { useEffect, useState } from "react";
import Badge from "./Badge";
import { api } from "../api";
import { sectionTitleStyle, smallButtonStyle, inputStyle } from "./modalStyles";

export default function ToneDocumentsSection({ client, onUpdated }) {
  const [documents, setDocuments] = useState([]);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [synthesizing, setSynthesizing] = useState(false);
  const [proposedTone, setProposedTone] = useState(client.tone_profile || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = () => api.listDocuments(client.id).then(setDocuments);

  useEffect(() => {
    load();
    setProposedTone(client.tone_profile || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadDocument(client.id, file);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleAddYoutube = async (e) => {
    e.preventDefault();
    if (!youtubeUrl.trim()) return;
    setUploading(true);
    setError(null);
    try {
      await api.addYoutubeDocument(client.id, youtubeUrl.trim());
      setYoutubeUrl("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (docId) => {
    await api.deleteDocument(client.id, docId);
    load();
  };

  const handleSynthesize = async () => {
    setSynthesizing(true);
    setError(null);
    try {
      const res = await api.synthesizeTone(client.id);
      setProposedTone(res.proposed_tone_profile);
    } catch (err) {
      setError(err.message);
    } finally {
      setSynthesizing(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await api.updateClient(client.id, { tone_profile: proposedTone });
      setSaved(true);
      onUpdated?.();
    } finally {
      setSaving(false);
    }
  };

  const statusTone = { pending: "neutral", processing: "neutral", done: "success", failed: "danger" };

  return (
    <section>
      <div style={sectionTitleStyle}>Tone & reference material</div>

      {documents.map((d) => (
        <div key={d.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 2px" }}>
          <div style={{ fontSize: 12, minWidth: 0 }}>
            <span style={{ fontWeight: 600 }}>{d.original_filename || d.source_url}</span>
            {d.status === "failed" && <div style={{ color: "var(--danger)" }}>{d.error_detail}</div>}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            <Badge tone={statusTone[d.status]}>{d.status}</Badge>
            <button onClick={() => handleDelete(d.id)} style={{ border: "none", background: "none", color: "var(--text-muted)", fontSize: 14 }}>
              ×
            </button>
          </div>
        </div>
      ))}

      <div style={{ display: "flex", gap: 10, marginTop: 10, alignItems: "center" }}>
        <label style={{ ...smallButtonStyle, display: "inline-block" }}>
          {uploading ? "Uploading…" : "Upload file"}
          <input type="file" accept=".pdf,.docx,.txt" onChange={handleFileChange} disabled={uploading} style={{ display: "none" }} />
        </label>
      </div>

      <form onSubmit={handleAddYoutube} style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <input
          placeholder="YouTube interview URL"
          value={youtubeUrl}
          onChange={(e) => setYoutubeUrl(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button type="submit" disabled={uploading} style={smallButtonStyle}>
          Add
        </button>
      </form>
      {error && <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 6 }}>{error}</div>}

      <div style={{ marginTop: 20 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)" }}>Tone profile</label>
          <button onClick={handleSynthesize} disabled={synthesizing} style={smallButtonStyle}>
            {synthesizing ? "Synthesizing…" : "Synthesize from documents"}
          </button>
        </div>
        <textarea
          value={proposedTone}
          onChange={(e) => {
            setProposedTone(e.target.value);
            setSaved(false);
          }}
          style={{ ...inputStyle, width: "100%", minHeight: 100, resize: "vertical" }}
        />
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, marginTop: 8 }}>
          {saved && <span style={{ fontSize: 12, color: "var(--success)" }}>Saved</span>}
          <button
            onClick={handleSave}
            disabled={saving}
            style={{ ...smallButtonStyle, background: "var(--primary)", color: "#fff", border: "none" }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </section>
  );
}
