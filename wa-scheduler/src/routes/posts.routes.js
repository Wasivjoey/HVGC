'use strict';

const fs = require('fs');
const path = require('path');
const express = require('express');
const multer = require('multer');
const db = require('../db');
const config = require('../config');

const router = express.Router();

fs.mkdirSync(config.uploadsDir, { recursive: true });
const upload = multer({
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, config.uploadsDir),
    filename: (req, file, cb) =>
      cb(null, `${Date.now()}-${Math.random().toString(36).slice(2)}${path.extname(file.originalname)}`),
  }),
  limits: { fileSize: 64 * 1024 * 1024 }, // 64 MB
});

function mediaTypeFor(mimetype) {
  if (!mimetype) return null;
  if (mimetype.startsWith('image/')) return 'image';
  if (mimetype.startsWith('video/')) return 'video';
  return 'document';
}

function hydrate(post) {
  const targets = db.prepare('SELECT group_jid, group_name FROM post_targets WHERE post_id = ?').all(post.id);
  const deliveries = db.prepare('SELECT * FROM deliveries WHERE post_id = ? ORDER BY sent_at DESC').all(post.id);
  return { ...post, targets, deliveries };
}

// List posts (optionally by account), newest schedule first.
router.get('/', (req, res) => {
  const accountId = req.query.account_id ? Number(req.query.account_id) : null;
  const rows = accountId
    ? db.prepare('SELECT * FROM posts WHERE account_id = ? ORDER BY run_at DESC').all(accountId)
    : db.prepare('SELECT * FROM posts ORDER BY run_at DESC').all();
  res.json(rows.map(hydrate));
});

router.get('/:id', (req, res) => {
  const post = db.prepare('SELECT * FROM posts WHERE id = ?').get(Number(req.params.id));
  if (!post) return res.status(404).json({ error: 'not found' });
  res.json(hydrate(post));
});

// Create a scheduled post. Accepts multipart (with optional media file) or JSON.
// Body fields: account_id, body, run_at (ISO), repeat, targets (JSON array of {jid,name})
router.post('/', upload.single('media'), (req, res) => {
  const accountId = Number(req.body.account_id);
  const acc = db.prepare('SELECT * FROM accounts WHERE id = ?').get(accountId);
  if (!acc) return res.status(400).json({ error: 'unknown account_id' });

  const body = (req.body.body || '').toString();
  const runAtRaw = req.body.run_at;
  const runAt = runAtRaw ? new Date(runAtRaw) : null;
  if (!runAt || Number.isNaN(runAt.getTime())) {
    return res.status(400).json({ error: 'run_at must be a valid date/time' });
  }
  const repeat = ['none', 'daily', 'weekly'].includes(req.body.repeat) ? req.body.repeat : 'none';

  let targets = [];
  try {
    targets = JSON.parse(req.body.targets || '[]');
  } catch (_) {
    return res.status(400).json({ error: 'targets must be a JSON array' });
  }
  if (!Array.isArray(targets) || targets.length === 0) {
    return res.status(400).json({ error: 'pick at least one group' });
  }
  if (!body.trim() && !req.file) {
    return res.status(400).json({ error: 'post needs text or a media attachment' });
  }

  const mediaPath = req.file ? req.file.path : null;
  const mediaType = req.file ? mediaTypeFor(req.file.mimetype) : null;

  const tx = db.transaction(() => {
    const info = db.prepare(`
      INSERT INTO posts (account_id, body, media_path, media_type, run_at, repeat)
      VALUES (@account_id, @body, @media_path, @media_type, @run_at, @repeat)
    `).run({
      account_id: accountId,
      body,
      media_path: mediaPath,
      media_type: mediaType,
      run_at: runAt.toISOString(),
      repeat,
    });
    const postId = Number(info.lastInsertRowid);
    const insT = db.prepare('INSERT INTO post_targets (post_id, group_jid, group_name) VALUES (?, ?, ?)');
    for (const t of targets) insT.run(postId, t.jid, t.name || null);
    return postId;
  });

  const postId = tx();
  res.json(hydrate(db.prepare('SELECT * FROM posts WHERE id = ?').get(postId)));
});

// Cancel a scheduled (not yet sent) post.
router.post('/:id/cancel', (req, res) => {
  const id = Number(req.params.id);
  const post = db.prepare('SELECT * FROM posts WHERE id = ?').get(id);
  if (!post) return res.status(404).json({ error: 'not found' });
  if (post.status === 'sent') return res.status(400).json({ error: 'already sent' });
  db.prepare(`UPDATE posts SET status='cancelled', updated_at=datetime('now') WHERE id=?`).run(id);
  res.json({ ok: true });
});

// Delete a post (and its media file).
router.delete('/:id', (req, res) => {
  const id = Number(req.params.id);
  const post = db.prepare('SELECT * FROM posts WHERE id = ?').get(id);
  if (post && post.media_path) { try { fs.rmSync(post.media_path, { force: true }); } catch (_) {} }
  db.prepare('DELETE FROM posts WHERE id = ?').run(id);
  res.json({ ok: true });
});

module.exports = router;
