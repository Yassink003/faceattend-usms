"""Blueprint Administration — tableau de bord global, analytics, gestion utilisateurs."""

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from functools import wraps
from loguru import logger
import io, pandas as pd
from sqlalchemy import func
from datetime import datetime, timedelta, timezone

from app import db
from app.models import User, Student, Teacher, Course, Session, Attendance, RoleEnum, AttendanceStatus
from app.services.attendance_service import AttendanceService
from app.utils.crypto import CryptoService
from app.models import User, Student, Teacher, Course, Session, Attendance, RoleEnum, AttendanceStatus, Enrollment
from app.models import  Evaluation, EvaluationStatus,AbsenceReport, AbsenceGravite, AbsenceReportStatus
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

# ═══════════════════════════════════════════════════════════════
##  COLLE CE BLOC dans app/api/admin.py
##  juste après la route def students() (ligne ~60)
## ═══════════════════════════════════════════════════════════════

@admin_bp.route("/students/new", methods=["GET", "POST"])
@admin_required
def create_student():
    """Formulaire de création d'un étudiant depuis l'interface admin."""
    from werkzeug.security import generate_password_hash
    from datetime import datetime, timezone
    from app.models import Course, Enrollment, RoleEnum
    from app.utils.crypto import CryptoService

    courses = Course.query.filter_by(is_active=True).order_by(Course.code).all()

    if request.method == "GET":
        return render_template("admin/create_student.html",
                               courses=courses, form_data=None)

    # ── Récupération des champs ──────────────────────────────
    first_name     = request.form.get("first_name",     "").strip()
    last_name      = request.form.get("last_name",      "").strip()
    student_number = request.form.get("student_number", "").strip()
    program        = request.form.get("program",        "").strip()
    year_of_study  = request.form.get("year_of_study",  type=int)
    group_name     = request.form.get("group_name",     "").strip()
    email          = request.form.get("email",          "").strip().lower()
    password       = request.form.get("password",       "")
    password_confirm = request.form.get("password_confirm", "")
    course_ids     = request.form.getlist("course_ids")

    # ── Validations ──────────────────────────────────────────
    errors = []

    if not first_name:
        errors.append("Le prénom est obligatoire.")
    if not last_name:
        errors.append("Le nom est obligatoire.")
    if not student_number:
        errors.append("Le matricule est obligatoire.")
    if not program:
        errors.append("La filière est obligatoire.")
    if not year_of_study:
        errors.append("L'année d'étude est obligatoire.")
    if not email:
        errors.append("L'email est obligatoire.")

    import re
    pwd_errors = []
    if len(password) < 8:
        pwd_errors.append("au moins 8 caractères")
    if not re.search(r"[A-Z]", password):
        pwd_errors.append("une majuscule")
    if not re.search(r"[a-z]", password):
        pwd_errors.append("une minuscule")
    if not re.search(r"[0-9]", password):
        pwd_errors.append("un chiffre")
    if not re.search(r"[^A-Za-z0-9]", password):
        pwd_errors.append("un caractère spécial (@, #, !, ...)")
    if pwd_errors:
        errors.append("Mot de passe trop faible — requis : " + ", ".join(pwd_errors) + ".")
    if password != password_confirm:
        errors.append("Les mots de passe ne correspondent pas.")

    # Unicité email
    if User.query.filter_by(email=email).first():
        errors.append(f"L'email '{email}' est déjà utilisé.")

    # Unicité matricule
    if Student.query.filter_by(student_number=student_number).first():
        errors.append(f"Le matricule '{student_number}' est déjà utilisé.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("admin/create_student.html",
                               courses=courses, form_data=request.form)

    # ── Création User ────────────────────────────────────────
    try:
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role=RoleEnum.STUDENT,
            is_active=True,
            consent_given=True,
            consent_date=datetime.now(timezone.utc),
        )
        db.session.add(user)
        db.session.flush()   # récupère user.id

        # ── Création Student ─────────────────────────────────
        student = Student(
            user_id=user.id,
            student_number=student_number,
            first_name=first_name,
            last_name=last_name,
            program=program,
            year_of_study=year_of_study,
            group_name=group_name or None,
        )
        student.pseudonym = CryptoService.pseudonymize(user.id)
        db.session.add(student)
        db.session.flush()   # récupère student.id

        # ── Inscriptions aux cours ───────────────────────────
        enrolled_courses = []
        for cid in course_ids:
            try:
                cid_int = int(cid)
            except ValueError:
                continue
            course = Course.query.get(cid_int)
            if course and not Enrollment.query.filter_by(
                student_id=student.id, course_id=cid_int
            ).first():
                db.session.add(Enrollment(
                    student_id=student.id,
                    course_id=cid_int,
                    enrolled_at=datetime.now(timezone.utc),
                ))
                enrolled_courses.append(course.code)

        db.session.commit()

        logger.info(
            f"[ADMIN] Étudiant créé : {student.full_name} "
            f"({student_number}) par {current_user.email}"
        )

        msg = f"Étudiant {first_name} {last_name} ({student_number}) créé avec succès."
        if enrolled_courses:
            msg += f" Inscrit à : {', '.join(enrolled_courses)}."
        flash(msg, "success")
        return redirect(url_for("admin.students"))

    except Exception as e:
        db.session.rollback()
        logger.error(f"[ADMIN] Erreur création étudiant : {e}")
        flash(f"Erreur lors de la création : {e}", "danger")
        return render_template("admin/create_student.html",
                               courses=courses, form_data=request.form)

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
    """Données pour les graphiques Chart.js du dashboard (présences, absences, tendances)."""
    now = datetime.now(timezone.utc)

    # ── Taux & répartition par cours (séances clôturées) ──
    courses = Course.query.filter_by(is_active=True).limit(10).all()
    chart_data = []
    for c in courses:
        sessions = c.sessions.filter_by(is_closed=True).all()
        if not sessions:
            continue
        total = present = late = absent = excused = 0
        for s in sessions:
            for st in (
                AttendanceStatus.PRESENT,
                AttendanceStatus.LATE,
                AttendanceStatus.ABSENT,
                AttendanceStatus.EXCUSED,
            ):
                n = s.attendances.filter_by(status=st).count()
                total += n
                if st == AttendanceStatus.PRESENT:
                    present += n
                elif st == AttendanceStatus.LATE:
                    late += n
                elif st == AttendanceStatus.ABSENT:
                    absent += n
                else:
                    excused += n
        chart_data.append({
            "course": c.code,
            "rate": round((present + late) / total * 100, 1) if total else 0,
            "present": present,
            "late": late,
            "absent": absent,
            "excused": excused,
            "total": total,
        })

    # ── Mix global des statuts (60 derniers jours) ──
    cutoff_mix = now - timedelta(days=60)
    mix_rows = (
        db.session.query(Attendance.status, func.count(Attendance.id))
        .join(Session, Session.id == Attendance.session_id)
        .filter(Session.is_closed.is_(True), Session.started_at >= cutoff_mix)
        .group_by(Attendance.status)
        .all()
    )
    mix_map = {row[0]: row[1] for row in mix_rows}
    status_mix = {
        "present": int(mix_map.get(AttendanceStatus.PRESENT, 0)),
        "late": int(mix_map.get(AttendanceStatus.LATE, 0)),
        "absent": int(mix_map.get(AttendanceStatus.ABSENT, 0)),
        "excused": int(mix_map.get(AttendanceStatus.EXCUSED, 0)),
    }

    # ── Tendance des absences (14 derniers jours, par date de séance) ──
    cutoff_trend = now - timedelta(days=14)
    trend_rows = (
        db.session.query(
            func.date(Session.started_at).label("day"),
            func.count(Attendance.id),
        )
        .select_from(Attendance)
        .join(Session, Session.id == Attendance.session_id)
        .filter(
            Attendance.status == AttendanceStatus.ABSENT,
            Session.started_at >= cutoff_trend,
        )
        .group_by(func.date(Session.started_at))
        .order_by(func.date(Session.started_at))
        .all()
    )
    trend_map = {str(r[0]): int(r[1]) for r in trend_rows}
    trend_labels = []
    trend_counts = []
    for i in range(13, -1, -1):
        d = (now - timedelta(days=i)).date()
        key = d.isoformat()
        trend_labels.append(d.strftime("%d/%m"))
        trend_counts.append(trend_map.get(key, 0))

    return jsonify({
        "courses": chart_data,
        "status_mix": status_mix,
        "absence_trend": {"labels": trend_labels, "counts": trend_counts},
    })

