"""Volunteer (user) facing blueprint."""

from datetime import date, timedelta

import os

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    current_app, send_from_directory, abort,
)

from db import get_db, now_iso
from helpers import (
    login_required, current_user, role_training_status, is_qualified, parse_video,
    save_avatar, delete_avatar, avatars_dir,
)

bp = Blueprint("user", __name__)


@bp.route("/")
@login_required
def dashboard():
    user = current_user()
    conn = get_db()
    today = date.today().isoformat()

    upcoming = conn.execute(
        "SELECT a.*, s.title AS service_title, s.service_date, s.start_time, s.location,"
        " r.name AS role_name"
        " FROM assignments a"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " WHERE a.user_id = ? AND s.service_date >= ?"
        " ORDER BY s.service_date, s.start_time",
        (user["id"], today),
    ).fetchall()

    # Outstanding required trainings the user has been assigned but not finished.
    pending_training = conn.execute(
        "SELECT ut.*, t.title, t.role_id, r.name AS role_name"
        " FROM user_training ut"
        " JOIN trainings t ON t.id = ut.training_id"
        " LEFT JOIN roles r ON r.id = t.role_id"
        " WHERE ut.user_id = ? AND ut.status != 'completed'"
        " ORDER BY t.title",
        (user["id"],),
    ).fetchall()

    open_swaps = conn.execute(
        "SELECT sw.*, a.role_id, s.title AS service_title, s.service_date,"
        " r.name AS role_name, u.name AS requester_name"
        " FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " JOIN users u ON u.id = sw.requested_by"
        " WHERE sw.status = 'open' AND sw.requested_by != ?"
        " ORDER BY s.service_date",
        (user["id"],),
    ).fetchall()
    # Only show swaps the user is actually qualified to cover.
    coverable = [sw for sw in open_swaps if is_qualified(conn, user["id"], sw["role_id"])]

    # Role qualification snapshot.
    roles = conn.execute(
        "SELECT r.* FROM roles r JOIN user_roles ur ON ur.role_id = r.id"
        " WHERE ur.user_id = ? ORDER BY r.name",
        (user["id"],),
    ).fetchall()
    role_status = []
    for r in roles:
        req, done = role_training_status(conn, user["id"], r["id"])
        role_status.append({"role": r, "required": req, "completed": done,
                            "qualified": done >= req})

    conn.close()
    return render_template(
        "dashboard.html",
        upcoming=upcoming,
        pending_training=pending_training,
        coverable=coverable,
        role_status=role_status,
    )


# ----------------------------------------------------------------- availability
@bp.route("/availability", methods=["GET", "POST"])
@login_required
def availability():
    user = current_user()
    conn = get_db()

    if request.method == "POST":
        status = request.form.get("status", "available")
        if status not in ("available", "unavailable"):
            status = "available"
        note = request.form.get("note", "").strip()
        start_raw = request.form.get("start", "").strip()
        end_raw = request.form.get("end", "").strip()

        # Build the list of days to mark: a single day (end omitted/equal) or an
        # inclusive date range.
        days = []
        try:
            start = date.fromisoformat(start_raw) if start_raw else None
        except ValueError:
            start = None
        try:
            end = date.fromisoformat(end_raw) if end_raw else None
        except ValueError:
            end = None

        if start and end and end < start:
            flash("End date can't be before the start date.", "danger")
        elif start:
            end = end or start
            span = (end - start).days
            if span > 366:
                flash("Please choose a range of one year or less.", "danger")
            else:
                d = start
                while d <= end:
                    days.append(d.isoformat())
                    d += timedelta(days=1)
        else:
            flash("Please pick a start date.", "danger")

        if days:
            label = "available" if status == "available" else "unavailable"
            for day in days:
                conn.execute(
                    "INSERT INTO availability (user_id, day, status, note) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (user_id, day) DO UPDATE SET status=excluded.status, note=excluded.note",
                    (user["id"], day, status, note),
                )
            conn.commit()
            if len(days) == 1:
                flash(f"Marked {days[0]} as {label}.", "success")
            else:
                flash(f"Marked {len(days)} days ({days[0]} → {days[-1]}) as {label}.", "success")
        conn.close()
        return redirect(url_for("user.availability"))

    today = date.today().isoformat()
    entries = conn.execute(
        "SELECT * FROM availability WHERE user_id = ? AND day >= ? ORDER BY day",
        (user["id"], today),
    ).fetchall()

    # Quick-pick: list the next 8 Sundays for one-click marking.
    sundays = []
    d = date.today()
    d += timedelta(days=(6 - d.weekday()) % 7)
    existing_days = {e["day"] for e in entries}
    for _ in range(8):
        sundays.append({"day": d.isoformat(), "marked": d.isoformat() in existing_days})
        d += timedelta(days=7)

    conn.close()
    return render_template("availability.html", entries=entries, sundays=sundays,
                           today=today)


