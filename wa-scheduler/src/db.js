'use strict';

const fs = require('fs');
const { DatabaseSync } = require('node:sqlite');
const config = require('./config');

fs.mkdirSync(config.dataDir, { recursive: true });

const db = new DatabaseSync(config.dbPath);
db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

// better-sqlite3-style transaction helper (node:sqlite has no built-in one).
db.transaction = (fn) => (...args) => {
  db.exec('BEGIN');
  try {
    const result = fn(...args);
    db.exec('COMMIT');
    return result;
  } catch (err) {
    db.exec('ROLLBACK');
    throw err;
  }
};

db.exec(`
  CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,
    wa_jid      TEXT,                 -- WhatsApp id once linked
    wa_name     TEXT,                 -- push name once linked
    status      TEXT NOT NULL DEFAULT 'disconnected', -- disconnected|qr|connecting|connected
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    body          TEXT NOT NULL DEFAULT '',
    media_path    TEXT,               -- optional attachment on disk
    media_type    TEXT,               -- image|video|document
    -- scheduling
    run_at        TEXT NOT NULL,      -- ISO timestamp (UTC) of next/only run
    repeat        TEXT NOT NULL DEFAULT 'none', -- none|daily|weekly
    -- lifecycle
    status        TEXT NOT NULL DEFAULT 'scheduled', -- scheduled|sending|sent|failed|cancelled
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS post_targets (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id   INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    group_jid TEXT NOT NULL,
    group_name TEXT
  );

  -- One delivery row per (post, group) so the history shows per-group outcome
  CREATE TABLE IF NOT EXISTS deliveries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    group_jid  TEXT NOT NULL,
    group_name TEXT,
    status     TEXT NOT NULL,        -- sent|failed
    error      TEXT,
    sent_at    TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS idx_posts_due ON posts(status, run_at);
  CREATE INDEX IF NOT EXISTS idx_targets_post ON post_targets(post_id);
  CREATE INDEX IF NOT EXISTS idx_deliveries_post ON deliveries(post_id);
`);

module.exports = db;
