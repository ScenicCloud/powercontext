import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

const model = "Xenova/all-MiniLM-L6-v2";
const revision = "751bff37182d3f1213fa05d7196b954e230abad9";
const expectedFiles = {
  "config.json": { bytes: 650, sha256: "7135149f7cffa1a573466c6e4d8423ed73b62fd2332c575bf738a0d033f70df7" },
  "tokenizer.json": { bytes: 711661, sha256: "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0" },
  "tokenizer_config.json": { bytes: 366, sha256: "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3" },
  "vocab.txt": { bytes: 231508, sha256: "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3" },
  "special_tokens_map.json": { bytes: 125, sha256: "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3" },
  "onnx/model.onnx": {
    bytes: 90387606,
    sha256: "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e",
  },
  "onnx/model_fp16.onnx": {
    bytes: 45297825,
    sha256: "2cdb5e58291813b6d6e248ed69010100246821a367fa17b1b81ae9483744533d",
  },
  "onnx/model_quantized.onnx": {
    bytes: 22972370,
    sha256: "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1",
  },
};
const destination = path.resolve("public/models", model);
const endpoint = process.env.HF_ENDPOINT || "https://hf-mirror.com";
const manifest = {
  model,
  revision,
  source: `https://huggingface.co/${model}/tree/${revision}`,
  downloadedAt: new Date().toISOString(),
  files: {},
};

function verified(data, expected) {
  return (
    data.length === expected.bytes &&
    createHash("sha256").update(data).digest("hex") === expected.sha256
  );
}

for (const [file, expected] of Object.entries(expectedFiles)) {
  const target = path.join(destination, file);
  await mkdir(path.dirname(target), { recursive: true });
  let data;
  try {
    const existing = await readFile(target);
    if (verified(existing, expected)) data = existing;
    else console.log(`${file}: checksum mismatch, downloading again...`);
  } catch {
    // Missing artifacts are downloaded below.
  }

  if (!data) {
    const url = `${endpoint}/${model}/resolve/${revision}/${file}`;
    console.log(`Downloading ${file}...`);
    const response = await fetch(url, { signal: AbortSignal.timeout(120000) });
    if (!response.ok) throw new Error(`${file}: HTTP ${response.status}`);
    data = Buffer.from(await response.arrayBuffer());
    if (!verified(data, expected)) throw new Error(`${file}: SHA-256 or size mismatch`);
    const temporary = `${target}.download`;
    await writeFile(temporary, data);
    await rename(temporary, target);
  }

  manifest.files[file] = { bytes: data.length, sha256: expected.sha256 };
  console.log(`${file}: ${(data.length / 1024 / 1024).toFixed(2)} MiB`);
}

const fp32Bytes = manifest.files["onnx/model.onnx"].bytes;
const fp16Bytes = manifest.files["onnx/model_fp16.onnx"].bytes;
const int8Bytes = manifest.files["onnx/model_quantized.onnx"].bytes;
manifest.modelSizes = {
  fp32Bytes,
  fp16Bytes,
  int8Bytes,
  fp16CompressionRatio: fp32Bytes / fp16Bytes,
  compressionRatio: fp32Bytes / int8Bytes,
};
await writeFile(path.resolve("public/models/manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Revision: ${revision}`);
console.log(`FP32 / FP16 compression ratio: ${manifest.modelSizes.fp16CompressionRatio.toFixed(3)}x`);
console.log(`FP32 / INT8 compression ratio: ${manifest.modelSizes.compressionRatio.toFixed(3)}x`);
