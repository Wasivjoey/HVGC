'use strict';

/**
 * Polling scheduler. Every tick it picks up posts whose run_at is due and
 * status is 'scheduled', sends them to each target group (with a human-like
 * random delay between groups), records per-group deliveries, and either marks
 * the post sent/failed or — for recurring posts — rolls run_at forward.
 */

const config = require('../config');
const db = require('./.././db');
const wa = require('../whatsapp/manager');

let timer = null;
const inFlight = new Set();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const jitter = () => {
  const { sendJitterMinMs: lo, sendJitterMaxMs: hi } = config;
  return Math.floor(lo + Math.random() * Math.max(0, hi - lo));
};

function nextRunAt(fromIso, repeat) {
  const d = new Date(fromIso);
  if (repeat === 'daily') d.setUTCDate(d.getUTCDate() + 1);
  else if (repeat === 'weekly') d.setUTCDate(d.getUTCDate() + 7);
  else return null;
  // If we're catching up on a missed run, keep advancing until it's in the future.
  while (d.getTime() <= Date.now()) {
    if (repeat === 'daily') d.setUTCDate(d.getUTCDate() + 1);
    else d.setUTCDate(d.getUTCDate() + 7);
  }
  return d.toISOString();
}

const duePostsStmt = db.prepare(`
  SELECT * FROM posts
  WHERE status = 'scheduled' AND run_at <= @now
  ORDER BY run_at ASC
  LIMIT 25
`);
const targetsStmt = db.prepare(`SELECT group_jid, group_name FROM post_targets WHERE post_id = ?`);
const markSendingStmt = db.prepare(`UPDATE posts SET status='sending', updated_at=datetime('now') WHERE id=?`);
const recordDeliveryStmt = db.prepare(`
  INSERT INTO deliveries (post_id, group_jid, group_name, status, error)
  VALUES (@post_id, @group_jid, @group_name, @status, @error)
`);

async function processPost(post) {
  if (inFlight.has(post.id)) return;
  inFlight.add(post.id);
  try {
    if (!wa.isConnected(post.account_id)) {
      // Account not linked/connected right now — leave it scheduled and retry
      // next tick rather than burning an attempt.
      return;
    }

    markSendingStmt.run(post.id);
    const targets = targetsStmt.all(post.id);
    let anyFailure = false;
    let firstError = null;

    for (let i = 0; i < targets.length; i++) {
      const t = targets[i];
      try {
        await wa.sendToGroup(post.account_id, t.group_jid, {
          body: post.body,
          mediaPath: post.media_path,
          mediaType: post.media_type,
        });
        recordDeliveryStmt.run({
          post_id: post.id, group_jid: t.group_jid, group_name: t.group_name,
          status: 'sent', error: null,
        });
      } catch (err) {
        anyFailure = true;
        firstError = firstError || String(err.message || err);
        recordDeliveryStmt.run({
          post_id: post.id, group_jid: t.group_jid, group_name: t.group_name,
          status: 'failed', error: String(err.message || err),
        });
      }
      // Human-like pause before the next group (skip after the last one).
      if (i < targets.length - 1) await sleep(jitter());
    }

    const attempts = post.attempts + 1;
    const rollTo = nextRunAt(post.run_at, post.repeat);

    if (anyFailure && attempts < config.maxSendAttempts) {
      // Retry the whole post next tick.
      db.prepare(`UPDATE posts SET status='scheduled', attempts=@a, last_error=@e, updated_at=datetime('now') WHERE id=@id`)
        .run({ id: post.id, a: attempts, e: firstError });
      return;
    }

    if (rollTo) {
      // Recurring: schedule the next occurrence and reset the counter.
      db.prepare(`UPDATE posts SET status='scheduled', run_at=@run, attempts=0, last_error=@e, updated_at=datetime('now') WHERE id=@id`)
        .run({ id: post.id, run: rollTo, e: anyFailure ? firstError : null });
    } else {
      db.prepare(`UPDATE posts SET status=@s, attempts=@a, last_error=@e, updated_at=datetime('now') WHERE id=@id`)
        .run({ id: post.id, s: anyFailure ? 'failed' : 'sent', a: attempts, e: anyFailure ? firstError : null });
    }
  } finally {
    inFlight.delete(post.id);
  }
}

async function tick() {
  const now = new Date().toISOString();
  const due = duePostsStmt.all({ now });
  for (const post of due) {
    // Fire-and-forget per post; inFlight guards against overlap across ticks.
    processPost(post).catch(() => {});
  }
}

function start() {
  if (timer) return;
  timer = setInterval(() => tick().catch(() => {}), config.schedulerTickMs);
  tick().catch(() => {});
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
}

module.exports = { start, stop, tick, nextRunAt };
