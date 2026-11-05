import assert from "node:assert/strict";
import test from "node:test";
import { api } from "../src/api.js";

test("existing ID lookups are split into server-sized batches", async (context) => {
  const originalFetch = globalThis.fetch;
  const batches = [];
  globalThis.fetch = async (_path, options) => {
    const ids = JSON.parse(options.body).ids;
    batches.push(ids.length);
    return { ok: true, status: 200, json: async () => ({ ids }) };
  };
  context.after(() => {
    globalThis.fetch = originalFetch;
  });

  const ids = Array.from({ length: 5001 }, (_, index) => `doc_${index}`);
  const result = await api.existingIds("test_collection", ids);
  assert.deepEqual(batches, [5000, 1]);
  assert.equal(result.ids.length, ids.length);
});
