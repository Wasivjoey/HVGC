"""Administrator blueprint: manage users, roles, trainings, services,
scheduling, and swap approvals."""

from datetime import date

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)

from db import get_db, now_iso
from helpers import (
    admin_required, current_user, role_training_status, is_qualified,
    qualified_users_for_role, save_document, delete_document,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
@admin_required
def dashboard():
    conn = get_db()
    today = date.today().isoformat()
    stats = {
        "users": conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
        "roles": conn.execute("SELECT COUNT(*) AS c FROM roles").fetchone()["c"],
        "trainings": conn.execute("SELECT COUNT(*) AS c FROM trainings").fetchone()["c"],
        "upcoming": conn.execute(
            "SELECT COUNT(*) AS c FROM services WHERE service_date >= ?", (today,)
        ).fetchone()["c"],
        "open_swaps": conn.execute(
            "SELECT COUNT(*) AS c FROM swap_requests WHERE status IN ('open','volunteered')"
        ).fetchone()["c"],
        "pending_training": conn.execute(
            "SELECT COUNT(*) AS c FROM user_training WHERE status != 'completed'"
        ).fetchone()["c"],
        "pending_approvals": conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE approved = 0"
        ).fetchone()["c"],
    }
    pending = conn.execute(
        "SELECT * FROM users WHERE approved = 0 ORDER BY created_at DESC"
    ).fetchall()
    upcoming = conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM assignments a WHERE a.service_id = s.id) AS slots"
        " FROM services s WHERE s.service_date >= ? ORDER BY s.service_date, s.start_time"
        " LIMIT 6",
        (today,),
    ).fetchall()
    swaps = conn.execute(
        "SELECT sw.*, u.name AS requester_name, cov.name AS covered_name,"
        " s.title AS service_title, s.service_date, r.name AS role_name"
        " FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " JOIN users u ON u.id = sw.requested_by"
        " LEFT JOIN users cov ON cov.id = sw.covered_by"
        " WHERE sw.status IN ('open','volunteered') ORDER BY sw.created_at DESC",
    ).fetchall()
    conn.close()
    return render_template("admin/dashboard.html", stats=stats, upcoming=upcoming,
                           swaps=swaps, pending=pending)


# ------------------------------------------------------------------------- users
@bp.route("/users")
@admin_required
def users():
    conn = get_db()
    rows = conn.execute("SELECT * FROM users ORDER BY is_admin DESC, name").fetchall()
    people = []
    for u in rows:
        role_count = conn.execute(
            "SELECT COUNT(*) AS c FROM user_roles WHERE user_id = ?", (u["id"],)
        ).fetchone()["c"]
        people.append({"u": u, "roles": role_count})
    conn.close()
    return render_template("admin/users.html", people=people)


@bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if u is None:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))

    all_roles = conn.execute("SELECT * FROM roles ORDER BY name").fetchall()
    assigned_role_ids = {
        r["role_id"] for r in conn.execute(
            "SELECT role_id FROM user_roles WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    role_view = []
    for r in all_roles:
        if r["id"] in assigned_role_ids:
            req, done = role_training_status(conn, user_id, r["id"])
            role_view.append({"role": r, "assigned": True, "required": req,
                              "completed": done, "qualified": done >= req})
        else:
            role_view.append({"role": r, "assigned": False})

    all_trainings = conn.execute(
        "SELECT t.*, r.name AS role_name FROM trainings t"
        " LEFT JOIN roles r ON r.id = t.role_id ORDER BY t.title"
    ).fetchall()
    user_training = {
        ut["training_id"]: ut for ut in conn.execute(
            "SELECT * FROM user_training WHERE user_id = ?", (user_id,)
        ).fetchall()
    }
    training_view = []
    for t in all_trainings:
        ut = user_training.get(t["id"])
        training_view.append({
            "t": t,
            "assigned": ut is not None,
            "status": ut["status"] if ut else None,
        })

    conn.close()
    return render_template(
        "admin/user_detail.html", u=u, role_view=role_view, training_view=training_view,
    )


@bp.route("/users/<int:user_id>/roles", methods=["POST"])
@admin_required
def update_user_roles(user_id):
    conn = get_db()
    role_id = int(request.form.get("role_id"))
    action = request.form.get("action")
    if action == "assign":
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, assigned_at)"
            " VALUES (?, ?, ?)",
            (user_id, role_id, now_iso()),
        )
        # Auto-assign the role's required trainings so the volunteer knows what
        # they must complete before serving.
        reqs = conn.execute(
            "SELECT id FROM trainings WHERE role_id = ? AND required = 1", (role_id,)
        ).fetchall()
        for t in reqs:
            conn.execute(
                "INSERT OR IGNORE INTO user_training (user_id, training_id, status, assigned_at)"
                " VALUES (?, ?, 'assigned', ?)",
                (user_id, t["id"], now_iso()),
            )
        flash("Role assigned and required training queued.", "success")
    elif action == "remove":
        conn.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id)
        )
        flash("Role removed.", "info")
    conn.commit()
    conn.close()
    return redirect(url_for("admin.user_detail", user_id=user_id))


