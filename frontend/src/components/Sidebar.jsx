import { useState } from "react";

export default function Sidebar({ clients, selectedId, onSelect, onAddClient }) {
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
      <div style={{ padding: "20px 16px 12px", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 2 }}>Engagement Queue</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{clients.length} clients</div>
        </div>
        <button
          onClick={onAddClient}
          title="Add client"
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: "var(--surface)",
            fontSize: 16,
            fontWeight: 600,
            color: "var(--primary)",
            lineHeight: 1,
          }}
        >
          +
        </button>
      </div>

      <div style={{ padding: "0 16px 12px" }}>
        <input
          placeholder="Search clients…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{
            width: "100%",
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            fontSize: 13,
          }}
        />
      </div>

      <nav style={{ overflowY: "auto", flex: 1, padding: "0 8px" }}>
        {filtered.map((c) => {
          const active = c.id === selectedId;
          return (
            <button
              key={c.id}
              onClick={() => onSelect(c.id)}
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
