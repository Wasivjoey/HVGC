"""Shared helpers: auth guards and the qualification rules that decide whether a
user is allowed to actually serve in a role."""

import io
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


def send_email(to_address, subject, body, attachments=None):
    """Send a plain-text email, optionally with attachments. Returns True if sent.

    attachments: list of (filename, data, maintype, subtype) tuples.
    Uses the Brevo HTTP API when a BREVO_API_KEY is configured (works over HTTPS
    on hosts that block SMTP ports, e.g. Render), otherwise falls back to SMTP.
    When neither is configured the message is logged and False is returned so
    callers can fall back to showing links on screen.
    """
    cfg = current_app.config
    if not cfg.get("EMAIL_ENABLED"):
        current_app.logger.info("[EMAIL not configured] To: %s | %s\n%s",
                                to_address, subject, body)
        return False
    if cfg.get("BREVO_API_KEY"):
        return _send_email_brevo(to_address, subject, body, attachments)
    return _send_email_smtp(to_address, subject, body, attachments)


def _send_email_brevo(to_address, subject, body, attachments=None):
    """Send via Brevo's transactional email API over HTTPS (port 443)."""
    import base64
    import json
    import urllib.error
    import urllib.request

    cfg = current_app.config
    payload = {
        "sender": {"email": cfg["SMTP_FROM"], "name": cfg.get("EMAIL_FROM_NAME", "HVGC LINEUP")},
        "to": [{"email": to_address}],
        "subject": subject,
        "textContent": body,
    }
    atts = []
    for filename, data, _maintype, _subtype in (attachments or []):
        if isinstance(data, str):
            data = data.encode("utf-8")
        atts.append({"name": filename, "content": base64.b64encode(data).decode("ascii")})
    if atts:
        payload["attachment"] = atts

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={"api-key": cfg["BREVO_API_KEY"], "content-type": "application/json",
                 "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        current_app.logger.info("Email sent to %s via Brevo: %s", to_address, subject)
        return True
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        current_app.logger.error("Brevo send FAILED to %s: %s %s", to_address, e.code, detail)
        return False
    except Exception as e:  # network problems shouldn't crash the request
        current_app.logger.error("Brevo send FAILED to %s: %s", to_address, e)
        return False


def _send_email_smtp(to_address, subject, body, attachments=None):
    """Send via SMTP (smtplib). Note: many hosts (e.g. Render) block SMTP ports."""
    cfg = current_app.config
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = to_address
    msg.set_content(body)
    for filename, data, maintype, subtype in (attachments or []):
        if isinstance(data, str):
            data = data.encode("utf-8")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    host, port = cfg["SMTP_HOST"], cfg["SMTP_PORT"]
    try:
        # Port 465 = implicit SSL; 587/25 = plain + STARTTLS.
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server as s:
            s.ehlo()
            if port != 465 and cfg.get("SMTP_TLS"):
                s.starttls()
                s.ehlo()
            if cfg.get("SMTP_USER"):
                s.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            s.send_message(msg)
        current_app.logger.info("Email sent to %s: %s", to_address, subject)
        return True
    except Exception as e:  # network/auth problems shouldn't crash registration
        current_app.logger.error("Email send FAILED to %s (%s:%s): %s",
                                 to_address, host, port, e)
        return False

ALLOWED_DOC_EXTENSIONS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "txt", "rtf", "png", "jpg", "jpeg",
}


def allowed_document(filename):
    return "." in filename and \
        filename.rsplit(".", 1)[1].lower() in ALLOWED_DOC_EXTENSIONS


def save_document(file_storage):
    """Read an uploaded document and return (stored_name, original_name, data).

    The bytes are returned so the caller can store them in the database (they
    survive redeploys, unlike files on Render's ephemeral disk). Returns
    (None, None, None) when no usable file was provided. Raises ValueError for a
    disallowed file type so the caller can flash a message.
    """
    if file_storage is None or not file_storage.filename:
        return (None, None, None)
    original = file_storage.filename
    if not allowed_document(original):
        raise ValueError("Unsupported file type.")
    safe = secure_filename(original) or "document"
    stored = f"{uuid.uuid4().hex}_{safe}"
    data = file_storage.read()
    limit_mb = current_app.config.get("MAX_DOC_MB", 5)
    if len(data) > limit_mb * 1024 * 1024:
        raise ValueError(
            f"Document is too large ({len(data) / 1024 / 1024:.1f} MB). "
            f"Please keep it under {limit_mb} MB (compress the PDF or export smaller)."
        )
    return (stored, original, data)


ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}


