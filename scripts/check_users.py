import sys, os
sys.path.insert(0, os.getcwd())

from app import create_app, db
from app.models import User
from werkzeug.security import check_password_hash

app = create_app()

# Comptes et mots de passe à tester
tests = [
    ("admin@usms.ac.ma",           "Admin@1234"),
    ("haytam.alaouil@usms.ac.ma",  "Haytam@2006"),
    ("haytam.alaouil@usms.ac.ma",  "haytam1234@"),
]

with app.app_context():
    print("\n" + "="*70)
    print("  DIAGNOSTIC COMPTES UTILISATEURS")
    print("="*70)

    for email, pwd in tests:
        print("\n  Email    :", email)
        print("  Password :", pwd)

        u = User.query.filter_by(email=email).first()

        if not u:
            print("  BDD      : ❌ EMAIL INTROUVABLE EN BASE")
            print("             → recrée le compte avec create_student.py ou seed-db")
            continue

        pwd_ok  = check_password_hash(u.password_hash, pwd)
        locked  = str(u.locked_until) if u.locked_until else "Non"
        deleted = str(u.deleted_at)   if u.deleted_at   else "Non"

        print("  Role     :", u.role.value)
        print("  Actif    :", u.is_active)
        print("  Password :", "✅ CORRECT" if pwd_ok else "❌ INCORRECT")
        print("  Bloqué   :", locked)
        print("  Deleted  :", deleted)
        print("  Echecs   :", u.failed_logins)

        if not pwd_ok:
            print("  → FIX    : mot de passe incorrect — utilise reset_password.py")
        if u.locked_until:
            print("  → FIX    : compte bloqué — utilise reset_password.py pour débloquer")
        if u.deleted_at:
            print("  → FIX    : compte soft-deleted — utilise reset_password.py pour restaurer")
        if not u.is_active:
            print("  → FIX    : compte inactif — utilise reset_password.py pour réactiver")

    print("\n" + "="*70)
