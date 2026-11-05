export function chunkText(input, maxChars = 700, overlap = 90) {
  const text = input.replace(/\r\n?/g, "\n").trim();
  if (!text) return [];

  const chunks = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + maxChars, text.length);
    if (end < text.length) {
      const window = text.slice(start, end);
      const minimum = Math.floor(maxChars * 0.55);
      const boundary = Math.max(
        window.lastIndexOf("\n\n"),
        window.lastIndexOf("。"),
        window.lastIndexOf("！"),
        window.lastIndexOf("？"),
        window.lastIndexOf(". "),
        window.lastIndexOf(" "),
      );
      if (boundary >= minimum) end = start + boundary + 1;
    }
    const chunk = text.slice(start, end).trim();
    if (chunk) chunks.push(chunk);
    if (end >= text.length) break;
    start = Math.max(end - overlap, start + 1);
  }
  return chunks;
}

async function sha256(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function textToDocuments(source, input, config) {
  const contentHash = await sha256(input);
  const chunks = chunkText(input);
  return chunks.map((chunk, index) => {
    const title = source.replace(/\.[^.]+$/, "");
    return {
      id: `doc_${contentHash.slice(0, 24)}_${index}`,
      text: `${title}\n${chunk}`,
      metadata: {
        source,
        title,
        contentHash,
        chunkIndex: index,
        chunkCount: chunks.length,
        model: config.model,
        dtype: config.dtype,
      },
    };
  });
}