def save_avatar(file_storage):
    """Process an uploaded photo into a square avatar; return (name, jpeg_bytes).

    Honours EXIF orientation, centre-crops to a square, and resizes to 256px so
    avatars are small and uniform. The JPEG bytes are returned for storage in
    the database. Returns None when no file was provided; raises ValueError on
    an unusable image.
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
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    return (stored, buf.getvalue())


def _ics_escape(s):
    return ((s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n").replace("\r", ""))


def _vevent_lines(uid, summary, service_date, start_time, location, description,
                  duration_min=120):
    """The VEVENT block for one service, with reminders. Floating local time."""
    from datetime import datetime, timedelta
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + stamp]
    if start_time:
        try:
            dt = datetime.strptime(f"{service_date} {start_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            dt = datetime.strptime(service_date, "%Y-%m-%d")
        end = dt + timedelta(minutes=duration_min)
        lines.append("DTSTART:" + dt.strftime("%Y%m%dT%H%M%S"))
        lines.append("DTEND:" + end.strftime("%Y%m%dT%H%M%S"))
    else:
        d = datetime.strptime(service_date, "%Y-%m-%d")
        lines.append("DTSTART;VALUE=DATE:" + d.strftime("%Y%m%d"))
        lines.append("DTEND;VALUE=DATE:" + (d + timedelta(days=1)).strftime("%Y%m%d"))
    lines.append("SUMMARY:" + _ics_escape(summary))
    if location:
        lines.append("LOCATION:" + _ics_escape(location))
    if description:
        lines.append("DESCRIPTION:" + _ics_escape(description))
    for trigger, note in (("-P1D", "Tomorrow you're serving with your ministry team"),
                          ("-PT1H", "You're serving with your ministry team in 1 hour")):
        lines += ["BEGIN:VALARM", "TRIGGER:" + trigger, "ACTION:DISPLAY",
                  "DESCRIPTION:" + _ics_escape(note), "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def _wrap_calendar(vevent_lines):
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HVGC LINEUP//EN",
            "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    return "\r\n".join(head + vevent_lines + ["END:VCALENDAR"]) + "\r\n"


def build_ics(uid, summary, service_date, start_time, location, description,
              duration_min=120):
    """A calendar file containing a single service event with reminders."""
    return _wrap_calendar(_vevent_lines(uid, summary, service_date, start_time,
                                        location, description, duration_min))


def build_ics_feed(events):
    """A calendar file containing many service events (the user's whole schedule).

    events: list of dicts with uid, summary, service_date, start_time, location,
    description."""
    lines = []
    for e in events:
        lines += _vevent_lines(e["uid"], e["summary"], e["service_date"],
                               e.get("start_time"), e.get("location"), e.get("description"))
    return _wrap_calendar(lines)


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


_TEAM_PALETTE = ["#2f80d8", "#2f9e54", "#8a5cd8", "#d9822b", "#159e8e",
                 "#c2479b", "#5b6cff", "#b0613c", "#6f8a3a", "#c79a2e"]


def team_color(team_id):
    """A stable colour for a team, so each ministry team is visually distinct."""
    if not team_id:
        return "#8a93a5"
    return _TEAM_PALETTE[int(team_id) % len(_TEAM_PALETTE)]


def lead_or_admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if not (user["is_admin"] or user["team_lead"]):
            flash("That area is for team leads and administrators.", "danger")
            return redirect(url_for("user.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def can_manage_member(actor, target):
    """Whether ``actor`` may manage ``target``: admins manage anyone; team leads
    manage non-admin members of their own team."""
    if not actor or not target:
        return False
    if actor["is_admin"]:
        return True
    return bool(actor["team_lead"]) and target["team_id"] == actor["team_id"] \
        and not target["is_admin"]


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


def notify(conn, user_id, body, link=None, email=False, subject=None,
           attachments=None, email_extra=None):
    """Queue an in-app notification for a user. Caller commits.

    When ``email`` is set, also send the message to the user's email address
    (used for high-priority events). ``email_extra`` adds an email-only line
    (e.g. a calendar link) and ``attachments`` are passed to send_email. Email
    failures never block the in-app notification.
    """
    conn.execute(
        "INSERT INTO notifications (user_id, body, link, is_read, created_at)"
        " VALUES (?, ?, ?, 0, ?)",
        (user_id, body, link, now_iso()),
    )
    if email:
        row = conn.execute(
            "SELECT name, email, email_opt_in FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row and row["email"] and row["email_opt_in"]:
            url = ""
            if link:
                try:
                    url = request.url_root.rstrip("/") + link
                except RuntimeError:  # no request context (shouldn't happen here)
                    url = link
            message = f"Hi {row['name']},\n\n{body}"
            if email_extra:
                message += f"\n\n{email_extra}"
            if url:
                message += f"\n\nOpen HVGC LINEUP: {url}"
            message += "\n\n— HVGC LINEUP"
            send_email(row["email"], subject or "HVGC LINEUP update", message,
                       attachments=attachments)


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


def assignment_conflicts(conn):
    """Pre-existing data where a user holds more than one role in a service.

    Returned as a list of dicts (service/user/roles). Portable across SQLite and
    Postgres — grouped in Python rather than with GROUP_CONCAT/string_agg.
    """
    rows = conn.execute(
        "SELECT a.service_id, a.user_id, u.name AS user_name,"
        " s.title AS service_title, s.service_date, r.name AS role_name"
        " FROM assignments a"
        " JOIN users u ON u.id = a.user_id"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " ORDER BY a.service_id, u.name, r.name"
    ).fetchall()
    grouped = {}
    for row in rows:
        key = (row["service_id"], row["user_id"])
        g = grouped.setdefault(key, {
            "service_id": row["service_id"], "user_id": row["user_id"],
            "user_name": row["user_name"], "service_title": row["service_title"],
            "service_date": row["service_date"], "roles": [],
        })
        g["roles"].append(row["role_name"])
    return [g for g in grouped.values() if len(g["roles"]) > 1]


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


def notify_assignment(conn, service_id, user_id, role_id):
    """Notify a freshly-assigned user (in-app + email with an .ics invite).

    Shared by the manual assign flow and the auto-scheduler so both send the
    same calendar invite and reminders. Caller commits.
    """
    svc = conn.execute(
        "SELECT title, service_date, start_time, location, notes FROM services WHERE id = ?",
        (service_id,),
    ).fetchone()
    role = conn.execute("SELECT name FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not (svc and role):
        return
    assignment = conn.execute(
        "SELECT id FROM assignments WHERE service_id = ? AND user_id = ? AND role_id = ?",
        (service_id, user_id, role_id),
    ).fetchone()
    if not assignment:
        return
    desc = f"You're serving as {role['name']} for {svc['title']}."
    if svc["notes"]:
        desc += "\n\n" + svc["notes"]
    ics = build_ics(f"assignment-{assignment['id']}@hvgc-lineup",
                    f"Serving: {role['name']} — {svc['title']}",
                    svc["service_date"], svc["start_time"], svc["location"], desc)
    cal_link = url_for("user.service_calendar", service_id=service_id, _external=True)
    notify(conn, user_id,
           f"You're scheduled as {role['name']} for {svc['title']} on "
           f"{svc['service_date']}.", url_for("user.service_detail", service_id=service_id),
           email=True, subject="You've been scheduled — HVGC LINEUP",
           attachments=[("hvgc-service.ics", ics, "text", "calendar")],
           email_extra=("📅 Add this to your calendar — the attached invite includes "
                        f"reminders the day before and an hour before.\nCalendar link: {cal_link}"))


# --------------------------------------------------------------- auto-scheduler

# Ranking of a candidate's availability on the service day. Lower is better;
# people who explicitly marked themselves available are preferred over those
# who simply haven't said anything. "unavailable" people are excluded outright.
_AVAIL_RANK = {"available": 0, None: 1}


def gather_role_candidates(conn, service, role_ids, exclude_user_ids=None):
    """Build the eligible-candidate pool the auto-scheduler chooses from.

    Returns ``{role_id: [candidate, ...]}`` where each candidate is a dict of
    plain facts: ``id, name, availability, note, load``. Only people who are
    *qualified* (hold the role and finished its required training) and *not
    marked unavailable* on the service date are included, so the hard rules —
    trained and available — are enforced before any AI ever sees the data.
    """
    exclude = set(exclude_user_ids or ())
    avail_map = {
        a["user_id"]: a for a in conn.execute(
            "SELECT user_id, status, note FROM availability WHERE day = ?",
            (service["service_date"],),
        ).fetchall()
    }
    # Fairness signal: how many assignments each person already holds overall.
    load_map = {
        row["user_id"]: row["c"] for row in conn.execute(
            "SELECT user_id, COUNT(*) AS c FROM assignments GROUP BY user_id"
        ).fetchall()
    }
    pool = {}
    for role_id in role_ids:
        cands = []
        for u in qualified_users_for_role(conn, role_id):
            if u["id"] in exclude:
                continue
            av = avail_map.get(u["id"])
            status = av["status"] if av else None
            if status == "unavailable":
                continue
            cands.append({
                "id": u["id"], "name": u["name"], "availability": status,
                "note": (av["note"] if av else None),
                "load": load_map.get(u["id"], 0),
            })
        pool[role_id] = cands
    return pool


def _candidate_sort_key(c):
    return (_AVAIL_RANK.get(c["availability"], 1), c["load"], c["name"].lower())


def _rules_pick(pool, role_names):
    """Greedy deterministic assignment. Fills the most-constrained roles first
    (fewest eligible people) so scarce specialists aren't used up on easy roles.
    Returns ``{role_id: user_id}``."""
    chosen = {}
    used = set()
    order = sorted(pool.keys(), key=lambda rid: (len(pool[rid]), role_names.get(rid, "")))
    for role_id in order:
        for c in sorted(pool[role_id], key=_candidate_sort_key):
            if c["id"] not in used:
                chosen[role_id] = c["id"]
                used.add(c["id"])
                break
    return chosen


def _ai_pick(service, pool, role_names):
    """Ask Claude to choose the roster from the pre-filtered pool.

    Returns ``{role_id: user_id}`` on success, or ``None`` on any failure so the
    caller can fall back to the deterministic rules engine. The AI only ever
    picks from the supplied (already trained + available) candidates.
    """
    import json
    import urllib.request

    cfg = current_app.config
    api_key = cfg.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    roles_payload = []
    for role_id, cands in pool.items():
        roles_payload.append({
            "role_id": role_id,
            "role_name": role_names.get(role_id, str(role_id)),
            "candidates": [
                {"user_id": c["id"], "name": c["name"],
                 "availability": c["availability"] or "not marked",
                 "current_load": c["load"],
                 "note": c["note"] or ""}
                for c in cands
            ],
        })
    instructions = (
        "You are scheduling volunteers for a church service. For each role, pick "
        "exactly one user_id from that role's candidate list, or leave it unfilled "
        "if that is the only way to avoid a conflict. Hard rules: (1) never assign "
        "the same person to more than one role; (2) only choose a user_id that "
        "appears in that role's candidate list; (3) prefer people whose availability "
        "is 'available' over 'not marked'; (4) balance the load — favour people with "
        "a lower current_load so serving is shared fairly. Respond with ONLY a JSON "
        "object of the form {\"assignments\": [{\"role_id\": <int>, \"user_id\": <int>}], "
        "\"unfilled\": [<role_id>, ...]}. No prose."
    )
    payload = {
        "service": {"title": service["title"], "date": service["service_date"],
                    "start_time": service["start_time"], "location": service["location"]},
        "roles": roles_payload,
    }
    body = json.dumps({
        "model": cfg.get("AUTOSCHEDULE_MODEL", "claude-sonnet-5"),
        "max_tokens": 1024,
        "messages": [{"role": "user",
                      "content": instructions + "\n\nDATA:\n" + json.dumps(payload)}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(block.get("text", "") for block in data.get("content", [])
                       if block.get("type") == "text").strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        parsed = json.loads(text[start:end + 1])
    except Exception as exc:  # network, auth, quota, malformed JSON — fall back
        current_app.logger.warning("AI auto-schedule failed, using rules: %s", exc)
        return None

    # Validate every pick against the pool; drop anything invalid or duplicated.
    valid_ids = {rid: {c["id"] for c in cands} for rid, cands in pool.items()}
    chosen = {}
    used = set()
    for item in parsed.get("assignments", []):
        try:
            role_id = int(item["role_id"])
            user_id = int(item["user_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if role_id in valid_ids and user_id in valid_ids[role_id] and user_id not in used:
            chosen[role_id] = user_id
            used.add(user_id)
    return chosen


def auto_schedule_plan(conn, service, role_ids, use_ai=False):
    """Produce a proposed roster for ``service`` covering ``role_ids``.

    Returns ``(assignments, unfilled, method)`` where ``assignments`` is a list
    of ``(role_id, user_id)`` pairs, ``unfilled`` is the role_ids no eligible
    person could be found for, and ``method`` is 'ai' or 'rules'. People already
    assigned to this service are excluded so we never double-book. The AI path
    only runs when requested *and* a key is configured, and silently falls back
    to the rules engine on any error.
    """
    already = {
        row["user_id"] for row in conn.execute(
            "SELECT user_id FROM assignments WHERE service_id = ?", (service["id"],)
        ).fetchall()
    }
    role_names = {
        r["id"]: r["name"] for r in conn.execute(
            "SELECT id, name FROM roles"
        ).fetchall()
    }
    pool = gather_role_candidates(conn, service, role_ids, exclude_user_ids=already)

    chosen = None
    method = "rules"
    if use_ai and current_app.config.get("AI_SCHEDULING_ENABLED"):
        chosen = _ai_pick(service, pool, role_names)
        if chosen is not None:
            method = "ai"
    if chosen is None:
        chosen = _rules_pick(pool, role_names)
    else:
        # The AI may leave roles unfilled; top them up with the rules engine so
        # we still fill everything we can, without reusing people it already chose.
        remaining = {rid: [c for c in pool[rid] if c["id"] not in set(chosen.values())]
                     for rid in role_ids if rid not in chosen}
        chosen.update(_rules_pick(remaining, role_names))

    assignments = [(rid, chosen[rid]) for rid in role_ids if rid in chosen]
    unfilled = [rid for rid in role_ids if rid not in chosen]
    return assignments, unfilled, method
