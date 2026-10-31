'use strict';

const path = require('path');
const express = require('express');
const session = require('express-session');

const config = require('./config');
const db = require('./db');
const { requireAuth, checkPassword } = require('./auth');
const scheduler = require('./scheduler/scheduler');
const wa = require('./whatsapp/manager');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(session({
  secret: config.sessionSecret,
  resave: false,
  saveUninitialized: false,
  cookie: { httpOnly: true, sameSite: 'lax', maxAge: 1000 * 60 * 60 * 24 * 7 },
}));

const PUBLIC = path.join(__dirname, '..', 'public');

// --- Auth endpoints ---
app.post('/api/login', (req, res) => {
  if (checkPassword(req.body.password)) {
    req.session.authed = true;
    return res.json({ ok: true });
  }
  res.status(401).json({ error: 'wrong password' });
});
app.post('/api/logout', (req, res) => {
  req.session.destroy(() => res.json({ ok: true }));
});
app.get('/login', (req, res) => res.sendFile(path.join(PUBLIC, 'login.html')));

// --- Protected API ---
app.use('/api/accounts', requireAuth, require('./routes/accounts.routes'));
app.use('/api/posts', requireAuth, require('./routes/posts.routes'));
app.get('/api/me', requireAuth, (req, res) => res.json({ ok: true }));

// --- Static assets (css/js) are public; the dashboard HTML + API stay gated ---
app.use('/assets', express.static(PUBLIC));

// --- Protected dashboard ---
app.get('/', requireAuth, (req, res) => res.sendFile(path.join(PUBLIC, 'index.html')));

app.listen(config.port, () => {
  console.log(`\nWA Scheduler running:  http://localhost:${config.port}`);
  if (config.dashboardPassword === 'change-me') {
    console.log('WARNING: DASHBOARD_PASSWORD is the default. Set it in .env.');
  }
  scheduler.start();

  // Re-open any sessions that were connected before a restart.
  const linked = db.prepare(`SELECT id FROM accounts WHERE wa_jid IS NOT NULL`).all();
  for (const a of linked) wa.startConnection(a.id).catch(() => {});
});
