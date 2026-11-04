import { readdir, readFile, writeFile } from "node:fs/promises";
import { basename, extname, join } from "node:path";
import { tokens } from "../workers/domain/tokens";

type Chunk = [{ title: string; excerpt: string }, Record<string, number>];
export async function buildKnowledge(directory: string) {
  const chunks: Chunk[] = [];
  async function visit(folder: string) {
    const entries = await readdir(folder, { withFileTypes: true });
    entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    for (const entry of entries) {
      const path = join(folder, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
        continue;
      }
      if (![".md", ".txt"].includes(extname(path).toLowerCase())) continue;
      const name = basename(path, extname(path));
      let title = name;
      const content = (await readFile(path, "utf8")).trim();
      for (let part of content.split(/\n\s*\n|(?=^#{1,6} )/m)) {
        if (part.startsWith("#")) {
          const end = part.indexOf("\n");
          title = (end < 0 ? part : part.slice(0, end))
            .replace(/^#+\s*|\s*#+$/g, "")
            .trim();
          part = end < 0 ? "" : part.slice(end + 1);
        }
        if (!part.trim()) continue;
        const counts: Record<string, number> = Object.create(null);
        for (const term of tokens(title + " " + part))
          counts[term] = (counts[term] || 0) + 1;
        chunks.push([
          { title: name + " · " + title, excerpt: part.trim() },
          counts,
        ]);
      }
    }
  }
  await visit(directory);
  const df: Record<string, number> = Object.create(null);
  let length = 0;
  for (const [, counts] of chunks) {
    for (const term of Object.keys(counts)) df[term] = (df[term] || 0) + 1;
    length += Object.values(counts).reduce((a, b) => a + b, 0);
  }
  return { chunks, df, avg: length / Math.max(chunks.length, 1) };
}
if (process.argv[1]?.endsWith("worker-knowledge.ts")) {
  const index = await buildKnowledge("knowledge");
  await writeFile(
    "workers/domain/index.generated.json",
    JSON.stringify(index, null, 2) + "\n",
  );
  console.log("知识库已构建，共 " + index.chunks.length + " 个片段。");
}
