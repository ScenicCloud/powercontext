import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { textToDocuments } from "../src/text.js";

const url = process.env.E2E_URL || "http://127.0.0.1:5173";
const collection = `e2e_${Date.now().toString(36)}`;
const browser = await chromium.launch({
  channel: process.env.CHROME_CHANNEL || undefined,
  headless: process.env.HEADFUL !== "1",
  args: ["--disable-webgpu"],
});
const report = { collection, checks: [], consoleErrors: [] };

try {
  await mkdir("results", { recursive: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on("console", (message) => {
    if (message.type() === "error") report.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => report.consoleErrors.push(error.message));
  await page.goto(url);
  await page.locator("#show-new-collection").click();
  await page.locator("#new-collection-name").fill(collection);
  await page.locator("#new-collection-form button[type=submit]").click();
  await page.waitForFunction((name) => document.querySelector("#collection-select").value === name, collection);
  report.checks.push("create and select collection");

  await page.locator("#load-sample").click();
  await page.locator("#import-button").click();
  await page.waitForFunction(() => /新增 [1-9]/.test(document.querySelector("#import-status").textContent), undefined, {
    timeout: 180000,
  });
  await page.waitForFunction(() => Number(document.querySelector("#chunk-count").textContent) > 0);
  await page.waitForSelector(".document-item");
  const importedCount = Number(await page.locator("#chunk-count").textContent());
  assert.ok(importedCount > 0);
  assert.doesNotMatch(await page.locator("#documents").textContent(), /AUTO/);
  assert.match(await page.locator("#backend-badge").textContent(), /WASM/);
  report.importedCount = importedCount;
  report.checks.push("browser WASM embedding, seekdb write and index refresh");

  await page.locator("#query").fill("混合检索如何兼顾关键词和语义？");
  await page.locator("#search-button").click();
  await page.waitForSelector(".result-card", { timeout: 60000 });
  assert.match(await page.locator("#search-summary").textContent(), /DBMS_HYBRID_SEARCH/);
  report.firstResult = await page.locator(".result-card h3").first().textContent();
  report.searchMs = await page.locator("#metric-search").textContent();
  report.totalMs = await page.locator("#metric-total").textContent();
  report.checks.push("local query embedding and database hybrid results");
  await page.screenshot({ path: "results/app.png", fullPage: true });

  await page.locator("#load-sample").click();
  await page.locator("#import-button").click();
  await page.waitForFunction(() => /跳过 [1-9]/.test(document.querySelector("#import-status").textContent));
  assert.equal(Number(await page.locator("#chunk-count").textContent()), importedCount);
  report.checks.push("incremental duplicate skip without collection growth");

  const recoveryText = "中断恢复测试：这一段文本已经写入 seekdb，但对应索引尚未刷新。";
  const recoveryDocuments = await textToDocuments("recovery.txt", recoveryText, {
    model: "Xenova/all-MiniLM-L6-v2",
    dtype: "q8",
  });
  const testEmbedding = Array.from({ length: 384 }, () => 1 / Math.sqrt(384));
  const origin = new URL(url).origin;
  const writeResponse = await fetch(`${origin}/api/collections/${collection}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ documents: recoveryDocuments.map((document) => ({ ...document, embedding: testEmbedding })) }),
  });
  assert.equal(writeResponse.status, 200);
  await page.locator("#file-input").setInputFiles({ name: "recovery.txt", mimeType: "text/plain", buffer: Buffer.from(recoveryText) });
  await page.locator("#import-button").click();
  await page.waitForFunction(() => document.querySelector("#import-status").textContent === "新增 0 · 跳过 1");
  const searchResponse = await fetch(`${origin}/api/collections/${collection}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: "no_matching_lexical_token", embedding: testEmbedding, topK: 20 }),
  });
  const recoveryResults = await searchResponse.json();
  assert.ok(recoveryResults.results.some((result) => result.id === recoveryDocuments[0].id));
  report.checks.push("duplicate retry refreshes an interrupted unindexed write");

  await page.locator("#collection-select").selectOption("personal_kb");
  await page.locator("#collection-select").selectOption(collection);
  await page.waitForSelector(".document-item");
  assert.equal(Number(await page.locator("#chunk-count").textContent()), importedCount + recoveryDocuments.length);
  report.checks.push("collection switch restores current documents and count");

  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#delete-collection").click();
  await page.waitForFunction((name) => document.querySelector("#collection-select").value !== name, collection);
  report.checks.push("test collection cleanup");
  report.backend = "WASM (WebGPU disabled by browser flag)";
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = error.stack;
  throw error;
} finally {
  await mkdir("results", { recursive: true });
  await writeFile("results/e2e.json", `${JSON.stringify(report, null, 2)}\n`);
  await browser.close();
}

console.log(`E2E passed: ${report.checks.length} checks`);