@bp.route("/availability/<int:entry_id>/delete", methods=["POST"])
@login_required
def delete_availability(entry_id):
    user = current_user()
    conn = get_db()
    conn.execute(
        "DELETE FROM availability WHERE id = ? AND user_id = ?", (entry_id, user["id"])
    )
    conn.commit()
    conn.close()
    flash("Availability entry removed.", "info")
    return redirect(url_for("user.availability"))


# ---------------------------------------------------------------------- services
@bp.route("/services")
@login_required
def services():
    conn = get_db()
    today = date.today().isoformat()
    upcoming = conn.execute(
        "SELECT * FROM services WHERE service_date >= ? ORDER BY service_date, start_time",
        (today,),
    ).fetchall()
    past = conn.execute(
        "SELECT * FROM services WHERE service_date < ? ORDER BY service_date DESC, start_time"
        " LIMIT 20",
        (today,),
    ).fetchall()
    conn.close()
    return render_template("services.html", upcoming=upcoming, past=past, today=today)


@bp.route("/services/<int:service_id>")
@login_required
def service_detail(service_id):
    user = current_user()
    conn = get_db()
    service = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    if service is None:
        conn.close()
        flash("Service not found.", "danger")
        return redirect(url_for("user.services"))

    roster = conn.execute(
        "SELECT a.*, u.name AS user_name, r.name AS role_name"
        " FROM assignments a"
        " JOIN users u ON u.id = a.user_id"
        " JOIN roles r ON r.id = a.role_id"
        " WHERE a.service_id = ? ORDER BY r.name",
        (service_id,),
    ).fetchall()

    my_assignments = [a for a in roster if a["user_id"] == user["id"]]

    # Open swap requests on this service (for context).
    swaps = conn.execute(
        "SELECT sw.*, u.name AS requester_name, r.name AS role_name"
        " FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id"
        " JOIN users u ON u.id = sw.requested_by"
        " JOIN roles r ON r.id = a.role_id"
        " WHERE a.service_id = ? AND sw.status IN ('open','volunteered')",
        (service_id,),
    ).fetchall()

    notes = conn.execute(
        "SELECT n.*, u.name AS author FROM service_notes n"
        " JOIN users u ON u.id = n.user_id"
        " WHERE n.service_id = ? ORDER BY n.created_at DESC",
        (service_id,),
    ).fetchall()

    conn.close()
    return render_template(
        "service_detail.html", service=service, roster=roster,
        my_assignments=my_assignments, swaps=swaps, notes=notes,
    )


@bp.route("/services/<int:service_id>/document")
@login_required
def service_document(service_id):
    conn = get_db()
    svc = conn.execute(
        "SELECT doc_filename, doc_original FROM services WHERE id = ?", (service_id,)
    ).fetchone()
    conn.close()
    if not svc or not svc["doc_filename"]:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_PATH"], svc["doc_filename"],
        as_attachment=False, download_name=svc["doc_original"],
    )


@bp.route("/services/<int:service_id>/note", methods=["POST"])
@login_required
def add_note(service_id):
    user = current_user()
    body = request.form.get("body", "").strip()
    if body:
        conn = get_db()
        conn.execute(
            "INSERT INTO service_notes (service_id, user_id, body, created_at)"
            " VALUES (?, ?, ?, ?)",
            (service_id, user["id"], body, now_iso()),
        )
        conn.commit()
        conn.close()
        flash("Note added.", "success")
    return redirect(url_for("user.service_detail", service_id=service_id))


@bp.route("/services/<int:service_id>/note/<int:note_id>/delete", methods=["POST"])
@login_required
def delete_note(service_id, note_id):
    user = current_user()
    conn = get_db()
    conn.execute(
        "DELETE FROM service_notes WHERE id = ? AND user_id = ?", (note_id, user["id"])
    )
    conn.commit()
    conn.close()
    return redirect(url_for("user.service_detail", service_id=service_id))


