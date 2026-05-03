import sys, os
sys.path.insert(0, os.getcwd())

from app import create_app, db
from app.models import User, Student, RoleEnum
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

app = create_app()

with app.app_context():
    # Créer le compte utilisateur
    u = User(
        email="yassine.klloul@usms.ac.ma",
        password_hash=generate_password_hash("yass1234@"),
        role=RoleEnum.STUDENT,
        is_active=True,
        consent_given=True,
        consent_date=datetime.now(timezone.utc)
    )
    db.session.add(u)
    db.session.flush()

    # Créer le profil étudiant
    s = Student(
        user_id=u.id,
        student_number="21000120",
        first_name="Yassine",       # ← change ici
        last_name="Kelloul",           # ← change ici
        program="INFO",                # ← ta filière
        year_of_study=3,               # ← ton année
        group_name="G1"                # ← ton groupe
    )
    db.session.add(s)
    db.session.commit()
    print("✅ Étudiant 21000120 créé avec succès !")