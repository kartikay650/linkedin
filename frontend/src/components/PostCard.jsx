import { useState } from "react";
import { api } from "../api.js";
import { toast } from "../toast.js";
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
  const [refining, setRefining] = useState(null);
  const [tweak, setTweak] = useState({});
  const [dismissing, setDismissing] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const [verifying, setVerifying] = useState(null);
  // Web-verify results, kept local so a claim check never reloads the feed.
  const [provByDraft, setProvByDraft] = useState({});

  // Drafts still being worked (drafted or scientist-approved, not yet posted/rejected).
  const workingDrafts = post.drafts.filter((d) => d.status === "pending" || d.status === "approved");
  const postedDraft = post.drafts.find((d) => d.status === "posted");

  const TWEAKS = [
    ["Shorter", "make it shorter, one or two sentences at most"],
    ["More personal", "make it more personal and human, in her own first-person voice"],
    ["More neutral", "make it more neutral and less opinionated; make the point without pushing a strong personal opinion"],
    ["More scientific", "make it more scientific and clinical in tone: precise, evidence-minded, measured"],
    ["More authoritative", "make it more authoritative, peer-to-peer between experts; never congratulatory, never 'well done' or 'great post'"],
    ["Remove opinion", "remove personal opinion and any unverified claim; keep only what reflects the post itself and facts grounded in her own material"],
  ];

  const handleRefine = async (draft, instruction) => {
    if (!instruction || !instruction.trim()) return;
    setRefining(draft.id);
    try {
      const updated = await api.refineDraft(draft.id, instruction.trim());
      setEditedText((prev) => ({ ...prev, [draft.id]: updated.text }));
      setTweak((prev) => ({ ...prev, [draft.id]: "" }));
      // Refresh the citation for the rewritten text, then re-check the web in bg.
      setProvByDraft((prev) => ({ ...prev, [draft.id]: updated.provenance || [] }));
      maybeVerify(updated);
    } catch (e) {
      toast(`Couldn't tweak that reply: ${e.message}. Try again.`);
    } finally {
      setRefining(null);
    }
  };

  const handleCopy = async (draft) => {
    await navigator.clipboard.writeText(editedText[draft.id] ?? draft.text);
    setCopiedId(draft.id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const handleCopyLink = async () => {
    if (!post.post_url) return;
    await navigator.clipboard.writeText(post.post_url);
    setLinkCopied(true);
    setTimeout(() => setLinkCopied(false), 1500);
  };

  const handleStatus = async (draft, status) => {
    try {
      await api.updateDraft(draft.id, { status, edited_text: editedText[draft.id] });
      onActioned();
    } catch (e) {
      toast(`Couldn't save that: ${e.message}. Try again.`);
    }
  };

  const handleDismiss = async () => {
    setDismissing(true);
    try {
      await api.dismissPost(post.id);
      onActioned();
    } catch (e) {
      toast(`Couldn't dismiss that post: ${e.message}. Try again.`);
      setDismissing(false);
    }
  };

  const handleVerify = async (draftId) => {
    setVerifying(draftId);
    try {
      const updated = await api.verifyClaims(draftId);
      // Update only this draft's citation locally — never reload the feed.
      setProvByDraft((prev) => ({ ...prev, [draftId]: updated.provenance || [] }));
    } catch {
      // Background best-effort — a slow/failed web check just leaves the claim
      // flagged "check manually"; never interrupt the operator.
    } finally {
      setVerifying(null);
    }
  };

  // Auto web-check a freshly produced draft if it has an unverified clinical claim.
  // Triggered only by generate/tweak (below) — never on passive page loads — so it
  // runs "in the workflow" without re-checking every time the dashboard opens.
  const maybeVerify = (draft) => {
    if (draft && (draft.provenance || []).some((s) => s.level === "unverified")) {
      handleVerify(draft.id);
    }
  };

  const handleDraftReply = async () => {
    setDrafting(true);
    try {
      const drafts = await api.draftReply(post.id);
      onActioned();
      maybeVerify(Array.isArray(drafts) ? drafts[0] : null);
    } catch (e) {
      toast(`Couldn't generate a reply: ${e.message}. Try again in a moment.`);
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

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
          <a
            href={post.post_url}
            target="_blank"
            rel="noreferrer"
            style={{ fontSize: 13, color: "var(--primary)", whiteSpace: "nowrap", textDecoration: "none" }}
          >
            Open post ↗
          </a>
          <button
            onClick={handleCopyLink}
            title="Copy this post's link to paste where the client is logged in"
            style={{ border: "none", background: "none", fontSize: 13, color: "var(--text-muted)", padding: 0, whiteSpace: "nowrap" }}
          >
            {linkCopied ? "Link copied ✓" : "Copy link"}
          </button>
          <button
            onClick={handleDismiss}
            disabled={dismissing}
            title="Remove this post from the feed"
            style={{ border: "none", background: "none", fontSize: 13, color: "var(--text-muted)", padding: 0 }}
          >
            {dismissing ? "Dismissing…" : "Dismiss"}
          </button>
        </div>
      </div>

      {post.summary && (
        <p style={{ color: "#111827", fontSize: 13, fontWeight: 500, lineHeight: 1.5, margin: "12px 0 4px" }}>
          {post.summary}
        </p>
      )}
      <p style={{ color: "#6b7280", fontSize: 13, lineHeight: 1.5, margin: post.summary ? "0 0 12px" : "12px 0" }}>
        {post.content_snippet}
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center" }}>
        <Badge tone={relevanceTone(post.relevance_score ?? 0)}>
          relevance {Math.round((post.relevance_score ?? 0) * 10)}/10
        </Badge>
        {postedDraft && <Badge tone="success">Posted</Badge>}
        {!postedDraft && workingDrafts.some((d) => d.status === "approved") && (
          <Badge tone="primary">Approved for posting</Badge>
        )}
      </div>
      {post.relevance_reason && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14, marginTop: -8 }}>
          {post.relevance_reason}
        </div>
      )}

      {postedDraft && workingDrafts.length === 0 && (
        <div style={{ background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 8, padding: 12, fontSize: 14, lineHeight: 1.5, color: "#374151" }}>
          {postedDraft.edited_text || postedDraft.text}
        </div>
      )}

      {workingDrafts.length === 0 && !postedDraft && (
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

      {workingDrafts.map((draft) => (
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
                fontSize: 14,
                lineHeight: 1.5,
                opacity: refining === draft.id ? 0.6 : 1,
              }}
              value={editedText[draft.id] ?? draft.text}
              disabled={refining === draft.id}
              onChange={(e) => setEditedText((prev) => ({ ...prev, [draft.id]: e.target.value }))}
            />

            {/* Tweak row: quick chips + free-text instruction */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 8 }}>
              {TWEAKS.map(([label, instruction]) => (
                <button
                  key={label}
                  disabled={refining === draft.id}
                  onClick={() => handleRefine(draft, instruction)}
                  style={{
                    padding: "4px 10px", borderRadius: 999, border: "1px solid var(--border)",
                    background: "var(--surface)", fontSize: 12, color: "var(--text-muted)",
                  }}
                >
                  {label}
                </button>
              ))}
              <input
                placeholder="or tell it how to change…"
                value={tweak[draft.id] || ""}
                disabled={refining === draft.id}
                onChange={(e) => setTweak((p) => ({ ...p, [draft.id]: e.target.value }))}
                onKeyDown={(e) => { if (e.key === "Enter") handleRefine(draft, tweak[draft.id]); }}
                style={{ flex: 1, minWidth: 140, padding: "6px 10px", borderRadius: 8, border: "1px solid var(--border)", fontSize: 13, fontFamily: "inherit" }}
              />
              <button
                onClick={() => handleRefine(draft, tweak[draft.id])}
                disabled={refining === draft.id || !(tweak[draft.id] || "").trim()}
                style={{
                  padding: "6px 12px", borderRadius: 8, border: "none",
                  background: "var(--primary)", color: "#fff", fontSize: 13, fontWeight: 600,
                  opacity: refining === draft.id || !(tweak[draft.id] || "").trim() ? 0.55 : 1,
                }}
              >
                {refining === draft.id ? "Tweaking…" : "Tweak"}
              </button>
            </div>

            <ProvenancePanel segments={provByDraft[draft.id] ?? draft.provenance} verifying={verifying === draft.id} />

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
                onClick={handleDraftReply}
                disabled={drafting || refining === draft.id}
                title="Generate a fresh reply"
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {drafting ? "Regenerating…" : "Regenerate"}
              </button>
              {draft.status !== "approved" && (
                <button
                  onClick={() => handleStatus(draft, "approved")}
                  title="Scientist review passed — ready for an account manager to post"
                  style={{
                    padding: "6px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--success)",
                    background: "var(--success-bg)",
                    color: "var(--success)",
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  Approve
                </button>
              )}
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

const Dot = ({ c }) => (
  <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: c, marginRight: 5, verticalAlign: "middle" }} />
);

// Clinical-safety trace, briefly: one status line, then only the claims that need
// a look. Grounded/general points aren't listed — the reassurance is the summary.
function ProvenancePanel({ segments, verifying }) {
  if (!Array.isArray(segments) || segments.length === 0) return null;
  const flagged = segments.filter((s) => s.level === "unverified" || s.level === "contradicted");
  const grounded = segments.filter((s) => s.level === "grounded").length;

  if (flagged.length === 0) {
    return (
      <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)" }}>
        <Dot c="#12b76a" />Grounded in her material. Nothing to verify.
      </div>
    );
  }

  return (
    <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-muted)", lineHeight: 1.5 }}>
      <div>
        <Dot c="#12b76a" />{grounded} grounded &nbsp;·&nbsp; <Dot c="#f79009" />{flagged.length} to verify
        {verifying && <span style={{ marginLeft: 8, fontStyle: "italic" }}>checking sources…</span>}
      </div>
      {flagged.map((s, i) => {
        const red = s.level === "contradicted";
        return (
          <div key={i} style={{ marginTop: 3 }}>
            <Dot c={red ? "#f04438" : "#f79009"} />
            <span style={{ color: "#374151" }}>"{s.text.trim().slice(0, 55)}{s.text.trim().length > 55 ? "…" : ""}"</span>
            {s.source_url ? (
              <>
                {" "}
                <a href={s.source_url} target="_blank" rel="noreferrer" style={{ color: "var(--primary)", fontWeight: 600 }}>source ↗</a>
              </>
            ) : (
              <span> — {red ? "contradicted, fix" : "unconfirmed, check"}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
