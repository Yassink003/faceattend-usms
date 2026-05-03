"""Blueprint d'authentification — login / logout."""

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from datetime import datetime, timezone, timedelta
from loguru import logger
from app import db, limiter
from app.models import User, RoleEnum, AuditLog

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/", methods=["GET"])
def index():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user.role)

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        user = User.query.filter_by(email=email, deleted_at=None).first()

        # ── Vérification account lock ────────────────────────
        if user and user.locked_until and user.locked_until > datetime.now(timezone.utc):
            remaining = int((user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
            flash(f"Compte bloqué. Réessayez dans {remaining} min.", "danger")
            return render_template("auth/login.html")

        # ── Validation ──────────────────────────────────────
        if not user or not check_password_hash(user.password_hash, password):
            if user:
                user.failed_logins = (user.failed_logins or 0) + 1
                from flask import current_app
                max_att = current_app.config["LOGIN_MAX_ATTEMPTS"]
                lockout = current_app.config["LOGIN_LOCKOUT_MINUTES"]
                if user.failed_logins >= max_att:
                    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout)
                    db.session.commit()
                    flash(f"Trop de tentatives. Compte bloqué {lockout} min.", "danger")
                    return render_template("auth/login.html")
                db.session.commit()

            flash("Email ou mot de passe incorrect.", "danger")
            logger.warning(f"[AUTH] Échec login pour '{email}'")
            return render_template("auth/login.html")

        if not user.is_active:
            flash("Compte désactivé. Contactez l'administration.", "warning")
            return render_template("auth/login.html")

        # ── Succès ──────────────────────────────────────────
        user.failed_logins = 0
        user.locked_until  = None
        db.session.commit()

        login_user(user, remember=remember)

        log = AuditLog(
            user_id=user.id, action="LOGIN",
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", "")[:255],
        )
        db.session.add(log)
        db.session.commit()

        logger.info(f"[AUTH] {user.email} connecté ({user.role.value})")
        flash(f"Bienvenue !", "success")
        return _redirect_by_role(user.role)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    log = AuditLog(
        user_id=current_user.id, action="LOGOUT",
        ip_address=request.remote_addr,
    )
    db.session.add(log)
    db.session.commit()
    logout_user()
    flash("Déconnecté avec succès.", "info")
    return redirect(url_for("auth.login"))


def _redirect_by_role(role: RoleEnum):
    routes = {
        RoleEnum.ADMIN:   "admin.dashboard",
        RoleEnum.TEACHER: "teacher.dashboard",
        RoleEnum.STUDENT: "student.dashboard",
    }
    return redirect(url_for(routes.get(role, "auth.login")))
