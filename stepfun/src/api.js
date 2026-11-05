async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (response.status === 204) return null;
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

export const api = {
  health: () => request("/api/health"),
  listCollections: () => request("/api/collections"),
  createCollection: (name) => request("/api/collections", { method: "POST", body: JSON.stringify({ name }) }),
  deleteCollection: (name) => request(`/api/collections/${name}`, { method: "DELETE" }),
  listDocuments: (name) => request(`/api/collections/${name}/documents`),
  async existingIds(name, ids) {
    const existing = [];
    for (let offset = 0; offset < ids.length; offset += 5000) {
      const response = await request(`/api/collections/${name}/existing-ids`, {
        method: "POST",
        body: JSON.stringify({ ids: ids.slice(offset, offset + 5000) }),
      });
      existing.push(...response.ids);
    }
    return { ids: existing };
  },
  addDocuments: (name, documents) =>
    request(`/api/collections/${name}/documents`, {
      method: "POST",
      body: JSON.stringify({ documents }),
    }),
  refresh: (name) => request(`/api/collections/${name}/refresh`, { method: "POST" }),
  search: (name, body) =>
    request(`/api/collections/${name}/search`, { method: "POST", body: JSON.stringify(body) }),
};