import re as _re
from werkzeug.security import generate_password_hash


# ══════════════════════════════════════════════════════════════
#  PROFESSEURS
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/teachers")
@admin_required
def teachers():
    page   = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query  = Teacher.query.join(User).filter(User.deleted_at.is_(None))
    if search:
        query = query.filter(
            db.or_(
                Teacher.first_name.ilike(f"%{search}%"),
                Teacher.last_name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                Teacher.department.ilike(f"%{search}%"),
            )
        )
    pagination = query.order_by(Teacher.last_name).paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/teachers.html", pagination=pagination, search=search)


@admin_bp.route("/teachers/new", methods=["GET", "POST"])
@admin_required
def create_teacher():
    courses = Course.query.filter_by(is_active=True).order_by(Course.code).all()

    if request.method == "GET":
        return render_template("admin/create_teacher.html", courses=courses, form_data=None)

    # ── Récupération des champs ──────────────────────────────
    first_name  = request.form.get("first_name",  "").strip()
    last_name   = request.form.get("last_name",   "").strip()
    department  = request.form.get("department",  "").strip()
    phone       = request.form.get("phone",       "").strip()
    email       = request.form.get("email",       "").strip().lower()
    password    = request.form.get("password",    "")
    password2   = request.form.get("password_confirm", "")
    course_ids  = request.form.getlist("course_ids")

    # ── Validations ──────────────────────────────────────────
    errors = []
    if not first_name:  errors.append("Le prénom est obligatoire.")
    if not last_name:   errors.append("Le nom est obligatoire.")
    if not email:       errors.append("L'email est obligatoire.")

    # Mot de passe fort
    pwd_errors = []
    if len(password) < 8:               pwd_errors.append("au moins 8 caractères")
    if not _re.search(r"[A-Z]", password): pwd_errors.append("une majuscule")
    if not _re.search(r"[a-z]", password): pwd_errors.append("une minuscule")
    if not _re.search(r"[0-9]", password): pwd_errors.append("un chiffre")
    if not _re.search(r"[^A-Za-z0-9]", password): pwd_errors.append("un caractère spécial")
    if pwd_errors:
        errors.append("Mot de passe trop faible — requis : " + ", ".join(pwd_errors) + ".")
    if password != password2:
        errors.append("Les mots de passe ne correspondent pas.")

    # Unicité email
    if User.query.filter_by(email=email).first():
        errors.append(f"L'email '{email}' est déjà utilisé.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("admin/create_teacher.html", courses=courses, form_data=request.form)

    # ── Création User ────────────────────────────────────────
    try:
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role=RoleEnum.TEACHER,
            is_active=True,
            consent_given=True,
            consent_date=datetime.now(timezone.utc),
        )
        db.session.add(user)
        db.session.flush()

        # ── Création Teacher ─────────────────────────────────
        teacher = Teacher(
            user_id=user.id,
            first_name=first_name,
            last_name=last_name,
            department=department or None,
            phone=phone or None,
        )
        db.session.add(teacher)
        db.session.flush()

        # ── Assignation des cours ────────────────────────────
        assigned = []
        for cid in course_ids:
            try:
                course = Course.query.get(int(cid))
                if course:
                    course.teacher_id = teacher.id
                    db.session.add(course)
                    assigned.append(course.code)
            except (ValueError, TypeError):
                continue

        db.session.commit()
        logger.info(f"[ADMIN] Professeur créé : {teacher.full_name} par {current_user.email}")

        msg = f"Professeur {first_name} {last_name} créé avec succès."
        if assigned:
            msg += f" Cours assignés : {', '.join(assigned)}."
        flash(msg, "success")
        return redirect(url_for("admin.teachers"))

    except Exception as e:
        db.session.rollback()
        logger.error(f"[ADMIN] Erreur création professeur : {e}")
        flash(f"Erreur : {e}", "danger")
        return render_template("admin/create_teacher.html", courses=courses, form_data=request.form)


