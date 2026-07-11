import { useEffect, useState } from "react";
import { api } from "../api";
import { sectionStyle, sectionTitleStyle, smallButtonStyle, inputStyle } from "./modalStyles";

// The structured brand profile that drives relevance scoring (audience/viewpoints/topics)
// and reply drafting (voice/viewpoints/key_messages/cta_rules/guardrails). Extracted from
// the client's uploaded strategy docs, then human-reviewed field-by-field before saving.
const FIELDS = [
  ["voice_guide", "Voice & how they write", "Tone, style, do's and don'ts, sample phrasings"],
  ["viewpoints", "Viewpoints / stances", "Their actual opinions, used to take real positions in replies"],
  ["audience", "Audience & pain points", "Who they're reaching, used to judge which posts are worth engaging"],
  ["key_messages", "Key messages / proof points", "Core positioning they want to reinforce"],
  ["cta_rules", "CTA rules", "How/when to point to resources, and what NOT to push"],
  ["guardrails", "Guardrails (hard rules)", "Rules the drafter must never violate, enforced on every draft"],
];

const labelStyle = { fontSize: 12, fontWeight: 600, color: "var(--text-muted)", display: "block", marginBottom: 4 };

export default function BrandProfileSection({ client, onUpdated }) {
  const [fields, setFields] = useState({});
  const [topics, setTopics] = useState("");
  const [suggested, setSuggested] = useState([]);
  const [extracting, setExtracting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const next = {};
    FIELDS.forEach(([key]) => (next[key] = client[key] || ""));
    setFields(next);
    setTopics((client.topics || []).join(", "));
    setSuggested([]);
    setSaved(false);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.id]);

  const setField = (key, value) => {
    setFields((f) => ({ ...f, [key]: value }));
    setSaved(false);
  };

  const handleExtract = async () => {
    setExtracting(true);
    setError(null);
    try {
      const p = await api.extractBrandProfile(client.id);
      const next = {};
      FIELDS.forEach(([key]) => (next[key] = p[key] || ""));
      setFields(next);
      setTopics((p.topics || []).join(", "));
      const creators = (p.suggested_creators || []).map((c) => ({ ...c, resolving: true }));
      setSuggested(creators);
      setSaved(false);
      // Resolve each creator's LinkedIn URL in its own request (kept separate from
      // the extraction so no single call approaches the serverless time limit).
      creators.forEach(async (c, idx) => {
        try {
          const r = await api.resolveCreator(client.id, c.name);
          setSuggested((list) =>
            list.map((x, i) => (i === idx ? { ...x, profile_url: r.profile_url, verified: r.verified, resolving: false } : x))
          );
        } catch {
          setSuggested((list) => list.map((x, i) => (i === idx ? { ...x, resolving: false } : x)));
        }
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setExtracting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await api.updateClient(client.id, {
        ...fields,
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

  const handleAddCreator = async (creator, idx) => {
    const url = creator.profile_url?.trim();
    if (!url) return;
    try {
      await api.addWatchCreator(client.id, { profile_url: url, label: creator.name });
      setSuggested((list) => list.filter((_, i) => i !== idx));
      onUpdated?.();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleTrackAllVerified = async () => {
    const toTrack = suggested.filter((c) => c.verified && c.profile_url?.trim());
    for (const c of toTrack) {
      try {
        await api.addWatchCreator(client.id, { profile_url: c.profile_url.trim(), label: c.name });
      } catch (err) {
        setError(err.message);
      }
    }
    const trackedUrls = new Set(toTrack.map((c) => c.profile_url.trim()));
    setSuggested((list) => list.filter((c) => !trackedUrls.has((c.profile_url || "").trim())));
    onUpdated?.();
  };

  const updateCreatorUrl = (idx, url) =>
    setSuggested((list) => list.map((c, i) => (i === idx ? { ...c, profile_url: url } : c)));

  return (
    <section style={sectionStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div style={sectionTitleStyle}>Brand profile</div>
        <button onClick={handleExtract} disabled={extracting} style={smallButtonStyle}>
          {extracting ? "Extracting…" : "Extract from documents"}
        </button>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
        Upload the client's strategy doc under "Tone &amp; reference material" below, then extract. Review and edit every
        section before saving, nothing is applied until you save.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {FIELDS.map(([key, label, hint]) => (
          <div key={key}>
            <label style={labelStyle}>{label}</label>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 4 }}>{hint}</div>
            <textarea
              value={fields[key] || ""}
              onChange={(e) => setField(key, e.target.value)}
              style={{ ...inputStyle, width: "100%", minHeight: key === "voice_guide" ? 90 : 70, resize: "vertical" }}
            />
          </div>
        ))}
        <div>
          <label style={labelStyle}>Topics (comma-separated)</label>
          <input
            style={{ ...inputStyle, width: "100%" }}
            value={topics}
            onChange={(e) => {
              setTopics(e.target.value);
              setSaved(false);
            }}
          />
        </div>
      </div>

      {suggested.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <label style={labelStyle}>Suggested profiles to track (links auto-resolved, confirm before tracking)</label>
            {suggested.some((c) => c.verified && c.profile_url?.trim()) && (
              <button onClick={handleTrackAllVerified} style={smallButtonStyle}>
                Track all verified
              </button>
            )}
          </div>
          {suggested.map((c, idx) => (
            <div
              key={idx}
              style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px", marginBottom: 6 }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</span>
                {c.resolving ? (
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>resolving link…</span>
                ) : c.profile_url?.trim() ? (
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      padding: "1px 6px",
                      borderRadius: 6,
                      color: c.verified ? "var(--success)" : "var(--text-muted)",
                      border: `1px solid ${c.verified ? "var(--success)" : "var(--border)"}`,
                    }}
                  >
                    {c.verified ? "✓ verified" : "unverified, check"}
                  </span>
                ) : (
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>no link found, paste manually</span>
                )}
              </div>
              {c.reason && <div style={{ fontSize: 12, color: "var(--text-muted)", margin: "4px 0 6px" }}>{c.reason}</div>}
              <div style={{ display: "flex", gap: 6 }}>
                <input
                  placeholder="LinkedIn profile URL (not found, paste manually)"
                  value={c.profile_url || ""}
                  onChange={(e) => updateCreatorUrl(idx, e.target.value)}
                  style={{ ...inputStyle, flex: 1 }}
                />
                <button
                  onClick={() => handleAddCreator(c, idx)}
                  disabled={!c.profile_url?.trim()}
                  style={{ ...smallButtonStyle, background: "var(--primary)", color: "#fff", border: "none" }}
                >
                  Track
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {error && <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 8 }}>{error}</div>}
      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, marginTop: 12 }}>
        {saved && <span style={{ fontSize: 12, color: "var(--success)" }}>Saved</span>}
        <button
          onClick={handleSave}
          disabled={saving}
          style={{ ...smallButtonStyle, background: "var(--primary)", color: "#fff", border: "none" }}
        >
          {saving ? "Saving…" : "Save brand profile"}
        </button>
      </div>
    </section>
  );
}
