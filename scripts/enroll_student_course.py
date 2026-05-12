import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Student, Course, Enrollment
from datetime import datetime, timezone

app = create_app()

with app.app_context():

    # ─── MODIFIE CES VALEURS ────────────────────────────────
    NUMERO_APOGEE = "22000777"  # ← ton numéro apogée
    CODES_COURS   = ["ASF101", "DDO102", "TEQ103", "EDN104"]
    # ────────────────────────────────────────────────────────

    student = Student.query.filter_by(student_number=NUMERO_APOGEE).first()
    if not student:
        print(f"❌ Étudiant {NUMERO_APOGEE} introuvable.")
        sys.exit(1)

    print(f"✅ Étudiant : {student.full_name} ({NUMERO_APOGEE})")

    for code in CODES_COURS:
        course = Course.query.filter_by(code=code).first()
        if not course:
            print(f"  ⚠️  Cours {code} introuvable — ignoré.")
            continue

        existant = Enrollment.query.filter_by(
            student_id=student.id,
            course_id=course.id
        ).first()

        if existant:
            print(f"  ⚠️  Déjà inscrit à : {course.name}")
        else:
            enr = Enrollment(
                student_id=student.id,
                course_id=course.id,
                enrolled_at=datetime.now(timezone.utc)
            )
            db.session.add(enr)
            print(f"  ✅ Inscrit à : {course.name} ({code})")

    db.session.commit()
    print("\n✅ Inscriptions terminées !")