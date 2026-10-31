'use strict';

const config = require('./config');

// Dashboard auth is a single shared password (self-hosted, single operator).
// The password itself is never stored; we just compare against the env value.
function requireAuth(req, res, next) {
  if (req.session && req.session.authed) return next();
  // Use originalUrl: inside a mounted router req.path is stripped of the prefix.
  if (req.originalUrl.startsWith('/api/')) {
    return res.status(401).json({ error: 'not authenticated' });
  }
  return res.redirect('/login');
}

function checkPassword(pw) {
  return typeof pw === 'string' && pw.length > 0 && pw === config.dashboardPassword;
}

module.exports = { requireAuth, checkPassword };
