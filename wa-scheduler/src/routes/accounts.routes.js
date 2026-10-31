'use strict';

const express = require('express');
const db = require('../db');
const wa = require('../whatsapp/manager');

const router = express.Router();

// List all accounts with live connection status.
router.get('/', (req, res) => {
  const rows = db.prepare('SELECT * FROM accounts ORDER BY id').all();
  const accounts = rows.map((a) => ({ ...a, live: wa.statusOf(a.id) }));
  res.json(accounts);
});

// Create an account record (not yet linked to WhatsApp).
router.post('/', (req, res) => {
  const label = (req.body.label || '').trim() || 'My WhatsApp';
  const info = db.prepare('INSERT INTO accounts (label) VALUES (?)').run(label);
  res.json(db.prepare('SELECT * FROM accounts WHERE id = ?').get(Number(info.lastInsertRowid)));
});

// Start linking: boots a Baileys connection; poll status to get the QR.
router.post('/:id/connect', async (req, res) => {
  const id = Number(req.params.id);
  const acc = db.prepare('SELECT * FROM accounts WHERE id = ?').get(id);
  if (!acc) return res.status(404).json({ error: 'account not found' });
  await wa.startConnection(id).catch((e) => { throw e; });
  res.json(wa.statusOf(id));
});

// Poll connection status + QR data URL.
router.get('/:id/status', (req, res) => {
  res.json(wa.statusOf(Number(req.params.id)));
});

// Live group list for the linked account.
router.get('/:id/groups', async (req, res) => {
  const id = Number(req.params.id);
  if (!wa.isConnected(id)) return res.json([]);
  await wa.refreshGroups(id).catch(() => {});
  res.json(wa.listGroups(id));
});

// Unlink / log out of WhatsApp (keeps the account record).
router.post('/:id/logout', async (req, res) => {
  await wa.logout(Number(req.params.id));
  res.json({ ok: true });
});

// Delete the account and everything under it.
router.delete('/:id', async (req, res) => {
  const id = Number(req.params.id);
  await wa.logout(id).catch(() => {});
  db.prepare('DELETE FROM accounts WHERE id = ?').run(id);
  res.json({ ok: true });
});

module.exports = router;