@bp.route("/assignments/<int:assignment_id>/respond", methods=["POST"])
@login_required
def respond_assignment(assignment_id):
    """Confirm or decline an assignment you've been scheduled for."""
    user = current_user()
    decision = request.form.get("decision")
    conn = get_db()
    a = conn.execute(
        "SELECT * FROM assignments WHERE id = ? AND user_id = ?",
        (assignment_id, user["id"]),
    ).fetchone()
    if a and decision in ("confirmed", "declined"):
        conn.execute(
            "UPDATE assignments SET status = ? WHERE id = ?", (decision, assignment_id)
        )
        conn.commit()
        flash(f"Assignment {decision}.", "success")
    service_id = a["service_id"] if a else None
    conn.close()
    if service_id:
        return redirect(url_for("user.service_detail", service_id=service_id))
    return redirect(url_for("user.dashboard"))


# ------------------------------------------------------------------------- swaps
@bp.route("/swaps")
@login_required
def swaps():
    user = current_user()
    conn = get_db()

    my_requests = conn.execute(
        "SELECT sw.*, s.title AS service_title, s.service_date, r.name AS role_name,"
        " cov.name AS covered_name"
        " FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " LEFT JOIN users cov ON cov.id = sw.covered_by"
        " WHERE sw.requested_by = ? ORDER BY sw.created_at DESC",
        (user["id"],),
    ).fetchall()

    open_all = conn.execute(
        "SELECT sw.*, a.role_id, s.title AS service_title, s.service_date,"
        " r.name AS role_name, u.name AS requester_name"
        " FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " JOIN users u ON u.id = sw.requested_by"
        " WHERE sw.status = 'open' AND sw.requested_by != ?"
        " ORDER BY s.service_date",
        (user["id"],),
    ).fetchall()
    coverable = [sw for sw in open_all if is_qualified(conn, user["id"], sw["role_id"])]

    conn.close()
    return render_template("swaps.html", my_requests=my_requests, coverable=coverable)


@bp.route("/assignments/<int:assignment_id>/swap", methods=["POST"])
@login_required
def request_swap(assignment_id):
    user = current_user()
    reason = request.form.get("reason", "").strip()
    conn = get_db()
    a = conn.execute(
        "SELECT * FROM assignments WHERE id = ? AND user_id = ?",
        (assignment_id, user["id"]),
    ).fetchone()
    if a is None:
        conn.close()
        flash("Assignment not found.", "danger")
        return redirect(url_for("user.dashboard"))
    existing = conn.execute(
        "SELECT id FROM swap_requests WHERE assignment_id = ? AND status IN ('open','volunteered')",
        (assignment_id,),
    ).fetchone()
    if existing:
        flash("A swap request is already open for that assignment.", "warning")
    else:
        conn.execute(
            "INSERT INTO swap_requests (assignment_id, requested_by, reason, status, created_at)"
            " VALUES (?, ?, ?, 'open', ?)",
            (assignment_id, user["id"], reason, now_iso()),
        )
        conn.commit()
        flash("Swap request posted. Qualified teammates can now volunteer.", "success")
    service_id = a["service_id"]
    conn.close()
    return redirect(url_for("user.service_detail", service_id=service_id))


@bp.route("/swaps/<int:swap_id>/volunteer", methods=["POST"])
@login_required
def volunteer_swap(swap_id):
    user = current_user()
    conn = get_db()
    sw = conn.execute(
        "SELECT sw.*, a.role_id FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id WHERE sw.id = ?",
        (swap_id,),
    ).fetchone()
    if sw is None or sw["status"] != "open":
        conn.close()
        flash("That swap is no longer available.", "warning")
        return redirect(url_for("user.swaps"))
    if not is_qualified(conn, user["id"], sw["role_id"]):
        conn.close()
        flash("You are not qualified for that role yet.", "danger")
        return redirect(url_for("user.swaps"))
    conn.execute(
        "UPDATE swap_requests SET covered_by = ?, status = 'volunteered' WHERE id = ?",
        (user["id"], swap_id),
    )
    conn.commit()
    conn.close()
    flash("Thanks for volunteering! An admin will confirm the swap.", "success")
    return redirect(url_for("user.swaps"))


@bp.route("/swaps/<int:swap_id>/cancel", methods=["POST"])
@login_required
def cancel_swap(swap_id):
    user = current_user()
    conn = get_db()
    conn.execute(
        "UPDATE swap_requests SET status = 'cancelled', resolved_at = ?"
        " WHERE id = ? AND requested_by = ? AND status IN ('open','volunteered')",
        (now_iso(), swap_id, user["id"]),
    )
    conn.commit()
    conn.close()
    flash("Swap request cancelled.", "info")
    return redirect(url_for("user.swaps"))


