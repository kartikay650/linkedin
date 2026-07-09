const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `${options.method || "GET"} ${path} failed: ${res.status}`);
  }
  return res.json();
}

// Multipart uploads must NOT set Content-Type manually — the browser needs to
// generate the boundary itself, which it can only do if fetch sets the header.
async function requestForm(path, formData) {
  const res = await fetch(`${BASE_URL}${path}`, { method: "POST", body: formData });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail || `POST ${path} failed: ${res.status}`);
  }
  return res.json();
}

export const api = {
  listClients: () => request("/clients"),
  listBurners: () => request("/burners"),
  createClient: (payload) => request("/clients", { method: "POST", body: JSON.stringify(payload) }),
  updateClient: (clientId, payload) =>
    request(`/clients/${clientId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listPosts: (clientId) => request(`/clients/${clientId}/posts`),
  updateDraft: (draftId, payload) =>
    request(`/drafts/${draftId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  draftReply: (postId) => request(`/posts/${postId}/draft`, { method: "POST" }),
  syncClient: (clientId) => request(`/clients/${clientId}/sync`, { method: "POST" }),

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

  listProspects: (clientId) => request(`/clients/${clientId}/prospects`),
  discoverProspects: (clientId) => request(`/clients/${clientId}/prospects/discover`, { method: "POST" }),
  approveProspect: (clientId, prospectId) =>
    request(`/clients/${clientId}/prospects/${prospectId}/approve`, { method: "POST" }),
  rejectProspect: (clientId, prospectId) =>
    request(`/clients/${clientId}/prospects/${prospectId}/reject`, { method: "POST" }),
};
