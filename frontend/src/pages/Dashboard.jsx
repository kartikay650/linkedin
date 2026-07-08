import { useEffect, useState, useCallback } from "react";
import { api } from "../api.js";
import Sidebar from "../components/Sidebar.jsx";
import PostCard from "../components/PostCard.jsx";
import EmptyState from "../components/EmptyState.jsx";
import AddClientModal from "../components/AddClientModal.jsx";
import ManageClientModal from "../components/ManageClientModal.jsx";

export default function Dashboard() {
  const [clients, setClients] = useState([]);
  const [selectedClientId, setSelectedClientId] = useState(null);
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [showAddClient, setShowAddClient] = useState(false);
  const [showManageClient, setShowManageClient] = useState(false);

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

  const loadPosts = useCallback(() => {
    if (!selectedClientId) return;
    setLoading(true);
    api
      .listPosts(selectedClientId)
      .then(setPosts)
      .finally(() => setLoading(false));
  }, [selectedClientId]);

  useEffect(() => {
    loadPosts();
  }, [loadPosts]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      await api.syncClient(selectedClientId);
      loadPosts();
    } catch (e) {
      setSyncError(e.message || "Sync failed — see backend logs.");
    } finally {
      setSyncing(false);
    }
  };

  const selectedClient = clients.find((c) => c.id === selectedClientId);

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar
        clients={clients}
        selectedId={selectedClientId}
        onSelect={setSelectedClientId}
        onAddClient={() => setShowAddClient(true)}
      />

      <main style={{ flex: 1, padding: "32px 40px", maxWidth: 760 }}>
        {selectedClient && (
          <header style={{ marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <h1 style={{ fontSize: 22, margin: 0 }}>{selectedClient.name}</h1>
              <div style={{ color: "var(--text-muted)", fontSize: 14, marginTop: 4 }}>
                {selectedClient.specialty} — review queue
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
                Manage profiles
              </button>
              <div>
                <button
                  onClick={handleSync}
                  disabled={syncing}
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
                  {syncing ? "Syncing…" : "Sync now"}
                </button>
                {syncing && (
                  <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6, maxWidth: 200 }}>
                    Can take a few minutes — requests are deliberately paced to protect the account.
                  </div>
                )}
                {syncError && (
                  <div style={{ fontSize: 12, color: "var(--danger)", marginTop: 6, maxWidth: 200 }}>{syncError}</div>
                )}
              </div>
            </div>
          </header>
        )}

        {!selectedClient && (
          <EmptyState title="No client selected" subtitle="Choose a client from the sidebar to see their queue." />
        )}

        {selectedClient && loading && <SkeletonList />}

        {selectedClient && !loading && posts.length === 0 && (
          <EmptyState
            title="All caught up"
            subtitle="No pending drafts for this client right now — check back after the next scrape run."
          />
        )}

        {selectedClient &&
          !loading &&
          posts.map((post) => <PostCard key={post.id} post={post} onActioned={loadPosts} />)}
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
      />
    </div>
  );
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
