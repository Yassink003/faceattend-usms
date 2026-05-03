"""
Modèles SQLAlchemy — FaceAttend
Toutes les données biométriques sont chiffrées AES-256-GCM avant persistance.
"""

from datetime import datetime, timezone
from enum import Enum as PyEnum
from flask_login import UserMixin
from app import db
from app.utils.crypto import CryptoService


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class RoleEnum(PyEnum):
    ADMIN   = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class AttendanceStatus(PyEnum):
    PRESENT  = "present"
    ABSENT   = "absent"
    LATE     = "late"
    EXCUSED  = "excused"


class JustificationStatus(PyEnum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ─────────────────────────────────────────────
# User (base account)
# ─────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash= db.Column(db.String(255), nullable=False)
    role         = db.Column(db.Enum(RoleEnum), nullable=False)
    is_active    = db.Column(db.Boolean, default=True)
    consent_given= db.Column(db.Boolean, default=False)          # CNDP
    consent_date = db.Column(db.DateTime)
    failed_logins= db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = db.Column(db.DateTime, onupdate=lambda: datetime.now(timezone.utc))
    deleted_at   = db.Column(db.DateTime)   # Soft delete (droit à l'oubli CNDP)

    # Relations polymorphes
    student_profile = db.relationship("Student", back_populates="user", uselist=False)
    teacher_profile = db.relationship("Teacher", back_populates="user", uselist=False)

    def __repr__(self):
        return f"<User {self.email} [{self.role.value}]>"


# ─────────────────────────────────────────────
# Student
# ─────────────────────────────────────────────

class Student(db.Model):
    __tablename__ = "students"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    student_number  = db.Column(db.String(20), unique=True, nullable=False)  # CNE / Matricule
    first_name      = db.Column(db.String(100), nullable=False)
    last_name       = db.Column(db.String(100), nullable=False)
    program         = db.Column(db.String(100))   # Filière
    year_of_study   = db.Column(db.Integer)
    group_name      = db.Column(db.String(50))

    # ── Données biométriques chiffrées ──────────────────────
    # face_encoding : vecteur 128-float sérialisé puis chiffré AES-256-GCM
    # face_photo    : JPEG bytes chiffrés AES-256-GCM
    face_encoding_enc  = db.Column(db.LargeBinary)   # AES-GCM ciphertext
    face_encoding_nonce= db.Column(db.LargeBinary)   # 96-bit nonce GCM
    face_encoding_tag  = db.Column(db.LargeBinary)   # 128-bit auth tag GCM
    face_photo_enc     = db.Column(db.LargeBinary)
    face_photo_nonce   = db.Column(db.LargeBinary)
    face_photo_tag     = db.Column(db.LargeBinary)
    face_enrolled_at   = db.Column(db.DateTime)
    pseudonym          = db.Column(db.String(64), unique=True)  # Pseudonymisation CNDP

    user        = db.relationship("User", back_populates="student_profile")
    attendances = db.relationship("Attendance", back_populates="student", lazy="dynamic")
    enrollments = db.relationship("Enrollment",  back_populates="student", lazy="dynamic")

    def set_face_encoding(self, encoding_bytes: bytes):
        """Chiffre et stocke l'encodage facial (AES-256-GCM)."""
        ct, nonce, tag = CryptoService.encrypt(encoding_bytes)
        self.face_encoding_enc   = ct
        self.face_encoding_nonce = nonce
        self.face_encoding_tag   = tag
        self.face_enrolled_at    = datetime.now(timezone.utc)

    def get_face_encoding(self) -> bytes | None:
        """Déchiffre et retourne l'encodage facial."""
        if not self.face_encoding_enc:
            return None
        return CryptoService.decrypt(
            self.face_encoding_enc,
            self.face_encoding_nonce,
            self.face_encoding_tag,
        )

    def set_face_photo(self, photo_bytes: bytes):
        ct, nonce, tag = CryptoService.encrypt(photo_bytes)
        self.face_photo_enc   = ct
        self.face_photo_nonce = nonce
        self.face_photo_tag   = tag

    def get_face_photo(self) -> bytes | None:
        if not self.face_photo_enc:
            return None
        return CryptoService.decrypt(
            self.face_photo_enc,
            self.face_photo_nonce,
            self.face_photo_tag,
        )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __repr__(self):
        return f"<Student {self.student_number} — {self.full_name}>"


# ─────────────────────────────────────────────
# Teacher
# ─────────────────────────────────────────────

class Teacher(db.Model):
    __tablename__ = "teachers"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name  = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    phone      = db.Column(db.String(20))

    user    = db.relationship("User", back_populates="teacher_profile")
    courses = db.relationship("Course", back_populates="teacher", lazy="dynamic")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


# ─────────────────────────────────────────────
# Course & Enrollment
# ─────────────────────────────────────────────

class Course(db.Model):
    __tablename__ = "courses"

    id          = db.Column(db.Integer, primary_key=True)
    teacher_id  = db.Column(db.Integer, db.ForeignKey("teachers.id"))
    name        = db.Column(db.String(150), nullable=False)
    code        = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text)
    credits     = db.Column(db.Integer, default=3)
    room        = db.Column(db.String(50))
    is_active   = db.Column(db.Boolean, default=True)

    teacher     = db.relationship("Teacher", back_populates="courses")
    sessions    = db.relationship("Session", back_populates="course", lazy="dynamic")
    enrollments = db.relationship("Enrollment", back_populates="course", lazy="dynamic")


