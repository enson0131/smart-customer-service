import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";

/** Node.js 本地入口使用 SQLite 适配本项目调用的 D1 接口。 */
export function openSQLite(path = ":memory:") {
  const sqlite = new DatabaseSync(path);
  sqlite.exec(readFileSync("workers/storage/schema.sql", "utf8"));
  function prepare(sql: string) {
    let values: (string | number | null)[] = [];
    return {
      bind(...args: typeof values) {
        values = args;
        return this;
      },
      async first(column?: string) {
        const row = sqlite.prepare(sql).get(...values);
        return column ? (row?.[column] ?? null) : row ? { ...row } : null;
      },
      async all() {
        return {
          results: sqlite
            .prepare(sql)
            .all(...values)
            .map((row) => ({ ...row })),
        };
      },
      run() {
        return sqlite.prepare(sql).run(...values);
      },
    };
  }
  const db = {
    prepare,
    async batch(statements: ReturnType<typeof prepare>[]) {
      sqlite.exec("BEGIN");
      try {
        const rows = [];
        // 同一事务内不让出事件循环，避免并发请求在连接上嵌套 BEGIN。
        for (const statement of statements) rows.push(statement.run());
        sqlite.exec("COMMIT");
        return rows;
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
    },
  } as unknown as D1Database;
  return { db, close: () => sqlite.close() };
}
