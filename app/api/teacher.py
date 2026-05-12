"""Blueprint Enseignant — gestion des séances, présences en temps réel."""

from venv import logger

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from functools import wraps
import io, pandas as pd
from datetime import datetime, timezone
from app import db

from app.services.attendance_service import AttendanceService

from app.models import (
    Teacher, Course, Session, Attendance, Student,
    RoleEnum, AttendanceStatus, Justification, JustificationStatus,
    Evaluation, EvaluationStatus, AbsenceReport, AbsenceGravite,
    AbsenceReportStatus, Enrollment
)

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
    room      = request.form.get("room", "").strip()
    threshold = request.form.get("late_threshold", 15, type=int)
 
    # ── Validation ───────────────────────────────────────────
    if not course_id:
        flash("Veuillez sélectionner un cours.", "danger")
        return redirect(url_for("teacher.dashboard"))
 
    # Vérifier que le cours appartient bien à ce professeur
    teacher = Teacher.query.filter_by(user_id=current_user.id).first()
    if not teacher:
        flash("Profil enseignant introuvable.", "danger")
        return redirect(url_for("teacher.dashboard"))
 
    course = Course.query.filter_by(id=course_id, teacher_id=teacher.id).first()
    if not course:
        flash("Cours introuvable ou non autorisé.", "danger")
        return redirect(url_for("teacher.dashboard"))
 
    # Vérifier qu'il y a des étudiants inscrits
    from app.models import Enrollment
    nb_enrolled = Enrollment.query.filter_by(course_id=course_id).count()
    if nb_enrolled == 0:
        flash(f"Aucun étudiant inscrit au cours '{course.name}'. Inscrivez des étudiants d'abord.", "warning")
        return redirect(url_for("teacher.dashboard"))
 
    # ── Ouvrir la séance ──────────────────────────────────────
    try:
        session = AttendanceService.open_session(
            course_id=course_id,
            room=room or course.room or "",
            late_threshold=threshold,
        )
        flash(f"Séance ouverte — {course.name} ({nb_enrolled} étudiant(s))", "success")
        return redirect(url_for("teacher.session_live", session_id=session.id))
 
    except Exception as e:
        logger.error(f"[TEACHER] Erreur ouverture séance : {e}")
        flash(f"Erreur lors de l'ouverture de la séance : {e}", "danger")
        return redirect(url_for("teacher.dashboard"))

@teacher_bp.route("/session/<int:session_id>")
@teacher_required
def session_live(session_id):
    session = Session.query.get_or_404(session_id)

    # Charger les étudiants avec eager loading pour éviter lazy load hors contexte
    students = (
        Student.query
        .join(Attendance, Attendance.student_id == Student.id)
        .filter(Attendance.session_id == session_id)
        .order_by(Student.last_name)
        .all()
    )
    attendances = {a.student_id: a for a in session.attendances.all()}

    # S'assurer que course est bien chargé
    _ = session.course.name   # force le chargement eager

    return render_template(
        "teacher/session_live.html",
        session=session,
        students=students,
        attendances=attendances,
    )

@teacher_required
@teacher_bp.route("/session/<int:session_id>/close", methods=["POST"])
@login_required
def close_session(session_id):
    AttendanceService.close_session(session_id)
    
    # Arrêter le thread caméra
    from app.api.camera import _stop_camera
    _stop_camera()
    
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
"""
NOUVELLES ROUTES — coller à la fin de app/api/teacher.py

Imports à ajouter en haut de teacher.py :
from app.models import (
    Teacher, Course, Session, Attendance, Student,
    RoleEnum, AttendanceStatus, Justification, JustificationStatus,
    Evaluation, EvaluationStatus, AbsenceReport, AbsenceGravite,
    AbsenceReportStatus, Enrollment
)
"""

# ══════════════════════════════════════════════════════════════
#  ÉVALUATIONS
# ══════════════════════════════════════════════════════════════

@teacher_bp.route("/evaluations")
@teacher_required
def evaluations():
    """Liste de toutes les fiches d'évaluation du professeur."""
    teacher = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    course_id = request.args.get("course_id", type=int)
    statut    = request.args.get("statut", "")

    query = Evaluation.query.filter_by(teacher_id=teacher.id)
    if course_id:
        query = query.filter_by(course_id=course_id)
    if statut:
        query = query.filter_by(statut=EvaluationStatus[statut.upper()])

    fiches   = query.order_by(Evaluation.created_at.desc()).all()
    courses  = teacher.courses.filter_by(is_active=True).all()
    return render_template("teacher/evaluations.html",
                           teacher=teacher,
                           fiches=fiches,
                           courses=courses,
                           selected_course=course_id,
                           selected_statut=statut)


