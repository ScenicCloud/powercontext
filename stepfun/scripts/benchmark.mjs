import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const url = process.env.BENCHMARK_URL || "http://127.0.0.1:5173/benchmark.html";
const browser = await chromium.launch({
  channel: process.env.CHROME_CHANNEL || undefined,
  headless: process.env.HEADFUL !== "1",
  args: ["--enable-unsafe-webgpu"],
});

try {
  const page = await browser.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") console.error(`browser: ${message.text()}`);
  });
  await page.goto(url);
  await page.locator("#run-benchmark").click();
  await page.waitForFunction(() => document.body.dataset.status === "complete", undefined, { timeout: 20 * 60 * 1000 });
  const raw = await page.locator("#raw-output").textContent();
  const parsed = JSON.parse(raw);
  await mkdir("results", { recursive: true });
  await writeFile("results/benchmark.json", `${JSON.stringify(parsed, null, 2)}\n`);
  if (parsed.configurations.some((configuration) => configuration.error)) {
    throw new Error("至少一组基准配置失败，请查看 results/benchmark.json");
  }
  console.table(
    parsed.configurations.map((configuration) => ({
      configuration: configuration.label,
      backend: configuration.backend,
      dtype: configuration.dtype,
      throughput: configuration.throughput.toFixed(2),
      searchMsP50: configuration.searchMsP50.toFixed(2),
      totalMsP50: configuration.totalMsP50.toFixed(2),
      recallAt5: configuration.recallAt5.toFixed(4),
      ndcgAt5: configuration.ndcgAt5.toFixed(4),
    })),
  );
  console.log("Saved results/benchmark.json");
} finally {
  await browser.close();
}
