import { Buffer } from "node:buffer";
import {
  BaseCheckpointSaver,
  WRITES_IDX_MAP,
} from "@langchain/langgraph-checkpoint";
import type {
  Checkpoint,
  CheckpointMetadata,
  CheckpointTuple,
  PendingWrite,
} from "@langchain/langgraph-checkpoint";
import type { RunnableConfig } from "@langchain/core/runnables";

// Native LangGraph checkpoint contract, persisted via the Worker D1 binding.
export class D1Saver extends BaseCheckpointSaver {
  constructor(private db: D1Database) {
    super();
  }

  private async encode(value: unknown) {
    const [type, bytes] = await this.serde.dumpsTyped(value);
    return JSON.stringify([type, Buffer.from(bytes).toString("base64")]);
  }
  private async decode(payload: string) {
    const [type, bytes] = JSON.parse(payload);
    return this.serde.loadsTyped(type, Buffer.from(bytes, "base64"));
  }
  async put(
    config: RunnableConfig,
    checkpoint: Checkpoint,
    metadata: CheckpointMetadata,
  ) {
    const {
      thread_id,
      checkpoint_ns = "",
      checkpoint_id = null,
    } = config.configurable!;
    await this.db
      .prepare("INSERT OR REPLACE INTO graph_checkpoints VALUES (?,?,?,?,?,?)")
      .bind(
        thread_id,
        checkpoint_ns,
        checkpoint.id,
        checkpoint_id,
        await this.encode(checkpoint),
        JSON.stringify(metadata),
      )
      .run();
    return {
      configurable: { thread_id, checkpoint_ns, checkpoint_id: checkpoint.id },
    };
  }
  async putWrites(
    config: RunnableConfig,
    writes: PendingWrite[],
    task: string,
  ) {
    const {
      thread_id,
      checkpoint_ns = "",
      checkpoint_id,
    } = config.configurable!;
    const statements = await Promise.all(
      writes.map(async ([channel, value], i) =>
        this.db
          .prepare(
            `INSERT INTO graph_writes VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(thread,ns,id,task,idx) DO UPDATE SET payload=excluded.payload WHERE excluded.idx<0`,
          )
          .bind(
            thread_id,
            checkpoint_ns,
            checkpoint_id,
            task,
            WRITES_IDX_MAP[channel] ?? i,
            channel,
            await this.encode(value),
          ),
      ),
    );
    if (statements.length) await this.db.batch(statements);
  }
  async getTuple(config: RunnableConfig): Promise<CheckpointTuple | undefined> {
    const {
      thread_id,
      checkpoint_ns = "",
      checkpoint_id = null,
    } = config.configurable!;
    const row = await this.db
      .prepare(
        `SELECT * FROM graph_checkpoints WHERE thread=? AND ns=?
      AND (? IS NULL OR id=?) ORDER BY id DESC LIMIT 1`,
      )
      .bind(thread_id, checkpoint_ns, checkpoint_id, checkpoint_id)
      .first<{
        id: string;
        parent: string | null;
        payload: string;
        metadata: string;
      }>();
    if (!row) return;
    const { results } = await this.db
      .prepare(
        "SELECT task,channel,payload FROM graph_writes WHERE thread=? AND ns=? AND id=? ORDER BY task,idx",
      )
      .bind(thread_id, checkpoint_ns, row.id)
      .all<{ task: string; channel: string; payload: string }>();
    const at = (id: string) => ({
      configurable: { thread_id, checkpoint_ns, checkpoint_id: id },
    });
    return {
      config: at(row.id),
      checkpoint: await this.decode(row.payload),
      metadata: JSON.parse(row.metadata),
      parentConfig: row.parent ? at(row.parent) : undefined,
      pendingWrites: await Promise.all(
        results.map(
          async (w) =>
            [w.task, w.channel, await this.decode(w.payload)] as [
              string,
              string,
              unknown,
            ],
        ),
      ),
    };
  }
  async *list(config: RunnableConfig) {
    const tuple = await this.getTuple(config);
    if (tuple) yield tuple;
  }
  async deleteThread(thread: string) {
    await this.db.batch(
      ["graph_writes", "graph_checkpoints"].map((table) =>
        this.db.prepare(`DELETE FROM ${table} WHERE thread=?`).bind(thread),
      ),
    );
  }
}
