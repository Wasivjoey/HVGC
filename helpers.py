"""Shared helpers: auth guards and the qualification rules that decide whether a
user is allowed to actually serve in a role."""

import os
import re
import smtplib
import uuid
from datetime import date
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urlparse, parse_qs

from flask import session, redirect, url_for, flash, g, current_app, request
from werkzeug.utils import secure_filename

from db import get_db, now_iso


def send_email(to_address, subject, body):
    """Send a plain-text email. Returns True if actually sent.

    When SMTP isn't configured the message (including any verification link) is
    written to the application log and the function returns False, so callers can
    fall back to showing the link on screen.
    """
    cfg = current_app.config
    if not cfg.get("EMAIL_ENABLED"):
        current_app.logger.info("[EMAIL not configured] To: %s | %s\n%s",
                                to_address, subject, body)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = to_address
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as s:
            if cfg.get("SMTP_TLS"):
                s.starttls()
            if cfg.get("SMTP_USER"):
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception as e:  # network/auth problems shouldn't crash registration
        current_app.logger.error("Email send failed: %s", e)
        return False

ALLOWED_DOC_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "txt", "rtf", "png", "jpg", "jpeg",
}


def allowed_document(filename):
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in ALLOWED_DOC_EXTENSIONS


def save_document(file_storage):
    """Persist an uploaded document and return (stored_name, original_name).

    Returns (None, None) when no usable file was provided. Raises ValueError for
    a disallowed file type so the caller can flash a message.
    """
    if file_storage is None or not file_storage.filename:
        return (None, None)
    original = file_storage.filename
    if not allowed_document(original):
        raise ValueError("Unsupported file type.")
    safe = secure_filename(original) or "document"
    stored = f"{uuid.uuid4().hex}_{safe}"
    dest = os.path.join(current_app.config["UPLOAD_PATH"], stored)
    file_storage.save(dest)
    return (stored, original)


def delete_document(stored_name):
    if not stored_name:
        return
    path = os.path.join(current_app.config["UPLOAD_PATH"], stored_name)
    try:
        os.remove(path)
    except OSError:
        pass


ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}


def avatars_dir():
    d = os.path.join(current_app.config["UPLOAD_PATH"], "avatars")
    os.makedirs(d, exist_ok=True)
    return d


def save_avatar(file_storage):
    """Process an uploaded photo into a square avatar and return its filename.

    Honours EXIF orientation, centre-crops to a square, and resizes to 256px so
    avatars are small and uniform. Raises ValueError on an unusable image.
    """
    if file_storage is None or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        raise ValueError("Please upload a PNG, JPG, GIF, or WEBP image.")

    from PIL import Image, ImageOps  # local import keeps Pillow optional elsewhere
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img = ImageOps.fit(img, (256, 256), method=Image.LANCZOS, centering=(0.5, 0.5))
    except Exception:
        raise ValueError("That image could not be read. Try a different photo.")

    stored = f"avatar_{uuid.uuid4().hex}.jpg"
    img.save(os.path.join(avatars_dir(), stored), "JPEG", quality=85, optimize=True)
    return stored


def delete_avatar(stored_name):
    if not stored_name:
        return
    try:
        os.remove(os.path.join(avatars_dir(), stored_name))
    except OSError:
        pass


