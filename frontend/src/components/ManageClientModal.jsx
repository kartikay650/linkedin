import { useEffect, useState } from "react";
import Modal from "./Modal";
import Badge from "./Badge";
import EmptyState from "./EmptyState";
import { api } from "../api";

const sectionStyle = { marginBottom: 28 };
const sectionTitleStyle = { fontSize: 13, fontWeight: 700, marginBottom: 10 };
const smallButtonStyle = {
  padding: "6px 12px",
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  fontSize: 12,
  fontWeight: 600,
};
const inputStyle = {
  padding: "7px 10px",
  borderRadius: 8,
  border: "1px solid var(--border)",
  fontSize: 13,
  fontFamily: "inherit",
};

export default function ManageClientModal({ open, onClose, client, onUpdated }) {
  if (!open || !client) return null;
  return (
    <Modal open={open} onClose={onClose} title={`Manage ${client.name}`} width={640}>
      <ClientDetailsSection client={client} onUpdated={onUpdated} />
      <WatchCreatorsSection client={client} />
      <ProspectsSection client={client} />
      <ToneDocumentsSection client={client} />
    </Modal>
  );
}

function ClientDetailsSection({ client, onUpdated }) {
  const [name, setName] = useState(client.name);
  const [specialty, setSpecialty] = useState(client.specialty);
  const [topics, setTopics] = useState(client.topics.join(", "));
  const [burnerId, setBurnerId] = useState(client.burner_id ? String(client.burner_id) : "");
  const [burners, setBurners] = useState([]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listBurners().then(setBurners);
    setName(client.name);
    setSpecialty(client.specialty);
    setTopics(client.topics.join(", "));
    setBurnerId(client.burner_id ? String(client.burner_id) : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await api.updateClient(client.id, {
        name: name.trim(),
        specialty: specialty.trim(),
        topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
        burner_id: burnerId ? Number(burnerId) : null,
      });
      setSaved(true);
      onUpdated?.();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>Client details</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Name</label>
          <input style={{ ...inputStyle, width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Specialty</label>
          <input style={{ ...inputStyle, width: "100%" }} value={specialty} onChange={(e) => setSpecialty(e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
            Topics (comma-separated)
          </label>
          <input style={{ ...inputStyle, width: "100%" }} value={topics} onChange={(e) => setTopics(e.target.value)} />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
            Burner account
          </label>
          <select style={{ ...inputStyle, width: "100%" }} value={burnerId} onChange={(e) => setBurnerId(e.target.value)}>
            <option value="">— none assigned —</option>
            {burners.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label} ({b.status})
              </option>
            ))}
          </select>
        </div>
        {error && <div style={{ fontSize: 12, color: "var(--danger)" }}>{error}</div>}
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
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

function WatchCreatorsSection({ client }) {
  const [creators, setCreators] = useState([]);
  const [profileUrl, setProfileUrl] = useState("");
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);

  const load = () => api.listWatchCreators(client.id).then(setCreators);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!profileUrl.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await api.addWatchCreator(client.id, { profile_url: profileUrl.trim(), label: label.trim() });
      setProfileUrl("");
      setLabel("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (creatorId) => {
    await api.removeWatchCreator(client.id, creatorId);
    load();
  };

  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>Tracked profiles</div>
      {creators.length === 0 && (
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>
          No profiles tracked yet for this client.
        </div>
      )}
      {creators.map((c) => (
        <div
          key={c.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "8px 10px",
            border: "1px solid var(--border)",
            borderRadius: 8,
            marginBottom: 6,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{c.label || "(no label)"}</div>
            <a
              href={c.profile_url}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 12, color: "var(--text-muted)", wordBreak: "break-all" }}
            >
              {c.profile_url}
            </a>
          </div>
          <button onClick={() => handleRemove(c.id)} style={{ ...smallButtonStyle, color: "var(--danger)", flexShrink: 0 }}>
            Remove
          </button>
        </div>
      ))}

      <form onSubmit={handleAdd} style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <input
          placeholder="LinkedIn profile URL"
          value={profileUrl}
          onChange={(e) => setProfileUrl(e.target.value)}
          style={{ ...inputStyle, flex: 2 }}
        />
        <input
          placeholder="Label"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button type="submit" disabled={adding} style={{ ...smallButtonStyle, background: "var(--primary)", color: "#fff", border: "none" }}>
          Add
        </button>
      </form>
      {error && <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 6 }}>{error}</div>}
    </section>
  );
}

function ProspectsSection({ client }) {
  const [prospects, setProspects] = useState([]);
  const [discovering, setDiscovering] = useState(false);
  const [notAvailable, setNotAvailable] = useState(false);

  const load = () => api.listProspects(client.id).then(setProspects);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const handleDiscover = async () => {
    setDiscovering(true);
    setNotAvailable(false);
    try {
      const res = await api.discoverProspects(client.id);
      if (res.status === "not_yet_available") {
        setNotAvailable(true);
      } else {
        load();
      }
    } finally {
      setDiscovering(false);
    }
  };

  const handleApprove = async (id) => {
    await api.approveProspect(client.id, id);
    load();
  };
  const handleReject = async (id) => {
    await api.rejectProspect(client.id, id);
    load();
  };

  const pending = prospects.filter((p) => p.status === "pending_review");
  const decided = prospects.filter((p) => p.status !== "pending_review");

  return (
    <section style={sectionStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={sectionTitleStyle}>Prospects</div>
        <button onClick={handleDiscover} disabled={discovering} style={smallButtonStyle}>
          {discovering ? "Searching…" : "Find prospects"}
        </button>
      </div>

      {notAvailable && (
        <EmptyState
          title="Not available yet"
          subtitle="Automated prospect discovery is still being built — LinkedIn search carries a checkpoint risk we haven't solved. Add profiles manually above for now."
        />
      )}

      {!notAvailable && pending.length === 0 && decided.length === 0 && (
        <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No prospects yet.</div>
      )}

      {pending.map((p) => (
        <div
          key={p.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "8px 10px",
            border: "1px solid var(--border)",
            borderRadius: 8,
            marginBottom: 6,
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{p.name || p.profile_url}</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{p.headline}</div>
          </div>
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            <button onClick={() => handleApprove(p.id)} style={{ ...smallButtonStyle, color: "var(--success)" }}>
              Approve
            </button>
            <button onClick={() => handleReject(p.id)} style={{ ...smallButtonStyle, color: "var(--danger)" }}>
              Reject
            </button>
          </div>
        </div>
      ))}

      {decided.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ fontSize: 12, color: "var(--text-muted)", cursor: "pointer" }}>
            {decided.length} previously reviewed
          </summary>
          {decided.map((p) => (
            <div key={p.id} style={{ display: "flex", justifyContent: "space-between", padding: "6px 4px", fontSize: 12, color: "var(--text-muted)" }}>
              <span>{p.name || p.profile_url}</span>
              <Badge tone={p.status === "approved" ? "success" : "danger"}>{p.status}</Badge>
            </div>
          ))}
        </details>
      )}
    </section>
  );
}

function ToneDocumentsSection({ client }) {
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
