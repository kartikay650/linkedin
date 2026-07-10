import { useEffect, useState } from "react";
import Modal from "./Modal";
import { api } from "../api";

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--border)",
  fontSize: 13,
  fontFamily: "inherit",
  boxSizing: "border-box",
};

const labelStyle = { fontSize: 12, fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: 4 };

const BRAND_KEYS = ["voice_guide", "viewpoints", "audience", "key_messages", "cta_rules", "guardrails"];

export default function AddClientModal({ open, onClose, onCreated }) {
  const [files, setFiles] = useState([]);
  const [reading, setReading] = useState(false);
  const [readNote, setReadNote] = useState(null);

  const [name, setName] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [toneProfile, setToneProfile] = useState("");
  const [topics, setTopics] = useState("");
  const [brand, setBrand] = useState({}); // hidden extracted sections, saved on create

  const [burnerId, setBurnerId] = useState("");
  const [burners, setBurners] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    api.listBurners().then((data) => {
      setBurners(data);
      if (data.length > 0) setBurnerId(String(data[0].id));
    }).catch(() => {});
  }, [open]);

  const reset = () => {
    setFiles([]); setReading(false); setReadNote(null);
    setName(""); setSpecialty(""); setLinkedinUrl(""); setToneProfile(""); setTopics(""); setBrand({});
    setError(null);
  };

  const handleClose = () => { reset(); onClose(); };

  const handleFiles = async (e) => {
    const chosen = Array.from(e.target.files || []);
    if (!chosen.length) return;
    setFiles(chosen);
    setReading(true);
    setReadNote(null);
    setError(null);
    try {
      const p = await api.extractFromUpload(chosen);
      if (p.name) setName(p.name);
      if (p.specialty) setSpecialty(p.specialty);
      if (Array.isArray(p.topics)) setTopics(p.topics.join(", "));
      if (p.voice_guide) setToneProfile(p.voice_guide);
      const b = {};
      BRAND_KEYS.forEach((k) => (b[k] = p[k] || ""));
      setBrand(b);
      setReadNote("Filled from your document(s) — review and edit anything below before creating.");
    } catch (err) {
      setError(err.message);
    } finally {
      setReading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!name.trim() || !specialty.trim()) {
      setError("Name and specialty are required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const client = await api.createClient({
        name: name.trim(),
        specialty: specialty.trim(),
        linkedin_url: linkedinUrl.trim() || null,
        tone_profile: toneProfile.trim(),
        topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
        burner_id: burnerId ? Number(burnerId) : null,
        ...brand,
      });
      // Persist the uploaded docs to the new client (so they're saved + reviewable in Manage).
      for (const f of files) {
        try { await api.uploadDocument(client.id, f); } catch { /* keep going */ }
      }
      reset();
      onCreated(client);
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={handleClose} title="Add client">
      <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {/* Document-first: upload to auto-fill everything below */}
        <div style={{ border: "1px dashed var(--border)", borderRadius: 10, padding: 14, background: "var(--bg)" }}>
          <label style={{ ...labelStyle, marginBottom: 6 }}>Upload the client's strategy doc(s) to auto-fill</label>
          <input type="file" accept=".pdf,.docx,.txt" multiple onChange={handleFiles} disabled={reading || saving} style={{ fontSize: 13 }} />
          {files.length > 0 && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>
              {files.map((f) => f.name).join(", ")}
            </div>
          )}
          {reading && <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>Reading documents…</div>}
          {readNote && <div style={{ fontSize: 12, color: "var(--success)", marginTop: 6 }}>{readNote}</div>}
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
            Optional — you can also fill everything in by hand. PDF, DOCX or TXT.
          </div>
        </div>

        <div>
          <label style={labelStyle}>Client's LinkedIn profile</label>
          <input style={inputStyle} value={linkedinUrl} onChange={(e) => setLinkedinUrl(e.target.value)} placeholder="https://www.linkedin.com/in/..." />
        </div>
        <div>
          <label style={labelStyle}>Name</label>
          <input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr. Jane Smith" />
        </div>
        <div>
          <label style={labelStyle}>Specialty</label>
          <input style={inputStyle} value={specialty} onChange={(e) => setSpecialty(e.target.value)} placeholder="Cardiology" />
        </div>
        <div>
          <label style={labelStyle}>Topics (comma-separated)</label>
          <input style={inputStyle} value={topics} onChange={(e) => setTopics(e.target.value)} placeholder="heart failure, statins, cardiac imaging" />
        </div>
        <div>
          <label style={labelStyle}>Burner account (legacy — not needed with Apify)</label>
          {burners.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>None registered. Fetching now runs through Apify, so this isn't required.</div>
          ) : (
            <select style={inputStyle} value={burnerId} onChange={(e) => setBurnerId(e.target.value)}>
              {burners.map((b) => (
                <option key={b.id} value={b.id}>{b.label} ({b.status})</option>
              ))}
            </select>
          )}
        </div>
        <div>
          <label style={labelStyle}>Tone / voice{brand.voice_guide ? " (auto-filled — editable)" : ""}</label>
          <textarea
            style={{ ...inputStyle, minHeight: 80, resize: "vertical" }}
            value={toneProfile}
            onChange={(e) => setToneProfile(e.target.value)}
            placeholder="Voice, do's/don'ts, sample phrases..."
          />
        </div>
        {Object.values(brand).some((v) => v) && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            The full brand profile (viewpoints, audience, key messages, guardrails) and suggested creators were also
            extracted — review and refine them under "Manage profiles" after creating.
          </div>
        )}
        {error && <div style={{ fontSize: 12, color: "var(--danger)" }}>{error}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button type="button" onClick={handleClose} style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", fontSize: 13 }}>
            Cancel
          </button>
          <button type="submit" disabled={saving || reading} style={{ padding: "8px 14px", borderRadius: 8, border: "none", background: "var(--primary)", color: "#fff", fontSize: 13, fontWeight: 600, opacity: saving || reading ? 0.7 : 1 }}>
            {saving ? "Creating…" : "Create client"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
