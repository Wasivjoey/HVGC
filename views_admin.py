"""Administrator blueprint: manage users, roles, trainings, services,
scheduling, and swap approvals."""

import secrets
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
)
from werkzeug.security import generate_password_hash

from db import (get_db, now_iso, execute_returning_id, ensure_one_role_index,
                default_team_id)
from helpers import (
    admin_required, current_user, role_training_status, is_qualified,
    qualified_users_for_role, save_document, delete_document,
    get_announcements, get_polls, notify, notify_all, assignment_conflicts,
    build_ics, delete_avatar,
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
    # Flag any pre-existing data where someone holds multiple roles in a service.
    # If there are none, opportunistically activate the DB-level constraint so it
    # turns on after cleanup without needing a redeploy.
    conflicts = assignment_conflicts(conn)
    if not conflicts:
        ensure_one_role_index(conn)

    conn.close()
    return render_template("admin/dashboard.html", stats=stats, upcoming=upcoming,
                           swaps=swaps, pending=pending, conflicts=conflicts)


# ------------------------------------------------------------------------- users
@bp.route("/users")
@admin_required
def users():
    conn = get_db()
    team_filter = request.args.get("team", type=int)
    if team_filter:
        rows = conn.execute(
            "SELECT u.*, t.name AS team_name FROM users u"
            " LEFT JOIN teams t ON t.id = u.team_id"
            " WHERE u.team_id = ? ORDER BY u.is_admin DESC, u.name",
            (team_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT u.*, t.name AS team_name FROM users u"
            " LEFT JOIN teams t ON t.id = u.team_id"
            " ORDER BY u.is_admin DESC, u.name",
        ).fetchall()
    people = []
    for u in rows:
        role_count = conn.execute(
            "SELECT COUNT(*) AS c FROM user_roles WHERE user_id = ?", (u["id"],)
        ).fetchone()["c"]
        people.append({"u": u, "roles": role_count})
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template("admin/users.html", people=people, teams=teams,
                           team_filter=team_filter)


@bp.route("/users/bulk-team", methods=["POST"])
@admin_required
def bulk_team():
    """Move the selected people into a team in one action."""
    conn = get_db()
    team_id = request.form.get("team_id", type=int)
    ids = [int(i) for i in request.form.getlist("user_ids") if str(i).isdigit()]
    team = conn.execute("SELECT name FROM teams WHERE id = ?", (team_id,)).fetchone()
    if not team or not ids:
        conn.close()
        flash("Pick at least one person and a team.", "warning")
        return redirect(url_for("admin.users"))
    for uid in ids:
        conn.execute("UPDATE users SET team_id = ? WHERE id = ?", (team_id, uid))
    conn.commit()
    conn.close()
    flash(f"Moved {len(ids)} member{'s' if len(ids) != 1 else ''} to {team['name']}.",
          "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if u is None:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))

    # Only roles available to this user's team (global roles have no team).
    all_roles = conn.execute(
        "SELECT * FROM roles WHERE team_id IS NULL OR team_id = ? ORDER BY name",
        (u["team_id"],),
    ).fetchall()
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

    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template(
        "admin/user_detail.html", u=u, role_view=role_view, training_view=training_view,
        teams=teams,
    )


@bp.route("/users/<int:user_id>/roles", methods=["POST"])
@admin_required
def update_user_roles(user_id):
    conn = get_db()
    role_id = int(request.form.get("role_id"))
    action = request.form.get("action")
    role = conn.execute("SELECT name FROM roles WHERE id = ?", (role_id,)).fetchone()
    role_name = role["name"] if role else "a role"
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
        notify(conn, user_id, f"You were assigned the {role_name} role.",
               url_for("user.profile"))
        flash("Role assigned and required training queued.", "success")
    elif action == "remove":
        conn.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?", (user_id, role_id)
        )
        notify(conn, user_id, f"The {role_name} role was removed from your account.",
               url_for("user.profile"))
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
    tr = conn.execute("SELECT title FROM trainings WHERE id = ?", (training_id,)).fetchone()
    tr_title = tr["title"] if tr else "a training"
    if action == "assign":
        conn.execute(
            "INSERT OR IGNORE INTO user_training (user_id, training_id, status, assigned_at)"
            " VALUES (?, ?, 'assigned', ?)",
            (user_id, training_id, now_iso()),
        )
        notify(conn, user_id, f"New training assigned: {tr_title}.",
               url_for("user.trainings"))
        flash("Training assigned.", "success")
    elif action == "complete":
        conn.execute(
            "UPDATE user_training SET status = 'completed', completed_at = ?"
            " WHERE user_id = ? AND training_id = ?",
            (now_iso(), user_id, training_id),
        )
        notify(conn, user_id, f"Your “{tr_title}” training was marked complete.",
               url_for("user.trainings"))
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
    notify(conn, user_id, "Your account has been approved — welcome aboard! 🎉",
           url_for("user.dashboard"), email=True,
           subject="Your HVGC LINEUP account is approved")
    conn.commit()
    conn.close()
    flash("Account approved.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


@bp.route("/users/<int:user_id>/details", methods=["POST"])
@admin_required
def update_user_details(user_id):
    conn = get_db()
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    if not name or not email or "@" not in email:
        flash("Name and a valid email are required.", "danger")
    elif conn.execute(
        "SELECT id FROM users WHERE email = ? AND id <> ?", (email, user_id)
    ).fetchone():
        flash("That email is already in use by another account.", "danger")
    else:
        conn.execute(
            "UPDATE users SET name = ?, email = ?, phone = ? WHERE id = ?",
            (name, email, phone, user_id),
        )
        notify(conn, user_id, "An administrator updated your account details.",
               url_for("user.profile"))
        conn.commit()
        flash("Account details updated.", "success")
    conn.close()
    return redirect(url_for("admin.user_detail", user_id=user_id))


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_user_password(user_id):
    conn = get_db()
    u = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    if u is None:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))

    temp = request.form.get("temp_password", "").strip()
    if not temp:
        temp = secrets.token_urlsafe(6)          # auto-generate if none supplied
    elif len(temp) < 6:
        conn.close()
        flash("Temporary password must be at least 6 characters.", "danger")
        return redirect(url_for("admin.user_detail", user_id=user_id))

    conn.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
        (generate_password_hash(temp, method="pbkdf2:sha256"), user_id),
    )
    notify(conn, user_id, "An administrator reset your password. You'll be asked to "
           "set a new one at your next sign-in.", url_for("user.dashboard"),
           email=True, subject="Your HVGC LINEUP password was reset")
    conn.commit()
    conn.close()
    flash(f"Password reset for @{u['username']}. Temporary password: {temp} — "
          "they'll be required to change it at next sign-in.", "success")
    return redirect(url_for("admin.user_detail", user_id=user_id))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    me = current_user()
    if user_id == me["id"]:
        flash("You can't delete your own account.", "warning")
        return redirect(url_for("admin.user_detail", user_id=user_id))
    conn = get_db()
    u = conn.execute(
        "SELECT name, is_admin, avatar FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if u is None:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))
    if u["is_admin"]:
        admins = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
        ).fetchone()["c"]
        if admins <= 1:
            conn.close()
            flash("You can't delete the last administrator.", "warning")
            return redirect(url_for("admin.user_detail", user_id=user_id))
    # Remove their avatar file; the database cascades remove the rest of their data.
    delete_avatar(u["avatar"])
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash(f"Deleted {u['name']}'s account and all of their data.", "info")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/team", methods=["POST"])
@admin_required
def set_user_team(user_id):
    conn = get_db()
    team_id = request.form.get("team_id") or None
    conn.execute("UPDATE users SET team_id = ? WHERE id = ?", (team_id, user_id))
    conn.commit()
    conn.close()
    flash("Team updated.", "success")
    return redirect(url_for("admin.user_detail", user_id=user_id))


