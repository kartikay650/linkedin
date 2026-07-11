import { useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";

function initials(name) {
  return (name || "?")
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function relevanceTone(score) {
  if (score >= 0.8) return "success";
  if (score >= 0.55) return "primary";
  return "neutral";
}

export default function PostCard({ post, onActioned }) {
  const [editedText, setEditedText] = useState({});
  const [copiedId, setCopiedId] = useState(null);
  const [drafting, setDrafting] = useState(false);

  const pendingDrafts = post.drafts.filter((d) => d.status === "pending");

  const handleCopy = async (draft) => {
    await navigator.clipboard.writeText(editedText[draft.id] ?? draft.text);
    setCopiedId(draft.id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const handleStatus = async (draft, status) => {
    await api.updateDraft(draft.id, { status, edited_text: editedText[draft.id] });
    onActioned();
  };

  const handleDraftReply = async () => {
    setDrafting(true);
    try {
      await api.draftReply(post.id);
      onActioned();
    } finally {
      setDrafting(false);
    }
  };

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        boxShadow: "var(--shadow)",
        padding: 18,
        marginBottom: 16,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              background: "#e0e7ff",
              color: "#3730a3",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 13,
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {initials(post.author_name)}
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{post.author_name || "Unknown author"}</div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              {post.posted_at ? new Date(post.posted_at).toLocaleDateString() : "recently"}
            </div>
          </div>
        </div>

        <a
          href={post.post_url}
          target="_blank"
          rel="noreferrer"
          style={{ fontSize: 13, color: "var(--primary)", whiteSpace: "nowrap", textDecoration: "none" }}
        >
          Open post ↗
        </a>
      </div>

      <p style={{ color: "#374151", fontSize: 14, lineHeight: 1.5, margin: "12px 0" }}>{post.content_snippet}</p>

      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <Badge tone={relevanceTone(post.relevance_score ?? 0)}>
          relevance {Math.round((post.relevance_score ?? 0) * 10)}/10
        </Badge>
      </div>
      {post.relevance_reason && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14, marginTop: -8 }}>
          {post.relevance_reason}
        </div>
      )}

      {pendingDrafts.length === 0 && (
        <button
          onClick={handleDraftReply}
          disabled={drafting}
          style={{
            padding: "8px 14px",
            borderRadius: 6,
            border: "none",
            background: drafting ? "#93b4f8" : "var(--primary)",
            color: "white",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {drafting ? "Drafting…" : "Draft reply"}
        </button>
      )}

      {pendingDrafts
        .map((draft) => (
          <div
            key={draft.id}
            style={{
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: 12,
              marginTop: 10,
            }}
          >
            <textarea
              rows={3}
              style={{
                width: "100%",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: 8,
                resize: "vertical",
              }}
              defaultValue={draft.text}
              onChange={(e) => setEditedText((prev) => ({ ...prev, [draft.id]: e.target.value }))}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
              <button
                onClick={() => handleCopy(draft)}
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {copiedId === draft.id ? "Copied ✓" : "Copy"}
              </button>
              <button
                onClick={() => handleStatus(draft, "posted")}
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "none",
                  background: "var(--primary)",
                  color: "white",
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                Mark posted
              </button>
              <button
                onClick={() => handleStatus(draft, "rejected")}
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
                  color: "var(--danger)",
                  fontSize: 13,
                  fontWeight: 500,
                  marginLeft: "auto",
                }}
              >
                Reject
              </button>
            </div>
          </div>
        ))}
    </div>
  );
}
