"""HVGC LINEUP — Flask application entry point.

Run locally:
    python3 app.py
Then open http://localhost:8000

Production (cloud):
    gunicorn 'app:create_app()' --bind 0.0.0.0:8000
"""

import os

from flask import Flask, redirect, url_for, session, request

from db import init_db
from helpers import current_user
import auth
import views_user
import views_admin


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Where uploaded programme-flow documents are stored. Use a mounted volume
    # on a cloud host so files survive redeploys (defaults next to the database).
    upload_path = os.environ.get(
        "UPLOAD_PATH", os.path.join(os.path.dirname(__file__), "uploads")
    )
    # Never let an unwritable UPLOAD_PATH crash startup (e.g. pointing at a disk
    # mount that doesn't exist on the free plan). Fall back to a temp directory.
    try:
        os.makedirs(upload_path, exist_ok=True)
    except OSError:
        import tempfile
        fallback = os.path.join(tempfile.gettempdir(), "hvgc-uploads")
        os.makedirs(fallback, exist_ok=True)
        print(f"[app] UPLOAD_PATH '{upload_path}' not writable; using {fallback}",
              flush=True)
        upload_path = fallback
    app.config["UPLOAD_PATH"] = upload_path
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB cap per upload

    # Outgoing email for address verification. If SMTP_HOST is unset, the app
    # runs in "no email" mode: verification links are logged and shown on screen
    # so accounts can still be verified without a mail server.
    app.config["SMTP_HOST"] = os.environ.get("SMTP_HOST")
    app.config["SMTP_PORT"] = int(os.environ.get("SMTP_PORT", "587"))
    app.config["SMTP_USER"] = os.environ.get("SMTP_USER")
    app.config["SMTP_PASSWORD"] = os.environ.get("SMTP_PASSWORD")
    app.config["SMTP_FROM"] = os.environ.get(
        "SMTP_FROM", os.environ.get("SMTP_USER") or "no-reply@hvgclineup.local"
    )
    app.config["SMTP_TLS"] = os.environ.get("SMTP_TLS", "1") != "0"
    app.config["EMAIL_ENABLED"] = bool(app.config["SMTP_HOST"])

    init_db()

    app.register_blueprint(auth.bp)
    app.register_blueprint(views_user.bp)
    app.register_blueprint(views_admin.bp)

    @app.context_processor
    def inject_user():
        return {"current_user": current_user()}

    # If an admin reset a user's password, force them to set a new one before
    # they can use anything else.
    @app.before_request
    def _force_password_change():
        user = current_user()
        if user and user["must_change_password"]:
            allowed = {"user.change_password", "auth.logout", "user.user_avatar",
                       "static", "healthz"}
            if request.endpoint not in allowed:
                return redirect(url_for("user.change_password"))

    @app.template_filter("pretty_date")
    def pretty_date(value):
        """Render an ISO date/datetime as a friendly string."""
        if not value:
            return ""
        from datetime import datetime
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(value, fmt).strftime("%a, %b %-d, %Y")
            except ValueError:
                continue
        return value

    @app.template_filter("pretty_dt")
    def pretty_dt(value):
        if not value:
            return ""
        from datetime import datetime
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").strftime("%b %-d, %Y · %-I:%M %p")
        except ValueError:
            return value

    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("FLASK_DEBUG")))
