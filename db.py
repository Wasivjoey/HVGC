"""Database layer for HVGC LINEUP.

Supports two backends, selected automatically:

* **Postgres** when ``DATABASE_URL`` is set to a ``postgres://`` /
  ``postgresql://`` URL (what cloud platforms provide). Requires psycopg2.
* **SQLite** otherwise, using the file at ``DATABASE_PATH`` — zero-dependency,
  great for local development.

The rest of the app uses ``?`` placeholders and a small set of SQL features; a
thin wrapper translates those to Postgres (``%s`` placeholders, ``ON CONFLICT``,
``RETURNING``) so the application code is identical on both backends.
"""

import os
import re
import sqlite3
from datetime import datetime, date

from werkzeug.security import generate_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "avteam.db"))

if USE_PG:
    import psycopg2
    import psycopg2.extras

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    username       TEXT UNIQUE,
    email          TEXT NOT NULL UNIQUE,
    phone          TEXT,
    password_hash  TEXT NOT NULL,
    is_admin       INTEGER NOT NULL DEFAULT 0,
    is_active      INTEGER NOT NULL DEFAULT 1,
    email_verified INTEGER NOT NULL DEFAULT 0,  -- has the user confirmed their email
    verify_token   TEXT,                        -- one-time email verification token
    approved       INTEGER NOT NULL DEFAULT 0,  -- has an admin approved this account
    avatar         TEXT,
    reset_token    TEXT,                        -- one-time password reset token
    reset_expires  TEXT,                        -- ISO expiry for the reset token
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

-- A role assigned to a user by an admin. A user may only be *scheduled* for a
-- role once every required training for that role has been completed.
CREATE TABLE IF NOT EXISTS user_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TEXT NOT NULL,
    UNIQUE(user_id, role_id)
);

CREATE TABLE IF NOT EXISTS trainings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    content     TEXT,
    video_url   TEXT,
    role_id     INTEGER REFERENCES roles(id) ON DELETE SET NULL,
    required    INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_training (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    training_id  INTEGER NOT NULL REFERENCES trainings(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'assigned',  -- assigned | completed
    assigned_at  TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(user_id, training_id)
);

CREATE TABLE IF NOT EXISTS services (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    service_date TEXT NOT NULL,      -- YYYY-MM-DD
    start_time   TEXT,               -- HH:MM
    location     TEXT,
    notes        TEXT,
    doc_filename TEXT,               -- stored programme-flow file name on disk
    doc_original TEXT,               -- original upload name shown to users
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id  INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | confirmed | declined
    created_at  TEXT NOT NULL,
    UNIQUE(service_id, user_id, role_id)
);

-- Per-user availability on a given calendar date.
CREATE TABLE IF NOT EXISTS availability (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day     TEXT NOT NULL,            -- YYYY-MM-DD
    status  TEXT NOT NULL,            -- available | unavailable
    note    TEXT,
    UNIQUE(user_id, day)
);

-- A request to give up an assignment. Another qualified user can volunteer to
-- cover it, and an admin approves the swap (which reassigns the slot).
CREATE TABLE IF NOT EXISTS swap_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    requested_by  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    covered_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    reason        TEXT,
    status        TEXT NOT NULL DEFAULT 'open',  -- open | volunteered | approved | rejected | cancelled
    created_at    TEXT NOT NULL,
    resolved_at   TEXT
);

-- Free-form notes attached to a service time by any team member.
CREATE TABLE IF NOT EXISTS service_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# --------------------------------------------------------------------- Postgres
def _translate(sql):
    """Rewrite our SQLite-flavoured SQL for Postgres."""
    if "INSERT OR IGNORE" in sql:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql.replace("?", "%s")


class _PGConn:
    """Adapts a psycopg2 connection to the small subset of the sqlite3 API the
    app uses (execute/executemany/executescript/commit/close), returning
    dict-like rows so templates and code work unchanged."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        cur = self.raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_translate(sql), params)
        return cur

    def executemany(self, sql, seq):
        cur = self.raw.cursor()
        cur.executemany(_translate(sql), list(seq))
        cur.close()

    def executescript(self, sql):
        cur = self.raw.cursor()
        cur.execute(sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"))
        cur.close()

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()


def get_db():
    if USE_PG:
        return _PGConn(psycopg2.connect(DATABASE_URL))
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def execute_returning_id(conn, sql, params=()):
    """Run an INSERT and return the new row's id, on either backend."""
    if USE_PG:
        cur = conn.execute(sql.rstrip().rstrip(";") + " RETURNING id", params)
        return cur.fetchone()["id"]
    return conn.execute(sql, params).lastrowid


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def _columns(conn, table):
    if USE_PG:
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


# Arbitrary fixed key so concurrent workers serialize first-run initialization.
_INIT_LOCK_KEY = 728114


def init_db():
    """Create tables (idempotent) and seed first-run data.

    Multiple gunicorn workers boot at once and each call this. On Postgres,
    concurrent ``CREATE TABLE`` statements can race, so we take a session-level
    advisory lock and let one worker initialise while the others wait.
    """
    conn = get_db()
    locked = False
    try:
        if USE_PG:
            conn.execute("SELECT pg_advisory_lock(?)", (_INIT_LOCK_KEY,))
            locked = True
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
        _seed(conn)
    finally:
        if locked:
            try:
                conn.execute("SELECT pg_advisory_unlock(?)", (_INIT_LOCK_KEY,))
                conn.commit()
            except Exception:
                pass
        conn.close()


