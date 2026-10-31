'use strict';

/**
 * Manages one Baileys WhatsApp Web connection per account.
 *
 * Each account gets its own multi-file auth state under data/sessions/<id>,
 * so sessions survive restarts (no need to re-scan the QR every time).
 *
 * IMPORTANT: this drives WhatsApp Web via an unofficial protocol. It works for
 * posting to groups, but automated/bulk use is against WhatsApp's Terms of
 * Service and can get a number banned. Keep volume human-like.
 */

const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');

const config = require('../config');
const db = require('../db');

// Minimal no-op logger satisfying Baileys' logger interface (avoids a pino dep).
const noop = () => {};
const logger = {
  level: 'silent',
  trace: noop, debug: noop, info: noop, warn: noop, error: noop, fatal: noop,
  child() { return logger; },
};
const SESSIONS_DIR = path.join(config.dataDir, 'sessions');
fs.mkdirSync(SESSIONS_DIR, { recursive: true });

/** @type {Map<number, {sock: any, status: string, qrDataUrl: string|null, groups: Map<string,string>}>} */
const connections = new Map();

function setAccountStatus(accountId, status, extra = {}) {
  const fields = { status, ...extra };
  const sets = Object.keys(fields).map((k) => `${k} = @${k}`).join(', ');
  db.prepare(`UPDATE accounts SET ${sets} WHERE id = @id`).run({ id: accountId, ...fields });
}

function getState(accountId) {
  return connections.get(accountId) || null;
}

function isConnected(accountId) {
  const s = connections.get(accountId);
  return !!(s && s.status === 'connected' && s.sock);
}

/**
 * Start (or restart) a connection for an account. Resolves immediately; the
 * QR / connected state is tracked on the in-memory connection object and
 * mirrored into the accounts table.
 */
async function startConnection(accountId) {
  const existing = connections.get(accountId);
  if (existing && (existing.status === 'connecting' || existing.status === 'connected')) {
    return existing;
  }

  const authDir = path.join(SESSIONS_DIR, String(accountId));
  fs.mkdirSync(authDir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ['WA Scheduler', 'Chrome', '1.0.0'],
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });

  const conn = connections.get(accountId) || { groups: new Map() };
  conn.sock = sock;
  conn.status = 'connecting';
  conn.qrDataUrl = null;
  connections.set(accountId, conn);
  setAccountStatus(accountId, 'connecting');

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      conn.status = 'qr';
      conn.qrDataUrl = await QRCode.toDataURL(qr).catch(() => null);
      setAccountStatus(accountId, 'qr');
    }

    if (connection === 'open') {
      conn.status = 'connected';
      conn.qrDataUrl = null;
      const jid = sock.user?.id || null;
      const name = sock.user?.name || sock.user?.verifiedName || null;
      setAccountStatus(accountId, 'connected', { wa_jid: jid, wa_name: name });
      refreshGroups(accountId).catch(() => {});
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      conn.status = 'disconnected';
      const loggedOut = code === DisconnectReason.loggedOut;
      if (loggedOut) {
        // Credentials are dead; wipe them so the next start shows a fresh QR.
        setAccountStatus(accountId, 'disconnected', { wa_jid: null, wa_name: null });
        try { fs.rmSync(authDir, { recursive: true, force: true }); } catch (_) {}
        connections.delete(accountId);
      } else {
        setAccountStatus(accountId, 'disconnected');
        // Transient drop (network, restart required): reconnect shortly.
        setTimeout(() => startConnection(accountId).catch(() => {}), 3000);
      }
    }
  });

  // Keep the group cache warm as metadata arrives.
  sock.ev.on('groups.upsert', () => refreshGroups(accountId).catch(() => {}));
  sock.ev.on('groups.update', () => refreshGroups(accountId).catch(() => {}));

  return conn;
}

async function refreshGroups(accountId) {
  const conn = connections.get(accountId);
  if (!conn || !conn.sock || conn.status !== 'connected') return [];
  const map = await conn.sock.groupFetchAllParticipating();
  conn.groups = new Map();
  for (const g of Object.values(map)) {
    conn.groups.set(g.id, g.subject || g.id);
  }
  return listGroups(accountId);
}

function listGroups(accountId) {
  const conn = connections.get(accountId);
  if (!conn || !conn.groups) return [];
  return [...conn.groups.entries()]
    .map(([jid, name]) => ({ jid, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Send one message (text and/or media) to a single group jid.
 * Throws on failure so the caller can record the error + retry.
 */
async function sendToGroup(accountId, groupJid, { body, mediaPath, mediaType }) {
  const conn = connections.get(accountId);
  if (!conn || !conn.sock || conn.status !== 'connected') {
    throw new Error('WhatsApp account is not connected');
  }

  let content;
  if (mediaPath && fs.existsSync(mediaPath)) {
    const buffer = fs.readFileSync(mediaPath);
    if (mediaType === 'image') {
      content = { image: buffer, caption: body || undefined };
    } else if (mediaType === 'video') {
      content = { video: buffer, caption: body || undefined };
    } else {
      content = {
        document: buffer,
        fileName: path.basename(mediaPath),
        caption: body || undefined,
      };
    }
  } else {
    content = { text: body || '' };
  }

  await conn.sock.sendMessage(groupJid, content);
}

async function logout(accountId) {
  const conn = connections.get(accountId);
  if (conn && conn.sock) {
    try { await conn.sock.logout(); } catch (_) {}
  }
  const authDir = path.join(SESSIONS_DIR, String(accountId));
  try { fs.rmSync(authDir, { recursive: true, force: true }); } catch (_) {}
  connections.delete(accountId);
  setAccountStatus(accountId, 'disconnected', { wa_jid: null, wa_name: null });
}

function statusOf(accountId) {
  const conn = connections.get(accountId);
  return {
    status: conn?.status || 'disconnected',
    qr: conn?.qrDataUrl || null,
    groupCount: conn?.groups?.size || 0,
  };
}

module.exports = {
  startConnection,
  refreshGroups,
  listGroups,
  sendToGroup,
  logout,
  statusOf,
  isConnected,
  getState,
};