@bp.route("/users/<int:user_id>/training", methods=["POST"])
@admin_required
def update_user_training(user_id):
    conn = get_db()
    training_id = int(request.form.get("training_id"))
    action = request.form.get("action")
    if action == "assign":
        conn.execute(
            "INSERT OR IGNORE INTO user_training (user_id, training_id, status, assigned_at)"
            " VALUES (?, ?, 'assigned', ?)",
            (user_id, training_id, now_iso()),
        )
        flash("Training assigned.", "success")
    elif action == "complete":
        conn.execute(
            "UPDATE user_training SET status = 'completed', completed_at = ?"
            " WHERE user_id = ? AND training_id = ?",
            (now_iso(), user_id, training_id),
        )
        flash("Training marked complete.", "success")
    elif action == "reset":
        conn.execute(
            "UPDATE user_training SET status = 'assigned', completed_at = NULL"
            " WHERE user_id = ? AND training_id = ?",
            (user_id, training_id),
        )
        flash("Training reset to incomplete.", "info")
    elif action == "remove":
        conn.execute(
            "DELETE FROM user_training WHERE user_id = ? AND training_id = ?",
            (user_id, training_id),
        )
        flash("Training unassigned.", "info")
    conn.commit()
    conn.close()
    return redirect(url_for("admin.user_detail", user_id=user_id))


@bp.route("/users/<int:user_id>/approve", methods=["POST"])
@admin_required
def quick_approve(user_id):
    conn = get_db()
    conn.execute("UPDATE users SET approved = 1, is_active = 1 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash("Account approved.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.route("/users/<int:user_id>/flags", methods=["POST"])
@admin_required
def update_user_flags(user_id):
    me = current_user()
    conn = get_db()
    action = request.form.get("action")
    if user_id == me["id"] and action in ("revoke_admin", "deactivate", "unapprove"):
        flash("You cannot change your own admin/approval/active status.", "warning")
    elif action == "make_admin":
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
        flash("User promoted to administrator.", "success")
    elif action == "revoke_admin":
        conn.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (user_id,))
        flash("Administrator rights revoked.", "info")
    elif action == "approve":
        conn.execute("UPDATE users SET approved = 1, is_active = 1 WHERE id = ?", (user_id,))
        flash("Account approved — the user can now sign in (after verifying email).",
              "success")
    elif action == "unapprove":
        conn.execute("UPDATE users SET approved = 0 WHERE id = ?", (user_id,))
        flash("Approval revoked.", "info")
    elif action == "verify_email":
        conn.execute(
            "UPDATE users SET email_verified = 1, verify_token = NULL WHERE id = ?",
            (user_id,),
        )
        flash("Email manually marked as verified.", "success")
    elif action == "activate":
        conn.execute("UPDATE users SET is_active = 1 WHERE id = ?", (user_id,))
        flash("User reactivated.", "success")
    elif action == "deactivate":
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        flash("User deactivated.", "info")
    conn.commit()
    conn.close()
    return redirect(url_for("admin.user_detail", user_id=user_id))


# ------------------------------------------------------------------------- roles
@bp.route("/roles", methods=["GET", "POST"])
@admin_required
def roles():
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if name:
            try:
                conn.execute(
                    "INSERT INTO roles (name, description) VALUES (?, ?)", (name, description)
                )
                conn.commit()
                flash("Role created.", "success")
            except Exception:
                flash("A role with that name already exists.", "danger")
        conn.close()
        return redirect(url_for("admin.roles"))

    rows = conn.execute("SELECT * FROM roles ORDER BY name").fetchall()
    role_view = []
    for r in rows:
        people = conn.execute(
            "SELECT COUNT(*) AS c FROM user_roles WHERE role_id = ?", (r["id"],)
        ).fetchone()["c"]
        qualified = len(qualified_users_for_role(conn, r["id"]))
        role_view.append({"r": r, "people": people, "qualified": qualified})
    conn.close()
    return render_template("admin/roles.html", role_view=role_view)


