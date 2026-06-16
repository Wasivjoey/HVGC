"""Authentication blueprint: register, email verification, login, logout.

New accounts are not usable immediately. A registrant must (1) verify their email
address via a one-time link and (2) be approved by an administrator before they
can sign in. Sign-in accepts either a username or an email address.
"""

import re
import secrets
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    current_app,
)
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db, now_iso, execute_returning_id
from helpers import send_email

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


def _send_verification(user_id, name, email, token):
    """Email the verification link; return (sent, link)."""
    link = url_for("auth.verify_email", token=token, _external=True)
    body = (
        f"Hi {name},\n\n"
        "Thanks for registering for HVGC LINEUP. Please confirm your email "
        "address by opening this link:\n\n"
        f"{link}\n\n"
        "After your email is verified, an administrator will approve your account "
        "and you'll be able to sign in.\n\n"
        "If you didn't request this, you can ignore this message."
    )
    sent = send_email(email, "Verify your HVGC LINEUP account", body)
    return sent, link


@bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("user.dashboard"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        errors = []
        if not name:
            errors.append("Name is required.")
        if not USERNAME_RE.match(username):
            errors.append("Username must be 3-20 characters: letters, numbers, or underscore.")
        if not email or "@" not in email:
            errors.append("A valid email is required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        conn = get_db()
        if not errors:
            if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
                errors.append("An account with that email already exists.")
            if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
                errors.append("That username is taken.")

        if errors:
            for e in errors:
                flash(e, "danger")
            conn.close()
            return render_template("auth/register.html", name=name, username=username,
                                   email=email, phone=phone)

        # If there is no administrator yet (fresh system), the first registrant
        # bootstraps as an approved, verified admin so the app is usable.
        admin_count = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE is_admin = 1"
        ).fetchone()["c"]
        bootstrap = admin_count == 0

        token = None if bootstrap else secrets.token_urlsafe(32)
        new_id = execute_returning_id(
            conn,
            "INSERT INTO users (name, username, email, phone, password_hash, is_admin,"
            " is_active, email_verified, verify_token, approved, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (
                name, username, email, phone,
                generate_password_hash(password, method="pbkdf2:sha256"),
                1 if bootstrap else 0,
                1 if bootstrap else 0,   # email_verified
                token,
                1 if bootstrap else 0,   # approved
                now_iso(),
            ),
        )
        conn.commit()
        conn.close()

        if bootstrap:
            session["user_id"] = new_id
            flash("Welcome! As the first account you've been set up as the administrator.",
                  "success")
            return redirect(url_for("admin.dashboard"))

        sent, link = _send_verification(new_id, name, email, token)
        # Without a mail server we surface the link so the account can still be
        # verified (and an admin can also see it on the People page).
        dev_link = None if (sent or current_app.config.get("EMAIL_ENABLED")) else link
        return render_template("auth/registered.html", email=email, sent=sent,
                               dev_link=dev_link)

    return render_template("auth/register.html")


@bp.route("/verify/<token>")
def verify_email(token):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE verify_token = ?", (token,)).fetchone()
    if user is None:
        conn.close()
        flash("That verification link is invalid or has already been used.", "danger")
        return redirect(url_for("auth.login"))
    conn.execute(
        "UPDATE users SET email_verified = 1, verify_token = NULL WHERE id = ?",
        (user["id"],),
    )
    conn.commit()
    conn.close()
    if user["approved"]:
        flash("Email verified — you can now sign in.", "success")
    else:
        flash("Email verified! An administrator will approve your account shortly.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    identifier = request.form.get("identifier", "").strip().lower()
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE (email = ? OR username = ?) AND email_verified = 0",
        (identifier, identifier),
    ).fetchone()
    if user:
        token = secrets.token_urlsafe(32)
        conn.execute("UPDATE users SET verify_token = ? WHERE id = ?", (token, user["id"]))
        conn.commit()
        _send_verification(user["id"], user["name"], user["email"], token)
    conn.close()
    flash("If that account exists and is unverified, a new verification link has been sent.",
          "info")
    return redirect(url_for("auth.login"))


@bp.route("/forgot", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id"):
        return redirect(url_for("user.dashboard"))
    dev_link = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? OR username = ?",
            (identifier, identifier),
        ).fetchone()
        if user:
            token = secrets.token_urlsafe(32)
            expires = (datetime.utcnow() + timedelta(hours=1)).isoformat(timespec="seconds")
            conn.execute(
                "UPDATE users SET reset_token = ?, reset_expires = ? WHERE id = ?",
                (token, expires, user["id"]),
            )
            conn.commit()
            link = url_for("auth.reset_password", token=token, _external=True)
            body = (
                f"Hi {user['name']},\n\n"
                "We received a request to reset your HVGC LINEUP password. Open this "
                "link to choose a new one (it expires in 1 hour):\n\n"
                f"{link}\n\n"
                "If you didn't request this, you can safely ignore this email — your "
                "password won't change."
            )
            sent = send_email(user["email"], "Reset your HVGC LINEUP password", body)
            if not sent and not current_app.config.get("EMAIL_ENABLED"):
                dev_link = link
        conn.close()
        # Always show the same message so we don't reveal which accounts exist.
        flash("If an account matches that username or email, a reset link has been sent.",
              "info")
        return render_template("auth/forgot.html", dev_link=dev_link, submitted=True)
    return render_template("auth/forgot.html")


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE reset_token = ?", (token,)).fetchone()
    valid = bool(user) and bool(user["reset_expires"]) and user["reset_expires"] >= now_iso()
    if not valid:
        conn.close()
        flash("That reset link is invalid or has expired. Please request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        errors = []
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if errors:
            for e in errors:
                flash(e, "danger")
            conn.close()
            return render_template("auth/reset.html", token=token)
        conn.execute(
            "UPDATE users SET password_hash = ?, reset_token = NULL, reset_expires = NULL"
            " WHERE id = ?",
            (generate_password_hash(password, method="pbkdf2:sha256"), user["id"]),
        )
        conn.commit()
        conn.close()
        flash("Your password has been reset — you can now sign in.", "success")
        return redirect(url_for("auth.login"))

    conn.close()
    return render_template("auth/reset.html", token=token)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("user.dashboard"))
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? OR username = ?",
            (identifier, identifier),
        ).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect username/email or password.", "danger")
            return render_template("auth/login.html", identifier=identifier)
        if not user["email_verified"]:
            flash("Please verify your email address first. Check your inbox for the link.",
                  "warning")
            return render_template("auth/login.html", identifier=identifier, unverified=True)
        if not user["approved"]:
            flash("Your account is awaiting administrator approval. You'll be able to sign "
                  "in once it's approved.", "warning")
            return render_template("auth/login.html", identifier=identifier)
        if not user["is_active"]:
            flash("Your account has been deactivated. Contact an administrator.", "danger")
            return render_template("auth/login.html", identifier=identifier)

        session.clear()
        session["user_id"] = user["id"]
        flash(f"Welcome back, {user['name'].split()[0]}!", "success")
        if user["is_admin"]:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("user.dashboard"))

    return render_template("auth/login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
