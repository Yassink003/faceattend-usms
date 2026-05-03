import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, Teacher, RoleEnum
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

app = create_app()

with app.app_context():

    # ─── MODIFIE CES INFORMATIONS ───────────────────────────
    EMAIL       = "prof.alami@usms.ac.ma"
    MOT_DE_PASSE = "Prof@1234"
    PRENOM      = "Mohammed"
    NOM         = "Alami"
    DEPARTEMENT = "Informatique"
    # ────────────────────────────────────────────────────────

    existant = User.query.filter_by(email=EMAIL).first()
    if existant:
        print(f"⚠️  Le compte {EMAIL} existe déjà.")
    else:
        u = User(
            email=EMAIL,
            password_hash=generate_password_hash(MOT_DE_PASSE),
            role=RoleEnum.TEACHER,
            is_active=True,
            consent_given=True,
            consent_date=datetime.now(timezone.utc)
        )
        db.session.add(u)
        db.session.flush()

        t = Teacher(
            user_id=u.id,
            first_name=PRENOM,
            last_name=NOM,
            department=DEPARTEMENT
        )
        db.session.add(t)
        db.session.commit()
        print(f"✅ Professeur créé avec succès !")
        print(f"   Email       : {EMAIL}")
        print(f"   Mot de passe : {MOT_DE_PASSE}")