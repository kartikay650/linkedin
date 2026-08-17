import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "../api.js";
import Sidebar from "../components/Sidebar.jsx";
import PostCard from "../components/PostCard.jsx";
import EmptyState from "../components/EmptyState.jsx";
import AddClientModal from "../components/AddClientModal.jsx";
import ManageClientModal from "../components/ManageClientModal.jsx";
import ProspectsPanel from "../components/ProspectsPanel.jsx";
import AnalyticsPanel from "../components/AnalyticsPanel.jsx";
import Toaster from "../components/Toaster.jsx";
import { toast } from "../toast.js";
import { STAGES, POST_VIEWS } from "../status.js";
import { runSync } from "../syncRunner.js";

export default function Dashboard() {
  const [clients, setClients] = useState([]);
  const [selectedClientId, setSelectedClientId] = useState(null);
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncNote, setSyncNote] = useState(null);
  const [syncError, setSyncError] = useState(null);
  const [canForce, setCanForce] = useState(false);
  const [showAddClient, setShowAddClient] = useState(false);
  const [showManageClient, setShowManageClient] = useState(false);
  const [usage, setUsage] = useState([]);
  const [view, setView] = useState("active");
  const [counts, setCounts] = useState(null);
  const [summary, setSummary] = useState(null);
  // Which stages have already popped an alert this session, so the pop-up fires once per
  // threshold-crossing instead of on every poll. Resets when a stage drops back under.
  const alertedRef = useRef({ to_post: false, to_approve: false });

  useEffect(() => {
    api.apifyUsage().then(setUsage).catch(() => {});
  }, []);

  const loadClients = useCallback(() => {
    return api.listClients().then((data) => {
      setClients(data);
      return data;
    });
  }, []);

  useEffect(() => {
    loadClients().then((data) => {
      if (data.length > 0) setSelectedClientId(data[0].id);
    });
  }, [loadClients]);

  const loadPosts = useCallback((silent) => {
    if (!selectedClientId || !POST_VIEWS.includes(view)) return;
    if (!silent) setLoading(true);
    api
      .listPosts(selectedClientId, view)
      .then(setPosts)
      .finally(() => { if (!silent) setLoading(false); });
    // Per-tab counts for the badges — refreshed alongside the list so they stay in sync
    // after any action (draft/approve/post/sync). View-independent, so fetched once here.
    api.postCounts(selectedClientId).then(setCounts).catch(() => {});
  }, [selectedClientId, view]);

  useEffect(() => {
    loadPosts();
  }, [loadPosts]);

  // Agency-wide "what's waiting" summary — powers the sidebar badge and the pop-up.
  // Polled (badge doesn't need sub-minute accuracy) and refreshed after a sync.
  const loadSummary = useCallback(() => {
    api.notificationsSummary().then(setSummary).catch(() => {});
  }, []);

  // Poll every 5 min and ONLY when the tab is actually visible (most open dashboards sit in a
  // background tab). Refresh immediately when the tab regains focus so it still feels current.
  // This, with the light-column summary read, is the main egress fix.
  useEffect(() => {
    if (!document.hidden) loadSummary();
    const id = setInterval(() => { if (!document.hidden) loadSummary(); }, 300000);
    const onVis = () => { if (!document.hidden) loadSummary(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", onVis); };
  }, [loadSummary]);

  // Fire the pop-up when a stage crosses its threshold (count OR age), once per crossing.
  useEffect(() => {
    if (!summary) return;
    const th = summary.thresholds || {};
    const check = (key, label) => {
      const s = summary[key];
      const t = th[key];
      if (!s || !t) return;
      const over = s.total >= t.count || (s.oldest_hours != null && s.oldest_hours >= t.hours);
      if (over && !alertedRef.current[key]) {
        alertedRef.current[key] = true;
        const age = s.oldest_hours != null ? ` (oldest ${fmtAge(s.oldest_hours)})` : "";
        toast(`${s.total} ${label}${age}. Click a client in the sidebar to handle them.`, "info");
      } else if (!over) {
        alertedRef.current[key] = false;
      }
    };
    check("to_post", "comments approved and waiting to post");
    check("to_approve", "comments waiting for approval");
  }, [summary]);

  // Jump straight to a client's stage tab from the sidebar notification breakdown.
  const goToStage = (clientId, stageView) => {
    setSelectedClientId(clientId);
    setView(stageView);
  };

  const handleSync = async (force = false) => {
    setSyncing(true);
    setSyncError(null);
    setCanForce(false);
    setSyncNote(force ? "Fetching the latest from every tracked profile…" : "Working out what's due…");
    try {
      // Baseline via the LIGHT counts endpoint (not the full feed) so detecting new posts
      // costs a few bytes, not ~half a MB per check.
      let baseline = counts?.[view] ?? posts.length;
      if (selectedClientId) {
        const c0 = await api.postCounts(selectedClientId).catch(() => null);
        if (c0) baseline = c0[view] ?? baseline;
      }
      // Universal, deduped sync across ALL clients. Without force, cadence means it only
      // fetches profiles actually due, so pressing it again the same day costs ~nothing.
      // force=true ignores cadence and refetches everything (for "a creator just posted").
      const { total } = await runSync({
        clientId: null,
        force,
        onProgress: (p) => {
          if (p.phase === "empty") setSyncNote("Everything's up to date — nothing new was due to fetch.");
          else if (p.phase === "done") setSyncNote(`Queued ${p.total} profiles. New posts land over the next few minutes.`);
          else if (p.phase === "firing") setSyncNote(`Queued ${p.done} / ${p.total} profiles…`);
        },
      });
      // Nothing due by cadence -> offer an explicit force fetch (LinkedIn may have new
      // posts we skipped to save credit). This is the fix for "I synced but the latest
      // post isn't showing": the normal sync deliberately didn't re-check recent profiles.
      if (total === 0 && !force) setCanForce(true);
      if (total > 0) {
        // Posts arrive asynchronously via webhook and can take a few minutes. Poll the LIGHT
        // counts (cheap) to detect when new posts land, and only pull the full feed ONCE when
        // they do — instead of re-downloading the whole feed every cycle.
        let appeared = false;
        for (let i = 0; i < 9 && !appeared; i++) {   // up to ~3 min at 20s intervals
          await new Promise((r) => setTimeout(r, 20000));
          if (!selectedClientId) break;
          const c = await api.postCounts(selectedClientId).catch(() => null);
          if (c) setCounts(c);
          const now = c?.[view];
          if (now != null && now > baseline) {
            appeared = true;
            loadPosts(true); // one full feed refresh, only now that there's something new
            setSyncNote(`${now - baseline} new post${now - baseline > 1 ? "s" : ""} arrived. More may still be landing.`);
          }
        }
        if (!appeared)
          setSyncNote("Done. Nothing new for this client yet — posts may still be arriving, check back shortly.");
      }
      loadSummary(); // refresh the waiting counts after a sync
      setTimeout(() => setSyncNote(null), 12000);
    } catch (e) {
      setSyncError(e.message || "Sync failed.");
      toast(`Sync failed: ${e.message || "unknown error"}. Please try again.`);
    } finally {
      setSyncing(false);
    }
  };

  const selectedClient = clients.find((c) => c.id === selectedClientId);
  const isPostView = POST_VIEWS.includes(view);

  // Only client-scoped views live in the tab strip now; agency-wide pages
  // (Creators & prospects, Analytics) are top-level nav in the sidebar.
  const TABS = POST_VIEWS.map((key) => [key, STAGES[key].label]);

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar
        clients={clients}
        selectedId={selectedClientId}
        clientMode={isPostView}
        activeView={view}
        summary={summary}
        onGoToStage={goToStage}
        onSelectClient={(id) => { setSelectedClientId(id); setView("active"); }}
        onNavigate={setView}
        onAddClient={() => setShowAddClient(true)}
      />

      <main style={{ flex: 1, padding: "32px 40px", maxWidth: 1080, width: "100%", boxSizing: "border-box" }}>
        {selectedClient && isPostView && (
          <header style={{ marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <h1 style={{ fontSize: 22, margin: 0 }}>{selectedClient.name}</h1>
              <div style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 4 }}>
                {selectedClient.specialty}
              </div>
            </div>
            <div style={{ textAlign: "right", display: "flex", gap: 8 }}>
              <button
                onClick={() => setShowManageClient(true)}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
                  fontSize: 13,
                  fontWeight: 600,
                  boxShadow: "var(--shadow)",
                }}
              >
                Manage profile
              </button>
              <div>
                <button
                  onClick={() => handleSync(false)}
                  disabled={syncing}
                  title="Fetch new posts for every client. Only pulls profiles that are due, so pressing it again the same day costs nothing."
                  style={{
                    padding: "8px 16px",
                    borderRadius: 8,
                    border: "1px solid var(--border)",
                    background: syncing ? "#f2f4f7" : "var(--surface)",
                    fontSize: 13,
                    fontWeight: 600,
                    boxShadow: "var(--shadow)",
                  }}
                >
                  {syncing ? "Syncing…" : "Sync all"}
                </button>
                {syncNote && (
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, maxWidth: 210 }}>
                    {syncNote}
                  </div>
                )}
                {canForce && !syncing && (
                  <button
                    onClick={() => handleSync(true)}
                    title="Ignore the daily fetch limit and re-check every tracked profile now. Use this when you know a creator just posted. Costs a little fetching credit."
                    style={{
                      marginTop: 6,
                      padding: 0,
                      border: "none",
                      background: "none",
                      color: "var(--accent, #2563eb)",
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: "pointer",
                      textDecoration: "underline",
                    }}
                  >
                    Fetch latest anyway
                  </button>
                )}
                {syncError && (
                  <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 6, maxWidth: 200 }}>{syncError}</div>
                )}
              </div>
            </div>
          </header>
        )}

        {(view === "creators" || view === "analytics") && (
          <h1 style={{ fontSize: 22, margin: "0 0 6px" }}>
            {view === "creators" ? "Creators & prospects" : "Analytics"}
          </h1>
        )}
        {view === "creators" && (
          <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 20 }}>
            The shared master list every client draws from. Add your own or promote a prospect to tracked, then assign each creator to the clients who should see their posts.
          </div>
        )}
        {view === "analytics" && (
          <div style={{ color: "var(--text-muted)", fontSize: 14, marginBottom: 20 }}>
            Pipeline across every client.
          </div>
        )}

        {isPostView && selectedClient && (
          <div style={{ display: "flex", gap: 6, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
            {TABS.map(([key, label]) => {
              const meta = STAGES[key];
              const selected = view === key;
              return (
                <button
                  key={key}
                  onClick={() => setView(key)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 12px",
                    borderRadius: 999,
                    border: `1px solid ${selected ? meta.color : "transparent"}`,
                    background: selected ? meta.color : meta.bg,
                    color: selected ? "#fff" : meta.color,
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  {label}
                  {counts && counts[key] != null && (
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        justifyContent: "center",
                        minWidth: 18,
                        height: 18,
                        padding: "0 5px",
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 700,
                        lineHeight: 1,
                        background: selected ? "#fff" : meta.color,
                        color: selected ? meta.color : "#fff",
                      }}
                    >
                      {counts[key]}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {view === "creators" ? (
          <ProspectsPanel />
        ) : view === "analytics" ? (
          <AnalyticsPanel />
        ) : !selectedClient ? (
          <EmptyState title="No client selected" subtitle="Choose a client from the sidebar to see their queue." />
        ) : loading ? (
          <SkeletonList />
        ) : posts.length === 0 ? (
          <EmptyState
            title="No fresh posts"
            subtitle="Nothing from the last 14 days yet. Hit Sync all to pull the latest, or check back after the morning sync."
          />
        ) : (
          posts.map((post) => <PostCard key={post.id} post={post} onActioned={() => { loadPosts(true); loadSummary(); }} />)
        )}

        {isPostView && usage.length > 0 && (
          <div style={{ marginTop: 36, paddingTop: 14, borderTop: "1px solid var(--border)", fontSize: 12, color: "var(--text-muted)" }}>
            Fetching credit this month:{" "}
            {usage.map((u, i) => (
              <span key={u.account}>
                {i > 0 ? "  ·  " : ""}${(u.used_usd ?? 0).toFixed(2)} / ${u.limit_usd ?? 5}
              </span>
            ))}
          </div>
        )}
      </main>

      <AddClientModal
        open={showAddClient}
        onClose={() => setShowAddClient(false)}
        onCreated={(client) => {
          setShowAddClient(false);
          loadClients().then(() => setSelectedClientId(client.id));
        }}
      />

      <ManageClientModal
        open={showManageClient}
        onClose={() => setShowManageClient(false)}
        client={selectedClient}
        onUpdated={loadClients}
        onDeleted={() => {
          setShowManageClient(false);
          loadClients().then((data) => setSelectedClientId(data.length ? data[0].id : null));
        }}
      />

      <Toaster />
    </div>
  );
}

// Compact age label from hours: "3d" / "5h" / "just now".
function fmtAge(hours) {
  if (hours == null) return "";
  if (hours >= 48) return `${Math.round(hours / 24)}d`;
  if (hours >= 1) return `${Math.round(hours)}h`;
  return "just now";
}

function SkeletonList() {
  return (
    <div>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            height: 120,
            borderRadius: "var(--radius)",
            background: "linear-gradient(90deg, #f0f1f3 25%, #f7f8f9 37%, #f0f1f3 63%)",
            backgroundSize: "400% 100%",
            animation: "shimmer 1.4s ease infinite",
            marginBottom: 16,
          }}
        />
      ))}
      <style>{`@keyframes shimmer { 0% { background-position: 100% 50% } 100% { background-position: 0 50% } }`}</style>
    </div>
  );
}
