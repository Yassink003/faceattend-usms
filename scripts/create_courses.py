import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Teacher, Course, User

app = create_app()

with app.app_context():

    # Récupérer le professeur
    teacher_user = User.query.filter_by(email="prof.alami@usms.ac.ma").first()
    if not teacher_user:
        print("❌ Professeur introuvable. Lance d'abord create_teacher.py")
        sys.exit(1)

    teacher = Teacher.query.filter_by(user_id=teacher_user.id).first()

    # ─── Liste des cours à créer ────────────────────────────
    cours = [
        {
            "name": "Administration Sécurisée et Forensics",
            "code": "ASF101",
            "description": "Sécurisation des systèmes et investigation numérique",
            "credits": 3,
            "room": "Salle A1"
        },
        {
            "name": "DevOps/DevSecOps",
            "code": "DDO102",
            "description": "Intégration continue, livraison continue et sécurité DevOps",
            "credits": 3,
            "room": "Salle A2"
        },
        {
            "name": "Technologies émergentes et Quantum",
            "code": "TEQ103",
            "description": "Intelligence artificielle, blockchain et informatique quantique",
            "credits": 3,
            "room": "Salle B1"
        },
        {
            "name": "Ethique et droit numérique",
            "code": "EDN104",
            "description": "Cadre juridique, RGPD, CNDP et éthique de l'IA",
            "credits": 3,
            "room": "Salle B2"
        },
    ]
    # ────────────────────────────────────────────────────────

    created = 0
    for c in cours:
        existant = Course.query.filter_by(code=c["code"]).first()
        if existant:
            print(f"⚠️  Cours '{c['name']}' existe déjà — ignoré.")
        else:
            course = Course(
                teacher_id=teacher.id,
                name=c["name"],
                code=c["code"],
                description=c["description"],
                credits=c["credits"],
                room=c["room"],
                is_active=True
            )
            db.session.add(course)
            created += 1
            print(f"✅ Cours créé : {c['name']} ({c['code']})")

    db.session.commit()
    print(f"\n✅ {created} cours ajouté(s) avec succès !")