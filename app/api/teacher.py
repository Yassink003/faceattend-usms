"""Blueprint Enseignant — gestion des séances, présences en temps réel."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from functools import wraps
import io, pandas as pd
from datetime import datetime, timezone
from app import db
from app.models import (
    Teacher, Course, Session, Attendance, Student,
    RoleEnum, AttendanceStatus, Justification, JustificationStatus
)
from app.services.attendance_service import AttendanceService

teacher_bp = Blueprint("teacher", __name__)


def teacher_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in (RoleEnum.TEACHER, RoleEnum.ADMIN):
            flash("Accès enseignants uniquement.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@teacher_bp.route("/dashboard")
@teacher_required
def dashboard():
    teacher = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    courses = teacher.courses.filter_by(is_active=True).all()
    active_sessions = Session.query.join(Course).filter(
        Course.teacher_id == teacher.id,
        Session.is_closed == False,
    ).all()
    return render_template("teacher/dashboard.html",
                           teacher=teacher,
                           courses=courses,
                           active_sessions=active_sessions)


@teacher_bp.route("/session/open", methods=["POST"])
@teacher_required
def open_session():
    course_id = request.form.get("course_id", type=int)
    room      = request.form.get("room", "")
    threshold = request.form.get("late_threshold", 15, type=int)

    session = AttendanceService.open_session(course_id, room, threshold)
    flash(f"Séance ouverte — ID #{session.id}", "success")
    return redirect(url_for("teacher.session_live", session_id=session.id))


@teacher_bp.route("/session/<int:session_id>")
@teacher_required
def session_live(session_id):
    session  = Session.query.get_or_404(session_id)
    students = (
        Student.query.join(Attendance)
        .filter(Attendance.session_id == session_id)
        .all()
    )
    attendances = {a.student_id: a for a in session.attendances}
    return render_template("teacher/session_live.html",
                           session=session,
                           students=students,
                           attendances=attendances)


@teacher_bp.route("/session/<int:session_id>/close", methods=["POST"])
@teacher_required
def close_session(session_id):
    AttendanceService.close_session(session_id)
    flash("Séance fermée.", "info")
    return redirect(url_for("teacher.dashboard"))


@teacher_bp.route("/session/<int:session_id>/mark", methods=["POST"])
@teacher_required
def mark_manual(session_id):
    student_id = request.form.get("student_id", type=int)
    status_str = request.form.get("status")
    status     = AttendanceStatus[status_str.upper()]
    AttendanceService.mark_manual(session_id, student_id, status, current_user.id)
    return jsonify({"success": True})


@teacher_bp.route("/session/<int:session_id>/export")
@teacher_required
def export_session(session_id):
    session  = Session.query.get_or_404(session_id)
    rows = []
    for att in session.attendances:
        rows.append({
            "Matricule": att.student.student_number,
            "Prénom":    att.student.first_name,
            "Nom":       att.student.last_name,
            "Statut":    att.status.value,
            "Détecté à": att.detected_at.strftime("%H:%M:%S") if att.detected_at else "",
            "Confiance": f"{att.confidence:.0%}" if att.confidence else "",
            "Méthode":   att.method or "",
        })
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Présences")
    output.seek(0)
    return send_file(output,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     download_name=f"presence_{session_id}.xlsx",
                     as_attachment=True)


@teacher_bp.route("/justifications")
@teacher_required
def justifications():
    teacher  = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    pending  = (Justification.query
                .join(Attendance).join(Session).join(Course)
                .filter(Course.teacher_id == teacher.id,
                        Justification.status == JustificationStatus.PENDING)
                .all())
    return render_template("teacher/justifications.html", pending=pending)


@teacher_bp.route("/justifications/<int:jid>/review", methods=["POST"])
@teacher_required
def review_justification(jid):
    j       = Justification.query.get_or_404(jid)
    action  = request.form.get("action")   # approve | reject
    note    = request.form.get("note", "")

    j.status       = JustificationStatus.APPROVED if action == "approve" else JustificationStatus.REJECTED
    j.reviewed_at  = datetime.now(timezone.utc)
    j.reviewer_note= note

    if j.status == JustificationStatus.APPROVED:
        j.attendance.status = AttendanceStatus.EXCUSED

    db.session.commit()
    flash(f"Justification {'approuvée' if action=='approve' else 'rejetée'}.", "success")
    return redirect(url_for("teacher.justifications"))


# ── API JSON (pour mise à jour live) ──────────────────────

@teacher_bp.route("/api/session/<int:session_id>/stats")
@teacher_required
def session_stats_api(session_id):
    session  = Session.query.get_or_404(session_id)
    return jsonify({
        "present": session.present_count,
        "absent":  session.absent_count,
        "total":   session.attendances.count(),
    })
