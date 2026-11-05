import { api } from "./api.js";
import { detectBackend, EmbeddingEngine, MODEL_ID } from "./embedding.js";
import { average, evaluateRanking, median } from "./metrics.js";
import { textToDocuments } from "./text.js";

const $ = (selector) => document.querySelector(selector);
const report = {
  startedAt: null,
  finishedAt: null,
  environment: null,
  model: null,
  dataset: null,
  runs: [],
  configurations: [],
};
let dataset;
let manifest;
let running = false;

function updateRaw() {
  $("#raw-output").textContent = JSON.stringify(report, null, 2);
}

function setStatus(message, completed, total) {
  $("#benchmark-status").textContent = message;
  $("#benchmark-progress").textContent = `${completed} / ${total}`;
  $("#benchmark-progress-bar").style.width = `${total ? (completed / total) * 100 : 0}%`;
}

function bytesLabel(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`;
}

function renderRows() {
  const tbody = $("#benchmark-results");
  tbody.replaceChildren();
  if (!report.configurations.length) {
    const row = document.createElement("tr");
    row.className = "lab-empty";
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.textContent = "正在等待第一组测试完成…";
    row.append(cell);
    tbody.append(row);
    return;
  }
  for (const result of report.configurations) {
    const row = document.createElement("tr");
    const values = result.error
      ? [`${result.label} · 失败`, "—", "—", "—", "—", "—", "—"]
      : [
          result.label,
          bytesLabel(result.modelBytes),
          `${result.throughput.toFixed(2)} chunks/s`,
          `${result.searchMsP50.toFixed(2)} ms`,
          `${result.totalMsP50.toFixed(2)} ms`,
          result.recallAt5.toFixed(4),
          result.ndcgAt5.toFixed(4),
        ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 0) {
        const detail = document.createElement("small");
        detail.textContent = result.error || `${result.dtype.toUpperCase()} · ${result.backend} · batch ${result.batchSize}`;
        cell.append(detail);
      }
      row.append(cell);
    });
    tbody.append(row);
  }
}

async function runConfiguration(spec, index, total) {
  const label = `${spec.dtype === "fp32" ? "FP32 基线" : "自适应 FP16/INT8"} + ${spec.backend === "auto" ? "自动后端" : "WASM"}`;
  const collection = `bench_${spec.dtype}_${Date.now().toString(36)}_${index}`;
  let fallbackReason = "";
  const engine = new EmbeddingEngine({
    onProgress: (progress) => {
      if (progress.status === "progress") setStatus(`${label} · ${progress.file} ${progress.progress?.toFixed(0) || 0}%`, index, total);
    },
    onBackendChange: (_backend, note) => {
      fallbackReason = note;
    },
  });
  const raw = { label, requestedBackend: spec.backend, dtype: spec.dtype, collection, batches: [], queries: [] };

  try {
    setStatus(`${label} · 创建独立集合`, index, total);
    await api.createCollection(collection);
    const initialized = await engine.initialize({ model: MODEL_ID, dtype: spec.dtype, backend: spec.backend });
    raw.backend = initialized.backend;
    raw.dtype = initialized.dtype;
    raw.fallbackReason = fallbackReason || null;
    raw.modelLoadMs = initialized.loadMs;
    raw.warmupMs = await engine.warmup();
    raw.modelBytes = {
      q8: manifest.modelSizes.int8Bytes,
      fp16: manifest.modelSizes.fp16Bytes,
      fp32: manifest.modelSizes.fp32Bytes,
    }[initialized.dtype];
    const documents = (
      await Promise.all(
        dataset.documents.map((document) =>
          textToDocuments(document.source, document.text, { ...spec, model: MODEL_ID, dtype: initialized.dtype }),
        ),
      )
    ).flat();

    let embeddingMs = 0;
    let writeMs = 0;
    for (let offset = 0; offset < documents.length; offset += spec.batchSize) {
      const batch = documents.slice(offset, offset + spec.batchSize);
      setStatus(`${label} · 向量化 ${offset + batch.length}/${documents.length}`, index, total);
      const embedded = await engine.embed(batch.map((document) => document.text));
      const written = await api.addDocuments(
        collection,
        batch.map((document, batchIndex) => ({ ...document, embedding: embedded.embeddings[batchIndex] })),
      );
      raw.batches.push({ chunks: batch.length, embeddingMs: embedded.embedMs, writeMs: written.writeMs });
      embeddingMs += embedded.embedMs;
      writeMs += written.writeMs;
    }
    raw.embeddingMs = embeddingMs;
    raw.writeMs = writeMs;
    raw.refreshMs = (await api.refresh(collection)).refreshMs;

    for (let run = 0; run < spec.runs; run += 1) {
      for (const query of dataset.queries) {
        setStatus(`${label} · 查询第 ${run + 1}/${spec.runs} 轮`, index, total);
        const startedAt = performance.now();
        const embedded = await engine.embed([query.query]);
        const response = await api.search(collection, {
          query: query.query,
          embedding: embedded.embeddings[0],
          topK: dataset.k,
        });
        const totalMs = performance.now() - startedAt;
        const sources = response.results.map((result) => result.metadata.source);
        const quality = evaluateRanking(sources, query.relevantSources, dataset.k);
        raw.queries.push({
          run,
          query: query.query,
          embeddingMs: embedded.embedMs,
          searchMs: response.searchMs,
          totalMs,
          sources,
          ...quality,
        });
      }
    }

    const firstRun = raw.queries.filter((query) => query.run === 0);
    return {
      label,
      dtype: raw.dtype,
      backend: raw.backend,
      batchSize: spec.batchSize,
      modelBytes: raw.modelBytes,
      modelLoadMs: raw.modelLoadMs,
      warmupMs: raw.warmupMs,
      embeddingMs,
      writeMs,
      refreshMs: raw.refreshMs,
      throughput: (documents.length * 1000) / embeddingMs,
      queryEmbeddingMsP50: median(raw.queries.map((query) => query.embeddingMs)),
      searchMsP50: median(raw.queries.map((query) => query.searchMs)),
      totalMsP50: median(raw.queries.map((query) => query.totalMs)),
      firstQueryTotalMs: firstRun[0]?.totalMs || 0,
      recallAt5: average(raw.queries.map((query) => query.recall)),
      ndcgAt5: average(raw.queries.map((query) => query.ndcg)),
    };
  } catch (error) {
    raw.error = error.message;
    return { label, dtype: spec.dtype, backend: raw.backend || spec.backend, batchSize: spec.batchSize, error: error.message };
  } finally {
    engine.dispose();
    report.runs.push(raw);
    if ($("#benchmark-cleanup").checked) {
      try {
        await api.deleteCollection(collection);
      } catch (error) {
        raw.cleanupError = error.message;
      }
    }
    updateRaw();
  }
}

async function runBenchmark() {
  if (running) return;
  const specs = [];
  const runs = Number($("#benchmark-runs").value);
  const batchSize = Number($("#benchmark-batch").value);
  if ($("#run-fp32").checked) specs.push({ dtype: "fp32", backend: "auto" });
  if ($("#run-int8").checked) specs.push({ dtype: "auto", backend: "auto" });
  if ($("#run-wasm").checked) specs.push({ dtype: "auto", backend: "wasm" });
  if (!specs.length || runs < 1 || runs > 5) return;
  specs.forEach((spec) => Object.assign(spec, { runs, batchSize }));

  running = true;
  $("#run-benchmark").disabled = true;
  $("#export-benchmark").disabled = true;
  document.body.dataset.status = "running";
  report.startedAt = new Date().toISOString();
  report.finishedAt = null;
  report.runs = [];
  report.configurations = [];
  report.dataset = { name: dataset.name, documents: dataset.documents.length, queries: dataset.queries.length, k: dataset.k, runs, batchSize };
  const backend = await detectBackend();
  const adapter = backend === "webgpu" ? await navigator.gpu.requestAdapter() : null;
  report.environment = {
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory || null,
    webgpuDetected: backend,
    webgpuFeatures: adapter ? Array.from(adapter.features) : [],
    webgpuAdapter: adapter?.info
      ? {
          vendor: adapter.info.vendor,
          architecture: adapter.info.architecture,
          device: adapter.info.device,
          description: adapter.info.description,
        }
      : null,
  };
  report.model = manifest;
  updateRaw();
  renderRows();

  for (let index = 0; index < specs.length; index += 1) {
    const result = await runConfiguration(specs[index], index, specs.length);
    report.configurations.push(result);
    renderRows();
    updateRaw();
  }
  report.finishedAt = new Date().toISOString();
  setStatus("全部测试完成", specs.length, specs.length);
  document.body.dataset.status = "complete";
  $("#run-benchmark").disabled = false;
  $("#export-benchmark").disabled = false;
  running = false;
  updateRaw();
}

$("#run-benchmark").addEventListener("click", runBenchmark);
$("#export-benchmark").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `localbase-benchmark-${Date.now()}.json`;
  link.click();
  URL.revokeObjectURL(url);
});

async function initialize() {
  $("#environment-info").textContent = `${navigator.userAgent} · ${navigator.hardwareConcurrency || "?"} logical cores`;
  const backend = await detectBackend();
  $("#backend-capability").textContent = backend === "webgpu" ? "检测到 WebGPU，将优先使用" : "未检测到 WebGPU，自动后端将使用 WASM";
  try {
    const [datasetResponse, manifestResponse] = await Promise.all([
      fetch("/data/evaluation.json"),
      fetch("/models/manifest.json"),
    ]);
    if (!datasetResponse.ok || !manifestResponse.ok) throw new Error("缺少评测数据或模型清单，请先运行 npm run model:download");
    dataset = await datasetResponse.json();
    manifest = await manifestResponse.json();
    $("#model-info").textContent = `${manifest.model} @ ${manifest.revision} · FP32 ${bytesLabel(manifest.modelSizes.fp32Bytes)} · FP16 ${bytesLabel(manifest.modelSizes.fp16Bytes)} · INT8 ${bytesLabel(manifest.modelSizes.int8Bytes)}`;
    report.model = manifest;
    updateRaw();
  } catch (error) {
    $("#run-benchmark").disabled = true;
    setStatus(error.message, 0, 0);
  }
}

initialize();
