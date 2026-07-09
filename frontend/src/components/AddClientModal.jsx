import { useEffect, useState } from "react";
import Modal from "./Modal";
import ToneDocumentsSection from "./ToneDocumentsSection";
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
  const [step, setStep] = useState("details"); // "details" | "documents"
  const [name, setName] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [toneProfile, setToneProfile] = useState("");
  const [topics, setTopics] = useState("");
  const [burnerId, setBurnerId] = useState("");
  const [burners, setBurners] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [createdClient, setCreatedClient] = useState(null);

  useEffect(() => {
    if (!open) return;
    api.listBurners().then((data) => {
      setBurners(data);
      if (data.length > 0) setBurnerId(String(data[0].id));
    });
  }, [open]);

  const reset = () => {
    setStep("details");
    setName("");
    setSpecialty("");
    setLinkedinUrl("");
    setToneProfile("");
    setTopics("");
    setError(null);
    setCreatedClient(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleCreateDetails = async (e) => {
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
      });
      setCreatedClient(client);
      setStep("documents");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleFinish = () => {
    const client = createdClient;
    reset();
    onCreated(client);
  };

  if (step === "documents" && createdClient) {
    return (
      <Modal open={open} onClose={handleFinish} title={`Add reference material for ${createdClient.name}`}>
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
          Optional — upload interview transcripts, YouTube URLs, or writing samples now, or skip and add them later
          from "Manage profiles."
        </div>
        <ToneDocumentsSection client={createdClient} />
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 16 }}>
          <button
            onClick={handleFinish}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "none",
              background: "var(--primary)",
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            Done
          </button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal open={open} onClose={handleClose} title="Add client">
      <form onSubmit={handleCreateDetails} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <label style={labelStyle}>Client's LinkedIn profile</label>
          <input
            style={inputStyle}
            value={linkedinUrl}
            onChange={(e) => setLinkedinUrl(e.target.value)}
            placeholder="https://www.linkedin.com/in/..."
          />
        </div>
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
          <label style={labelStyle}>Burner account (fetches this client's posts)</label>
          {burners.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--danger)" }}>
              No burner accounts registered yet — this client can be added, but "Sync now" won't work until one is.
            </div>
          ) : (
            <select
              style={inputStyle}
              value={burnerId}
              onChange={(e) => setBurnerId(e.target.value)}
            >
              {burners.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.label} ({b.status})
                </option>
              ))}
            </select>
          )}
        </div>
        <div>
          <label style={labelStyle}>Tone profile (optional — can also fetch above or add later from documents)</label>
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
            {saving ? "Adding…" : "Continue"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
