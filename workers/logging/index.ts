import { AsyncLocalStorage } from "node:async_hooks";
const context = new AsyncLocalStorage<string>();
let sink: ((line: string) => void) | undefined;
export function setLogSink(write: (line: string) => void) {
  sink = write;
}
export function log(event: string, data: unknown = {}) {
  const line = JSON.stringify(
    {
      time: new Date().toISOString(),
      task_id: context.getStore(),
      event,
      data,
    },
    (key, value) => {
      if (/^(ticket|api_?key|authorization|cookie)$/i.test(key))
        return "[redacted]";
      return typeof value === "string"
        ? value.replace(/\b(?:P-[a-f0-9-]+|sk-[\w-]+)/gi, "[redacted]")
        : value;
    },
  );
  if (sink) sink(line);
  else console.log(line);
}
export async function withTask<T>(visitor: string, run: () => Promise<T>) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(visitor),
  );
  const task = Array.from(new Uint8Array(digest).slice(0, 8), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");
  return context.run(task, run);
}
