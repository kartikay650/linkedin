export default function EmptyState({ title, subtitle }) {
  return (
    <div
      style={{
        border: "1px dashed var(--border)",
        borderRadius: "var(--radius)",
        padding: "48px 24px",
        textAlign: "center",
        color: "var(--text-muted)",
      }}
    >
      <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 14 }}>{subtitle}</div>
    </div>
  );
}