# --------------------------------------------------------------------- trainings
@bp.route("/trainings")
@login_required
def trainings():
    user = current_user()
    conn = get_db()
    assigned = conn.execute(
        "SELECT ut.*, t.title, t.description, t.role_id, r.name AS role_name"
        " FROM user_training ut"
        " JOIN trainings t ON t.id = ut.training_id"
        " LEFT JOIN roles r ON r.id = t.role_id"
        " WHERE ut.user_id = ? ORDER BY ut.status, t.title",
        (user["id"],),
    ).fetchall()
    conn.close()
    return render_template("trainings.html", assigned=assigned)


@bp.route("/trainings/<int:training_id>")
@login_required
def training_detail(training_id):
    user = current_user()
    conn = get_db()
    row = conn.execute(
        "SELECT ut.*, t.title, t.description, t.content, t.video_url, t.role_id,"
        " r.name AS role_name"
        " FROM user_training ut"
        " JOIN trainings t ON t.id = ut.training_id"
        " LEFT JOIN roles r ON r.id = t.role_id"
        " WHERE ut.user_id = ? AND ut.training_id = ?",
        (user["id"], training_id),
    ).fetchone()
    conn.close()
    if row is None:
        flash("That training has not been assigned to you.", "warning")
        return redirect(url_for("user.trainings"))
    video = parse_video(row["video_url"])
    return render_template("training_detail.html", t=row, video=video)


@bp.route("/trainings/<int:training_id>/complete", methods=["POST"])
@login_required
def complete_training(training_id):
    user = current_user()
    conn = get_db()
    conn.execute(
        "UPDATE user_training SET status = 'completed', completed_at = ?"
        " WHERE user_id = ? AND training_id = ?",
        (now_iso(), user["id"], training_id),
    )
    conn.commit()
    conn.close()
    flash("Training marked complete. Nice work!", "success")
    return redirect(url_for("user.trainings"))


# ----------------------------------------------------------------------- profile
@bp.route("/users/<int:user_id>/avatar")
@login_required
def user_avatar(user_id):
    conn = get_db()
    row = conn.execute("SELECT avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not row or not row["avatar"]:
        abort(404)
    return send_from_directory(avatars_dir(), row["avatar"], max_age=300)


@bp.route("/manual")
@login_required
def manual():
    pdf_exists = os.path.exists(
        os.path.join(current_app.root_path, "MANUAL.pdf")
    )
    return render_template("manual.html", pdf_exists=pdf_exists)


@bp.route("/manual/pdf")
@login_required
def manual_pdf():
    pdf_path = os.path.join(current_app.root_path, "MANUAL.pdf")
    if not os.path.exists(pdf_path):
        abort(404)
    return send_from_directory(
        current_app.root_path, "MANUAL.pdf",
        as_attachment=True, download_name="HVGC-LINEUP-Manual.pdf",
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    conn = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        if name:
            conn.execute(
                "UPDATE users SET name = ?, phone = ? WHERE id = ?",
                (name, phone, user["id"]),
            )

        # Remove existing avatar if requested.
        if request.form.get("remove_avatar") == "1":
            delete_avatar(user["avatar"])
            conn.execute("UPDATE users SET avatar = NULL WHERE id = ?", (user["id"],))

        # Handle a newly uploaded avatar photo.
        try:
            new_avatar = save_avatar(request.files.get("avatar"))
        except ValueError as ex:
            conn.commit()
            conn.close()
            flash(str(ex), "danger")
            return redirect(url_for("user.profile"))
        if new_avatar:
            delete_avatar(user["avatar"])
            conn.execute(
                "UPDATE users SET avatar = ? WHERE id = ?", (new_avatar, user["id"])
            )

        conn.commit()
        conn.close()
        flash("Profile updated.", "success")
        return redirect(url_for("user.profile"))

    roles = conn.execute(
        "SELECT r.* FROM roles r JOIN user_roles ur ON ur.role_id = r.id"
        " WHERE ur.user_id = ? ORDER BY r.name",
        (user["id"],),
    ).fetchall()
    role_status = []
    for r in roles:
        req, done = role_training_status(conn, user["id"], r["id"])
        role_status.append({"role": r, "required": req, "completed": done,
                            "qualified": done >= req})
    conn.close()
    return render_template("profile.html", role_status=role_status)
