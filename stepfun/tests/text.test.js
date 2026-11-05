import assert from "node:assert/strict";
import test from "node:test";
import { chunkText, textToDocuments } from "../src/text.js";

test("chunkText handles empty input", () => {
  assert.deepEqual(chunkText(" \n "), []);
});

test("chunkText covers long text with bounded deterministic chunks", () => {
  const input = Array.from({ length: 30 }, (_, index) => `第 ${index} 段。${"本地向量检索。".repeat(40)}`).join("\n\n");
  const first = chunkText(input, 300, 40);
  const second = chunkText(input, 300, 40);
  assert.deepEqual(first, second);
  assert.ok(first.length > 5);
  assert.ok(first.every((chunk) => chunk.length > 0 && chunk.length <= 300));
  assert.ok(first.join("").includes("第 0 段"));
  assert.ok(first.at(-1).includes("本地向量检索"));
});

test("textToDocuments produces stable incremental IDs and complete metadata", async () => {
  const config = { model: "Xenova/all-MiniLM-L6-v2", dtype: "q8" };
  const first = await textToDocuments("notes.md", "第一段内容\n\n第二段内容", config);
  const second = await textToDocuments("notes.md", "第一段内容\n\n第二段内容", config);
  assert.deepEqual(first.map((document) => document.id), second.map((document) => document.id));
  assert.equal(first[0].metadata.chunkCount, first.length);
  assert.equal(first[0].metadata.dtype, "q8");
  assert.equal(first[0].metadata.contentHash.length, 64);
  assert.ok(first[0].text.startsWith("notes\n"));
});
