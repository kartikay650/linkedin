import { useState } from "react";
import Modal from "./Modal";
import { api } from "../api";

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid var(--border)",
  fontSize: 13,
  fontFamily: "inherit",
};

const labelStyle = { fontSize: 12, fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: 4 };

export default function AddClientModal({ open, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [toneProfile, setToneProfile] = useState("");
  const [topics, setTopics] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const reset = () => {
    setName("");
    setSpecialty("");
    setToneProfile("");
    setTopics("");
    setError(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleSubmit = async (e) => {
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
        tone_profile: toneProfile.trim(),
        topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
      });
      reset();
      onCreated(client);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={handleClose} title="Add client">
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <label style={labelStyle}>Name</label>
          <input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr. Jane Smith" />
        </div>
        <div>
          <label style={labelStyle}>Specialty</label>
          <input
            style={inputStyle}
            value={specialty}
            onChange={(e) => setSpecialty(e.target.value)}
            placeholder="Cardiology"
          />
        </div>
        <div>
          <label style={labelStyle}>Topics (comma-separated)</label>
          <input
            style={inputStyle}
            value={topics}
            onChange={(e) => setTopics(e.target.value)}
            placeholder="heart failure, statins, cardiac imaging"
          />
        </div>
        <div>
          <label style={labelStyle}>Tone profile (optional — can add later from documents)</label>
          <textarea
            style={{ ...inputStyle, minHeight: 70, resize: "vertical" }}
            value={toneProfile}
            onChange={(e) => setToneProfile(e.target.value)}
            placeholder="Voice, do's/don'ts, sample phrases..."
          />
        </div>
        {error && <div style={{ fontSize: 12, color: "var(--danger)" }}>{error}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
          <button
            type="button"
            onClick={handleClose}
            style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", fontSize: 13 }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "none",
              background: "var(--primary)",
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
              opacity: saving ? 0.7 : 1,
            }}
          >
            {saving ? "Adding…" : "Add client"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
