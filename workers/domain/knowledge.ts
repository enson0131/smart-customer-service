import { tokens } from "./tokens";
import data from "./index.generated.json";
type Source = { title: string; excerpt: string };
const { chunks, df, avg } = data as unknown as {
  chunks: [Source, Record<string, number>][];
  df: Record<string, number>;
  avg: number;
};
export function search(query: string) {
  const terms = new Set(tokens(query));
  const ranked = chunks
    .map(([source, counts]) => {
      const matches = [...terms].filter((t) => Object.hasOwn(counts, t));
      const length = Object.values(counts).reduce((a, b) => a + b, 0);
      const score =
        matches.length < terms.size * 0.22
          ? 0
          : matches.reduce(
              (sum, t) =>
                sum +
                (Math.log1p((chunks.length - df[t] + 0.5) / (df[t] + 0.5)) *
                  counts[t] *
                  2.2) /
                  (counts[t] + 1.2 * (0.25 + (0.75 * length) / avg)),
              0,
            );
      return { source, score };
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score);
  return ranked
    .slice(0, 2)
    .filter((x) => x.score >= ranked[0].score * 0.65)
    .map((x) => x.source);
}
