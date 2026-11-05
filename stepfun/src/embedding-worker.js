import { env, pipeline } from "@huggingface/transformers";

env.localModelPath = "/models/";
env.allowLocalModels = true;
env.allowRemoteModels = false;

let extractor = null;
let configurationKey = "";

async function initialize(config, id) {
  const key = `${config.model}:${config.dtype}:${config.device}`;
  if (extractor && configurationKey === key) {
    self.postMessage({ type: "ready", id, cached: true });
    return;
  }

  const startedAt = performance.now();
  extractor = await pipeline("feature-extraction", config.model, {
    dtype: config.dtype,
    device: config.device,
    progress_callback: (progress) => self.postMessage({ type: "download", id, progress }),
  });
  configurationKey = key;
  self.postMessage({ type: "ready", id, loadMs: performance.now() - startedAt, cached: false });
}

async function embed(texts, id, warmup = false) {
  const startedAt = performance.now();
  const output = await extractor(texts, {
    pooling: "mean",
    normalize: true,
    truncation: true,
    max_length: 512,
  });
  const [rows, dimension] = output.dims;
  const embeddings = Array.from({ length: rows }, (_, row) =>
    Array.from(output.data.slice(row * dimension, (row + 1) * dimension)),
  );
  self.postMessage({ type: "embedded", id, embeddings, embedMs: performance.now() - startedAt, warmup });
}

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "initialize") await initialize(data.config, data.id);
    if (data.type === "embed") await embed(data.texts, data.id, data.warmup);
  } catch (error) {
    self.postMessage({ type: "error", id: data.id, message: error.message, operation: data.type });
  }
};