@bp.route("/roles/<int:role_id>/edit", methods=["POST"])
@admin_required
def edit_role(role_id):
    conn = get_db()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if name:
        conn.execute(
            "UPDATE roles SET name = ?, description = ? WHERE id = ?",
            (name, description, role_id),
        )
        conn.commit()
        flash("Role updated.", "success")
    conn.close()
    return redirect(url_for("admin.roles"))


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@admin_required
def delete_role(role_id):
    conn = get_db()
    conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
    conn.commit()
    conn.close()
    flash("Role deleted.", "info")
    return redirect(url_for("admin.roles"))


# --------------------------------------------------------------------- trainings
@bp.route("/trainings", methods=["GET", "POST"])
@admin_required
def trainings():
    conn = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        content = request.form.get("content", "").strip()
        video_url = request.form.get("video_url", "").strip()
        role_id = request.form.get("role_id") or None
        required = 1 if request.form.get("required") == "on" else 0
        if title:
            conn.execute(
                "INSERT INTO trainings (title, description, content, video_url, role_id, required, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, description, content, video_url, role_id, required, now_iso()),
            )
            conn.commit()
            flash("Training created.", "success")
        conn.close()
        return redirect(url_for("admin.trainings"))

    rows = conn.execute(
        "SELECT t.*, r.name AS role_name FROM trainings t"
        " LEFT JOIN roles r ON r.id = t.role_id ORDER BY t.title"
    ).fetchall()
    training_view = []
    for t in rows:
        done = conn.execute(
            "SELECT COUNT(*) AS c FROM user_training WHERE training_id = ? AND status = 'completed'",
            (t["id"],),
        ).fetchone()["c"]
        assigned = conn.execute(
            "SELECT COUNT(*) AS c FROM user_training WHERE training_id = ?", (t["id"],)
        ).fetchone()["c"]
        training_view.append({"t": t, "done": done, "assigned": assigned})
    all_roles = conn.execute("SELECT * FROM roles ORDER BY name").fetchall()
    conn.close()
    return render_template("admin/trainings.html", training_view=training_view, roles=all_roles)


@bp.route("/trainings/<int:training_id>/edit", methods=["POST"])
@admin_required
def edit_training(training_id):
    conn = get_db()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    content = request.form.get("content", "").strip()
    video_url = request.form.get("video_url", "").strip()
    role_id = request.form.get("role_id") or None
    required = 1 if request.form.get("required") == "on" else 0
    if title:
        conn.execute(
            "UPDATE trainings SET title = ?, description = ?, content = ?, video_url = ?,"
            " role_id = ?, required = ? WHERE id = ?",
            (title, description, content, video_url, role_id, required, training_id),
        )
        conn.commit()
        flash("Training updated.", "success")
    conn.close()
    return redirect(url_for("admin.trainings"))


@bp.route("/trainings/<int:training_id>/delete", methods=["POST"])
@admin_required
def delete_training(training_id):
    conn = get_db()
    conn.execute("DELETE FROM trainings WHERE id = ?", (training_id,))
    conn.commit()
    conn.close()
    flash("Training deleted.", "info")
    return redirect(url_for("admin.trainings"))


# ---------------------------------------------------------------------- services
@bp.route("/services", methods=["GET", "POST"])
@admin_required
def services():
    conn = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        service_date = request.form.get("service_date", "").strip()
        start_time = request.form.get("start_time", "").strip()
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()
        if title and service_date:
            try:
                stored, original = save_document(request.files.get("document"))
            except ValueError as e:
                flash(str(e), "danger")
                conn.close()
                return redirect(url_for("admin.services"))
            conn.execute(
                "INSERT INTO services (title, service_date, start_time, location, notes,"
                " doc_filename, doc_original, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, service_date, start_time, location, notes, stored, original, now_iso()),
            )
            conn.commit()
            flash("Service created.", "success")
        else:
            flash("Title and date are required.", "danger")
        conn.close()
        return redirect(url_for("admin.services"))

    today = date.today().isoformat()
    upcoming = conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM assignments a WHERE a.service_id = s.id) AS slots"
        " FROM services s WHERE s.service_date >= ? ORDER BY s.service_date, s.start_time",
        (today,),
    ).fetchall()
    past = conn.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM assignments a WHERE a.service_id = s.id) AS slots"
        " FROM services s WHERE s.service_date < ? ORDER BY s.service_date DESC LIMIT 15",
        (today,),
    ).fetchall()
    conn.close()
    return render_template("admin/services.html", upcoming=upcoming, past=past, today=today)


