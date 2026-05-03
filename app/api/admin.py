"""Blueprint Administration — tableau de bord global, analytics, gestion utilisateurs."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from functools import wraps
from loguru import logger
import io, pandas as pd
from app import db
from app.models import User, Student, Teacher, Course, Session, Attendance, RoleEnum, AttendanceStatus
from app.services.attendance_service import AttendanceService
from app.utils.crypto import CryptoService

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != RoleEnum.ADMIN:
            flash("Accès réservé aux administrateurs.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    stats = {
        "total_students": Student.query.count(),
        "total_teachers": Teacher.query.count(),
        "total_courses":  Course.query.count(),
        "active_sessions": Session.query.filter_by(is_closed=False).count(),
        "enrolled_faces":  Student.query.filter(Student.face_encoding_enc.isnot(None)).count(),
        "at_risk_count":   len(AttendanceService.get_at_risk_students()),
    }
    return render_template("admin/dashboard.html", stats=stats)


@admin_bp.route("/students")
@admin_required
def students():
    page     = request.args.get("page", 1, type=int)
    search   = request.args.get("q", "")
    query    = Student.query.join(User).filter(User.deleted_at.is_(None))
    if search:
        query = query.filter(
            db.or_(
                Student.first_name.ilike(f"%{search}%"),
                Student.last_name.ilike(f"%{search}%"),
                Student.student_number.ilike(f"%{search}%"),
            )
        )
    pagination = query.paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/students.html", pagination=pagination, search=search)


@admin_bp.route("/at-risk")
@admin_required
def at_risk():
    threshold = request.args.get("threshold", 70, type=float) / 100
    at_risk   = AttendanceService.get_at_risk_students(threshold)
    return render_template("admin/at_risk.html", at_risk=at_risk, threshold=threshold * 100)


@admin_bp.route("/reports/export")
@admin_required
def export_report():
    """Génère un rapport Excel global des présences."""
    rows = (
        db.session.query(
            Student.student_number,
            Student.first_name,
            Student.last_name,
            Student.program,
            Course.name.label("course"),
            Session.started_at,
            Attendance.status,
        )
        .join(Attendance, Attendance.student_id == Student.id)
        .join(Session, Session.id == Attendance.session_id)
        .join(Course, Course.id == Session.course_id)
        .order_by(Session.started_at.desc())
        .all()
    )

    df = pd.DataFrame(rows, columns=[
        "Matricule", "Prénom", "Nom", "Filière",
        "Cours", "Date séance", "Statut"
    ])
    df["Statut"] = df["Statut"].apply(lambda x: x.value if hasattr(x, "value") else x)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Présences")
    output.seek(0)

    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name="rapport_presences.xlsx",
        as_attachment=True,
    )


# ── API JSON ────────────────────────────────────────────────

@admin_bp.route("/api/stats")
@admin_required
def api_stats():
    """Données pour les graphiques Chart.js du dashboard."""
    # Taux de présence par cours (7 derniers cours)
    courses = Course.query.filter_by(is_active=True).limit(10).all()
    chart_data = []
    for c in courses:
        sessions = c.sessions.filter_by(is_closed=True).all()
        if not sessions:
            continue
        total   = sum(s.attendances.count() for s in sessions)
        present = sum(
            s.attendances.filter(
                Attendance.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.LATE])
            ).count()
            for s in sessions
        )
        chart_data.append({
            "course": c.code,
            "rate":   round(present / total * 100, 1) if total else 0,
        })

    return jsonify({"courses": chart_data})
