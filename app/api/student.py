"""Blueprint Étudiant — historique personnel, justifications."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timezone
from app import db
from app.models import Student, Attendance, AttendanceStatus, Justification, JustificationStatus, RoleEnum
from app.services.attendance_service import AttendanceService

student_bp = Blueprint("student", __name__)


def student_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role not in (RoleEnum.STUDENT, RoleEnum.ADMIN):
            flash("Accès étudiants uniquement.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@student_bp.route("/dashboard")
@student_required
def dashboard():
    student = Student.query.filter_by(user_id=current_user.id).first_or_404()
    stats   = AttendanceService.get_student_stats(student.id)
    recent  = (Attendance.query
               .filter_by(student_id=student.id)
               .order_by(Attendance.id.desc())
               .limit(10).all())
    return render_template("student/dashboard.html",
                           student=student, stats=stats, recent=recent)


@student_bp.route("/history")
@student_required
def history():
    student    = Student.query.filter_by(user_id=current_user.id).first_or_404()
    page       = request.args.get("page", 1, type=int)
    course_id  = request.args.get("course_id", type=int)
    query      = Attendance.query.filter_by(student_id=student.id)
    if course_id:
        from app.models import Session
        query = query.join(Session).filter(Session.course_id == course_id)
    pagination = query.order_by(Attendance.id.desc()).paginate(page=page, per_page=15)
    return render_template("student/history.html",
                           student=student, pagination=pagination)


@student_bp.route("/justify/<int:attendance_id>", methods=["GET", "POST"])
@student_required
def justify(attendance_id):
    student = Student.query.filter_by(user_id=current_user.id).first_or_404()
    att     = Attendance.query.filter_by(
        id=attendance_id, student_id=student.id
    ).first_or_404()

    if att.status != AttendanceStatus.ABSENT:
        flash("Seules les absences peuvent être justifiées.", "warning")
        return redirect(url_for("student.history"))

    if att.justification:
        flash("Une justification existe déjà pour cette absence.", "info")
        return redirect(url_for("student.history"))

    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Veuillez indiquer un motif.", "danger")
            return render_template("student/justify.html", attendance=att)

        j = Justification(
            attendance_id=att.id,
            reason=reason,
            submitted_at=datetime.now(timezone.utc),
        )
        db.session.add(j)
        db.session.commit()
        flash("Justification soumise. En attente de validation.", "success")
        return redirect(url_for("student.history"))

    return render_template("student/justify.html", attendance=att)
