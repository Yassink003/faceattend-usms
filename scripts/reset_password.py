import sys, os
sys.path.insert(0, os.getcwd())

from app import create_app, db
from app.models import User, RoleEnum
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

app = create_app()

# ── MODIFIE CES VALEURS ──────────────────────────────────────
REPAIRS = [
    {
        "email":       "admin@usms.ac.ma",
        "new_password": "Admin@1234",
        "role":         RoleEnum.ADMIN,
    },
    {
        "email":       "haytam.alaouil@usms.ac.ma",
        "new_password": "Haytam@2006",
        "role":         RoleEnum.STUDENT,
    },
]
# ────────────────────────────────────────────────────────────

with app.app_context():
    print("\n" + "="*60)
    print("  RESET / RÉPARATION COMPTES")
    print("="*60)

    for item in REPAIRS:
        email = item["email"]
        pwd   = item["new_password"]
        role  = item["role"]

        u = User.query.filter_by(email=email).first()

        if not u:
            print("\n  Email :", email)
            print("  ❌ Introuvable — création du compte...")
            u = User(
                email=email,
                password_hash=generate_password_hash(pwd),
                role=role,
                is_active=True,
                consent_given=True,
                consent_date=datetime.now(timezone.utc),
            )
            db.session.add(u)
            db.session.commit()
            print("  ✅ Compte créé avec succès")
            continue

        # Réinitialisation complète
        u.password_hash  = generate_password_hash(pwd)
        u.is_active      = True
        u.failed_logins  = 0
        u.locked_until   = None
        u.deleted_at     = None
        u.consent_given  = True

        db.session.add(u)
        db.session.commit()

        print("\n  Email        :", email)
        print("  Nouveau mdp  :", pwd)
        print("  Role         :", u.role.value)
        print("  ✅ Compte réparé — bloquage levé, mot de passe réinitialisé")

    print("\n" + "="*60)
    print("  Connecte-toi sur http://localhost:5000")
    print("="*60)
