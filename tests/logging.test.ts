import assert from "node:assert/strict";
import { test } from "node:test";
import { log, setLogSink, withTask } from "../workers/logging";

test("日志串联选单前后任务，隐藏访客标识、密钥和票据", async () => {
  const lines: string[] = [];
  setLogSink((line) => lines.push(line));
  await withTask("private-visitor", async () =>
    log("task.wait", { ticket: "P-0123456789", api_key: "secret" }),
  );
  await withTask("private-visitor", async () =>
    log("task.resume", { text: "ticket=P-0123456789" }),
  );
  assert.equal(JSON.parse(lines[0]).task_id, JSON.parse(lines[1]).task_id);
  assert.doesNotMatch(lines.join("\n"), /private-visitor|P-0123456789|secret/);
});
