"""
scripts/seed.py — Peuple la BDD avec des données de test.
Usage : flask seed-db
"""

import click
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash
from app import db
from app.models import User, Student, Teacher, Course, Enrollment, RoleEnum
from app.utils.crypto import CryptoService


@click.command("seed-db")
@with_appcontext
def seed_db():
    """Insère les données initiales (admin, enseignants, étudiants, cours)."""
    click.echo("🌱 Seeding database…")

    db.create_all()

    # ── Admin ────────────────────────────────────────────────
    if not User.query.filter_by(email="admin@usms.ac.ma").first():
        admin_user = User(
            email="admin@usms.ac.ma",
            password_hash=generate_password_hash("Admin@1234"),
            role=RoleEnum.ADMIN,
            consent_given=True,
        )
        db.session.add(admin_user)
        db.session.flush()
        click.echo("  ✅ Admin créé : admin@usms.ac.ma / Admin@1234")

    # ── Enseignants ──────────────────────────────────────────
    teachers_data = [
        ("prof.alami@usms.ac.ma",    "Prof@1234", "Mohammed", "Alami",   "Informatique"),
        ("prof.benzakour@usms.ac.ma","Prof@1234", "Fatima",   "Benzakour","Mathématiques"),
    ]
    teacher_objects = []
    for email, pwd, fn, ln, dept in teachers_data:
        if not User.query.filter_by(email=email).first():
            u = User(email=email, password_hash=generate_password_hash(pwd),
                     role=RoleEnum.TEACHER, consent_given=True)
            db.session.add(u)
            db.session.flush()
            t = Teacher(user_id=u.id, first_name=fn, last_name=ln, department=dept)
            db.session.add(t)
            db.session.flush()
            teacher_objects.append(t)
            click.echo(f"  ✅ Enseignant : {email}")

    # ── Cours ────────────────────────────────────────────────
    if teacher_objects:
        courses_data = [
            ("Algorithmique Avancée",     "INFO301", teacher_objects[0].id, "Amphi A"),
            ("Bases de Données",           "INFO302", teacher_objects[0].id, "Salle 101"),
            ("Analyse Mathématique",       "MATH201", teacher_objects[1].id if len(teacher_objects)>1 else teacher_objects[0].id, "Amphi B"),
        ]
        course_objects = []
        for name, code, tid, room in courses_data:
            if not Course.query.filter_by(code=code).first():
                c = Course(name=name, code=code, teacher_id=tid, room=room)
                db.session.add(c)
                db.session.flush()
                course_objects.append(c)
                click.echo(f"  ✅ Cours : {code} — {name}")
    else:
        course_objects = Course.query.all()

    # ── Étudiants ────────────────────────────────────────────
    students_data = [
        ("etudiant1@usms.ac.ma", "Etu@1234", "Youssef",  "El Mansouri", "INFO", 3, "G1"),
        ("etudiant2@usms.ac.ma", "Etu@1234", "Sara",      "Benali",      "INFO", 3, "G1"),
        ("etudiant3@usms.ac.ma", "Etu@1234", "Karim",     "Tazi",        "MATH", 2, "G2"),
        ("etudiant4@usms.ac.ma", "Etu@1234", "Nadia",     "Chaoui",      "INFO", 3, "G2"),
        ("etudiant5@usms.ac.ma", "Etu@1234", "Hamza",     "Ouali",       "MATH", 2, "G1"),
    ]
    student_objects = []
    for i, (email, pwd, fn, ln, prog, yr, grp) in enumerate(students_data, start=1):
        if not User.query.filter_by(email=email).first():
            u = User(email=email, password_hash=generate_password_hash(pwd),
                     role=RoleEnum.STUDENT, consent_given=True)
            db.session.add(u)
            db.session.flush()
            s = Student(
                user_id=u.id,
                student_number=f"CNE{2024000+i}",
                first_name=fn, last_name=ln,
                program=prog, year_of_study=yr, group_name=grp,
            )
            s.pseudonym = CryptoService.pseudonymize(u.id)
            db.session.add(s)
            db.session.flush()
            student_objects.append(s)
            click.echo(f"  ✅ Étudiant : {email}")

    # ── Inscriptions aux cours ───────────────────────────────
    if student_objects and course_objects:
        for s in student_objects:
            for c in course_objects:
                if not Enrollment.query.filter_by(student_id=s.id, course_id=c.id).first():
                    db.session.add(Enrollment(student_id=s.id, course_id=c.id))

    db.session.commit()
    click.echo("\n✨ Seed terminé avec succès !")
    click.echo("\n📋 Comptes de test :")
    click.echo("   Admin    : admin@usms.ac.ma          / Admin@1234")
    click.echo("   Enseignant: prof.alami@usms.ac.ma    / Prof@1234")
    click.echo("   Étudiant : etudiant1@usms.ac.ma      / Etu@1234")
