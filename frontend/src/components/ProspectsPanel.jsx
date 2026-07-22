import { useEffect, useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";
import { runSync } from "../syncRunner.js";

// The shared, agency-wide creator database. Prospects (lead-gen targets) and
// tracked creators (fetched + commented on) live here. Operators add their own
// and promote a prospect to tracked — no automatic discovery.
export default function ProspectsPanel() {
  const [creators, setCreators] = useState([]);
  const [clients, setClients] = useState([]);
  const [assignOpen, setAssignOpen] = useState(null); // creator id whose client picker is open
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState("prospect");
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");
  const [addMsg, setAddMsg] = useState(null); // {type: "error"|"ok", text}
  const [sync, setSync] = useState(null); // {done, total, phase}

  const handleSyncAll = async () => {
    if (sync && sync.phase === "firing") return; // already running
    setSync({ done: 0, total: 0, phase: "planning" });
    try {
      await runSync({ onProgress: setSync });
    } catch (e) {
      toast(`Sync hit a snag: ${e.message}. Already-queued profiles keep fetching; try again for the rest.`);
    }
  };

  const load = () => {
    setLoading(true);
    api.listCreators().then(setCreators).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(load, []);
  useEffect(() => { api.listClients().then(setClients).catch(() => {}); }, []);

  // Assign / unassign ONE client to a creator. Driven by the checkbox's desired state
  // (shouldHave) and sent as a single-client add/remove — so ticking several boxes
  // quickly can't overwrite each other (the old full-list save raced and dropped ticks).
  const setClientAssignment = async (creatorId, clientId, shouldHave) => {
    const apply = (add) => setCreators((prev) => prev.map((x) => {
      if (x.id !== creatorId) return x;
      const ids = new Set(x.client_ids || []);
      if (add) ids.add(clientId); else ids.delete(clientId);
      return { ...x, client_ids: [...ids] };
    }));
    apply(shouldHave); // optimistic
    try {
      if (shouldHave) await api.assignCreatorClient(creatorId, clientId);
      else await api.unassignCreatorClient(creatorId, clientId);
    } catch (err) {
      apply(!shouldHave); // revert just this toggle
      toast(`Couldn't save that change: ${err.message}. Try again.`);
    }
  };

  const q = query.trim().toLowerCase();
  const match = (c) => !q || `${c.name || ""} ${c.headline || ""} ${c.profile_url || ""}`.toLowerCase().includes(q);
  // How often a tracked creator posts — controls fetch cadence (spend).
  const setFreq = async (c, freq) => {
    setCreators((prev) => prev.map((x) => (x.id === c.id ? { ...x, post_frequency: freq } : x)));
    try {
      await api.updateCreator(c.id, { post_frequency: freq });
    } catch (err) {
      toast(`Couldn't update frequency: ${err.message}`);
      load();
    }
  };

  const prospects = creators.filter((c) => c.kind === "prospect" && match(c));
  const tracked = creators.filter((c) => c.kind === "creator" && match(c));

  const add = async (e) => {
    e.preventDefault();
    setAddMsg(null);
    const u = url.trim();
    // Clear, unmissable guidance instead of silently doing nothing.
    if (!u) {
      setAddMsg({ type: "error", text: "Paste the person's LinkedIn profile URL (like https://www.linkedin.com/in/their-name) to save them." });
      return;
    }
    if (!/linkedin\.com\/in\//i.test(u)) {
      setAddMsg({ type: "error", text: "That doesn't look like a LinkedIn profile. The link should contain linkedin.com/in/… (a personal profile, not a company page or a search link)." });
      return;
    }
    setSaving(true);
    try {
      const created = await api.addCreator({ name: name.trim(), profile_url: u, kind });
      const wasDup = creators.some((c) => c.id === created.id); // addCreator returns the existing row on a duplicate URL
      setName(""); setUrl("");
      await load();
      if (wasDup) {
        const asWhat = created.kind === "creator" ? "a tracked creator" : "a prospect";
        setAddMsg({ type: "ok", text: `${created.name || "That profile"} is already in the list (as ${asWhat}).` });
      } else {
        setAddMsg({ type: "ok", text: `Saved ${created.name || "profile"}.` });
      }
    } catch (err) {
      setAddMsg({ type: "error", text: err.message || "Couldn't save that profile. Please try again." });
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

  const Section = ({ title, subtitle, rows, promoteTo, promoteLabel, assignable }) => (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>{title}</h3>
        <span style={{ fontSize: 13, color: "var(--text-muted)" }}>{rows.length}</span>
      </div>
      <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 10 }}>{subtitle}</div>
      <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: assignable ? "visible" : "hidden" }}>
        {rows.length === 0 && <div style={{ padding: 14, fontSize: 13, color: "var(--text-muted)" }}>None yet.</div>}
        {rows.map((c, i) => (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", borderTop: i ? "1px solid var(--border)" : "none" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.name || "—"}</div>
              <a href={c.profile_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--primary)", textDecoration: "none" }}>
                {c.profile_url.replace("https://www.linkedin.com", "").replace(/\/$/, "")}
              </a>
            </div>
            {assignable && (
              <select
                value={c.post_frequency || "sometimes"}
                onChange={(e) => setFreq(c, e.target.value)}
                title="How often they post — controls how often we re-fetch them (fewer fetches = lower cost)"
                style={{ ...pillBtn, padding: "6px 8px", cursor: "pointer" }}
              >
                <option value="yes">Weekly+</option>
                <option value="sometimes">Monthly</option>
                <option value="no">Rarely</option>
              </select>
            )}
            {assignable && (
              <div style={{ position: "relative" }}>
                <button onClick={() => setAssignOpen(assignOpen === c.id ? null : c.id)} style={pillBtn}>
                  {(c.client_ids?.length || 0)} client{(c.client_ids?.length || 0) === 1 ? "" : "s"} ▾
                </button>
                {assignOpen === c.id && (
                  <div style={popover}>
                    {clients.length === 0 && (
                      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No clients yet.</div>
                    )}
                    {clients.map((cl) => (
                      <label key={cl.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 2px", fontSize: 13, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={(c.client_ids || []).includes(cl.id)}
                          onChange={(e) => setClientAssignment(c.id, cl.id, e.target.checked)}
                        />
                        {cl.name}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button onClick={() => setKindOf(c, promoteTo)} style={pillBtn}>{promoteLabel}</button>
            <button onClick={() => remove(c)} style={{ ...pillBtn, color: "var(--danger)", borderColor: "var(--border)" }}>Remove</button>
          </div>
        ))}
      </div>
    </div>
  );

  const busy = sync && (sync.phase === "firing" || sync.phase === "planning");
  const pct = sync && sync.total ? Math.round((sync.done / sync.total) * 100) : 0;

  return (
    <div>
      <div style={{ marginBottom: 20, padding: 14, border: "1px solid var(--border)", borderRadius: "var(--radius)", background: "var(--surface)", boxShadow: "var(--shadow)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>Sync all tracked profiles</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2, maxWidth: 640 }}>
              Fetches every due profile once and adds fresh posts to all clients tracking them. Infrequent posters are skipped until they're due, to keep scraping cost down.
            </div>
          </div>
          <button
            onClick={handleSyncAll}
            disabled={busy}
            style={{ ...pillBtn, background: busy ? "#93b4f8" : "var(--primary)", color: "#fff", border: "none", padding: "9px 16px", whiteSpace: "nowrap" }}
          >
            {busy ? "Syncing…" : "Sync all"}
          </button>
        </div>
        {sync && sync.phase !== "empty" && (
          <div style={{ marginTop: 12 }}>
            <div style={{ height: 6, background: "var(--bg)", borderRadius: 4, overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: "var(--primary)", transition: "width .3s" }} />
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>
              {sync.phase === "planning"
                ? "Working out what's due…"
                : sync.phase === "done"
                  ? `Queued all ${sync.total} profiles. New posts arrive over the next few minutes.`
                  : `Queued ${sync.done} / ${sync.total} profiles for fetching…`}
            </div>
          </div>
        )}
        {sync && sync.phase === "empty" && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10 }}>
            Nothing due right now — everything tracked was fetched recently.
          </div>
        )}
      </div>

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
      {addMsg && (
        <div style={{ fontSize: 12, marginTop: -14, marginBottom: 16, color: addMsg.type === "error" ? "var(--danger)" : "var(--success)" }}>
          {addMsg.text}
        </div>
      )}

      <div style={{ position: "relative", marginBottom: 18 }}>
        <input
          placeholder="Search the list by name, headline, or profile…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ ...inp, width: "100%", boxSizing: "border-box", paddingRight: 68 }}
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", border: "none", background: "none", color: "var(--text-muted)", fontSize: 12, cursor: "pointer" }}
          >
            Clear
          </button>
        )}
      </div>

      {loading ? (
        <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>
      ) : (
        <>
          <Section
            title="Tracked creators"
            subtitle="Assign each creator to the clients who should see their posts (only assigned clients get them). Set how often they post — frequent posters are fetched often, rare ones seldom, to keep scraping cost down."
            rows={tracked}
            promoteTo="prospect"
            promoteLabel="Move to prospects"
            assignable
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
const popover = { position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 20, minWidth: 200, maxHeight: 260, overflowY: "auto", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: 10, boxShadow: "0 6px 20px rgba(0,0,0,0.12)" };
