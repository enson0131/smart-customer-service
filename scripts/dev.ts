import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import {
  existsSync,
  appendFileSync,
  writeFileSync,
  statSync,
  renameSync,
} from "node:fs";
import { resolve, sep, extname } from "node:path";
import worker from "../workers";
import { openSQLite } from "../workers/storage/sqlite";
import { setLogSink } from "../workers/logging";

if (existsSync(".env")) process.loadEnvFile(".env");
if (!process.env.DEEPSEEK_API_KEY?.trim())
  throw new Error("请在 .env 配置 DEEPSEEK_API_KEY");
await mkdir("data/logs", { recursive: true });
const database = openSQLite("data/support.sqlite");
const logPath = "data/logs/tasks.jsonl",
  prettyPath = "data/logs/tasks.pretty.json";
let events: unknown[] = existsSync(logPath)
  ? (await readFile(logPath, "utf8"))
      .split("\n")
      .filter(Boolean)
      .map((line) => JSON.parse(line))
  : [];
setLogSink((line) => {
  if (existsSync(logPath) && statSync(logPath).size >= 5 * 1024 * 1024) {
    for (let i = 2; i >= 0; i--) {
      const from = logPath + (i ? "." + i : "");
      if (existsSync(from)) renameSync(from, logPath + "." + (i + 1));
    }
    events = [];
  }
  appendFileSync(logPath, line + "\n");
  events.push(JSON.parse(line));
  writeFileSync(prettyPath, JSON.stringify(events, null, 2) + "\n");
  console.log(line);
});
const publicRoot = resolve("public");
const env = {
  DB: database.db,
  DEEPSEEK_API_KEY: process.env.DEEPSEEK_API_KEY,
  DEEPSEEK_BASE_URL: process.env.DEEPSEEK_BASE_URL,
  ASSETS: {
    async fetch(req: Request) {
      const url = new URL(req.url);
      const path = resolve(
        publicRoot,
        "." +
          decodeURIComponent(
            url.pathname === "/" ? "/index.html" : url.pathname,
          ),
      );
      if (!path.startsWith(publicRoot + sep))
        return new Response("Not found", { status: 404 });
      try {
        const content = await readFile(path);
        const type: Record<string, string> = {
          ".html": "text/html; charset=utf-8",
          ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8",
        };
        return new Response(content, {
          headers: {
            "content-type": type[extname(path)] || "application/octet-stream",
          },
        });
      } catch {
        return new Response("Not found", { status: 404 });
      }
    },
  } as Fetcher,
};
const port = Number(process.env.PORT || 8000);
const server = createServer(async (incoming, outgoing) => {
  try {
    const chunks: Buffer[] = [];
    for await (const chunk of incoming) chunks.push(Buffer.from(chunk));
    const headers = new Headers();
    for (const [key, value] of Object.entries(incoming.headers))
      if (value)
        headers.set(key, Array.isArray(value) ? value.join(",") : value);
    const request = new Request("http://127.0.0.1:" + port + incoming.url, {
      method: incoming.method,
      headers,
      body: chunks.length ? Buffer.concat(chunks) : undefined,
    });
    const response = await worker.fetch(request, env);
    outgoing.statusCode = response.status;
    response.headers.forEach((value, key) =>
      outgoing.setHeader(
        key,
        key === "set-cookie" ? value.replace("; Secure", "") : value,
      ),
    );
    outgoing.end(Buffer.from(await response.arrayBuffer()));
  } catch (error) {
    console.error(
      "local.request.error",
      error instanceof Error ? error.name : "Error",
    );
    outgoing.statusCode = 500;
    outgoing.end("Internal server error");
  }
});
server.listen(port, "127.0.0.1", () =>
  console.log("售后演示 http://127.0.0.1:" + port),
);
for (const signal of ["SIGINT", "SIGTERM"] as const)
  process.on(signal, () =>
    server.close(() => {
      database.close();
      process.exit(0);
    }),
  );
