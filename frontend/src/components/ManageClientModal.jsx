import { useEffect, useState } from "react";
import Modal from "./Modal";
import Badge from "./Badge";
import EmptyState from "./EmptyState";
import ToneDocumentsSection from "./ToneDocumentsSection";
import BrandProfileSection from "./BrandProfileSection";
import { api } from "../api";
import { sectionStyle, sectionTitleStyle, smallButtonStyle, inputStyle } from "./modalStyles";

export default function ManageClientModal({ open, onClose, client, onUpdated, onDeleted }) {
  if (!open || !client) return null;
  return (
    <Modal open={open} onClose={onClose} title={`Manage ${client.name}`} width={640}>
      <ClientDetailsSection client={client} onUpdated={onUpdated} />
      <WatchCreatorsSection client={client} />
      <ProspectsSection client={client} />
      <ToneDocumentsSection client={client} onUpdated={onUpdated} />
      <BrandProfileSection client={client} onUpdated={onUpdated} />
      <BenchmarkExamplesSection client={client} onUpdated={onUpdated} />
      <FeedbackSection client={client} />
      <DeleteClientSection client={client} onDeleted={onDeleted} />
    </Modal>
  );
}

function DeleteClientSection({ client, onDeleted }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const handleDelete = async () => {
    if (!window.confirm(`Delete ${client.name}? This removes their profile, documents, tracked profiles and posts. This can't be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteClient(client.id);
      onDeleted?.(client.id);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <section style={{ borderTop: "1px solid var(--border)", paddingTop: 16, marginTop: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Remove this client and everything associated with them.</div>
        <button
          onClick={handleDelete}
          disabled={busy}
          style={{ ...smallButtonStyle, color: "var(--danger)", borderColor: "var(--border)" }}
        >
          {busy ? "Deleting…" : "Delete client"}
        </button>
      </div>
      {error && <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 8 }}>{error}</div>}
    </section>
  );
}

function ClientDetailsSection({ client, onUpdated }) {
  const [name, setName] = useState(client.name);
  const [specialty, setSpecialty] = useState(client.specialty);
  const [linkedinUrl, setLinkedinUrl] = useState(client.linkedin_url || "");
  const [topics, setTopics] = useState(client.topics.join(", "));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setName(client.name);
    setSpecialty(client.specialty);
    setLinkedinUrl(client.linkedin_url || "");
    setTopics(client.topics.join(", "));
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
        linkedin_url: linkedinUrl.trim() || null,
        topics: topics.split(",").map((t) => t.trim()).filter(Boolean),
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
            Client's LinkedIn profile
          </label>
          <input
            style={{ ...inputStyle, width: "100%" }}
            value={linkedinUrl}
            onChange={(e) => setLinkedinUrl(e.target.value)}
            placeholder="https://www.linkedin.com/in/..."
          />
        </div>
        <div>
          <label style={{ fontSize: 12, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>
            Topics (comma-separated)
          </label>
          <input style={{ ...inputStyle, width: "100%" }} value={topics} onChange={(e) => setTopics(e.target.value)} />
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

function BenchmarkExamplesSection({ client, onUpdated }) {
  const [text, setText] = useState(client.benchmark_examples || "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setText(client.benchmark_examples || "");
    setSaved(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await api.updateClient(client.id, { benchmark_examples: text });
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
      <div style={sectionTitleStyle}>Example replies (tone benchmark)</div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
        Paste a few ideal replies (and, if useful, ones to avoid) in this client's voice. Every new draft is
        anchored to these. Label them, e.g. "GOOD: ..." / "AVOID: ...".
      </div>
      <textarea
        rows={6}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"GOOD: Good friends and love keep the heart healthy, Francesco. We really underestimate how deeply relationships affect the body.\nAVOID: Great post! This is such an important reminder."}
        style={{ ...inputStyle, width: "100%", resize: "vertical", lineHeight: 1.5, fontFamily: "inherit" }}
      />
      {error && <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 6 }}>{error}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, marginTop: 8 }}>
        {saved && <span style={{ fontSize: 12, color: "var(--success)" }}>Saved</span>}
        <button
          onClick={handleSave}
          disabled={saving}
          style={{ ...smallButtonStyle, background: "var(--primary)", color: "#fff", border: "none" }}
        >
          {saving ? "Saving…" : "Save examples"}
        </button>
      </div>
    </section>
  );
}

function FeedbackSection({ client }) {
  const [notes, setNotes] = useState([]);
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () => api.listFeedback(client.id).then(setNotes).catch(() => {});

  useEffect(() => {
    load();
    setText("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const handleAdd = async (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    setAdding(true);
    try {
      await api.addFeedback(client.id, text.trim());
      setText("");
      load();
    } finally {
      setAdding(false);
    }
  };

  const handleDelete = async (id) => {
    await api.deleteFeedback(client.id, id);
    load();
  };

  // Only the most recent few are actually fed to the drafter; flag the rest as inactive.
  const ACTIVE = 5;

  return (
    <section style={sectionStyle}>
      <div style={sectionTitleStyle}>AI guidance notes</div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
        Corrections applied to every new draft for this client. The {ACTIVE} most recent are active — prune old ones so guidance stays sharp.
      </div>
      {notes.length === 0 && (
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8 }}>No notes yet.</div>
      )}
      {notes.map((n, i) => (
        <div
          key={n.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 10,
            padding: "8px 10px",
            border: "1px solid var(--border)",
            borderRadius: 8,
            marginBottom: 6,
            opacity: i < ACTIVE ? 1 : 0.55,
          }}
        >
          <div style={{ minWidth: 0, fontSize: 13 }}>
            {i >= ACTIVE && <Badge tone="neutral">inactive</Badge>} {n.note}
          </div>
          <button onClick={() => handleDelete(n.id)} style={{ ...smallButtonStyle, color: "var(--danger)", flexShrink: 0 }}>
            Delete
          </button>
        </div>
      ))}
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <input
          placeholder="e.g. Keep replies under two sentences."
          value={text}
          onChange={(e) => setText(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button type="submit" disabled={adding} style={{ ...smallButtonStyle, background: "var(--primary)", color: "#fff", border: "none" }}>
          {adding ? "Adding…" : "Add note"}
        </button>
      </form>
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
          title="Coming soon"
          subtitle="Automatic prospect discovery is on the way. For now, people found in the client's documents are tracked automatically, and you can add more under Tracked profiles above."
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
