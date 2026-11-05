import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import { requestGuard } from "./security.js";
import { KnowledgeBaseStore } from "./store.js";
import {
  HttpError,
  validateCollectionName,
  validateDocuments,
  validateSearch,
} from "./validation.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.PORT || 3000);
const databasePath = process.env.SEEKDB_PATH || path.join(root, "data", "seekdb");
const store = new KnowledgeBaseStore(databasePath);
const app = express();

app.disable("x-powered-by");
app.use(requestGuard(port));
app.use(express.json({ limit: "12mb" }));

app.get("/api/health", async (_request, response) => {
  await store.getClient();
  response.json({ ok: true, database: "seekdb", mode: "embedded", embeddingLocation: "browser" });
});

app.get("/api/collections", async (_request, response) => {
  response.json({ collections: await store.listCollections() });
});

app.post("/api/collections", async (request, response) => {
  const name = validateCollectionName(request.body.name);
  response.status(201).json(await store.createCollection(name));
});

app.delete("/api/collections/:name", async (request, response) => {
  const name = validateCollectionName(request.params.name);
  await store.deleteCollection(name);
  response.status(204).end();
});

app.get("/api/collections/:name/documents", async (request, response) => {
  const name = validateCollectionName(request.params.name);
  response.json({ documents: await store.listDocuments(name) });
});

app.post("/api/collections/:name/existing-ids", async (request, response) => {
  const name = validateCollectionName(request.params.name);
  const ids = request.body.ids;
  if (!Array.isArray(ids) || ids.length > 5000 || ids.some((id) => typeof id !== "string")) {
    throw new HttpError(400, "文档 ID 列表无效");
  }
  response.json({ ids: await store.existingIds(name, ids) });
});

app.post("/api/collections/:name/documents", async (request, response) => {
  const name = validateCollectionName(request.params.name);
  const documents = validateDocuments(request.body.documents);
  response.json(await store.addDocuments(name, documents));
});

app.post("/api/collections/:name/refresh", async (request, response) => {
  const name = validateCollectionName(request.params.name);
  response.json(await store.refresh(name));
});

app.post("/api/collections/:name/search", async (request, response) => {
  const name = validateCollectionName(request.params.name);
  response.json(await store.search(name, validateSearch(request.body)));
});

if (process.env.NODE_ENV === "production") {
  app.use(express.static(path.join(root, "dist")));
  app.get("/{*path}", (_request, response) => response.sendFile(path.join(root, "dist", "index.html")));
}

app.use((error, _request, response, _next) => {
  const status = error instanceof HttpError ? error.status : error.type === "entity.too.large" ? 413 : 500;
  if (status === 500) console.error(error);
  response.status(status).json({ error: status === 500 ? "操作失败，请检查服务日志" : error.message });
});

await store.createCollection("personal_kb");
const server = app.listen(port, "127.0.0.1", () => {
  console.log(`StepFun API listening on http://127.0.0.1:${port}`);
  console.log(`seekdb embedded data: ${databasePath}`);
});

async function shutdown() {
  server.close(async () => {
    await store.close();
    process.exit(0);
  });
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