def _migrate(conn):
    """Idempotent column additions for SQLite databases created by an earlier
    version of the app. On a fresh Postgres database every column already exists
    (it's in the schema), so these are all no-ops."""
    cols = _columns(conn, "trainings")
    if "video_url" not in cols:
        conn.execute("ALTER TABLE trainings ADD COLUMN video_url TEXT")
        conn.commit()

    scols = _columns(conn, "services")
    if "doc_filename" not in scols:
        conn.execute("ALTER TABLE services ADD COLUMN doc_filename TEXT")
        conn.commit()
    if "doc_original" not in scols:
        conn.execute("ALTER TABLE services ADD COLUMN doc_original TEXT")
        conn.commit()

    ucols = _columns(conn, "users")
    if "avatar" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
        conn.commit()

    # Accounts now require a username, a verified email, and admin approval.
    # Existing accounts are grandfathered in (verified + approved) so nobody is
    # locked out by the upgrade.
    if "username" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        used = set()
        for r in conn.execute("SELECT id, email FROM users").fetchall():
            local = re.sub(r"[^a-z0-9_]", "", (r["email"] or "user").split("@")[0].lower()) or "user"
            cand, n = local, 1
            while cand in used:
                n += 1
                cand = f"{local}{n}"
            used.add(cand)
            conn.execute("UPDATE users SET username = ? WHERE id = ?", (cand, r["id"]))
        conn.commit()
    if "email_verified" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE users SET email_verified = 1")  # grandfather existing
        conn.commit()
    if "verify_token" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN verify_token TEXT")
        conn.commit()
    if "approved" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE users SET approved = 1")  # grandfather existing
        conn.commit()
    if "reset_token" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
        conn.commit()
    if "reset_expires" not in ucols:
        conn.execute("ALTER TABLE users ADD COLUMN reset_expires TEXT")
        conn.commit()


def _seed(conn):
    # Seed default AV roles once.
    existing_roles = conn.execute("SELECT COUNT(*) AS c FROM roles").fetchone()["c"]
    if existing_roles == 0:
        default_roles = [
            ("Audio Engineer", "Run the sound board, mix front-of-house and monitors."),
            ("Lighting", "Operate stage and house lighting cues."),
            ("Camera Operator", "Run a broadcast or IMAG camera during the service."),
            ("Video Director", "Call camera shots and run the video switcher."),
            ("Lyrics / ProPresenter", "Run lyrics, scripture, and slides software."),
            ("Livestream", "Manage the online stream and recording."),
            ("Photographer", "Capture stills throughout the service."),
        ]
        conn.executemany(
            "INSERT INTO roles (name, description) VALUES (?, ?)", default_roles
        )
        conn.commit()

    # Seed an initial admin account once.
    admin = conn.execute(
        "SELECT id FROM users WHERE email = ?", ("admin@avteam.app",)
    ).fetchone()
    if admin is None:
        conn.execute(
            "INSERT INTO users (name, username, email, phone, password_hash, is_admin,"
            " is_active, email_verified, approved, created_at)"
            " VALUES (?, ?, ?, ?, ?, 1, 1, 1, 1, ?)",
            (
                "Team Administrator",
                "admin",
                "admin@avteam.app",
                "",
                generate_password_hash("admin123", method="pbkdf2:sha256"),
                now_iso(),
            ),
        )
        conn.commit()

    # Seed a starter required training per role once.
    existing_training = conn.execute("SELECT COUNT(*) AS c FROM trainings").fetchone()["c"]
    if existing_training == 0:
        roles = conn.execute("SELECT id, name FROM roles").fetchall()
        for r in roles:
            conn.execute(
                "INSERT INTO trainings (title, description, content, role_id, required, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (
                    f"{r['name']} Basics",
                    f"Required onboarding before serving in the {r['name']} role.",
                    (
                        f"Welcome to the {r['name']} team!\n\n"
                        "1. Review the equipment checklist and signal flow.\n"
                        "2. Shadow an experienced volunteer for one service.\n"
                        "3. Learn the pre-service and post-service procedures.\n"
                        "4. Know who to contact if something goes wrong.\n\n"
                        "Mark this training complete once you have read this and "
                        "completed your shadow service."
                    ),
                    r["id"],
                    now_iso(),
                ),
            )
        conn.commit()

    # Seed a couple of upcoming sample services once.
    existing_services = conn.execute("SELECT COUNT(*) AS c FROM services").fetchone()["c"]
    if existing_services == 0:
        conn.executemany(
            "INSERT INTO services (title, service_date, start_time, location, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Sunday Morning Service", _next_sunday(), "09:00", "Main Auditorium",
                 "Standard weekend gathering.", now_iso()),
                ("Sunday Evening Service", _next_sunday(), "18:00", "Main Auditorium",
                 "Acoustic set, lighter lighting cues.", now_iso()),
            ],
        )
        conn.commit()


def _next_sunday():
    today = date.today()
    days_ahead = (6 - today.weekday()) % 7  # Monday=0 .. Sunday=6
    days_ahead = days_ahead or 7
    from datetime import timedelta
    return (today + timedelta(days=days_ahead)).isoformat()
