import { useEffect, useState } from "react";
import { subscribeToast } from "../toast";

export default function Toaster() {
  const [items, setItems] = useState([]);

  useEffect(
    () =>
      subscribeToast((t) => {
        setItems((prev) => [...prev, t]);
        setTimeout(() => setItems((prev) => prev.filter((x) => x.id !== t.id)), 7000);
      }),
    []
  );

  const dismiss = (id) => setItems((prev) => prev.filter((x) => x.id !== id));

  return (
    <div style={{ position: "fixed", bottom: 20, right: 20, zIndex: 2000, display: "flex", flexDirection: "column", gap: 8 }}>
      {items.map((t) => {
        const palette = {
          error: { bg: "var(--danger-bg)", fg: "var(--danger)", border: "#fecaca" },
          info: { bg: "#fef3c7", fg: "#b45309", border: "#fde68a" }, // amber — "needs attention"
          success: { bg: "var(--success-bg)", fg: "var(--success)", border: "#bbf7d0" },
        };
        const p = palette[t.type] || palette.success;
        return (
          <div
            key={t.id}
            onClick={() => dismiss(t.id)}
            role="alert"
            style={{
              background: p.bg,
              color: p.fg,
              border: `1px solid ${p.border}`,
              borderRadius: 10,
              padding: "11px 14px",
              fontSize: 13,
              lineHeight: 1.45,
              maxWidth: 340,
              boxShadow: "0 4px 14px rgba(16,24,40,0.12)",
              cursor: "pointer",
            }}
          >
            {t.message}
          </div>
        );
      })}
    </div>
  );
}
