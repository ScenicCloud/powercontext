import "./style.css";
import { api } from "./api.js";
import { EmbeddingEngine, MODEL_ID } from "./embedding.js";
import { textToDocuments } from "./text.js";

const $ = (selector) => document.querySelector(selector);
const settings = (() => {
  try {
    return JSON.parse(localStorage.getItem("stepfun.settings")) || {};
  } catch {
    return {};
  }
})();

const state = {
  collections: [],
  activeCollection: settings.activeCollection || "personal_kb",
  files: [],
  documents: [],
  busy: false,
  modelPromise: null,
  modelKey: null,
  modelLoadMs: 0,
  warmupMs: 0,
  operationSequence: 0,
  searchSequence: 0,
  documentSequence: 0,
  metrics: [],
};

try {
  state.metrics = JSON.parse(localStorage.getItem("stepfun.metrics")) || [];
} catch {
  state.metrics = [];
}

$("#dtype").value = settings.dtype || "auto";
$("#batch-size").value = String(settings.batchSize || 8);

let toastTimer;
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").className = `toast visible${error ? " error" : ""}`;
  toastTimer = setTimeout(() => ($("#toast").className = "toast"), 4500);
}

function formatMs(value) {
  if (!Number.isFinite(value)) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value.toFixed(1)} ms`;
}

function saveSettings() {
  localStorage.setItem(
    "stepfun.settings",
    JSON.stringify({
      activeCollection: state.activeCollection,
      dtype: $("#dtype").value,
      batchSize: Number($("#batch-size").value),
    }),
  );
}

function saveMetric(metric, collection = state.activeCollection) {
  state.metrics.unshift({
    timestamp: new Date().toISOString(),
    collection,
    model: MODEL_ID,
    dtype: engine.dtype || $("#dtype").value,
    requestedDtype: $("#dtype").value,
    backend: engine.backend,
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    ...metric,
  });
  state.metrics = state.metrics.slice(0, 100);
  localStorage.setItem("stepfun.metrics", JSON.stringify(state.metrics));
}

function updateBackend(backend, note = "") {
  const badge = $("#backend-badge");
  badge.className = `backend-badge${backend === "wasm" ? " fallback" : ""}`;
  badge.replaceChildren();
  const dot = document.createElement("span");
  const selected = $("#dtype").value;
  const dtype = engine.dtype || (selected === "auto" ? (backend === "webgpu" ? "fp16" : "q8") : selected);
  const precision = { q8: "INT8", fp16: "FP16", fp32: "FP32" }[dtype] || dtype;
  badge.append(dot, document.createTextNode(`${backend === "webgpu" ? "WebGPU" : "WASM"} · ${precision}`));
  if (note) $("#download-status").textContent = note;
}

const engine = new EmbeddingEngine({
  onProgress: (progress) => {
    if (progress.status === "progress") {
      const percent = Number.isFinite(progress.progress) ? ` ${progress.progress.toFixed(0)}%` : "";
      $("#download-status").textContent = `模型文件 ${progress.file || ""}${percent}`;
    } else if (progress.status === "done") {
      $("#download-status").textContent = `${progress.file || "模型文件"} 下载完成`;
    }
  },
  onBackendChange: (backend, note) => {
    updateBackend(backend, note);
    toast(note, true);
  },
});

async function ensureModel() {
  const key = `${MODEL_ID}:${$("#dtype").value}`;
  if (state.modelKey === key && engine.config) return;
  if (state.modelPromise) return state.modelPromise;

  state.modelPromise = (async () => {
    $("#load-model").disabled = true;
    $("#model-state").textContent = "加载中";
    $("#download-status").textContent = "正在初始化本地推理运行时…";
    try {
      const result = await engine.initialize({ model: MODEL_ID, dtype: $("#dtype").value, backend: "auto" });
      state.modelLoadMs = result.loadMs;
      updateBackend(result.backend);
      $("#download-status").textContent = "模型已加载，正在预热推理…";
      state.warmupMs = await engine.warmup();
      state.modelKey = key;
      $("#model-state").textContent = result.cached ? "缓存就绪" : "模型就绪";
      $("#download-status").textContent = `加载 ${formatMs(result.loadMs)} · 预热 ${formatMs(state.warmupMs)}`;
      $("#metric-load").textContent = formatMs(result.loadMs);
    } catch (error) {
      state.modelKey = null;
      $("#model-state").textContent = "加载失败";
      $("#download-status").textContent = error.message;
      throw error;
    } finally {
      $("#load-model").disabled = false;
    }
  })().finally(() => {
    state.modelPromise = null;
  });
  return state.modelPromise;
}

function setBusy(busy) {
  state.busy = busy;
  for (const selector of [
    "#dtype",
    "#batch-size",
    "#collection-select",
    "#file-input",
    "#search-button",
    "#load-sample",
    "#delete-collection",
    "#show-new-collection",
    "#new-collection-name",
    "#new-collection-form button[type=submit]",
    "#cancel-new-collection",
  ]) {
    $(selector).disabled = busy;
  }
  $("#import-button").disabled = busy || state.files.length === 0;
  $("#query").disabled = busy;
}

function setProgress(percent, message) {
  $("#import-progress").style.width = `${percent}%`;
  $("#import-status").textContent = message;
}

function renderCollections() {
  const select = $("#collection-select");
  select.replaceChildren();
  for (const collection of state.collections) {
    const option = document.createElement("option");
    option.value = collection.name;
    option.textContent = `${collection.name} (${collection.count})`;
    select.append(option);
  }
  if (!state.collections.some((collection) => collection.name === state.activeCollection)) {
    state.activeCollection = state.collections[0]?.name || "";
  }
  select.value = state.activeCollection;
  const active = state.collections.find((collection) => collection.name === state.activeCollection);
  $("#chunk-count").textContent = active?.count || 0;
  saveSettings();
}

async function refreshCollections() {
  const { collections } = await api.listCollections();
  state.collections = collections.sort((a, b) => a.name.localeCompare(b.name));
  renderCollections();
}

async function refreshDocuments() {
  if (!state.activeCollection) return;
  const sequence = ++state.documentSequence;
  const collection = state.activeCollection;
  const { documents } = await api.listDocuments(collection);
  if (sequence !== state.documentSequence || collection !== state.activeCollection) return;
  state.documents = documents;
  $("#source-count").textContent = new Set(documents.map((document) => document.metadata.contentHash)).size;
  const container = $("#documents");
  container.replaceChildren();
  if (documents.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "暂无内容，请先导入文本。";
    container.append(empty);
    return;
  }
  for (const record of documents.slice(-8).reverse()) {
    const item = document.createElement("article");
    item.className = "document-item";
    const title = document.createElement("strong");
    title.textContent = record.metadata.title;
    const preview = document.createElement("p");
    preview.textContent = record.text;
    const meta = document.createElement("span");
    meta.textContent = `${record.metadata.dtype.toUpperCase()} · CHUNK ${record.metadata.chunkIndex + 1}/${record.metadata.chunkCount}`;
    item.append(title, preview, meta);
    container.append(item);
  }
}

async function switchCollection(name) {
  state.searchSequence += 1;
  state.activeCollection = name;
  saveSettings();
  renderCollections();
  $("#results").replaceChildren();
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = "在当前知识库中输入查询，结果会显示在这里";
  $("#results").append(empty);
  $("#search-summary").textContent = "";
  await refreshDocuments();
}

function handleFiles(files) {
  const accepted = Array.from(files).filter((file) => {
    if (!/\.(txt|md|markdown|text)$/i.test(file.name)) {
      toast(`${file.name} 不是支持的文本文件`, true);
      return false;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast(`${file.name} 超过 5 MB`, true);
      return false;
    }
    return true;
  });
  const unique = new Map([...state.files, ...accepted].map((file) => [`${file.name}:${file.size}:${file.lastModified}`, file]));
  state.files = Array.from(unique.values());
  renderFiles();
}

function renderFiles() {
  const container = $("#selected-files");
  container.replaceChildren();
  state.files.forEach((file, index) => {
    const chip = document.createElement("span");
    chip.className = "file-chip";
    const label = document.createElement("span");
    label.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.onclick = () => {
      state.files.splice(index, 1);
      renderFiles();
    };
    chip.append(label, remove);
    container.append(chip);
  });
  $("#import-button").disabled = state.busy || state.files.length === 0;
}

async function importDocuments() {
  if (state.files.length === 0 || !state.activeCollection) return;
  const collection = state.activeCollection;
  const config = { model: MODEL_ID, dtype: $("#dtype").value };
  const batchSize = Number($("#batch-size").value);
  let inserted = 0;
  let skipped = 0;
  let embeddingMs = 0;
  let writeMs = 0;
  let refreshMs = 0;
  let processed = 0;
  const importStartedAt = performance.now();
  const operation = ++state.operationSequence;
  setBusy(true);
  setProgress(3, "读取与分块…");

  try {
    const documentGroups = await Promise.all(
      state.files.map(async (file) => textToDocuments(file.name, await file.text(), config)),
    );
    const documents = documentGroups.flat();
    if (documents.length === 0) throw new Error("所选文件没有可导入的文本");

    setProgress(8, `检查 ${documents.length} 个分块…`);
    const existing = await api.existingIds(collection, documents.map((document) => document.id));
    const existingIds = new Set(existing.ids);
    const pending = documents.filter((document) => !existingIds.has(document.id));
    skipped = documents.length - pending.length;

    if (pending.length > 0) {
      await ensureModel();
      for (const document of pending) document.metadata.dtype = engine.dtype;
      for (let offset = 0; offset < pending.length; offset += batchSize) {
        const batch = pending.slice(offset, offset + batchSize);
        setProgress(12 + (offset / pending.length) * 68, `本地向量化 ${Math.min(offset + batch.length, pending.length)}/${pending.length}`);
        const embedded = await engine.embed(batch.map((document) => document.text));
        embeddingMs += embedded.embedMs;
        const response = await api.addDocuments(
          collection,
          batch.map((document, index) => ({ ...document, embedding: embedded.embeddings[index] })),
        );
        inserted += response.inserted;
        skipped += response.skipped;
        writeMs += response.writeMs;
        processed += batch.length;
      }
    }

    setProgress(90, "刷新 seekdb 索引…");
    refreshMs = (await api.refresh(collection)).refreshMs;
    const totalMs = performance.now() - importStartedAt;
    saveMetric({
      type: "import",
      batchSize,
      chunks: processed,
      inserted,
      skipped,
      embeddingMs,
      writeMs,
      refreshMs,
      totalMs,
      throughput: embeddingMs > 0 ? (processed * 1000) / embeddingMs : 0,
      modelLoadMs: state.modelLoadMs,
      warmupMs: state.warmupMs,
    }, collection);
    setProgress(100, `新增 ${inserted} · 跳过 ${skipped}`);
    toast(inserted > 0 ? `已写入 ${inserted} 个分块，索引刷新完成` : "所有内容均已存在，索引已刷新");
    state.files = [];
    renderFiles();
  } catch (error) {
    if (inserted > 0) await api.refresh(collection);
    setProgress(0, "导入失败");
    toast(error.message, true);
  } finally {
    if (operation === state.operationSequence) setBusy(false);
    await Promise.all([refreshCollections(), refreshDocuments()]);
  }
}

function renderResults(payload, query) {
  const container = $("#results");
  container.replaceChildren();
  $("#search-summary").textContent = `${payload.results.length} 条结果 · ${payload.fusion} · 查询“${query}”`;
  if (payload.results.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "没有找到相关内容，请尝试其他查询或导入更多文档。";
    container.append(empty);
    return;
  }

  payload.results.forEach((result, index) => {
    const card = document.createElement("article");
    card.className = "result-card";
    const rank = document.createElement("span");
    rank.className = "result-rank";
    rank.textContent = String(index + 1).padStart(2, "0");
    const content = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = result.metadata.title;
    const text = document.createElement("p");
    const body = result.text.split("\n").slice(1).join("\n") || result.text;
    text.textContent = body.length > 420 ? `${body.slice(0, 420)}…` : body;
    const meta = document.createElement("div");
    meta.className = "result-meta";
    meta.textContent = `${result.metadata.source} · 分块 ${result.metadata.chunkIndex + 1}/${result.metadata.chunkCount} · ${result.metadata.dtype.toUpperCase()}`;
    content.append(title, text, meta);
    const score = document.createElement("div");
    score.className = "result-score";
    score.textContent = Number.isFinite(result.score) ? result.score.toFixed(5) : "—";
    const scoreLabel = document.createElement("small");
    scoreLabel.textContent = "RRF 融合得分";
    score.append(scoreLabel);
    card.append(rank, content, score);
    container.append(card);
  });
}

async function search(event) {
  event.preventDefault();
  const query = $("#query").value.trim();
  if (!query || !state.activeCollection) return;
  const collection = state.activeCollection;
  const sequence = ++state.searchSequence;
  const operation = ++state.operationSequence;
  const startedAt = performance.now();
  setBusy(true);
  $("#search-summary").textContent = "正在浏览器本地生成查询向量…";

  try {
    await ensureModel();
    const embedded = await engine.embed([query]);
    const response = await api.search(collection, {
      query,
      embedding: embedded.embeddings[0],
      topK: Number($("#top-k").value),
    });
    if (sequence !== state.searchSequence || collection !== state.activeCollection) return;
    const totalMs = performance.now() - startedAt;
    renderResults(response, query);
    $("#metric-embed").textContent = formatMs(embedded.embedMs);
    $("#metric-search").textContent = formatMs(response.searchMs);
    $("#metric-total").textContent = formatMs(totalMs);
    saveMetric({
      type: "query",
      query,
      embeddingMs: embedded.embedMs,
      searchMs: response.searchMs,
      totalMs,
      resultIds: response.results.map((result) => result.id),
      modelLoadMs: state.modelLoadMs,
    }, collection);
  } catch (error) {
    $("#search-summary").textContent = "检索失败";
    toast(error.message, true);
  } finally {
    if (operation === state.operationSequence) setBusy(false);
  }
}

$("#file-input").addEventListener("change", (event) => handleFiles(event.target.files));
$("#drop-zone").addEventListener("dragover", (event) => {
  event.preventDefault();
  $("#drop-zone").classList.add("dragging");
});
$("#drop-zone").addEventListener("dragleave", () => $("#drop-zone").classList.remove("dragging"));
$("#drop-zone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("#drop-zone").classList.remove("dragging");
  handleFiles(event.dataTransfer.files);
});
$("#import-button").addEventListener("click", importDocuments);
$("#search-form").addEventListener("submit", search);
$("#collection-select").addEventListener("change", (event) => switchCollection(event.target.value));
$("#refresh-documents").addEventListener("click", refreshDocuments);
$("#load-model").addEventListener("click", () => ensureModel().catch((error) => toast(error.message, true)));
$("#dtype").addEventListener("change", () => {
  state.modelKey = null;
  engine.dispose();
  saveSettings();
  updateBackend("wasm", "精度已更改，正在重新加载模型…");
  $("#backend-badge").className = "backend-badge idle";
  ensureModel().catch((error) => toast(error.message, true));
});
$("#batch-size").addEventListener("change", saveSettings);
$("#show-new-collection").addEventListener("click", () => {
  $("#new-collection-form").hidden = false;
  $("#new-collection-name").focus();
});
$("#cancel-new-collection").addEventListener("click", () => ($("#new-collection-form").hidden = true));
$("#new-collection-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  try {
    const name = $("#new-collection-name").value.trim();
    await api.createCollection(name);
    $("#new-collection-form").hidden = true;
    $("#new-collection-name").value = "";
    await refreshCollections();
    await switchCollection(name);
    toast(`知识库 ${name} 已创建`);
  } catch (error) {
    toast(error.message, true);
  }
});
$("#delete-collection").addEventListener("click", async () => {
  if (state.collections.length <= 1) {
    toast("至少需要保留一个知识库", true);
    return;
  }
  const name = state.activeCollection;
  if (!confirm(`确定删除知识库 ${name} 及其全部分块吗？此操作不可撤销。`)) return;
  try {
    await api.deleteCollection(name);
    await refreshCollections();
    await switchCollection(state.activeCollection);
    toast(`知识库 ${name} 已删除`);
  } catch (error) {
    toast(error.message, true);
  }
});
$("#load-sample").addEventListener("click", async () => {
  try {
    const response = await fetch("/samples/seekdb-guide.txt");
    if (!response.ok) throw new Error("示例语料加载失败");
    const text = await response.text();
    handleFiles([new File([text], "seekdb-guide.txt", { type: "text/plain" })]);
    toast("示例语料已加入导入队列");
  } catch (error) {
    toast(error.message, true);
  }
});
$("#export-metrics").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(state.metrics, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `stepfun-metrics-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
});

async function initialize() {
  try {
    await refreshCollections();
    await refreshDocuments();
    ensureModel().catch((error) => toast(`模型加载失败：${error.message}`, true));
  } catch (error) {
    toast(`应用初始化失败：${error.message}`, true);
  }
}

initialize();
