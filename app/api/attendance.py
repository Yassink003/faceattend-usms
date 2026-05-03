"""Blueprint REST Attendance — endpoints JSON pour le frontend dynamique."""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app.models import Session, Attendance, AttendanceStatus, RoleEnum
from app.services.attendance_service import AttendanceService
from app import db

attendance_bp = Blueprint("attendance", __name__)


@attendance_bp.route("/session/<int:session_id>/live")
@login_required
def live_data(session_id):
    """Données temps réel pour polling AJAX (toutes les 3s)."""
    session = Session.query.get_or_404(session_id)
    data = []
    for att in session.attendances.join(
        att.student if False else Attendance.__table__
    ).all() if False else session.attendances.all():
        data.append({
            "student_id":     att.student_id,
            "student_number": att.student.student_number,
            "name":           att.student.full_name,
            "status":         att.status.value,
            "detected_at":    att.detected_at.isoformat() if att.detected_at else None,
            "confidence":     att.confidence,
        })
    return jsonify({
        "session_id": session_id,
        "is_closed":  session.is_closed,
        "present":    session.present_count,
        "absent":     session.absent_count,
        "total":      session.attendances.count(),
        "attendances": data,
    })


@attendance_bp.route("/session/<int:session_id>/mark", methods=["POST"])
@login_required
def mark(session_id):
    if current_user.role not in (RoleEnum.TEACHER, RoleEnum.ADMIN):
        return jsonify({"error": "Unauthorized"}), 403

    body       = request.json or {}
    student_id = body.get("student_id")
    status_str = body.get("status", "present").upper()

    try:
        status = AttendanceStatus[status_str]
    except KeyError:
        return jsonify({"error": "Statut invalide"}), 400

    att = AttendanceService.mark_manual(session_id, student_id, status, current_user.id)
    return jsonify({"success": True, "status": att.status.value})
