"""Blueprint REST Attendance — endpoints JSON pour le frontend dynamique."""

import time
import json
from flask import Blueprint, jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
from app.models import Session, Attendance, AttendanceStatus, RoleEnum
from app.services.attendance_service import AttendanceService
from app import db

attendance_bp = Blueprint("attendance", __name__)


# ══════════════════════════════════════════════════════════════
#  POLLING — données JSON (fallback navigateurs anciens)
# ══════════════════════════════════════════════════════════════

@attendance_bp.route("/session/<int:session_id>/live")
@login_required
def live_data(session_id):
    """Données temps réel pour polling AJAX (fallback si SSE indisponible)."""
    session = Session.query.get_or_404(session_id)

    att_list = []
    for att in session.attendances.all():
        att_list.append({
            "student_id":     att.student_id,
            "student_number": att.student.student_number,
            "name":           att.student.full_name,
            "status":         att.status.value,
            "detected_at":    att.detected_at.isoformat() if att.detected_at else None,
            "confidence":     att.confidence,
        })

    return jsonify({
        "session_id":  session_id,
        "is_closed":   session.is_closed,
        "present":     session.present_count,
        "absent":      session.absent_count,
        "late":        session.attendances.filter_by(
                           status=AttendanceStatus.LATE).count(),
        "total":       session.attendances.count(),
        "attendances": att_list,
    })


# ══════════════════════════════════════════════════════════════
#  MARQUAGE MANUEL
# ══════════════════════════════════════════════════════════════

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

    att = AttendanceService.mark_manual(
        session_id, student_id, status, current_user.id
    )
    return jsonify({"success": True, "status": att.status.value})


# ══════════════════════════════════════════════════════════════
#  SERVER-SENT EVENTS — mise à jour temps réel
# ══════════════════════════════════════════════════════════════

@attendance_bp.route("/session/<int:session_id>/events")
@login_required
def session_events(session_id):
    """
    Server-Sent Events : pousse les changements de statut en temps réel.
    Le JS dans session_live.html se connecte ici via EventSource.
    Pas de polling — le serveur envoie uniquement quand un statut change.
    """

    def stream():
        last_snapshot   = None
        heartbeat_count = 0

        while True:
            try:
                # ── Lire la BDD ──────────────────────────────
                session = Session.query.get(session_id)

                if not session:
                    yield "data: {\"closed\": true}\n\n"
                    break

                atts = session.attendances.all()

                present = 0
                absent  = 0
                late    = 0
                att_list = []

                for att in atts:
                    s = att.status.value
                    if   s == "present": present += 1
                    elif s == "absent":  absent  += 1
                    elif s == "late":    late    += 1

                    att_list.append({
                        "student_id":  att.student_id,
                        "status":      s,
                        "detected_at": att.detected_at.isoformat()
                                       if att.detected_at else None,
                        "confidence":  round(float(att.confidence), 4)
                                       if att.confidence else None,
                    })

                # ── Snapshot pour détecter les changements ───
                snapshot = json.dumps(
                    sorted(att_list, key=lambda x: x["student_id"]),
                    sort_keys=True
                )

                if snapshot != last_snapshot:
                    last_snapshot = snapshot
                    payload = json.dumps({
                        "present":     present,
                        "absent":      absent,
                        "late":        late,
                        "total":       len(atts),
                        "closed":      session.is_closed,
                        "attendances": att_list,
                    })
                    yield f"data: {payload}\n\n"

                # ── Heartbeat toutes les 20s ──────────────────
                # Empêche les proxies/navigateurs de couper la connexion
                heartbeat_count += 1
                if heartbeat_count >= 20:
                    yield ": heartbeat\n\n"
                    heartbeat_count = 0

                # ── Fermer si séance clôturée ─────────────────
                if session.is_closed:
                    yield "data: {\"closed\": true}\n\n"
                    break

            except Exception as e:
                # Envoyer l'erreur sans couper le stream
                safe = str(e).replace('"', "'")
                yield f"data: {{\"error\": \"{safe}\"}}\n\n"

            # Vérifier la BDD toutes les secondes
            time.sleep(1)

    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        }
    )
