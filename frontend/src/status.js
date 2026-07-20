// Pipeline stages, their labels, and one color each — shared by the tab bar and the
// post/reply cards so a post's stage looks the same everywhere.
// Flow: Queue (needs a draft) -> Draft (awaiting approval) -> Approved -> Posted.
export const STAGES = {
  active:   { label: "Queue",    color: "#475569", bg: "#eef2f6" }, // slate  — needs a draft
  draft:    { label: "Draft",    color: "#b45309", bg: "#fef3c7" }, // amber  — drafted, awaiting approval
  approved: { label: "Approved", color: "#047857", bg: "#d1fae5" }, // green  — ready to post
  posted:   { label: "Posted",   color: "#1d4ed8", bg: "#dbeafe" }, // blue   — done
  all:      { label: "All",      color: "#475569", bg: "#eef2f6" },
};

export const POST_VIEWS = ["active", "draft", "approved", "posted", "all"];

// The stage a post is in, derived from its drafts (highest reached stage wins).
// A generated-but-not-moved reply is "pending" and counts as Queue, not Draft.
export function postStage(post) {
  const statuses = (post.drafts || []).map((d) => d.status);
  if (statuses.includes("posted")) return "posted";
  if (statuses.includes("approved")) return "approved";
  if (statuses.includes("drafted")) return "draft";
  return "active"; // undrafted, or a generated (pending) reply still in the Queue
}

// Stage for a single draft. "pending" (just generated, still in Queue) reads as Queue;
// "drafted" (explicitly moved) reads as Draft.
export function draftStage(draft) {
  if (draft.status === "posted") return "posted";
  if (draft.status === "approved") return "approved";
  if (draft.status === "drafted") return "draft";
  return "active";
}
