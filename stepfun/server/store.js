import { mkdir } from "node:fs/promises";
import { performance } from "node:perf_hooks";
import { SeekdbClient } from "seekdb";
import { EMBEDDING_DIMENSION } from "./validation.js";

export class KnowledgeBaseStore {
  constructor(databasePath) {
    this.databasePath = databasePath;
    this.client = null;
    this.pending = Promise.resolve();
  }

  // Embedded native bindings allow only one active operation per client.
  serialize(operation) {
    const result = this.pending.then(operation, operation);
    this.pending = result.catch(() => {});
    return result;
  }

  async getClient() {
    if (!this.client) {
      await mkdir(this.databasePath, { recursive: true });
      this.client = new SeekdbClient({ path: this.databasePath, database: "test" });
    }
    return this.client;
  }

  async getCollection(name) {
    const client = await this.getClient();
    return client.getCollection({ name, embeddingFunction: null });
  }

  async createCollection(name) {
    return this.serialize(async () => {
      const client = await this.getClient();
      const collection = await client.getOrCreateCollection({
        name,
        configuration: { dimension: EMBEDDING_DIMENSION, distance: "cosine" },
        embeddingFunction: null,
      });
      return { name: collection.name, count: await collection.count() };
    });
  }

  async listCollections() {
    return this.serialize(async () => {
      const client = await this.getClient();
      const collections = await client.listCollections({ withEmbeddingFunction: false });
      const result = [];
      for (const collection of collections) {
        result.push({ name: collection.name, count: await collection.count() });
      }
      return result;
    });
  }

  async deleteCollection(name) {
    return this.serialize(async () => {
      const client = await this.getClient();
      await client.deleteCollection(name);
    });
  }

  async existingIds(name, ids) {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const existing = await collection.get({ ids, include: ["metadatas"] });
      return existing.ids;
    });
  }

  async addDocuments(name, documents) {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const unique = Array.from(new Map(documents.map((document) => [document.id, document])).values());
      const existing = await collection.get({ ids: unique.map((document) => document.id), include: ["metadatas"] });
      const existingIds = new Set(existing.ids);
      const fresh = unique.filter((document) => !existingIds.has(document.id));

      const startedAt = performance.now();
      if (fresh.length > 0) {
        await collection.add({
          ids: fresh.map((document) => document.id),
          documents: fresh.map((document) => document.text),
          embeddings: fresh.map((document) => document.embedding),
          metadatas: fresh.map((document) => document.metadata),
        });
      }
      return {
        inserted: fresh.length,
        skipped: documents.length - fresh.length,
        writeMs: performance.now() - startedAt,
        count: await collection.count(),
      };
    });
  }

  async refresh(name) {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const startedAt = performance.now();
      await collection.refresh_index();
      return { refreshMs: performance.now() - startedAt, count: await collection.count() };
    });
  }

  async listDocuments(name, limit = 60) {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const result = await collection.get({ limit, include: ["documents", "metadatas"] });
      return result.ids.map((id, index) => ({
        id,
        text: result.documents[index],
        metadata: result.metadatas[index],
      }));
    });
  }

  async search(name, { query, embedding, topK }) {
    return this.serialize(async () => {
      const collection = await this.getCollection(name);
      const candidateCount = Math.max(20, topK * 4);
      const startedAt = performance.now();
      const result = await collection.hybridSearch({
        query: {
          whereDocument: { $contains: query },
          nResults: candidateCount,
        },
        knn: {
          queryEmbeddings: [embedding],
          nResults: candidateCount,
        },
        rank: {
          rrf: { rankWindowSize: 50, rankConstant: 60 },
        },
        nResults: topK,
        include: ["documents", "metadatas", "distances"],
      });

      const ids = result.ids[0] ?? [];
      const documents = result.documents?.[0] ?? [];
      const metadatas = result.metadatas?.[0] ?? [];
      const distances = result.distances?.[0] ?? [];
      return {
        searchMs: performance.now() - startedAt,
        fusion: "seekdb DBMS_HYBRID_SEARCH / RRF",
        results: ids.map((id, index) => ({
          id,
          text: documents[index],
          metadata: metadatas[index],
          score: distances[index] ?? null,
        })),
      };
    });
  }

  async close() {
    return this.serialize(async () => {
      if (this.client) {
        await this.client.close();
        this.client = null;
      }
    });
  }
}
