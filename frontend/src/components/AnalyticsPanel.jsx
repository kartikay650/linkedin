import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AnalyticsPanel() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    api.analytics().then(setData).catch(() => setErr(true));
  }, []);

  if (err) return <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Couldn't load analytics. Try again.</div>;
  if (!data) return <div style={{ color: "var(--text-muted)", fontSize: 14 }}>Loading…</div>;

  const { totals, top_authors, per_client } = data;
  const stats = [
    ["Clients", totals.clients],
    ["Posts in queue", totals.posts],
    ["Replies drafted", totals.drafts],
    ["Approved", totals.approved],
    ["Posted", totals.posted],
  ];

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, marginBottom: 28 }}>
        {stats.map(([label, n]) => (
          <div key={label} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: "16px 18px", boxShadow: "var(--shadow)" }}>
            <div style={{ fontSize: 26, fontWeight: 700 }}>{n}</div>
            <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 20 }}>
        <Card title="Who we're engaging with most" subtitle="By replies approved or posted">
          {top_authors.length === 0 ? (
            <Empty>No replies approved or posted yet.</Empty>
          ) : (
            top_authors.map((a, i) => {
              const max = top_authors[0].replies || 1;
              return (
                <div key={i} style={{ padding: "9px 0", borderTop: i ? "1px solid var(--border)" : "none" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, marginBottom: 4 }}>
                    <span style={{ fontWeight: 600 }}>{a.author}</span>
                    <span style={{ color: "var(--text-muted)" }}>{a.replies}</span>
                  </div>
                  <div style={{ height: 6, background: "var(--bg)", borderRadius: 4, overflow: "hidden" }}>
                    <div style={{ width: `${(a.replies / max) * 100}%`, height: "100%", background: "var(--primary)" }} />
                  </div>
                </div>
              );
            })
          )}
        </Card>

        <Card title="Per client" subtitle="Pipeline across the queue">
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto auto", gap: "8px 14px", fontSize: 13, alignItems: "center" }}>
            <span style={hdr}>Client</span><span style={hdr}>Posts</span><span style={hdr}>Draft</span><span style={hdr}>Appr.</span><span style={hdr}>Posted</span>
            {per_client.map((c, i) => (
              <Row key={i} c={c} />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

const Card = ({ title, subtitle, children }) => (
  <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 18, boxShadow: "var(--shadow)" }}>
    <div style={{ fontSize: 15, fontWeight: 600 }}>{title}</div>
    {subtitle && <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>{subtitle}</div>}
    {children}
  </div>
);
const Empty = ({ children }) => <div style={{ fontSize: 13, color: "var(--text-muted)", paddingTop: 6 }}>{children}</div>;
const hdr = { fontSize: 11, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.4 };
const Row = ({ c }) => (
  <>
    <span style={{ fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.client}</span>
    <span>{c.posts}</span>
    <span>{c.pending}</span>
    <span>{c.approved}</span>
    <span>{c.posted}</span>
  </>
);
