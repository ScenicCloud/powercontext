import assert from "node:assert/strict";
import test from "node:test";
import { validateCollectionName, validateDocuments, validateEmbedding, validateSearch } from "../server/validation.js";

const embedding = Array.from({ length: 384 }, (_, index) => index / 384);
const document = {
  id: "doc_abc_0",
  text: "本地检索",
  embedding,
  metadata: {
    source: "a.txt",
    title: "a",
    contentHash: "abc",
    model: "model",
    dtype: "q8",
    chunkIndex: 0,
    chunkCount: 1,
  },
};

test("collection names are constrained before reaching seekdb", () => {
  assert.equal(validateCollectionName("research_notes"), "research_notes");
  assert.throws(() => validateCollectionName("bad-name"));
  assert.throws(() => validateCollectionName("1bad"));
});

test("embeddings require exactly 384 finite values", () => {
  assert.equal(validateEmbedding(embedding), embedding);
  assert.throws(() => validateEmbedding([1, 2, 3]));
  const invalid = [...embedding];
  invalid[10] = Number.NaN;
  assert.throws(() => validateEmbedding(invalid));
});

test("document validation preserves only supported metadata", () => {
  const [validated] = validateDocuments([document]);
  assert.equal(validated.metadata.source, "a.txt");
  assert.ok(validated.metadata.importedAt);
  assert.equal(validated.embedding.length, 384);
  assert.throws(() => validateDocuments([]));
  assert.throws(() => validateDocuments(Array.from({ length: 33 }, () => document)));
});

test("search validation enforces query and topK boundaries", () => {
  const result = validateSearch({ query: " hybrid ", embedding, topK: 5 });
  assert.equal(result.query, "hybrid");
  assert.equal(result.topK, 5);
  assert.throws(() => validateSearch({ query: "", embedding }));
  assert.throws(() => validateSearch({ query: "valid", embedding, topK: 21 }));
});