class Enrollment(db.Model):
    """Association étudiant ↔ cours."""
    __tablename__ = "enrollments"
    __table_args__ = (db.UniqueConstraint("student_id", "course_id"),)

    id          = db.Column(db.Integer, primary_key=True)
    student_id  = db.Column(db.Integer, db.ForeignKey("students.id"))
    course_id   = db.Column(db.Integer, db.ForeignKey("courses.id"))
    enrolled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    student = db.relationship("Student", back_populates="enrollments")
    course  = db.relationship("Course",  back_populates="enrollments")


# ─────────────────────────────────────────────
# Session (séance de cours)
# ─────────────────────────────────────────────

class Session(db.Model):
    __tablename__ = "sessions"

    id           = db.Column(db.Integer, primary_key=True)
    course_id    = db.Column(db.Integer, db.ForeignKey("courses.id"))
    started_at   = db.Column(db.DateTime, nullable=False)
    ended_at     = db.Column(db.DateTime)
    room         = db.Column(db.String(50))
    is_closed    = db.Column(db.Boolean, default=False)
    # Heure limite pour marquer "présent" (en minutes après started_at)
    late_threshold_minutes = db.Column(db.Integer, default=15)

    course      = db.relationship("Course", back_populates="sessions")
    attendances = db.relationship("Attendance", back_populates="session", lazy="dynamic")

    @property
    def present_count(self):
        return self.attendances.filter_by(status=AttendanceStatus.PRESENT).count()

    @property
    def absent_count(self):
        return self.attendances.filter_by(status=AttendanceStatus.ABSENT).count()


# ─────────────────────────────────────────────
# Attendance
# ─────────────────────────────────────────────

class Attendance(db.Model):
    __tablename__ = "attendances"
    __table_args__ = (db.UniqueConstraint("session_id", "student_id"),)

    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey("sessions.id"))
    student_id   = db.Column(db.Integer, db.ForeignKey("students.id"))
    status       = db.Column(db.Enum(AttendanceStatus), default=AttendanceStatus.ABSENT)
    detected_at  = db.Column(db.DateTime)
    confidence   = db.Column(db.Float)         # Score de similarité faciale
    method       = db.Column(db.String(20), default="face")  # face | manual

    session = db.relationship("Session",  back_populates="attendances")
    student = db.relationship("Student",  back_populates="attendances")
    justification = db.relationship("Justification", back_populates="attendance", uselist=False)


# ─────────────────────────────────────────────
# Justification d'absence
# ─────────────────────────────────────────────

class Justification(db.Model):
    __tablename__ = "justifications"

    id            = db.Column(db.Integer, primary_key=True)
    attendance_id = db.Column(db.Integer, db.ForeignKey("attendances.id"), unique=True)
    reason        = db.Column(db.Text, nullable=False)
    document_path = db.Column(db.String(255))   # Chemin vers justificatif uploadé
    status        = db.Column(db.Enum(JustificationStatus), default=JustificationStatus.PENDING)
    submitted_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at   = db.Column(db.DateTime)
    reviewer_note = db.Column(db.Text)

    attendance = db.relationship("Attendance", back_populates="justification")


# ─────────────────────────────────────────────
# Audit Log (traçabilité CNDP)
# ─────────────────────────────────────────────

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    action     = db.Column(db.String(100), nullable=False)
    resource   = db.Column(db.String(100))
    resource_id= db.Column(db.Integer)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    timestamp  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    details    = db.Column(db.JSON)

    user = db.relationship("User")
