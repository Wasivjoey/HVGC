"""Español para Todos — Flask backend.

Serves the PWA (public/) and a small JSON API for accounts and per-account
progress tracking. Auth uses signed bearer tokens (itsdangerous) so no extra
dependencies beyond Flask are required; passwords are hashed with werkzeug.
"""

import os
import re
import sys
import sqlite3
import secrets
from datetime import datetime, date, timedelta

from flask import Flask, request, jsonify, send_from_directory, g
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Run from the app's own directory. This keeps relative paths predictable and
# avoids os.getcwd() failing when the launcher's working directory is one the
# process isn't allowed to read (e.g. a macOS TCC-protected folder).
try:
    os.chdir(BASE_DIR)
except OSError:
    pass
# Allow `from src.curriculum ...` regardless of the process working directory.
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.curriculum import CURRICULUM, LESSON_IDS  # noqa: E402
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# On Render, mount a persistent disk and set DATA_DIR to its path (e.g. /data)
# so the SQLite file survives deploys. Locally it defaults to ./data.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

# Set SECRET_KEY in the environment for production so tokens survive restarts.
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
TOKEN_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

app = Flask(__name__, static_folder=None)
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="auth")

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            email         TEXT,
            password_hash TEXT NOT NULL,
            learner_name  TEXT,
            age_band      TEXT,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS lesson_progress (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            lesson_id    TEXT NOT NULL,
            score        INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT NOT NULL,
            UNIQUE (user_id, lesson_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS daily_activity (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL,
            day               TEXT NOT NULL,
            lessons_completed INTEGER NOT NULL DEFAULT 0,
            minutes           INTEGER NOT NULL DEFAULT 0,
            UNIQUE (user_id, day),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    db.commit()
    db.close()


init_db()


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def public_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "learnerName": row["learner_name"],
        "ageBand": row["age_band"],
        "createdAt": row["created_at"],
    }


def make_token(user_id):
    return serializer.dumps({"uid": user_id})


def current_user():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:]
    try:
        data = serializer.loads(token, max_age=TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (data["uid"],)).fetchone()
    return row


def require_auth():
    user = current_user()
    if user is None:
        return None, (jsonify(error="Not authenticated"), 401)
    return user, None


# --------------------------------------------------------------------------- #
# API: auth
# --------------------------------------------------------------------------- #
@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(error="Username and password are required"), 400
    if not (3 <= len(username) <= 30):
        return jsonify(error="Username must be 3–30 characters"), 400
    if len(password) < 6:
        return jsonify(error="Password must be at least 6 characters"), 400

    db = get_db()
    exists = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if exists:
        return jsonify(error="That username is already taken"), 409

    cur = db.execute(
        """INSERT INTO users (username, email, password_hash, learner_name, age_band, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            username,
            (data.get("email") or "").strip() or None,
            generate_password_hash(password, method="pbkdf2:sha256"),
            (data.get("learnerName") or "").strip() or None,
            (data.get("ageBand") or "").strip() or None,
            datetime.utcnow().isoformat(),
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(token=make_token(row["id"]), user=public_user(row))


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify(error="Username and password are required"), 400
    row = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify(error="Incorrect username or password"), 401
    return jsonify(token=make_token(row["id"]), user=public_user(row))


@app.get("/api/me")
def me():
    user, err = require_auth()
    if err:
        return err
    return jsonify(user=public_user(user))


@app.put("/api/me")
def update_me():
    user, err = require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    db = get_db()
    db.execute(
        "UPDATE users SET learner_name = ?, age_band = ?, email = ? WHERE id = ?",
        (
            (data.get("learnerName") or user["learner_name"]),
            (data.get("ageBand") or user["age_band"]),
            (data.get("email") or user["email"]),
            user["id"],
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return jsonify(user=public_user(row))


# --------------------------------------------------------------------------- #
# API: curriculum (public)
# --------------------------------------------------------------------------- #
@app.get("/api/curriculum")
def curriculum():
    return jsonify(CURRICULUM)


# --------------------------------------------------------------------------- #
# API: progress
# --------------------------------------------------------------------------- #
def compute_streak(days):
    active = set(days)
    cursor = date.today()
    if cursor.isoformat() not in active:
        cursor = cursor - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in active:
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


@app.get("/api/progress")
def get_progress():
    user, err = require_auth()
    if err:
        return err
    db = get_db()
    rows = db.execute(
        "SELECT lesson_id, score, completed_at FROM lesson_progress WHERE user_id = ?",
        (user["id"],),
    ).fetchall()
    activity = db.execute(
        "SELECT day, lessons_completed, minutes FROM daily_activity WHERE user_id = ? ORDER BY day DESC",
        (user["id"],),
    ).fetchall()

    completed = {
        r["lesson_id"]: {"score": r["score"], "completedAt": r["completed_at"]} for r in rows
    }
    activity_list = [
        {"day": a["day"], "lessons_completed": a["lessons_completed"], "minutes": a["minutes"]}
        for a in activity
    ]
    return jsonify(
        completed=completed,
        completedCount=len(rows),
        totalLessons=len(LESSON_IDS),
        activity=activity_list,
        streak=compute_streak([a["day"] for a in activity]),
        totalMinutes=sum(a["minutes"] for a in activity),
    )


@app.post("/api/progress/complete")
def complete_lesson():
    user, err = require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    lesson_id = data.get("lessonId")
    if lesson_id not in LESSON_IDS:
        return jsonify(error="Unknown lesson"), 400

    try:
        score = max(0, min(100, int(data.get("score") or 0)))
    except (TypeError, ValueError):
        score = 0
    try:
        minutes = max(0, min(600, int(data.get("minutes") or 0)))
    except (TypeError, ValueError):
        minutes = 0
    day = data.get("day")
    if not (isinstance(day, str) and DAY_RE.match(day)):
        day = date.today().isoformat()
    now = datetime.utcnow().isoformat()

    db = get_db()
    already = db.execute(
        "SELECT id FROM lesson_progress WHERE user_id = ? AND lesson_id = ?",
        (user["id"], lesson_id),
    ).fetchone()

    db.execute(
        """INSERT INTO lesson_progress (user_id, lesson_id, score, completed_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, lesson_id)
           DO UPDATE SET score = MAX(score, excluded.score), completed_at = excluded.completed_at""",
        (user["id"], lesson_id, score, now),
    )
    inc = 0 if already else 1
    db.execute(
        """INSERT INTO daily_activity (user_id, day, lessons_completed, minutes)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, day)
           DO UPDATE SET lessons_completed = lessons_completed + ?, minutes = minutes + ?""",
        (user["id"], day, inc, minutes, inc, minutes),
    )
    db.commit()
    return jsonify(ok=True)


# --------------------------------------------------------------------------- #
# Static PWA
# --------------------------------------------------------------------------- #
@app.get("/service-worker.js")
def service_worker():
    resp = send_from_directory(PUBLIC_DIR, "service-worker.js")
    resp.headers["Cache-Control"] = "no-cache"  # never cache the SW itself
    return resp


@app.get("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.get("/<path:path>")
def static_or_spa(path):
    full = os.path.join(PUBLIC_DIR, path)
    if os.path.isfile(full):
        return send_from_directory(PUBLIC_DIR, path)
    # SPA fallback for client routes
    return send_from_directory(PUBLIC_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=True)
