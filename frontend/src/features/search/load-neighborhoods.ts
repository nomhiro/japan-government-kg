import { neighborhood, type NeighborhoodResponse, type SearchHit } from "../../api/client";

/** 100結果でもAPIを同時に100回呼ばない。一部失敗は結果ごとに保持する。 */
export async function loadNeighborhoods(hits: readonly SearchHit[]) {
  const neighborhoods: (NeighborhoodResponse | null)[] = Array(hits.length).fill(null);
  let next = 0;
  let failedCount = 0;
  await Promise.all(Array.from({ length: Math.min(4, hits.length) }, async () => {
    while (next < hits.length) {
      const i = next++;
      try { neighborhoods[i] = await neighborhood(hits[i]!.id_path, { depth: 1 }); }
      catch { failedCount++; }
    }
  }));
  return { neighborhoods, failedCount };
}
