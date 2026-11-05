export function average(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

export function median(values) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function evaluateRanking(sources, relevantSources, k = 5) {
  const relevant = new Set(relevantSources);
  const seen = new Set();
  let hits = 0;
  let dcg = 0;
  sources.slice(0, k).forEach((source, index) => {
    if (seen.has(source)) return;
    seen.add(source);
    if (relevant.has(source)) {
      hits += 1;
      dcg += 1 / Math.log2(index + 2);
    }
  });
  const idealCount = Math.min(relevant.size, k);
  const idealDcg = Array.from({ length: idealCount }, (_, index) => 1 / Math.log2(index + 2)).reduce(
    (sum, value) => sum + value,
    0,
  );
  return {
    recall: relevant.size ? hits / relevant.size : 0,
    ndcg: idealDcg ? dcg / idealDcg : 0,
  };
}
