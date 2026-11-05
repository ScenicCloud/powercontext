import assert from "node:assert/strict";

const base = process.env.API_URL || "http://127.0.0.1:3000";
const name = `smoke_${Date.now().toString(36)}`;
const first = Array.from({ length: 384 }, (_, index) => (index === 0 ? 1 : 0));
const second = Array.from({ length: 384 }, (_, index) => (index === 1 ? 1 : 0));

async function request(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json" },
  });
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) throw new Error(body.error);
  return body;
}

try {
  await request("/api/collections", { method: "POST", body: JSON.stringify({ name }) });
  const metadata = {
    source: "smoke.txt",
    title: "smoke",
    contentHash: "smoke",
    model: "manual-test-vector",
    dtype: "fp32",
    chunkIndex: 0,
    chunkCount: 1,
  };
  await request(`/api/collections/${name}/documents`, {
    method: "POST",
    body: JSON.stringify({
      documents: [
        { id: "smoke_alpha", text: "alpha exact keyword", embedding: first, metadata },
        { id: "smoke_beta", text: "beta other content", embedding: second, metadata },
      ],
    }),
  });
  await request(`/api/collections/${name}/refresh`, { method: "POST" });
  const response = await request(`/api/collections/${name}/search`, {
    method: "POST",
    body: JSON.stringify({ query: "alpha", embedding: first, topK: 2 }),
  });
  assert.equal(response.results[0]?.id, "smoke_alpha");
  assert.equal(response.fusion, "seekdb DBMS_HYBRID_SEARCH / RRF");
  console.log(JSON.stringify(response, null, 2));
  console.log("seekdb native hybrid smoke test passed");
} finally {
  await request(`/api/collections/${name}`, { method: "DELETE" });
}
