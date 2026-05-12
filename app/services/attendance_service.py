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
from sqlalchemy import func


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
        # APRÈS (1 seule requête SQL) :
        enrollments = Enrollment.query.filter_by(course_id=course_id).all()
        db.session.bulk_insert_mappings(Attendance, [
          {
             "session_id": session.id,
             "student_id": enr.student_id,
             "status":     AttendanceStatus.ABSENT,
             "method":     "face",
          }
          for enr in enrollments
        ])

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
                              known_encodings: list[dict],
                              spoof_service=None) -> list[dict]:
        """
        Reçoit un frame OpenCV, identifie les visages et marque les présences.
        Si spoof_service fourni, vérifie la vivacité avant de pointer.
        Retourne la liste des détections.
        """
        detections = FaceRecognitionService.identify_faces_in_frame(
            frame,
            known_encodings,
            spoof_service=spoof_service    # ← passer le service anti-spoofing
        )

        for d in detections:
            # Bloquer les tentatives de spoofing
            if d.get("spoof"):
                logger.warning(
                    f"[ATTENDANCE] Spoof bloqué — "
                    f"score={d.get('liveness', {}).get('score', 0):.2f}"
                )
                continue

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
       """Détecte les étudiants en décrochage — 1 seule requête SQL agrégée."""
       rows = (
            db.session.query(
                Student,
                func.count(Attendance.id).label("total"),
                func.sum(db.case(
                   (Attendance.status.in_([
                       AttendanceStatus.PRESENT,
                       AttendanceStatus.LATE
                   ]), 1),
                   else_=0
                )).label("present")
        )
          .join(Attendance, Attendance.student_id == Student.id)
          .group_by(Student.id)
          .having(func.count(Attendance.id) >= 3)
          .all()
       )
       result = []
       for student, total, present in rows:
           present = present or 0
           rate    = round(present / total * 100, 1) if total else 0
           if rate / 100 < threshold:
               result.append({
                   "student": student,
                   "stats": {
                      "total":   total,
                      "present": present,
                      "absent":  total - present,
                      "rate":    rate,
                      "at_risk": True,
                  }
             })
       return sorted(result, key=lambda x: x["stats"]["rate"])