@teacher_bp.route("/evaluations/new", methods=["GET", "POST"])
@teacher_required
def evaluation_new():
    """Formulaire de création d'une fiche d'évaluation."""
    teacher   = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    courses   = teacher.courses.filter_by(is_active=True).all()
    course_id = request.args.get("course_id", type=int) or \
                request.form.get("course_id", type=int)
    student_id = request.args.get("student_id", type=int) or \
                 request.form.get("student_id", type=int)

    # Étudiants du cours sélectionné
    students = []
    if course_id:
        students = [e.student for e in
                    Enrollment.query.filter_by(course_id=course_id).all()]

    if request.method == "GET":
        selected_student = Student.query.get(student_id) if student_id else None
        return render_template("teacher/evaluation_form.html",
                               teacher=teacher,
                               courses=courses,
                               students=students,
                               course_id=course_id,
                               selected_student=selected_student,
                               eval=None)

    # ── POST — créer ou sauvegarder ──────────────────────────
    action     = request.form.get("action", "brouillon")
    course_id  = request.form.get("course_id",  type=int)
    student_id = request.form.get("student_id", type=int)

    if not course_id or not student_id:
        flash("Cours et étudiant obligatoires.", "danger")
        return redirect(url_for("teacher.evaluation_new"))

    ev = Evaluation(
        teacher_id         = teacher.id,
        student_id         = student_id,
        course_id          = course_id,
        note_participation = request.form.get("note_participation", 0, type=float),
        note_travail       = request.form.get("note_travail",       0, type=float),
        note_comportement  = request.form.get("note_comportement",  0, type=float),
        note_assiduite     = request.form.get("note_assiduite",     0, type=float),
        commentaire        = request.form.get("commentaire", "").strip(),
        statut             = EvaluationStatus.ENVOYEE if action == "envoyer"
                             else EvaluationStatus.BROUILLON,
        sent_at            = datetime.now(timezone.utc) if action == "envoyer" else None,
    )
    ev.calc_note_globale()
    db.session.add(ev)
    db.session.commit()

    if action == "envoyer":
        flash(f"Fiche envoyée à l'administration — Note : {ev.note_globale}/20", "success")
    else:
        flash("Fiche sauvegardée en brouillon.", "success")
    return redirect(url_for("teacher.evaluations"))


@teacher_bp.route("/evaluations/<int:eval_id>/edit", methods=["GET", "POST"])
@teacher_required
def evaluation_edit(eval_id):
    """Modifier une fiche en brouillon."""
    teacher = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    ev      = Evaluation.query.get_or_404(eval_id)

    if ev.teacher_id != teacher.id:
        flash("Accès non autorisé.", "danger")
        return redirect(url_for("teacher.evaluations"))
    if ev.statut == EvaluationStatus.ENVOYEE:
        flash("Une fiche envoyée ne peut plus être modifiée.", "warning")
        return redirect(url_for("teacher.evaluations"))

    courses  = teacher.courses.filter_by(is_active=True).all()
    students = [e.student for e in
                Enrollment.query.filter_by(course_id=ev.course_id).all()]

    if request.method == "GET":
        return render_template("teacher/evaluation_form.html",
                               teacher=teacher,
                               courses=courses,
                               students=students,
                               course_id=ev.course_id,
                               selected_student=ev.student,
                               eval=ev)

    action = request.form.get("action", "brouillon")
    ev.note_participation = request.form.get("note_participation", 0, type=float)
    ev.note_travail       = request.form.get("note_travail",       0, type=float)
    ev.note_comportement  = request.form.get("note_comportement",  0, type=float)
    ev.note_assiduite     = request.form.get("note_assiduite",     0, type=float)
    ev.commentaire        = request.form.get("commentaire", "").strip()
    ev.calc_note_globale()

    if action == "envoyer":
        ev.statut  = EvaluationStatus.ENVOYEE
        ev.sent_at = datetime.now(timezone.utc)
        flash(f"Fiche envoyée — Note : {ev.note_globale}/20", "success")
    else:
        flash("Brouillon mis à jour.", "success")

    db.session.commit()
    return redirect(url_for("teacher.evaluations"))


@teacher_bp.route("/evaluations/<int:eval_id>/delete", methods=["POST"])
@teacher_required
def evaluation_delete(eval_id):
    """Supprimer un brouillon."""
    teacher = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    ev      = Evaluation.query.get_or_404(eval_id)
    if ev.teacher_id != teacher.id or ev.statut != EvaluationStatus.BROUILLON:
        flash("Suppression impossible.", "danger")
        return redirect(url_for("teacher.evaluations"))
    db.session.delete(ev)
    db.session.commit()
    flash("Brouillon supprimé.", "success")
    return redirect(url_for("teacher.evaluations"))


# ══════════════════════════════════════════════════════════════
#  RAPPORTS D'ABSENCE
# ══════════════════════════════════════════════════════════════

@teacher_bp.route("/absence-reports")
@teacher_required
def absence_reports():
    """Liste des rapports d'absence envoyés par ce professeur."""
    teacher   = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    courses   = teacher.courses.filter_by(is_active=True).all()
    course_id = request.args.get("course_id", type=int)

    query = AbsenceReport.query.filter_by(teacher_id=teacher.id)
    if course_id:
        query = query.filter_by(course_id=course_id)
    reports = query.order_by(AbsenceReport.created_at.desc()).all()

    return render_template("teacher/absence_reports.html",
                           teacher=teacher,
                           reports=reports,
                           courses=courses,
                           selected_course=course_id)


