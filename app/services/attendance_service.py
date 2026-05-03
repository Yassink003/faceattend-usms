"""
AttendanceService — Logique métier pour la gestion des présences.
"""

from datetime import datetime, timezone, timedelta
from loguru import logger
from app import db
from app.models import (
    Session, Attendance, Student, Enrollment,
    AttendanceStatus, AuditLog
)
from app.services.face_service import FaceRecognitionService


class AttendanceService:

    # ── Gestion des séances ─────────────────────────────────

    @classmethod
    def open_session(cls, course_id: int, room: str = None,
                     late_threshold: int = 15) -> Session:
        """Ouvre une nouvelle séance et initialise les absences."""
        session = Session(
            course_id=course_id,
            started_at=datetime.now(timezone.utc),
            room=room,
            late_threshold_minutes=late_threshold,
        )
        db.session.add(session)
        db.session.flush()  # Obtenir l'id avant commit

        # Marquer tous les étudiants inscrits comme absents par défaut
        enrollments = Enrollment.query.filter_by(course_id=course_id).all()
        for enr in enrollments:
            att = Attendance(
                session_id=session.id,
                student_id=enr.student_id,
                status=AttendanceStatus.ABSENT,
            )
            db.session.add(att)

        db.session.commit()
        logger.info(f"[ATTENDANCE] Séance {session.id} ouverte pour cours {course_id}")
        return session

    @classmethod
    def close_session(cls, session_id: int) -> Session:
        session = Session.query.get_or_404(session_id)
        session.ended_at  = datetime.now(timezone.utc)
        session.is_closed = True
        db.session.commit()
        logger.info(f"[ATTENDANCE] Séance {session_id} fermée.")
        return session

    # ── Marquage automatique (reconnaissance faciale) ───────

    @classmethod
    def mark_present_by_face(cls, session_id: int, student_id: int,
                              confidence: float) -> Attendance | None:
        """
        Marque un étudiant présent (ou en retard) via reconnaissance faciale.
        """
        session = Session.query.get(session_id)
        if not session or session.is_closed:
            logger.warning(f"[ATTENDANCE] Séance {session_id} fermée ou inexistante.")
            return None

        att = Attendance.query.filter_by(
            session_id=session_id, student_id=student_id
        ).first()

        if not att:
            logger.warning(f"[ATTENDANCE] Étudiant {student_id} non inscrit à cette séance.")
            return None

        # Déjà présent → ne pas écraser
        if att.status in (AttendanceStatus.PRESENT, AttendanceStatus.LATE):
            return att

        # Vérifier retard
        # Normaliser les deux datetimes en naive UTC pour la comparaison
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        started = session.started_at.replace(tzinfo=None) if session.started_at else now
        elapsed = (now - started).total_seconds() / 60
        status  = (AttendanceStatus.LATE
                   if elapsed > session.late_threshold_minutes
                   else AttendanceStatus.PRESENT)

        att.status      = status
        att.detected_at = datetime.now(timezone.utc)
        att.confidence  = confidence
        att.method      = "face"

        db.session.commit()
        logger.info(f"[ATTENDANCE] Étudiant {student_id} → {status.value} (conf={confidence:.2%})")
        return att

    # ── Marquage manuel (enseignant) ────────────────────────

    @classmethod
    def mark_manual(cls, session_id: int, student_id: int,
                    status: AttendanceStatus, teacher_user_id: int) -> Attendance:
        att = Attendance.query.filter_by(
            session_id=session_id, student_id=student_id
        ).first_or_404()

        att.status  = status
        att.method  = "manual"

        log = AuditLog(
            user_id=teacher_user_id,
            action="MANUAL_MARK",
            resource="attendance",
            resource_id=att.id,
            details={"status": status.value},
        )
        db.session.add(log)
        db.session.commit()
        return att

    # ── Traitement d'un frame caméra ────────────────────────

    @classmethod
    def process_camera_frame(cls, frame, session_id: int,
                              known_encodings: list[dict]) -> list[dict]:
        """
        Reçoit un frame OpenCV, identifie les visages et marque les présences.
        Retourne la liste des détections.
        """
        detections = FaceRecognitionService.identify_faces_in_frame(frame, known_encodings)

        for d in detections:
            if d["student_id"] and d["confidence"] >= 0.55:
                cls.mark_present_by_face(
                    session_id=session_id,
                    student_id=d["student_id"],
                    confidence=d["confidence"],
                )

        return detections

    # ── Analytics ───────────────────────────────────────────

    @classmethod
    def get_student_stats(cls, student_id: int, course_id: int = None) -> dict:
        """Statistiques d'assiduité d'un étudiant."""
        query = Attendance.query.join(Session).filter(
            Attendance.student_id == student_id
        )
        if course_id:
            query = query.filter(Session.course_id == course_id)

        attendances = query.all()
        total   = len(attendances)
        present = sum(1 for a in attendances if a.status in
                      (AttendanceStatus.PRESENT, AttendanceStatus.LATE))
        absent  = sum(1 for a in attendances if a.status == AttendanceStatus.ABSENT)
        excused = sum(1 for a in attendances if a.status == AttendanceStatus.EXCUSED)

        return {
            "total":    total,
            "present":  present,
            "absent":   absent,
            "excused":  excused,
            "rate":     round(present / total * 100, 1) if total else 0,
            "at_risk":  (present / total) < 0.70 if total >= 5 else False,
        }

    @classmethod
    def get_at_risk_students(cls, threshold: float = 0.70) -> list[dict]:
        """Détecte les étudiants en décrochage (taux présence < seuil)."""
        students = Student.query.all()
        at_risk = []
        for s in students:
            stats = cls.get_student_stats(s.id)
            if stats["total"] >= 3 and stats["rate"] / 100 < threshold:
                at_risk.append({
                    "student": s,
                    "stats":   stats,
                })
        return sorted(at_risk, key=lambda x: x["stats"]["rate"])