@admin_bp.route("/teachers/<int:teacher_id>")
@admin_required
def teacher_detail(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    courses = teacher.courses.filter_by(is_active=True).all()
    all_courses = Course.query.filter_by(is_active=True).order_by(Course.code).all()
    return render_template("admin/teacher_detail.html",
                           teacher=teacher, courses=courses, all_courses=all_courses)


# ══════════════════════════════════════════════════════════════
#  MATIÈRES / COURS
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/courses")
@admin_required
def courses():
    page   = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query  = Course.query
    if search:
        query = query.filter(
            db.or_(
                Course.name.ilike(f"%{search}%"),
                Course.code.ilike(f"%{search}%"),
                Course.room.ilike(f"%{search}%"),
            )
        )
    pagination = query.order_by(Course.code).paginate(page=page, per_page=20, error_out=False)
    return render_template("admin/courses.html", pagination=pagination, search=search)


@admin_bp.route("/courses/new", methods=["GET", "POST"])
@admin_required
def create_course():
    teachers = Teacher.query.join(User).filter(User.is_active == True).order_by(Teacher.last_name).all()
    students = Student.query.join(User).filter(User.deleted_at.is_(None)).order_by(Student.last_name).all()

    if request.method == "GET":
        return render_template("admin/create_course.html",
                               teachers=teachers, students=students, form_data=None)

    # ── Récupération des champs ──────────────────────────────
    name        = request.form.get("name",       "").strip()
    code        = request.form.get("code",       "").strip().upper()
    description = request.form.get("description","").strip()
    credits     = request.form.get("credits",    3, type=int)
    room        = request.form.get("room",       "").strip()
    teacher_id  = request.form.get("teacher_id", type=int)
    is_active   = request.form.get("is_active",  "1") == "1"
    student_ids = request.form.getlist("student_ids")

    # ── Validations ──────────────────────────────────────────
    errors = []
    if not name:        errors.append("L'intitulé de la matière est obligatoire.")
    if not code:        errors.append("Le code matière est obligatoire.")
    if not room:        errors.append("La salle est obligatoire.")
    if not teacher_id:  errors.append("L'enseignant responsable est obligatoire.")

    if code and Course.query.filter_by(code=code).first():
        errors.append(f"Le code '{code}' est déjà utilisé par une autre matière.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("admin/create_course.html",
                               teachers=teachers, students=students, form_data=request.form)

    # ── Création du cours ────────────────────────────────────
    try:
        course = Course(
            name=name,
            code=code,
            description=description or None,
            credits=credits,
            room=room,
            teacher_id=teacher_id,
            is_active=is_active,
        )
        db.session.add(course)
        db.session.flush()

        # ── Inscriptions étudiants ───────────────────────────
        enrolled = []
        from app.models import Enrollment
        for sid in student_ids:
            try:
                sid_int = int(sid)
                if not Enrollment.query.filter_by(student_id=sid_int, course_id=course.id).first():
                    db.session.add(Enrollment(
                        student_id=sid_int,
                        course_id=course.id,
                        enrolled_at=datetime.now(timezone.utc),
                    ))
                    enrolled.append(sid_int)
            except (ValueError, TypeError):
                continue

        db.session.commit()
        logger.info(f"[ADMIN] Matière créée : {code} — {name} par {current_user.email}")

        msg = f"Matière '{name}' ({code}) créée avec succès."
        if enrolled:
            msg += f" {len(enrolled)} étudiant(s) inscrit(s)."
        flash(msg, "success")
        return redirect(url_for("admin.courses"))

    except Exception as e:
        db.session.rollback()
        logger.error(f"[ADMIN] Erreur création matière : {e}")
        flash(f"Erreur : {e}", "danger")
        return render_template("admin/create_course.html",
                               teachers=teachers, students=students, form_data=request.form)


@admin_bp.route("/courses/<int:course_id>")
@admin_required
def course_detail(course_id):
    course   = Course.query.get_or_404(course_id)
    enrolled = course.enrollments.all()
    sessions = course.sessions.order_by(Session.started_at.desc()).limit(10).all()
    return render_template("admin/course_detail.html",
                           course=course, enrolled=enrolled, sessions=sessions)


# ══════════════════════════════════════════════════════════════
#  LISTE ÉTUDIANTS PAR COURS (API JSON — pour sélecteur dynamique)
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/api/courses/<int:course_id>/students")
@admin_required
def api_course_students(course_id):
    course = Course.query.get_or_404(course_id)
    enrolled = [
        {
            "id":             e.student.id,
            "full_name":      e.student.full_name,
            "student_number": e.student.student_number,
            "program":        e.student.program,
            "enrolled_at":    e.enrolled_at.isoformat() if e.enrolled_at else None,
            "face_enrolled":  e.student.face_encoding_enc is not None,
        }
        for e in course.enrollments.all()
    ]
    return jsonify({
        "course": course.name,
        "code":   course.code,
        "count":  len(enrolled),
        "students": enrolled,
    })
"""
NOUVELLES ROUTES ADMIN — coller à la fin de app/api/admin.py

Imports supplémentaires à ajouter en haut de admin.py :
from app.models import (
    User, Student, Teacher, Course, Session, Attendance,
    RoleEnum, AttendanceStatus, Enrollment, Justification,
    Evaluation, EvaluationStatus,
    AbsenceReport, AbsenceGravite, AbsenceReportStatus
)
"""

import re as _re
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash


# ══════════════════════════════════════════════════════════════
#  ÉVALUATIONS — VUE ADMIN
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/evaluations")
@admin_required
def evaluations():
    """Toutes les fiches d'évaluation envoyées par les professeurs."""
    course_id  = request.args.get("course_id",  type=int)
    teacher_id = request.args.get("teacher_id", type=int)
    student_id = request.args.get("student_id", type=int)
    page       = request.args.get("page", 1, type=int)

    query = Evaluation.query.filter_by(statut=EvaluationStatus.ENVOYEE)
    if course_id:  query = query.filter_by(course_id=course_id)
    if teacher_id: query = query.filter_by(teacher_id=teacher_id)
    if student_id: query = query.filter_by(student_id=student_id)

    pagination = query.order_by(Evaluation.sent_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    teachers = Teacher.query.join(User).filter(User.is_active == True).all()
    courses  = Course.query.filter_by(is_active=True).all()
    students = Student.query.join(User).filter(User.deleted_at.is_(None)).all()

    return render_template("admin/evaluations.html",
                           pagination=pagination,
                           teachers=teachers,
                           courses=courses,
                           students=students,
                           f_course=course_id,
                           f_teacher=teacher_id,
                           f_student=student_id)


@admin_bp.route("/evaluations/<int:eval_id>/comment", methods=["POST"])
@admin_required
def evaluation_comment(eval_id):
    """Ajouter un commentaire admin sur une fiche."""
    ev = Evaluation.query.get_or_404(eval_id)
    ev.admin_commentaire = request.form.get("commentaire", "").strip()
    db.session.commit()
    flash("Commentaire enregistré.", "success")
    return redirect(url_for("admin.evaluations"))


@admin_bp.route("/evaluations/<int:eval_id>/archive", methods=["POST"])
@admin_required
def evaluation_archive(eval_id):
    """Archiver une fiche d'évaluation."""
    ev = Evaluation.query.get_or_404(eval_id)
    ev.statut             = EvaluationStatus.ARCHIVEE
    ev.admin_archived_at  = datetime.now(timezone.utc)
    db.session.commit()
    flash("Fiche archivée.", "success")
    return redirect(url_for("admin.evaluations"))


# ══════════════════════════════════════════════════════════════
#  RAPPORTS D'ABSENCE — VUE ADMIN
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/absence-reports")
@admin_required
def absence_reports():
    """Tous les rapports d'absence reçus."""
    course_id  = request.args.get("course_id",  type=int)
    teacher_id = request.args.get("teacher_id", type=int)
    gravite    = request.args.get("gravite",    "")
    statut     = request.args.get("statut",     "")
    page       = request.args.get("page", 1, type=int)

    query = AbsenceReport.query
    if course_id:  query = query.filter_by(course_id=course_id)
    if teacher_id: query = query.filter_by(teacher_id=teacher_id)
    if gravite:    query = query.filter_by(gravite=AbsenceGravite[gravite.upper()])
    if statut:     query = query.filter_by(statut=AbsenceReportStatus[statut.upper()])

    pagination = query.order_by(AbsenceReport.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    teachers = Teacher.query.all()
    courses  = Course.query.filter_by(is_active=True).all()

    return render_template("admin/absence_reports.html",
                           pagination=pagination,
                           teachers=teachers,
                           courses=courses,
                           f_course=course_id,
                           f_teacher=teacher_id,
                           f_gravite=gravite,
                           f_statut=statut)


@admin_bp.route("/absence-reports/<int:report_id>/treat", methods=["POST"])
@admin_required
def absence_report_treat(report_id):
    """Marquer un rapport comme vu ou traité."""
    report     = AbsenceReport.query.get_or_404(report_id)
    action     = request.form.get("action", "vu")
    admin_note = request.form.get("admin_note", "").strip()

    report.admin_note = admin_note
    if action == "traite":
        report.statut           = AbsenceReportStatus.TRAITE
        report.admin_treated_at = datetime.now(timezone.utc)
    else:
        report.statut = AbsenceReportStatus.VU

    db.session.commit()
    flash(f"Rapport marqué comme {'traité' if action == 'traite' else 'vu'}.", "success")
    return redirect(url_for("admin.absence_reports"))


# ══════════════════════════════════════════════════════════════
#  ÉDITION ÉTUDIANT
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@admin_required
def student_edit(student_id):
    """Modifier toutes les informations d'un étudiant."""
    student  = Student.query.get_or_404(student_id)
    user     = student.user
    courses  = Course.query.filter_by(is_active=True).order_by(Course.code).all()
    enrolled = {e.course_id for e in student.enrollments.all()}

    if request.method == "GET":
        return render_template("admin/student_edit.html",
                               student=student,
                               user=user,
                               courses=courses,
                               enrolled=enrolled)

    action = request.form.get("action", "identite")

    # ── Onglet Identité ──────────────────────────────────────
    if action == "identite":
         student.first_name    = request.form.get("first_name",    student.first_name).strip()
         student.last_name     = request.form.get("last_name",     student.last_name).strip()
         student.program       = request.form.get("program",       student.program or "").strip()
         student.year_of_study = request.form.get("year_of_study", student.year_of_study, type=int)
         student.group_name    = request.form.get("group_name",    student.group_name or "").strip() or None

         new_email = request.form.get("email", user.email).strip().lower()
         if new_email != user.email:
           # Vérifier unicité SEULEMENT si email différent
            existing = User.query.filter(
            User.email == new_email,
            User.id != user.id        # ← exclure l'utilisateur lui-même
            ).first()
         if existing:
            flash(f"L'email '{new_email}' est déjà utilisé.", "danger")
            return redirect(url_for("admin.student_edit", student_id=student_id))
            user.email = new_email
 
         db.session.add(student)
         db.session.add(user)
         db.session.commit()
         flash("Informations mises à jour.", "success")

    # ── Onglet Sécurité — reset mot de passe ─────────────────
    elif action == "password":
        pwd  = request.form.get("password", "")
        pwd2 = request.form.get("password_confirm", "")
        errors = []
        if len(pwd) < 8:                   errors.append("8 caractères minimum")
        if not _re.search(r"[A-Z]", pwd):  errors.append("une majuscule")
        if not _re.search(r"[a-z]", pwd):  errors.append("une minuscule")
        if not _re.search(r"[0-9]", pwd):  errors.append("un chiffre")
        if not _re.search(r"[^A-Za-z0-9]", pwd): errors.append("un caractère spécial")
        if pwd != pwd2: errors.append("les mots de passe ne correspondent pas")
        if errors:
            flash("Mot de passe invalide : " + ", ".join(errors) + ".", "danger")
        else:
            user.password_hash  = generate_password_hash(pwd)
            user.failed_logins  = 0
            user.locked_until   = None
            db.session.commit()
            flash("Mot de passe réinitialisé.", "success")

    # ── Onglet Statut ────────────────────────────────────────
    elif action == "statut":
        user.is_active = request.form.get("is_active") == "1"
        db.session.commit()
        flash(f"Compte {'activé' if user.is_active else 'désactivé'}.", "success")

    # ── Onglet Cours — ajouter / retirer ─────────────────────
    elif action == "cours":
        new_ids = set(int(x) for x in request.form.getlist("course_ids"))

        # Retirer les cours décochés
        for enr in student.enrollments.all():
            if enr.course_id not in new_ids:
                db.session.delete(enr)

        # Ajouter les nouveaux
        for cid in new_ids:
            if cid not in enrolled:
                db.session.add(Enrollment(
                    student_id=student.id,
                    course_id=cid,
                    enrolled_at=datetime.now(timezone.utc)
                ))
        db.session.commit()
        flash("Inscriptions aux cours mises à jour.", "success")

    # ── Onglet Biométrie — reset enrôlement ──────────────────
    elif action == "biometrie":
        student.face_encoding_enc   = None
        student.face_encoding_nonce = None
        student.face_encoding_tag   = None
        student.face_photo_enc      = None
        student.face_photo_nonce    = None
        student.face_photo_tag      = None
        student.face_enrolled_at    = None
        db.session.add(student)
        db.session.commit()
        flash("Données biométriques supprimées. Ré-enrôlement nécessaire.", "warning")

    # ── Onglet Danger — soft delete ──────────────────────────
    elif action == "supprimer":
        confirm = request.form.get("confirm_email", "")
        if confirm != user.email:
            flash("Email de confirmation incorrect.", "danger")
        else:
            user.deleted_at  = datetime.now(timezone.utc)
            user.is_active   = False
            db.session.commit()
            flash(f"Compte {user.email} supprimé.", "success")
            return redirect(url_for("admin.students"))

    return redirect(url_for("admin.student_edit", student_id=student_id))


# ══════════════════════════════════════════════════════════════
#  ÉDITION PROFESSEUR
# ══════════════════════════════════════════════════════════════

@admin_bp.route("/teachers/<int:teacher_id>/edit", methods=["GET", "POST"])
@admin_required
def teacher_edit(teacher_id):
    """Modifier toutes les informations d'un professeur."""
    teacher = Teacher.query.get_or_404(teacher_id)
    user    = teacher.user
    courses_all      = Course.query.filter_by(is_active=True).order_by(Course.code).all()
    assigned_courses = {c.id for c in teacher.courses.all()}

    if request.method == "GET":
        return render_template("admin/teacher_edit.html",
                               teacher=teacher,
                               user=user,
                               courses_all=courses_all,
                               assigned_courses=assigned_courses)

    action = request.form.get("action", "identite")

    # ── Identité ─────────────────────────────────────────────
    if action == "identite":
        teacher.first_name = request.form.get("first_name", teacher.first_name).strip()
        teacher.last_name  = request.form.get("last_name",  teacher.last_name).strip()
        teacher.department = request.form.get("department", teacher.department or "").strip() or None
        teacher.phone      = request.form.get("phone",      teacher.phone or "").strip() or None

        new_email = request.form.get("email", user.email).strip().lower()
        if new_email != user.email:
            if User.query.filter_by(email=new_email).first():
                flash("Cet email est déjà utilisé.", "danger")
                return redirect(url_for("admin.teacher_edit", teacher_id=teacher_id))
            user.email = new_email

        db.session.commit()
        flash("Informations mises à jour.", "success")

    # ── Mot de passe ──────────────────────────────────────────
    elif action == "password":
        pwd  = request.form.get("password", "")
        pwd2 = request.form.get("password_confirm", "")
        errors = []
        if len(pwd) < 8:                   errors.append("8 caractères minimum")
        if not _re.search(r"[A-Z]", pwd):  errors.append("une majuscule")
        if not _re.search(r"[a-z]", pwd):  errors.append("une minuscule")
        if not _re.search(r"[0-9]", pwd):  errors.append("un chiffre")
        if not _re.search(r"[^A-Za-z0-9]", pwd): errors.append("un caractère spécial")
        if pwd != pwd2: errors.append("les mots de passe ne correspondent pas")
        if errors:
            flash("Mot de passe invalide : " + ", ".join(errors) + ".", "danger")
        else:
            user.password_hash = generate_password_hash(pwd)
            user.failed_logins = 0
            user.locked_until  = None
            db.session.commit()
            flash("Mot de passe réinitialisé.", "success")

    # ── Cours assignés ────────────────────────────────────────
    elif action == "cours":
        new_ids = set(int(x) for x in request.form.getlist("course_ids"))
        for c in courses_all:
            if c.id in new_ids:
                c.teacher_id = teacher.id
            elif c.teacher_id == teacher.id:
                c.teacher_id = None
        db.session.commit()
        flash("Cours mis à jour.", "success")

    # ── Statut ────────────────────────────────────────────────
    elif action == "statut":
        user.is_active = request.form.get("is_active") == "1"
        db.session.commit()
        flash(f"Compte {'activé' if user.is_active else 'désactivé'}.", "success")

    # ── Suppression ───────────────────────────────────────────
    elif action == "supprimer":
        if request.form.get("confirm_email") != user.email:
            flash("Email de confirmation incorrect.", "danger")
        else:
            user.deleted_at = datetime.now(timezone.utc)
            user.is_active  = False
            db.session.commit()
            flash(f"Compte {user.email} supprimé.", "success")
            return redirect(url_for("admin.teachers"))

    return redirect(url_for("admin.teacher_edit", teacher_id=teacher_id))

