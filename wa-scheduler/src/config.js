'use strict';

const path = require('path');
require('dotenv').config();

const ROOT = path.resolve(__dirname, '..');

function num(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

const config = {
  root: ROOT,
  dataDir: path.join(ROOT, 'data'),
  uploadsDir: path.join(ROOT, 'uploads'),
  dbPath: path.join(ROOT, 'data', 'app.db'),

  port: num(process.env.PORT, 3000),
  dashboardPassword: process.env.DASHBOARD_PASSWORD || 'change-me',
  sessionSecret: process.env.SESSION_SECRET || 'insecure-dev-secret-change-me',

  schedulerTickMs: num(process.env.SCHEDULER_TICK_MS, 15000),
  sendJitterMinMs: num(process.env.SEND_JITTER_MIN_MS, 4000),
  sendJitterMaxMs: num(process.env.SEND_JITTER_MAX_MS, 18000),
  maxSendAttempts: num(process.env.MAX_SEND_ATTEMPTS, 3),
};

module.exports = config;