@bp.route("/teams", methods=["GET", "POST"])
@admin_required
def teams():
    conn = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            try:
                conn.execute("INSERT INTO teams (name, created_at) VALUES (?, ?)",
                             (name, now_iso()))
                conn.commit()
                flash("Team created.", "success")
            except Exception:
                flash("A team with that name already exists.", "danger")
        conn.close()
        return redirect(url_for("admin.teams"))
    rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    team_view = []
    for t in rows:
        members = conn.execute("SELECT COUNT(*) AS c FROM users WHERE team_id = ?",
                               (t["id"],)).fetchone()["c"]
        leads = conn.execute("SELECT name FROM users WHERE team_id = ? AND team_lead = 1"
                             " ORDER BY name", (t["id"],)).fetchall()
        team_view.append({"t": t, "members": members, "leads": [l["name"] for l in leads]})
    conn.close()
    return render_template("admin/teams.html", team_view=team_view)


@bp.route("/teams/<int:team_id>/rename", methods=["POST"])
@admin_required
def rename_team(team_id):
    conn = get_db()
    name = request.form.get("name", "").strip()
    if name:
        conn.execute("UPDATE teams SET name = ? WHERE id = ?", (name, team_id))
        conn.commit()
        flash("Team renamed.", "success")
    conn.close()
    return redirect(url_for("admin.teams"))


