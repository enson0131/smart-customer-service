CREATE TABLE IF NOT EXISTS visitors (
    id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, visitor TEXT NOT NULL REFERENCES visitors(id),
    product TEXT NOT NULL, cents INTEGER NOT NULL, delivered TEXT
);
CREATE INDEX IF NOT EXISTS orders_visitor ON orders(visitor);
CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY, visitor TEXT NOT NULL REFERENCES visitors(id),
    order_id TEXT UNIQUE NOT NULL REFERENCES orders(id), ticket TEXT UNIQUE NOT NULL,
    cents INTEGER NOT NULL, reason TEXT NOT NULL, chat_id TEXT NOT NULL REFERENCES chats(id)
);
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL REFERENCES visitors(id),
    topic TEXT NOT NULL DEFAULT '', selected TEXT, ticket TEXT, reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS chats_visitor ON chats(visitor_id);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id),
    message TEXT NOT NULL, answer TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_messages_chat ON chat_messages(chat_id,id);