@bp.route("/services/<int:service_id>/edit", methods=["POST"])
@admin_required
def edit_service(service_id):
    conn = get_db()
    svc = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    title = request.form.get("title", "").strip()
    service_date = request.form.get("service_date", "").strip()
    start_time = request.form.get("start_time", "").strip()
    location = request.form.get("location", "").strip()
    notes = request.form.get("notes", "").strip()
    if svc and title and service_date:
        conn.execute(
            "UPDATE services SET title = ?, service_date = ?, start_time = ?, location = ?,"
            " notes = ? WHERE id = ?",
            (title, service_date, start_time, location, notes, service_id),
        )
        # Optionally replace the programme-flow document.
        try:
            stored, original = save_document(request.files.get("document"))
        except ValueError as e:
            conn.commit()
            conn.close()
            flash(str(e), "danger")
            return redirect(url_for("admin.schedule", service_id=service_id))
        if stored:
            delete_document(svc["doc_filename"])
            conn.execute(
                "UPDATE services SET doc_filename = ?, doc_original = ? WHERE id = ?",
                (stored, original, service_id),
            )
        conn.commit()
        flash("Service updated.", "success")
    conn.close()
    return redirect(url_for("admin.schedule", service_id=service_id))


@bp.route("/services/<int:service_id>/document/remove", methods=["POST"])
@admin_required
def remove_service_document(service_id):
    conn = get_db()
    svc = conn.execute("SELECT doc_filename FROM services WHERE id = ?", (service_id,)).fetchone()
    if svc:
        delete_document(svc["doc_filename"])
        conn.execute(
            "UPDATE services SET doc_filename = NULL, doc_original = NULL WHERE id = ?",
            (service_id,),
        )
        conn.commit()
        flash("Programme document removed.", "info")
    conn.close()
    return redirect(url_for("admin.schedule", service_id=service_id))


@bp.route("/services/<int:service_id>/delete", methods=["POST"])
@admin_required
def delete_service(service_id):
    conn = get_db()
    svc = conn.execute("SELECT doc_filename FROM services WHERE id = ?", (service_id,)).fetchone()
    if svc:
        delete_document(svc["doc_filename"])
    conn.execute("DELETE FROM services WHERE id = ?", (service_id,))
    conn.commit()
    conn.close()
    flash("Service deleted.", "info")
    return redirect(url_for("admin.services"))


@bp.route("/services/<int:service_id>/schedule")
@admin_required
def schedule(service_id):
    """The scheduling board for one service: assign qualified, available people
    to each role."""
    conn = get_db()
    service = conn.execute("SELECT * FROM services WHERE id = ?", (service_id,)).fetchone()
    if service is None:
        conn.close()
        flash("Service not found.", "danger")
        return redirect(url_for("admin.services"))

    roster = conn.execute(
        "SELECT a.*, u.name AS user_name, r.name AS role_name"
        " FROM assignments a"
        " JOIN users u ON u.id = a.user_id"
        " JOIN roles r ON r.id = a.role_id"
        " WHERE a.service_id = ? ORDER BY r.name, u.name",
        (service_id,),
    ).fetchall()
    assigned_pairs = {(a["user_id"], a["role_id"]) for a in roster}

    # For each role, list candidates and tag whether they're qualified and
    # available on the service date.
    avail_map = {
        a["user_id"]: a for a in conn.execute(
            "SELECT user_id, status, note FROM availability WHERE day = ?",
            (service["service_date"],),
        ).fetchall()
    }
    roles = conn.execute("SELECT * FROM roles ORDER BY name").fetchall()
    role_board = []
    for r in roles:
        candidates = conn.execute(
            "SELECT u.* FROM users u JOIN user_roles ur ON ur.user_id = u.id"
            " WHERE ur.role_id = ? AND u.is_active = 1 ORDER BY u.name",
            (r["id"],),
        ).fetchall()
        cand_view = []
        for c in candidates:
            av = avail_map.get(c["id"])
            cand_view.append({
                "u": c,
                "qualified": is_qualified(conn, c["id"], r["id"]),
                "availability": av["status"] if av else None,
                "already": (c["id"], r["id"]) in assigned_pairs,
            })
        role_board.append({"role": r, "candidates": cand_view})

    conn.close()
    return render_template(
        "admin/schedule.html", service=service, roster=roster, role_board=role_board,
    )


