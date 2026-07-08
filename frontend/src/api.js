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

export const api = {
  listClients: () => request("/clients"),
  listPosts: (clientId) => request(`/clients/${clientId}/posts`),
  updateDraft: (draftId, payload) =>
    request(`/drafts/${draftId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  draftReply: (postId) => request(`/posts/${postId}/draft`, { method: "POST" }),
  syncClient: (clientId) => request(`/clients/${clientId}/sync`, { method: "POST" }),
};
