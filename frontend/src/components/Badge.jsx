export default function Badge({ tone = "neutral", children }) {
  const tones = {
    neutral: { bg: "#f2f4f7", color: "#374151" },
    success: { bg: "var(--success-bg)", color: "var(--success)" },
    danger: { bg: "var(--danger-bg)", color: "var(--danger)" },
    primary: { bg: "#eff4ff", color: "var(--primary)" },
  };
  const { bg, color } = tones[tone] ?? tones.neutral;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 600,
        background: bg,
        color,
      }}
    >
      {children}
    </span>
  );
}
