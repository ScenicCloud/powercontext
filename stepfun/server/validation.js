export const EMBEDDING_DIMENSION = 384;
export const MAX_BATCH_SIZE = 32;

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function validateCollectionName(value) {
  if (typeof value !== "string" || !/^[a-zA-Z][a-zA-Z0-9_]{2,39}$/.test(value)) {
    throw new HttpError(400, "知识库名称需为 3–40 位字母、数字或下划线，并以字母开头");
  }
  return value;
}

export function validateEmbedding(value) {
  if (!Array.isArray(value) || value.length !== EMBEDDING_DIMENSION || !value.every(Number.isFinite)) {
    throw new HttpError(400, `向量必须是 ${EMBEDDING_DIMENSION} 维有限数值数组`);
  }
  return value;
}

export function validateDocuments(value) {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_BATCH_SIZE) {
    throw new HttpError(400, `每批文档数量必须为 1–${MAX_BATCH_SIZE}`);
  }

  return value.map((document) => {
    if (!document || typeof document !== "object") {
      throw new HttpError(400, "文档格式无效");
    }
    if (typeof document.id !== "string" || !/^[a-zA-Z0-9_-]{3,128}$/.test(document.id)) {
      throw new HttpError(400, "文档 ID 格式无效");
    }
    if (typeof document.text !== "string" || !document.text.trim() || document.text.length > 10000) {
      throw new HttpError(400, "文档正文不能为空且不能超过 10000 字符");
    }
    const metadata = document.metadata;
    if (!metadata || typeof metadata !== "object") {
      throw new HttpError(400, "文档元数据缺失");
    }
    for (const field of ["source", "title", "contentHash", "model", "dtype"]) {
      if (typeof metadata[field] !== "string" || metadata[field].length > 512) {
        throw new HttpError(400, `元数据 ${field} 无效`);
      }
    }
    if (!Number.isInteger(metadata.chunkIndex) || !Number.isInteger(metadata.chunkCount)) {
      throw new HttpError(400, "文档分块序号无效");
    }

    return {
      id: document.id,
      text: document.text,
      embedding: validateEmbedding(document.embedding),
      metadata: {
        source: metadata.source,
        title: metadata.title,
        contentHash: metadata.contentHash,
        model: metadata.model,
        dtype: metadata.dtype,
        chunkIndex: metadata.chunkIndex,
        chunkCount: metadata.chunkCount,
        importedAt: new Date().toISOString(),
      },
    };
  });
}

export function validateSearch(body) {
  if (!body || typeof body.query !== "string" || !body.query.trim() || body.query.length > 500) {
    throw new HttpError(400, "查询不能为空且不能超过 500 字符");
  }
  const topK = body.topK ?? 6;
  if (!Number.isInteger(topK) || topK < 1 || topK > 20) {
    throw new HttpError(400, "返回数量必须为 1–20 的整数");
  }
  return {
    query: body.query.trim(),
    embedding: validateEmbedding(body.embedding),
    topK,
  };
}
