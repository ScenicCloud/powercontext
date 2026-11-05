export const MODEL_ID = "Xenova/all-MiniLM-L6-v2";

export async function detectBackend() {
  if (!navigator.gpu) return "wasm";
  try {
    const adapter = await navigator.gpu.requestAdapter();
    return adapter ? "webgpu" : "wasm";
  } catch {
    return "wasm";
  }
}

export class EmbeddingEngine {
  constructor({ onProgress, onBackendChange } = {}) {
    this.onProgress = onProgress;
    this.onBackendChange = onBackendChange;
    this.worker = null;
    this.pending = new Map();
    this.sequence = 0;
    this.config = null;
    this.backend = null;
    this.dtype = null;
    this.loadMs = 0;
  }

  async initialize(config) {
    const requestedBackend = config.backend || "auto";
    const device = requestedBackend === "auto" ? await detectBackend() : requestedBackend;
    const dtype = config.dtype === "auto" ? (device === "webgpu" ? "fp16" : "q8") : config.dtype;
    const key = `${config.model}:${dtype}:${device}`;
    if (this.config === key) return { backend: this.backend, dtype: this.dtype, loadMs: 0, cached: true };

    this.dispose();
    const startedAt = performance.now();
    try {
      const result = await this.startWorker({ ...config, dtype }, device);
      this.config = key;
      this.backend = device;
      this.dtype = dtype;
      this.loadMs = performance.now() - startedAt;
      return { backend: device, dtype, loadMs: this.loadMs, cached: result.cached };
    } catch (error) {
      if (device !== "webgpu" || requestedBackend === "webgpu") throw error;
      const fallbackDtype = config.dtype === "auto" ? "q8" : config.dtype;
      this.onBackendChange?.("wasm", `WebGPU 初始化失败，已自动降级：${error.message}`);
      const result = await this.startWorker({ ...config, dtype: fallbackDtype }, "wasm");
      this.config = `${config.model}:${fallbackDtype}:wasm`;
      this.backend = "wasm";
      this.dtype = fallbackDtype;
      this.loadMs = performance.now() - startedAt;
      return { backend: "wasm", dtype: fallbackDtype, loadMs: this.loadMs, cached: result.cached };
    }
  }

  startWorker(config, device) {
    this.dispose();
    this.worker = new Worker(new URL("./embedding-worker.js", import.meta.url), { type: "module" });
    this.worker.onmessage = ({ data }) => this.handleMessage(data);
    this.worker.onerror = (event) => {
      for (const { reject } of this.pending.values()) reject(new Error(event.message));
      this.pending.clear();
    };
    return this.call({ type: "initialize", config: { ...config, device } });
  }

  handleMessage(data) {
    const pending = this.pending.get(data.id);
    if (data.type === "download") {
      this.onProgress?.(data.progress);
      return;
    }
    if (!pending) return;
    this.pending.delete(data.id);
    if (data.type === "error") pending.reject(new Error(data.message));
    else pending.resolve(data);
  }

  call(message) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.worker.postMessage({ ...message, id });
    });
  }

  async embed(texts) {
    if (!this.worker || !this.config) throw new Error("模型尚未加载");
    return this.call({ type: "embed", texts });
  }

  async warmup() {
    const result = await this.call({ type: "embed", texts: ["model warmup"], warmup: true });
    return result.embedMs;
  }

  dispose() {
    this.worker?.terminate();
    this.worker = null;
    this.config = null;
    this.dtype = null;
    for (const { reject } of this.pending.values()) reject(new Error("模型已重新配置"));
    this.pending.clear();
  }
}