@bp.route("/teams/<int:team_id>/delete", methods=["POST"])
@admin_required
def delete_team(team_id):
    conn = get_db()
    default = default_team_id(conn)
    if team_id == default:
        conn.close()
        flash("The default Ministry Team can't be deleted.", "warning")
        return redirect(url_for("admin.teams"))
    # Move members to the default team, then remove the team.
    conn.execute("UPDATE users SET team_id = ? WHERE team_id = ?", (default, team_id))
    conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()
    conn.close()
    flash("Team deleted; its members moved to the Ministry Team.", "info")
    return redirect(url_for("admin.teams"))


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
        notify(conn, user_id, "You're now an administrator. 🛠️", url_for("admin.dashboard"))
        flash("User promoted to administrator.", "success")
    elif action == "revoke_admin":
        conn.execute("UPDATE users SET is_admin = 0 WHERE id = ?", (user_id,))
        notify(conn, user_id, "Your administrator access was removed.",
               url_for("user.dashboard"))
        flash("Administrator rights revoked.", "info")
    elif action == "make_lead":
        conn.execute("UPDATE users SET team_lead = 1 WHERE id = ?", (user_id,))
        notify(conn, user_id, "You're now a team lead — you can manage your team.",
               url_for("user.team"))
        flash("User is now a team lead.", "success")
    elif action == "remove_lead":
        conn.execute("UPDATE users SET team_lead = 0 WHERE id = ?", (user_id,))
        flash("Team lead role removed.", "info")
    elif action == "approve":
        conn.execute("UPDATE users SET approved = 1, is_active = 1 WHERE id = ?", (user_id,))
        notify(conn, user_id, "Your account has been approved — welcome aboard! 🎉",
               url_for("user.dashboard"), email=True,
               subject="Your HVGC LINEUP account is approved")
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
        notify(conn, user_id, "Your account was reactivated.", url_for("user.dashboard"))
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
        team_id = request.form.get("team_id") or None
        if name:
            try:
                conn.execute(
                    "INSERT INTO roles (name, description, team_id) VALUES (?, ?, ?)",
                    (name, description, team_id),
                )
                conn.commit()
                flash("Role created.", "success")
            except Exception:
                flash("A role with that name already exists.", "danger")
        conn.close()
        return redirect(url_for("admin.roles"))

    rows = conn.execute(
        "SELECT r.*, t.name AS team_name FROM roles r"
        " LEFT JOIN teams t ON t.id = r.team_id ORDER BY r.name"
    ).fetchall()
    role_view = []
    for r in rows:
        people = conn.execute(
            "SELECT COUNT(*) AS c FROM user_roles WHERE role_id = ?", (r["id"],)
        ).fetchone()["c"]
        qualified = len(qualified_users_for_role(conn, r["id"]))
        role_view.append({"r": r, "people": people, "qualified": qualified})
    teams = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
    conn.close()
    return render_template("admin/roles.html", role_view=role_view, teams=teams)


