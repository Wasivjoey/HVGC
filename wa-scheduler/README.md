# WA Scheduler

Self-hosted platform to **schedule posts to your WhatsApp groups and communities**.
Link your WhatsApp by QR, pick groups, write a message (with optional image/video/file),
set a time, and it posts for you — once, daily, or weekly.

## ⚠️ Read this first

There is **no official WhatsApp API for posting to groups**. This tool drives
**WhatsApp Web** through the unofficial [Baileys](https://github.com/WhiskeySockets/Baileys)
library using your own linked number.

- Automated / bulk messaging is **against WhatsApp's Terms of Service**.
- Numbers that post aggressively **can be banned**.
- Keep volume low and human-like. The scheduler already adds a randomized delay
  between each group send (`SEND_JITTER_*` in `.env`) to help.

Use it for your own groups and genuine content. You accept the risk to your number.

## Stack

- **Node.js + Express** — API and dashboard
- **Baileys** — WhatsApp Web engine (no browser/Chromium needed)
- **better-sqlite3** — local database (`data/app.db`)
- Vanilla HTML/CSS/JS dashboard (no build step)

## Setup

```bash
cd wa-scheduler
npm install
cp .env.example .env
# edit .env: set DASHBOARD_PASSWORD and SESSION_SECRET
npm start
```

Open http://localhost:3000, sign in with `DASHBOARD_PASSWORD`, then:

1. **Link WhatsApp** — click *Link WhatsApp*, scan the QR with
   WhatsApp → *Linked devices* → *Link a device*.
2. **Schedule a post** — write your message, pick groups, choose a time and
   repeat, hit *Schedule*.
3. The scheduler sends due posts automatically and records per-group results
   under **Posts**.

Sessions persist in `data/sessions/<accountId>`, so you don't re-scan after a restart.

## How it works

- `src/whatsapp/manager.js` — one Baileys connection per account; QR, groups, sending.
- `src/scheduler/scheduler.js` — polls every `SCHEDULER_TICK_MS`, sends due posts
  with jitter + retry (`MAX_SEND_ATTEMPTS`), rolls recurring posts forward.
- `src/routes/*` — REST API (`/api/accounts`, `/api/posts`).
- `public/` — the dashboard.

## Configuration (`.env`)

| Variable | Meaning |
|---|---|
| `PORT` | Dashboard/API port (default 3000) |
| `DASHBOARD_PASSWORD` | Password to sign in to the dashboard |
| `SESSION_SECRET` | Secret for signing session cookies |
| `SCHEDULER_TICK_MS` | How often to check for due posts |
| `SEND_JITTER_MIN_MS` / `SEND_JITTER_MAX_MS` | Random delay between group sends |
| `MAX_SEND_ATTEMPTS` | Retries before a post is marked failed |

## Notes & limits

- Multiple WhatsApp accounts (numbers) are supported — add more with **+ Account**.
- Times are stored in UTC; the dashboard shows/sends in your browser's local time.
- "Communities" in WhatsApp are collections of groups — target the underlying
  groups (they appear in the group list).
- This is a single-operator tool (one shared dashboard password). Put it behind
  a reverse proxy / VPN if you expose it beyond localhost.
