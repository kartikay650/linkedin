import { useEffect, useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";

// The shared, agency-wide creator database. Prospects (lead-gen targets) and
// tracked creators (fetched + commented on) live here. Operators add their own
// and promote a prospect to tracked — no automatic discovery.
export default function ProspectsPanel() {
  const [creators, setCreators] = useState([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState("prospect");
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true);
    api.listCreators().then(setCreators).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const prospects = creators.filter((c) => c.kind === "prospect");
  const tracked = creators.filter((c) => c.kind === "creator");

  const add = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSaving(true);
    try {
      await api.addCreator({ name: name.trim(), profile_url: url.trim(), kind });
      setName(""); setUrl("");
      load();
    } catch (err) {
      toast(`Couldn't add: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const setKindOf = async (c, k) => {
    try { await api.updateCreator(c.id, { kind: k }); load(); }
    catch (err) { toast(`Couldn't update: ${err.message}`); }
  };
  const remove = async (c) => {
    if (!window.confirm(`Remove ${c.name || c.profile_url} from the list?`)) return;
    try { await api.deleteCreator(c.id); load(); }
    catch (err) { toast(`Couldn't remove: ${err.message}`); }
  };

  const Section = ({ title, subtitle, rows, promoteTo, promoteLabel }) => (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>{title}</h3>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{rows.length}</span>
      </div>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>{subtitle}</div>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden" }}>
        {rows.length === 0 && <div style={{ padding: 14, fontSize: 13, color: "var(--text-muted)" }}>None yet.</div>}
        {rows.map((c, i) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", borderTop: i ? "1px solid var(--border)" : "none" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name || "—"}</div>
              <a href={c.profile_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--primary)", textDecoration: "none" }}>
                {c.profile_url.replace("https://www.linkedin.com", "").replace(/\/$/, "")}
              </a>
            </div>
            <button onClick={() => setKindOf(c, promoteTo)} style={pillBtn}>{promoteLabel}</button>
            <button onClick={() => remove(c)} style={{ ...pillBtn, color: "var(--danger)", borderColor: "var(--border)" }}>Remove</button>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div>
      <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 24, alignItems: "center" }}>
        <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} style={{ ...inp, width: 180 }} />
        <input placeholder="LinkedIn profile URL" value={url} onChange={(e) => setUrl(e.target.value)} style={{ ...inp, flex: 1, minWidth: 240 }} />
        <select value={kind} onChange={(e) => setKind(e.target.value)} style={{ ...inp, width: 150 }}>
          <option value="prospect">Prospect</option>
          <option value="creator">Tracked creator</option>
        </select>
        <button type="submit" disabled={saving} style={{ ...pillBtn, background: "var(--primary)", color: "#fff", border: "none", padding: "9px 16px" }}>
          {saving ? "Adding…" : "Add"}
        </button>
      </form>

      {loading ? (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>
      ) : (
        <>
          <Section
            title="Tracked creators"
            subtitle="Their recent posts are pulled into every client's feed and ranked by relevance."
            rows={tracked}
            promoteTo="prospect"
            promoteLabel="Move to prospects"
          />
          <Section
            title="Prospects"
            subtitle="Lead-gen targets from your list. Not auto-commented — promote one to start tracking their posts."
            rows={prospects}
            promoteTo="creator"
            promoteLabel="Track"
          />
        </>
      )}
    </div>
  );
}

const inp = { padding: "9px 12px", borderRadius: 8, border: "1px solid var(--border)", fontSize: 14, fontFamily: "inherit", background: "var(--surface)" };
const pillBtn = { padding: "6px 12px", borderRadius: 8, border: "1px solid var(--border)", background: "var(--surface)", fontSize: 13, fontWeight: 600, whiteSpace: "nowrap" };
