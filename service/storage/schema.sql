CREATE TABLE IF NOT EXISTS visitors (
    id TEXT PRIMARY KEY, topic TEXT NOT NULL DEFAULT '', selected TEXT, ticket TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, visitor TEXT NOT NULL REFERENCES visitors(id),
    product TEXT NOT NULL, cents INTEGER NOT NULL, delivered TEXT
);
CREATE INDEX IF NOT EXISTS orders_visitor ON orders(visitor);
CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY, visitor TEXT NOT NULL REFERENCES visitors(id),
    order_id TEXT UNIQUE NOT NULL REFERENCES orders(id), ticket TEXT UNIQUE NOT NULL,
    cents INTEGER NOT NULL, reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_turns (
    id INTEGER PRIMARY KEY, visitor TEXT NOT NULL REFERENCES visitors(id),
    message TEXT NOT NULL, answer TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_turns_visitor ON chat_turns(visitor,id);
CREATE TABLE IF NOT EXISTS pending_tasks (
    visitor TEXT PRIMARY KEY REFERENCES visitors(id), snapshot TEXT NOT NULL
);

-- LangGraph checkpointer: completed conversations remain in chat_turns.
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    thread TEXT NOT NULL, ns TEXT NOT NULL, id TEXT NOT NULL,
    parent TEXT, payload TEXT NOT NULL, metadata TEXT NOT NULL,
    PRIMARY KEY (thread, ns, id)
);
CREATE TABLE IF NOT EXISTS graph_writes (
    thread TEXT NOT NULL, ns TEXT NOT NULL, id TEXT NOT NULL,
    task TEXT NOT NULL, idx INTEGER NOT NULL, channel TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY (thread, ns, id, task, idx)
);
