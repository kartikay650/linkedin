import { supabase } from "./supabase";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Attach the current Supabase session token to every API call.
async function authHeader() {
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handle(res, path, method) {
  if (res.status === 401) {
    await supabase.auth.signOut(); // session expired, bounce back to login
    throw new Error("Your session expired, please sign in again.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `${method || "GET"} ${path} failed: ${res.status}`);
  }
  return res.json();
}

async function request(path, options = {}) {
  const { headers: optHeaders, ...rest } = options;
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(await authHeader()), ...optHeaders },
    ...rest,
  });
  return handle(res, path, options.method);
}

// Multipart uploads must NOT set Content-Type manually, the browser needs to
// generate the boundary itself, which it can only do if fetch sets the header.
async function requestForm(path, formData) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { ...(await authHeader()) },
    body: formData,
  });
  return handle(res, path, "POST");
}

export const api = {
  listClients: () => request("/clients"),
  createClient: (payload) => request("/clients", { method: "POST", body: JSON.stringify(payload) }),
  docText: (file) => {
    const form = new FormData();
    form.append("file", file);
    return requestForm("/clients/doc-text", form);
  },
  extractBrand: (text) => request("/clients/extract-brand", { method: "POST", body: JSON.stringify({ text }) }),
  updateClient: (clientId, payload) =>
    request(`/clients/${clientId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteClient: (clientId) => request(`/clients/${clientId}`, { method: "DELETE" }),
  listPosts: (clientId, view = "active") => request(`/clients/${clientId}/posts?view=${encodeURIComponent(view)}`),
  updateDraft: (draftId, payload) =>
    request(`/drafts/${draftId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  draftReply: (postId) => request(`/posts/${postId}/draft`, { method: "POST" }),
  refineDraft: (draftId, instruction) =>
    request(`/drafts/${draftId}/refine`, { method: "POST", body: JSON.stringify({ instruction }) }),
  verifyClaims: (draftId) => request(`/drafts/${draftId}/verify-claims`, { method: "POST" }),
  syncClient: (clientId) => request(`/clients/${clientId}/sync`, { method: "POST" }),
  syncPlan: (clientId) => request("/sync/plan", { method: "POST", body: JSON.stringify({ client_id: clientId ?? null }) }),
  syncFire: (profiles) => request("/sync/fire", { method: "POST", body: JSON.stringify({ profiles }) }),
  dismissPost: (postId) => request(`/posts/${postId}/dismiss`, { method: "POST" }),
  apifyUsage: () => request("/apify-usage"),
  analytics: () => request("/analytics"),

  listCreators: (kind) => request(`/creators${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`),
  addCreator: (payload) => request("/creators", { method: "POST", body: JSON.stringify(payload) }),
  updateCreator: (id, payload) => request(`/creators/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteCreator: (id) => request(`/creators/${id}`, { method: "DELETE" }),
  setCreatorClients: (id, clientIds) =>
    request(`/creators/${id}/clients`, { method: "PUT", body: JSON.stringify({ client_ids: clientIds }) }),

  listFeedback: (clientId) => request(`/clients/${clientId}/feedback`),
  addFeedback: (clientId, note) =>
    request(`/clients/${clientId}/feedback`, { method: "POST", body: JSON.stringify({ note }) }),
  deleteFeedback: (clientId, feedbackId) =>
    request(`/clients/${clientId}/feedback/${feedbackId}`, { method: "DELETE" }),

  listWatchCreators: (clientId) => request(`/clients/${clientId}/watch-creators`),
  addWatchCreator: (clientId, payload) =>
    request(`/clients/${clientId}/watch-creators`, { method: "POST", body: JSON.stringify(payload) }),
  removeWatchCreator: (clientId, creatorId) =>
    request(`/clients/${clientId}/watch-creators/${creatorId}`, { method: "DELETE" }),

  listDocuments: (clientId) => request(`/clients/${clientId}/documents`),
  uploadDocument: (clientId, file) => {
    const form = new FormData();
    form.append("file", file);
    return requestForm(`/clients/${clientId}/documents/upload`, form);
  },
  addYoutubeDocument: (clientId, url) =>
    request(`/clients/${clientId}/documents/youtube`, { method: "POST", body: JSON.stringify({ url }) }),
  deleteDocument: (clientId, docId) =>
    request(`/clients/${clientId}/documents/${docId}`, { method: "DELETE" }),
  synthesizeTone: (clientId) => request(`/clients/${clientId}/tone-synthesis`, { method: "POST" }),
  extractBrandProfile: (clientId) => request(`/clients/${clientId}/extract-brand-profile`, { method: "POST" }),
  resolveCreator: (clientId, name) =>
    request(`/clients/${clientId}/resolve-creator`, { method: "POST", body: JSON.stringify({ name }) }),
  trackSuggestedCreators: (clientId, creators) =>
    request(`/clients/${clientId}/track-suggested-creators`, { method: "POST", body: JSON.stringify({ creators }) }),

  listProspects: (clientId) => request(`/clients/${clientId}/prospects`),
  discoverProspects: (clientId) => request(`/clients/${clientId}/prospects/discover`, { method: "POST" }),
  approveProspect: (clientId, prospectId) =>
    request(`/clients/${clientId}/prospects/${prospectId}/approve`, { method: "POST" }),
  rejectProspect: (clientId, prospectId) =>
    request(`/clients/${clientId}/prospects/${prospectId}/reject`, { method: "POST" }),
};
