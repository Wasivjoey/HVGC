'use strict';

const path = require('path');
require('dotenv').config();

const ROOT = path.resolve(__dirname, '..');

function num(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

// DATA_DIR / UPLOADS_DIR let a host point these at a persistent disk (e.g. a
// Render disk) so the SQLite DB, WhatsApp sessions, and uploaded media survive
// restarts and deploys. Default to folders inside the project for local dev.
const dataDir = process.env.DATA_DIR
  ? path.resolve(process.env.DATA_DIR)
  : path.join(ROOT, 'data');
const uploadsDir = process.env.UPLOADS_DIR
  ? path.resolve(process.env.UPLOADS_DIR)
  : path.join(ROOT, 'uploads');

const config = {
  root: ROOT,
  dataDir,
  uploadsDir,
  dbPath: path.join(dataDir, 'app.db'),

  port: num(process.env.PORT, 3000),
  dashboardPassword: process.env.DASHBOARD_PASSWORD || 'change-me',
  sessionSecret: process.env.SESSION_SECRET || 'insecure-dev-secret-change-me',

  schedulerTickMs: num(process.env.SCHEDULER_TICK_MS, 15000),
  sendJitterMinMs: num(process.env.SEND_JITTER_MIN_MS, 4000),
  sendJitterMaxMs: num(process.env.SEND_JITTER_MAX_MS, 18000),
  maxSendAttempts: num(process.env.MAX_SEND_ATTEMPTS, 3),
};

module.exports = config;