@bp.route("/services/<int:service_id>/assign", methods=["POST"])
@admin_required
def assign(service_id):
    conn = get_db()
    user_id = int(request.form.get("user_id"))
    role_id = int(request.form.get("role_id"))
    force = request.form.get("force") == "1"

    if not force and not is_qualified(conn, user_id, role_id):
        conn.close()
        flash("That person is not qualified for this role yet (training incomplete).",
              "warning")
        return redirect(url_for("admin.schedule", service_id=service_id))

    conn.execute(
        "INSERT OR IGNORE INTO assignments (service_id, user_id, role_id, status, created_at)"
        " VALUES (?, ?, ?, 'scheduled', ?)",
        (service_id, user_id, role_id, now_iso()),
    )
    conn.commit()
    conn.close()
    flash("Assigned.", "success")
    return redirect(url_for("admin.schedule", service_id=service_id))


@bp.route("/assignments/<int:assignment_id>/unassign", methods=["POST"])
@admin_required
def unassign(assignment_id):
    conn = get_db()
    a = conn.execute("SELECT service_id FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    conn.commit()
    service_id = a["service_id"] if a else None
    conn.close()
    flash("Removed from schedule.", "info")
    if service_id:
        return redirect(url_for("admin.schedule", service_id=service_id))
    return redirect(url_for("admin.services"))


# ------------------------------------------------------------------------- swaps
@bp.route("/swaps")
@admin_required
def swaps():
    conn = get_db()
    rows = conn.execute(
        "SELECT sw.*, u.name AS requester_name, cov.name AS covered_name,"
        " s.title AS service_title, s.service_date, r.name AS role_name, a.role_id"
        " FROM swap_requests sw"
        " JOIN assignments a ON a.id = sw.assignment_id"
        " JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id"
        " JOIN users u ON u.id = sw.requested_by"
        " LEFT JOIN users cov ON cov.id = sw.covered_by"
        " ORDER BY CASE sw.status WHEN 'volunteered' THEN 0 WHEN 'open' THEN 1 ELSE 2 END,"
        " sw.created_at DESC",
    ).fetchall()
    conn.close()
    return render_template("admin/swaps.html", swaps=rows)


@bp.route("/swaps/<int:swap_id>/approve", methods=["POST"])
@admin_required
def approve_swap(swap_id):
    conn = get_db()
    sw = conn.execute("SELECT * FROM swap_requests WHERE id = ?", (swap_id,)).fetchone()
    if sw is None or sw["status"] != "volunteered" or sw["covered_by"] is None:
        conn.close()
        flash("This swap has no volunteer to approve yet.", "warning")
        return redirect(url_for("admin.swaps"))
    # Reassign the underlying slot to the volunteer.
    conn.execute(
        "UPDATE assignments SET user_id = ?, status = 'scheduled' WHERE id = ?",
        (sw["covered_by"], sw["assignment_id"]),
    )
    conn.execute(
        "UPDATE swap_requests SET status = 'approved', resolved_at = ? WHERE id = ?",
        (now_iso(), swap_id),
    )
    conn.commit()
    conn.close()
    flash("Swap approved and schedule updated.", "success")
    return redirect(url_for("admin.swaps"))


@bp.route("/swaps/<int:swap_id>/reject", methods=["POST"])
@admin_required
def reject_swap(swap_id):
    conn = get_db()
    conn.execute(
        "UPDATE swap_requests SET status = 'rejected', resolved_at = ? WHERE id = ?",
        (now_iso(), swap_id),
    )
    conn.commit()
    conn.close()
    flash("Swap rejected.", "info")
    return redirect(url_for("admin.swaps"))


# ------------------------------------------------------------------ availability
@bp.route("/availability")
@admin_required
def availability():
    conn = get_db()
    today = date.today().isoformat()
    services = conn.execute(
        "SELECT * FROM services WHERE service_date >= ? ORDER BY service_date, start_time LIMIT 10",
        (today,),
    ).fetchall()
    users = conn.execute(
        "SELECT * FROM users WHERE is_active = 1 ORDER BY name"
    ).fetchall()
    # Build a matrix: user -> {service_date: status}
    avail = {}
    for row in conn.execute("SELECT user_id, day, status FROM availability").fetchall():
        avail.setdefault(row["user_id"], {})[row["day"]] = row["status"]
    conn.close()
    return render_template(
        "admin/availability.html", services=services, users=users, avail=avail,
    )
