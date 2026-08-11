import { useState } from "react";

// Agency-wide pages, not scoped to any one client.
const WORKSPACE_NAV = [
  ["creators", "Creators & prospects", "The shared master list every client draws from"],
  ["analytics", "Analytics", "Pipeline across all clients"],
];

// The two hand-off stages surfaced in the "Waiting" panel. view = the tab to open.
const WAITING_ROWS = [
  { key: "to_post", label: "To post", view: "approved", color: "#047857" },
  { key: "to_approve", label: "To approve", view: "draft", color: "#b45309" },
];

function ageLabel(h) {
  if (h == null) return "";
  if (h >= 48) return `${Math.round(h / 24)}d`;
  if (h >= 1) return `${Math.round(h)}h`;
  return "new";
}

export default function Sidebar({ clients, selectedId, clientMode, activeView, summary, onGoToStage, onSelectClient, onNavigate, onAddClient }) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(null);

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

      {/* Always-on "what's waiting" across ALL clients — the poster/approver's at-a-glance
          signal. Click a stage to see which clients have items; click a client to jump there. */}
      {summary && (
        <div style={{ padding: "0 8px 10px" }}>
          <div style={sectionLabel}>Waiting</div>
          {WAITING_ROWS.map(({ key, label, view, color }) => {
            const s = summary[key] || { total: 0, by_client: [] };
            const t = (summary.thresholds || {})[key] || {};
            const over =
              (t.count != null && s.total >= t.count) ||
              (t.hours != null && s.oldest_hours != null && s.oldest_hours >= t.hours);
            const open = expanded === key;
            const byClient = s.by_client || [];
            return (
              <div key={key}>
                <button
                  onClick={() => setExpanded(open ? null : key)}
                  title={over ? "Over the alert threshold — needs attention" : ""}
                  style={{
                    display: "flex", width: "100%", alignItems: "center", justifyContent: "space-between",
                    padding: "8px 12px", marginBottom: 2, borderRadius: 8, border: "none",
                    background: open ? "#f1f5f9" : "transparent", cursor: "pointer",
                  }}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{open ? "▾" : "▸"}</span>
                    <span style={{ fontWeight: 600, fontSize: 14, color: "var(--text)" }}>{label}</span>
                  </span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                    {s.total > 0 && s.oldest_hours != null && (
                      <span style={{ fontSize: 11, color: over ? "var(--danger)" : "var(--text-muted)" }}>
                        {ageLabel(s.oldest_hours)}
                      </span>
                    )}
                    <span
                      style={{
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                        minWidth: 20, height: 20, padding: "0 6px", borderRadius: 999,
                        fontSize: 12, fontWeight: 700, color: "#fff",
                        background: s.total === 0 ? "#cbd5e1" : over ? "var(--danger)" : color,
                      }}
                    >
                      {s.total}
                    </span>
                  </span>
                </button>
                {open && byClient.map((bc) => (
                  <button
                    key={bc.id}
                    onClick={() => onGoToStage(bc.id, view)}
                    style={{
                      display: "flex", width: "100%", alignItems: "center", justifyContent: "space-between",
                      padding: "6px 12px 6px 30px", marginBottom: 2, borderRadius: 8, border: "none",
                      background: "transparent", cursor: "pointer", fontSize: 13, color: "var(--text)",
                    }}
                  >
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{bc.name}</span>
                    <span style={{ color: "var(--text-muted)" }}>
                      {bc.count}{bc.oldest_hours != null ? ` · ${ageLabel(bc.oldest_hours)}` : ""}
                    </span>
                  </button>
                ))}
                {open && byClient.length === 0 && (
                  <div style={{ padding: "4px 12px 6px 30px", fontSize: 12, color: "var(--text-muted)" }}>
                    Nothing waiting.
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

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
