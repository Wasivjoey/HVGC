'use strict';

const $ = (id) => document.getElementById(id);

// Small inline icon set (one stroke weight) so the UI never leans on emoji.
const svg = (paths) =>
  `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ` +
  `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
const ICON = {
  check: svg('<path d="M20 6 9 17l-5-5"/>'),
  clip: svg('<path d="m21.4 11.1-9.2 9.2a5 5 0 0 1-7-7l9.1-9.2a3.3 3.3 0 0 1 4.7 4.7l-9.1 9.1a1.7 1.7 0 0 1-2.4-2.4l8.5-8.4"/>'),
};
const api = async (url, opts = {}) => {
  const res = await fetch(url, opts);
  if (res.status === 401) { location.href = '/login'; throw new Error('unauth'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
};

let accounts = [];
let currentAccountId = null;
let statusTimer = null;

// ---------- Accounts ----------
async function loadAccounts() {
  accounts = await api('/api/accounts');
  const sel = $('accountSelect');
  sel.innerHTML = '';
  for (const a of accounts) {
    const opt = document.createElement('option');
    opt.value = a.id;
    opt.textContent = a.wa_name ? `${a.label} (${a.wa_name})` : a.label;
    sel.appendChild(opt);
  }
  if (accounts.length === 0) {
    await createAccount('My WhatsApp');
    return;
  }
  if (!currentAccountId || !accounts.find((a) => a.id === currentAccountId)) {
    currentAccountId = accounts[0].id;
  }
  sel.value = currentAccountId;
  await refreshAll();
}

async function createAccount(label) {
  const name = label || prompt('Name this account (e.g. "Marketing line")', 'My WhatsApp');
  if (name === null) return;
  const acc = await api('/api/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: name }),
  });
  currentAccountId = acc.id;
  await loadAccounts();
}

// ---------- Connection ----------
function setStatusDot(status) {
  $('statusDot').className = 'dot ' + status;
}

async function pollStatus() {
  if (!currentAccountId) return;
  let s;
  try { s = await api(`/api/accounts/${currentAccountId}/status`); }
  catch { return; }
  setStatusDot(s.status);
  renderConnection(s);
  if (s.status === 'connected') {
    await loadGroups();
    // Slow the poll once connected.
    scheduleStatusPoll(8000);
  } else if (s.status === 'qr' || s.status === 'connecting') {
    scheduleStatusPoll(2500);
  } else {
    scheduleStatusPoll(5000);
  }
}
function scheduleStatusPoll(ms) {
  clearTimeout(statusTimer);
  statusTimer = setTimeout(pollStatus, ms);
}

function renderConnection(s) {
  const el = $('connectionBody');
  if (s.status === 'connected') {
    const acc = accounts.find((a) => a.id === currentAccountId) || {};
    el.innerHTML = `
      <p class="connected-line">${ICON.check} <span>Connected${acc.wa_name ? ' as <b>' + escapeHtml(acc.wa_name) + '</b>' : ''}.</span></p>
      <p class="muted">${s.groupCount} group(s) available.</p>
      <div class="row">
        <button class="ghost small" id="reloadGroupsBtn">Reload groups</button>
        <button class="danger small" id="logoutWaBtn">Unlink WhatsApp</button>
      </div>`;
    $('reloadGroupsBtn').onclick = loadGroups;
    $('logoutWaBtn').onclick = unlinkWa;
  } else if (s.status === 'qr' && s.qr) {
    el.innerHTML = `
      <p>Open WhatsApp → <b>Linked devices</b> → <b>Link a device</b> and scan:</p>
      <div class="qr"><img src="${s.qr}" alt="QR code" /></div>`;
  } else if (s.status === 'connecting') {
    el.innerHTML = `<p class="muted">Connecting…</p>`;
  } else {
    el.innerHTML = `
      <p class="muted">Not linked.</p>
      <button id="connectBtn">Link WhatsApp</button>`;
    $('connectBtn').onclick = connectWa;
  }
}

async function connectWa() {
  await api(`/api/accounts/${currentAccountId}/connect`, { method: 'POST' });
  scheduleStatusPoll(1000);
}
async function unlinkWa() {
  if (!confirm('Unlink this WhatsApp account?')) return;
  await api(`/api/accounts/${currentAccountId}/logout`, { method: 'POST' });
  $('groupList').innerHTML = '<p class="muted">Connect WhatsApp to load groups.</p>';
  pollStatus();
}

// ---------- Groups ----------
let groups = [];
async function loadGroups() {
  try { groups = await api(`/api/accounts/${currentAccountId}/groups`); }
  catch { groups = []; }
  const el = $('groupList');
  if (groups.length === 0) {
    el.innerHTML = '<p class="muted">No groups found (or still syncing).</p>';
    return;
  }
  el.innerHTML = groups.map((g) => `
    <label><input type="checkbox" value="${escapeHtml(g.jid)}" data-name="${escapeHtml(g.name)}" />
      ${escapeHtml(g.name)}</label>`).join('');
}

// ---------- Compose ----------
$('composeForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('composeErr'); err.hidden = true;
  const checked = [...document.querySelectorAll('#groupList input:checked')]
    .map((c) => ({ jid: c.value, name: c.dataset.name }));
  const runAtLocal = $('runAt').value;
  if (!runAtLocal) { showErr(err, 'Pick a send time.'); return; }
  if (checked.length === 0) { showErr(err, 'Pick at least one group.'); return; }

  const fd = new FormData();
  fd.append('account_id', currentAccountId);
  fd.append('body', $('body').value);
  // datetime-local is local time; convert to ISO (UTC) for the server.
  fd.append('run_at', new Date(runAtLocal).toISOString());
  fd.append('repeat', $('repeat').value);
  fd.append('targets', JSON.stringify(checked));
  if ($('media').files[0]) fd.append('media', $('media').files[0]);

  const btn = $('scheduleBtn'); btn.disabled = true; btn.textContent = 'Scheduling…';
  try {
    await api('/api/posts', { method: 'POST', body: fd });
    $('composeForm').reset();
    await loadPosts();
    $('composeHint').textContent = 'Scheduled ✓';
    setTimeout(() => ($('composeHint').textContent = ''), 2500);
  } catch (ex) {
    showErr(err, ex.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Schedule';
  }
});

// ---------- Posts ----------
async function loadPosts() {
  const posts = await api(`/api/posts?account_id=${currentAccountId}`);
  const el = $('postList');
  if (posts.length === 0) { el.innerHTML = '<p class="empty">No posts yet.</p>'; return; }
  el.innerHTML = posts.map(renderPost).join('');
  el.querySelectorAll('[data-cancel]').forEach((b) =>
    (b.onclick = () => cancelPost(b.dataset.cancel)));
  el.querySelectorAll('[data-del]').forEach((b) =>
    (b.onclick = () => deletePost(b.dataset.del)));
}

function renderPost(p) {
  const when = new Date(p.run_at).toLocaleString();
  const repeat = p.repeat === 'none' ? '' : ` · repeats ${p.repeat}`;
  const chips = p.targets.map((t) => `<span class="chip">${escapeHtml(t.group_name || t.group_jid)}</span>`).join('');
  const sent = p.deliveries.filter((d) => d.status === 'sent').length;
  const failed = p.deliveries.filter((d) => d.status === 'failed').length;
  const deliverySummary = p.deliveries.length
    ? `<div class="meta">Delivered: ${sent} ok${failed ? `, ${failed} failed` : ''}</div>` : '';
  const err = p.last_error ? `<div class="meta error">${escapeHtml(p.last_error)}</div>` : '';
  const canCancel = p.status === 'scheduled';
  return `
    <div class="post">
      <div class="row spread">
        <span class="badge ${p.status}">${p.status}</span>
        <span class="meta">${when}${repeat}</span>
      </div>
      ${p.media_type ? `<div class="meta media-tag">${ICON.clip} ${escapeHtml(p.media_type)}</div>` : ''}
      <div class="body">${escapeHtml(p.body || '(media only)')}</div>
      <div class="chips">${chips}</div>
      ${deliverySummary}
      ${err}
      <div class="row" style="margin-top:10px">
        ${canCancel ? `<button class="ghost small" data-cancel="${p.id}">Cancel</button>` : ''}
        <button class="danger small" data-del="${p.id}">Delete</button>
      </div>
    </div>`;
}

async function cancelPost(id) {
  await api(`/api/posts/${id}/cancel`, { method: 'POST' });
  loadPosts();
}
async function deletePost(id) {
  if (!confirm('Delete this post?')) return;
  await api(`/api/posts/${id}`, { method: 'DELETE' });
  loadPosts();
}

// ---------- helpers ----------
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function showErr(el, msg) { el.textContent = msg; el.hidden = false; }

async function refreshAll() {
  await pollStatus();
  await loadPosts();
}

// ---------- wiring ----------
$('accountSelect').addEventListener('change', (e) => {
  currentAccountId = Number(e.target.value);
  clearTimeout(statusTimer);
  refreshAll();
});
$('newAccountBtn').onclick = () => createAccount();
$('refreshPostsBtn').onclick = loadPosts;
$('logoutBtn').onclick = async () => { await api('/api/logout', { method: 'POST' }); location.href = '/login'; };

// Default the datetime picker to 1 hour out.
(() => {
  const d = new Date(Date.now() + 3600_000);
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  $('runAt').value = d.toISOString().slice(0, 16);
})();

loadAccounts().catch((e) => console.error(e));
