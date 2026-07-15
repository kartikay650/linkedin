import { useState } from "react";

// Agency-wide pages, not scoped to any one client.
const WORKSPACE_NAV = [
  ["creators", "Creators & prospects", "The shared master list every client draws from"],
  ["analytics", "Analytics", "Pipeline across all clients"],
];

export default function Sidebar({ clients, selectedId, clientMode, activeView, onSelectClient, onNavigate, onAddClient }) {
  const [query, setQuery] = useState("");

  const filtered = clients.filter((c) =>
    `${c.name} ${c.specialty}`.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <aside
      style={{
        width: 260,
        borderRight: "1px solid var(--border)",
        background: "var(--surface)",
        height: "100vh",
        position: "sticky",
        top: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ padding: "20px 16px 14px" }}>
        <div style={{ fontWeight: 700, fontSize: 16 }}>Engagement Queue</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{clients.length} clients</div>
      </div>

      {/* Agency-wide pages */}
      <div style={{ padding: "0 8px 8px" }}>
        <div style={sectionLabel}>Workspace</div>
        {WORKSPACE_NAV.map(([key, label, hint]) => {
          const active = !clientMode && activeView === key;
          return (
            <button
              key={key}
              onClick={() => onNavigate(key)}
              title={hint}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "9px 12px",
                marginBottom: 2,
                borderRadius: 8,
                border: "none",
                background: active ? "#eff4ff" : "transparent",
                color: active ? "var(--primary)" : "var(--text)",
                fontWeight: 600,
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              {label}
            </button>
          );
        })}
      </div>

      <div style={{ borderTop: "1px solid var(--border)", margin: "4px 12px 10px" }} />

      {/* Clients */}
      <div style={{ padding: "0 16px", display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ ...sectionLabel, padding: 0 }}>Clients</div>
        <button
          onClick={onAddClient}
          title="Add client"
          style={{
            width: 24,
            height: 24,
            borderRadius: 7,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            fontSize: 15,
            fontWeight: 600,
            color: "var(--primary)",
            lineHeight: 1,
            cursor: "pointer",
          }}
        >
          +
        </button>
      </div>

      <div style={{ padding: "0 16px 10px" }}>
        <input
          placeholder="Search clients…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{
            width: "100%",
            boxSizing: "border-box",
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            fontSize: 13,
          }}
        />
      </div>

      <nav style={{ overflowY: "auto", flex: 1, padding: "0 8px 12px" }}>
        {filtered.map((c) => {
          const active = clientMode && c.id === selectedId;
          return (
            <button
              key={c.id}
              onClick={() => onSelectClient(c.id)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "10px 12px",
                marginBottom: 4,
                borderRadius: 8,
                border: "none",
                background: active ? "#eff4ff" : "transparent",
                color: active ? "var(--primary)" : "var(--text)",
                cursor: "pointer",
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 14 }}>{c.name}</div>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{c.specialty}</div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <div style={{ padding: 12, fontSize: 13, color: "var(--text-muted)" }}>No matches.</div>
        )}
      </nav>
    </aside>
  );
}

const sectionLabel = {
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: 0.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  padding: "0 12px 6px",
};