def parse_video(url):
    """Turn an arbitrary video link into something we can embed and control.

    Returns a dict: {kind, src, original} where kind is one of
    'youtube' | 'vimeo' | 'file' | 'link'. For youtube/vimeo, src is an embed
    URL with the JS API enabled so we can pause it when the user leaves the
    window. For 'file' it's a direct media URL for an HTML5 <video>.
    """
    if not url:
        return None
    url = url.strip()
    low = url.lower()

    # YouTube — watch?v=, youtu.be/, /embed/, /shorts/
    yt_id = None
    m = re.search(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    if m:
        yt_id = m.group(1)
    elif "youtube.com" in low:
        q = parse_qs(urlparse(url).query)
        if q.get("v"):
            yt_id = q["v"][0]
    if yt_id:
        return {"kind": "youtube",
                "src": f"https://www.youtube.com/embed/{yt_id}?enablejsapi=1&rel=0",
                "original": url}

    # Vimeo — vimeo.com/<id>
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", url)
    if m:
        return {"kind": "vimeo",
                "src": f"https://player.vimeo.com/video/{m.group(1)}",
                "original": url}

    # Direct video file
    if re.search(r"\.(mp4|webm|ogg|mov|m4v)(\?.*)?$", low):
        return {"kind": "file", "src": url, "original": url}

    # Anything else — just a link out
    return {"kind": "link", "src": url, "original": url}


def current_user():
    uid = session.get("user_id")
    if uid is None:
        return None
    if getattr(g, "_cached_user_id", None) == uid:
        return g._cached_user
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    g._cached_user_id = uid
    g._cached_user = user
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if not user["is_admin"]:
            flash("That area is for administrators only.", "danger")
            return redirect(url_for("user.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def role_training_status(conn, user_id, role_id):
    """Return (required_count, completed_count) of required trainings for a role.

    A user is qualified for a role when every *required* training tied to that
    role has been completed by the user.
    """
    required = conn.execute(
        "SELECT id FROM trainings WHERE role_id = ? AND required = 1", (role_id,)
    ).fetchall()
    required_ids = [t["id"] for t in required]
    if not required_ids:
        return (0, 0)
    placeholders = ",".join("?" for _ in required_ids)
    completed = conn.execute(
        f"SELECT COUNT(*) AS c FROM user_training"
        f" WHERE user_id = ? AND status = 'completed' AND training_id IN ({placeholders})",
        [user_id, *required_ids],
    ).fetchone()["c"]
    return (len(required_ids), completed)


def is_qualified(conn, user_id, role_id):
    """True when the user has the role assigned AND finished its required training."""
    has_role = conn.execute(
        "SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = ?",
        (user_id, role_id),
    ).fetchone()
    if not has_role:
        return False
    required, completed = role_training_status(conn, user_id, role_id)
    return completed >= required


def notify(conn, user_id, body, link=None, email=False, subject=None):
    """Queue an in-app notification for a user. Caller commits.

    When ``email`` is set, also send the message to the user's email address
    (used for high-priority events). Email failures never block the in-app
    notification — send_email already degrades gracefully when SMTP is unset.
    """
    conn.execute(
        "INSERT INTO notifications (user_id, body, link, is_read, created_at)"
        " VALUES (?, ?, ?, 0, ?)",
        (user_id, body, link, now_iso()),
    )
    if email:
        row = conn.execute(
            "SELECT name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row and row["email"]:
            url = ""
            if link:
                try:
                    url = request.url_root.rstrip("/") + link
                except RuntimeError:  # no request context (shouldn't happen here)
                    url = link
            message = (f"Hi {row['name']},\n\n{body}"
                       + (f"\n\nOpen HVGC LINEUP: {url}" if url else "")
                       + "\n\n— HVGC LINEUP")
            send_email(row["email"], subject or "HVGC LINEUP update", message)


def notify_all(conn, body, link=None, exclude_id=None):
    """Notify every active user (optionally excluding one, e.g. the actor)."""
    if exclude_id:
        rows = conn.execute(
            "SELECT id FROM users WHERE is_active = 1 AND id <> ?", (exclude_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT id FROM users WHERE is_active = 1").fetchall()
    for r in rows:
        notify(conn, r["id"], body, link)


def unread_notification_count(conn, user_id):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()["c"]


def get_announcements(conn, active_only=True):
    """Announcements for display. active_only filters to live, unexpired ones."""
    if active_only:
        return conn.execute(
            "SELECT a.*, u.name AS author FROM announcements a"
            " LEFT JOIN users u ON u.id = a.created_by"
            " WHERE a.active = 1 AND (a.expires_at IS NULL OR a.expires_at >= ?)"
            " ORDER BY a.created_at DESC",
            (date.today().isoformat(),),
        ).fetchall()
    return conn.execute(
        "SELECT a.*, u.name AS author FROM announcements a"
        " LEFT JOIN users u ON u.id = a.created_by ORDER BY a.created_at DESC"
    ).fetchall()


def poll_is_open(poll, now_str=None):
    if poll["closed"]:
        return False
    now_str = now_str or now_iso()
    return not poll["closes_at"] or poll["closes_at"] >= now_str


def get_polls(conn, user_id=None, only_open=False, with_voters=False):
    """Return polls with their options, vote counts/percentages, the current
    user's choice, and whether the poll is still open.

    When ``with_voters`` is set (admin view only), each option also includes the
    list of users who chose it. Volunteers never get this — their results stay
    anonymous.
    """
    now = now_iso()
    result = []
    for p in conn.execute("SELECT * FROM polls ORDER BY created_at DESC").fetchall():
        is_open = poll_is_open(p, now)
        if only_open and not is_open:
            continue
        opts = conn.execute(
            "SELECT * FROM poll_options WHERE poll_id = ? ORDER BY position, id",
            (p["id"],),
        ).fetchall()
        counts = {o["id"]: 0 for o in opts}
        for v in conn.execute(
            "SELECT option_id, COUNT(*) AS c FROM poll_votes WHERE poll_id = ?"
            " GROUP BY option_id", (p["id"],)
        ).fetchall():
            counts[v["option_id"]] = v["c"]
        total = sum(counts.values())
        user_opt = None
        if user_id is not None:
            uv = conn.execute(
                "SELECT option_id FROM poll_votes WHERE poll_id = ? AND user_id = ?",
                (p["id"], user_id),
            ).fetchone()
            user_opt = uv["option_id"] if uv else None

        voters_by_option = {}
        if with_voters:
            for v in conn.execute(
                "SELECT pv.option_id, u.name FROM poll_votes pv"
                " JOIN users u ON u.id = pv.user_id"
                " WHERE pv.poll_id = ? ORDER BY u.name", (p["id"],)
            ).fetchall():
                voters_by_option.setdefault(v["option_id"], []).append(v["name"])

        result.append({
            "poll": p,
            "open": is_open,
            "total": total,
            "user_option_id": user_opt,
            "options": [{
                "id": o["id"], "text": o["text"], "votes": counts[o["id"]],
                "pct": round(counts[o["id"]] * 100 / total) if total else 0,
                "voters": voters_by_option.get(o["id"], []),
            } for o in opts],
        })
    return result


def qualified_users_for_role(conn, role_id):
    """All active users who are assigned the role and have finished its training."""
    candidates = conn.execute(
        "SELECT u.* FROM users u"
        " JOIN user_roles ur ON ur.user_id = u.id"
        " WHERE ur.role_id = ? AND u.is_active = 1"
        " ORDER BY u.name",
        (role_id,),
    ).fetchall()
    return [u for u in candidates if is_qualified(conn, u["id"], role_id)]
