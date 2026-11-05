import assert from "node:assert/strict";
import test from "node:test";
import { average, evaluateRanking, median } from "../src/metrics.js";

test("median handles odd and even samples", () => {
  assert.equal(median([9, 1, 5]), 5);
  assert.equal(median([4, 1, 8, 2]), 3);
  assert.equal(average([2, 4, 6]), 4);
});

test("Recall@K and nDCG@K use unique relevant sources", () => {
  const quality = evaluateRanking(["a.txt", "other.txt", "a.txt", "b.txt"], ["a.txt", "b.txt"], 4);
  assert.equal(quality.recall, 1);
  const expected = (1 + (1 / Math.log2(5))) / (1 + (1 / Math.log2(3)));
  assert.ok(Math.abs(quality.ndcg - expected) < 1e-12);
});

test("missing relevant results produce zero quality", () => {
  assert.deepEqual(evaluateRanking(["x.txt"], ["a.txt"], 5), { recall: 0, ndcg: 0 });
});