@teacher_bp.route("/absence-reports/new", methods=["GET", "POST"])
@teacher_required
def absence_report_new():
    """Générer et envoyer un rapport d'absence pour un étudiant."""
    teacher   = Teacher.query.filter_by(user_id=current_user.id).first_or_404()
    courses   = teacher.courses.filter_by(is_active=True).all()
    course_id = request.args.get("course_id", type=int) or \
                request.form.get("course_id", type=int)
    student_id = request.args.get("student_id", type=int) or \
                 request.form.get("student_id", type=int)

    # Calcul automatique des stats si étudiant + cours sélectionnés
    stats = None
    students = []
    if course_id:
        students = [e.student for e in
                    Enrollment.query.filter_by(course_id=course_id).all()]

    if course_id and student_id:
        # Récupérer toutes les séances du cours
        sessions = Session.query.filter_by(course_id=course_id, is_closed=True).all()
        nb_seances = len(sessions)
        session_ids = [s.id for s in sessions]

        # Récupérer les présences de l'étudiant
        atts = Attendance.query.filter(
            Attendance.session_id.in_(session_ids),
            Attendance.student_id == student_id
        ).all() if session_ids else []

        nb_absences = sum(1 for a in atts if a.status == AttendanceStatus.ABSENT)
        nb_retards  = sum(1 for a in atts if a.status == AttendanceStatus.LATE)
        nb_presents = sum(1 for a in atts if a.status in
                          (AttendanceStatus.PRESENT, AttendanceStatus.LATE,
                           AttendanceStatus.EXCUSED))
        taux = round(nb_presents / nb_seances, 4) if nb_seances > 0 else 0.0

        # Gravité automatique
        if taux < 0.50:   gravite = AbsenceGravite.CRITIQUE
        elif taux < 0.75: gravite = AbsenceGravite.ATTENTION
        else:             gravite = AbsenceGravite.INFO

        stats = {
            "nb_seances":  nb_seances,
            "nb_absences": nb_absences,
            "nb_retards":  nb_retards,
            "taux":        round(taux * 100, 1),
            "gravite":     gravite,
            "sessions":    sessions,
            "attendances": {a.session_id: a for a in atts},
        }

    if request.method == "GET":
        return render_template("teacher/absence_report_form.html",
                               teacher=teacher,
                               courses=courses,
                               students=students,
                               course_id=course_id,
                               student_id=student_id,
                               stats=stats)

    # ── POST — enregistrer et envoyer ────────────────────────
    if not stats:
        flash("Sélectionnez un cours et un étudiant.", "danger")
        return redirect(url_for("teacher.absence_report_new"))

    sessions_list = Session.query.filter_by(
        course_id=course_id, is_closed=True
    ).order_by(Session.started_at).all()

    report = AbsenceReport(
        teacher_id    = teacher.id,
        student_id    = student_id,
        course_id     = course_id,
        nb_seances    = stats["nb_seances"],
        nb_absences   = stats["nb_absences"],
        nb_retards    = stats["nb_retards"],
        taux_presence = stats["taux"] / 100,
        periode_debut = sessions_list[0].started_at if sessions_list else None,
        periode_fin   = sessions_list[-1].started_at if sessions_list else None,
        commentaire   = request.form.get("commentaire", "").strip(),
        gravite       = stats["gravite"],
        statut        = AbsenceReportStatus.NOUVEAU,
    )
    db.session.add(report)
    db.session.commit()

    flash(f"Rapport d'absence envoyé à l'administration.", "success")
    return redirect(url_for("teacher.absence_reports"))
"""
Ajoute cette route dans app/api/teacher.py
Elle est appelée par le JS de evaluation_form.html via loadStudents()
"""

@teacher_bp.route("/api/courses/<int:course_id>/students")
@login_required
def api_course_students(course_id):
    """
    Retourne la liste des étudiants inscrits à un cours (JSON).
    Appelé par le JS du formulaire d'évaluation quand le prof change de cours.
    """
    from app.models import Enrollment
    teacher = Teacher.query.filter_by(user_id=current_user.id).first_or_404()

    # Vérifier que le cours appartient bien à ce professeur
    course = Course.query.filter_by(
        id=course_id, teacher_id=teacher.id
    ).first()

    if not course:
        return jsonify({"error": "Cours introuvable ou non autorisé"}), 404

    enrollments = Enrollment.query.filter_by(course_id=course_id).all()
    students = []
    for e in enrollments:
        students.append({
            "id":             e.student.id,
            "full_name":      e.student.full_name,
            "student_number": e.student.student_number,
            "face_enrolled":  e.student.face_encoding_enc is not None,
        })

    return jsonify({
        "course":   course.name,
        "code":     course.code,
        "count":    len(students),
        "students": students,
    })