@bp.route("/roles/<int:role_id>/edit", methods=["POST"])
@admin_required
def edit_role(role_id):
    conn = get_db()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    team_id = request.form.get("team_id") or None
    if name:
        conn.execute(
            "UPDATE roles SET name = ?, description = ?, team_id = ? WHERE id = ?",
            (name, description, team_id, role_id),
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
    # user_id -> the role they already hold in this service (for one-role-per-service)
    serving_role = {a["user_id"]: a["role_name"] for a in roster}

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
            already = (c["id"], r["id"]) in assigned_pairs
            cand_view.append({
                "u": c,
                "qualified": is_qualified(conn, c["id"], r["id"]),
                "availability": av["status"] if av else None,
                "already": already,
                # Serving a *different* role in this service → can't take this one.
                "busy_role": serving_role.get(c["id"]) if not already else None,
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

    # One role per person per service: block if they already hold a slot here.
    existing = conn.execute(
        "SELECT r.name FROM assignments a JOIN roles r ON r.id = a.role_id"
        " WHERE a.service_id = ? AND a.user_id = ?",
        (service_id, user_id),
    ).fetchone()
    if existing:
        conn.close()
        flash(f"That person is already serving as {existing['name']} for this service. "
              "Remove them from that role first to reassign.", "warning")
        return redirect(url_for("admin.schedule", service_id=service_id))

    conn.execute(
        "INSERT OR IGNORE INTO assignments (service_id, user_id, role_id, status, created_at)"
        " VALUES (?, ?, ?, 'scheduled', ?)",
        (service_id, user_id, role_id, now_iso()),
    )
    svc = conn.execute(
        "SELECT title, service_date, start_time, location, notes FROM services WHERE id = ?",
        (service_id,),
    ).fetchone()
    role = conn.execute("SELECT name FROM roles WHERE id = ?", (role_id,)).fetchone()
    if svc and role:
        assignment = conn.execute(
            "SELECT id FROM assignments WHERE service_id = ? AND user_id = ? AND role_id = ?",
            (service_id, user_id, role_id),
        ).fetchone()
        # Build a calendar invite (.ics) with reminders to attach to the email.
        desc = f"You're serving as {role['name']} for {svc['title']}."
        if svc["notes"]:
            desc += "\n\n" + svc["notes"]
        ics = build_ics(f"assignment-{assignment['id']}@hvgc-lineup",
                        f"AV Team: {role['name']} — {svc['title']}",
                        svc["service_date"], svc["start_time"], svc["location"], desc)
        cal_link = url_for("user.service_calendar", service_id=service_id, _external=True)
        notify(conn, user_id,
               f"You're scheduled as {role['name']} for {svc['title']} on "
               f"{svc['service_date']}.", url_for("user.service_detail", service_id=service_id),
               email=True, subject="You've been scheduled — HVGC LINEUP",
               attachments=[("hvgc-service.ics", ics, "text", "calendar")],
               email_extra=("📅 Add this to your calendar — the attached invite includes "
                            f"reminders the day before and an hour before.\nCalendar link: {cal_link}"))
    conn.commit()
    conn.close()
    flash("Assigned.", "success")
    return redirect(url_for("admin.schedule", service_id=service_id))


@bp.route("/assignments/<int:assignment_id>/unassign", methods=["POST"])
@admin_required
def unassign(assignment_id):
    conn = get_db()
    a = conn.execute(
        "SELECT a.service_id, a.user_id, s.title AS service_title, s.service_date,"
        " r.name AS role_name"
        " FROM assignments a JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id WHERE a.id = ?",
        (assignment_id,),
    ).fetchone()
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    if a:
        notify(conn, a["user_id"],
               f"You were removed from {a['service_title']} on {a['service_date']} "
               f"({a['role_name']}).", url_for("user.services"))
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

    # The volunteer must not already serve another role in the same service.
    conflict = conn.execute(
        "SELECT r.name FROM assignments a JOIN roles r ON r.id = a.role_id"
        " WHERE a.service_id = (SELECT service_id FROM assignments WHERE id = ?)"
        " AND a.user_id = ? AND a.id <> ?",
        (sw["assignment_id"], sw["covered_by"], sw["assignment_id"]),
    ).fetchone()
    if conflict:
        conn.close()
        flash(f"Can't approve — the volunteer is already serving as {conflict['name']} "
              "for this service.", "warning")
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
    info = conn.execute(
        "SELECT s.title AS service_title, s.service_date, r.name AS role_name,"
        " s.id AS service_id"
        " FROM assignments a JOIN services s ON s.id = a.service_id"
        " JOIN roles r ON r.id = a.role_id WHERE a.id = ?",
        (sw["assignment_id"],),
    ).fetchone()
    if info:
        link = url_for("user.service_detail", service_id=info["service_id"])
        notify(conn, sw["covered_by"],
               f"Your swap was approved — you're now {info['role_name']} for "
               f"{info['service_title']} on {info['service_date']}.", link,
               email=True, subject="Swap approved — you're scheduled (HVGC LINEUP)")
        notify(conn, sw["requested_by"],
               f"Your swap request for {info['service_title']} was approved and covered.",
               link)
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


# --------------------------------------------------------------- announcements
@bp.route("/announcements", methods=["GET", "POST"])
@admin_required
def announcements():
    me = current_user()
    conn = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        expires_at = request.form.get("expires_at", "").strip() or None
        if title and body:
            conn.execute(
                "INSERT INTO announcements (title, body, created_by, active, expires_at, created_at)"
                " VALUES (?, ?, ?, 1, ?, ?)",
                (title, body, me["id"], expires_at, now_iso()),
            )
            notify_all(conn, f"📣 New announcement: {title}",
                       url_for("user.dashboard"), exclude_id=me["id"])
            conn.commit()
            flash("Announcement posted and the team was notified.", "success")
        else:
            flash("Title and message are required.", "danger")
        conn.close()
        return redirect(url_for("admin.announcements"))

    items = get_announcements(conn, active_only=False)
    conn.close()
    return render_template("admin/announcements.html", items=items, today=date.today().isoformat())


@bp.route("/announcements/<int:ann_id>/edit", methods=["POST"])
@admin_required
def edit_announcement(ann_id):
    conn = get_db()
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    expires_at = request.form.get("expires_at", "").strip() or None
    if title and body:
        conn.execute(
            "UPDATE announcements SET title = ?, body = ?, expires_at = ? WHERE id = ?",
            (title, body, expires_at, ann_id),
        )
        conn.commit()
        flash("Announcement updated.", "success")
    else:
        flash("Title and message are required.", "danger")
    conn.close()
    return redirect(url_for("admin.announcements"))


@bp.route("/announcements/<int:ann_id>/toggle", methods=["POST"])
@admin_required
def toggle_announcement(ann_id):
    conn = get_db()
    conn.execute("UPDATE announcements SET active = 1 - active WHERE id = ?", (ann_id,))
    conn.commit()
    conn.close()
    flash("Announcement updated.", "info")
    return redirect(url_for("admin.announcements"))


@bp.route("/announcements/<int:ann_id>/delete", methods=["POST"])
@admin_required
def delete_announcement(ann_id):
    conn = get_db()
    conn.execute("DELETE FROM announcements WHERE id = ?", (ann_id,))
    conn.commit()
    conn.close()
    flash("Announcement deleted.", "info")
    return redirect(url_for("admin.announcements"))


# ----------------------------------------------------------------------- polls
@bp.route("/polls", methods=["GET", "POST"])
@admin_required
def polls():
    me = current_user()
    conn = get_db()
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        options = [o.strip() for o in request.form.getlist("option") if o.strip()]
        try:
            days = int(request.form.get("days", "7"))
        except ValueError:
            days = 7
        days = max(1, min(days, 90))
        if not question or len(options) < 2:
            flash("A question and at least two options are required.", "danger")
            conn.close()
            return redirect(url_for("admin.polls"))
        closes_at = (datetime.utcnow() + timedelta(days=days)).isoformat(timespec="seconds")
        poll_id = execute_returning_id(
            conn,
            "INSERT INTO polls (question, created_by, closes_at, closed, created_at)"
            " VALUES (?, ?, ?, 0, ?)",
            (question, me["id"], closes_at, now_iso()),
        )
        for i, text in enumerate(options):
            conn.execute(
                "INSERT INTO poll_options (poll_id, text, position) VALUES (?, ?, ?)",
                (poll_id, text, i),
            )
        conn.commit()
        flash(f"Poll created — open for {days} day{'s' if days != 1 else ''}.", "success")
        conn.close()
        return redirect(url_for("admin.polls"))

    poll_view = get_polls(conn, user_id=me["id"], with_voters=True)
    conn.close()
    return render_template("admin/polls.html", poll_view=poll_view)


@bp.route("/polls/<int:poll_id>/close", methods=["POST"])
@admin_required
def close_poll(poll_id):
    conn = get_db()
    conn.execute("UPDATE polls SET closed = 1 WHERE id = ?", (poll_id,))
    conn.commit()
    conn.close()
    flash("Poll closed.", "info")
    return redirect(url_for("admin.polls"))


@bp.route("/polls/<int:poll_id>/reopen", methods=["POST"])
@admin_required
def reopen_poll(poll_id):
    # Reopen and extend the closing time a week out so it isn't instantly closed.
    new_close = (datetime.utcnow() + timedelta(days=7)).isoformat(timespec="seconds")
    conn = get_db()
    conn.execute("UPDATE polls SET closed = 0, closes_at = ? WHERE id = ?", (new_close, poll_id))
    conn.commit()
    conn.close()
    flash("Poll reopened for 7 more days.", "success")
    return redirect(url_for("admin.polls"))


@bp.route("/polls/<int:poll_id>/delete", methods=["POST"])
@admin_required
def delete_poll(poll_id):
    conn = get_db()
    conn.execute("DELETE FROM polls WHERE id = ?", (poll_id,))
    conn.commit()
    conn.close()
    flash("Poll deleted.", "info")
    return redirect(url_for("admin.polls"))
