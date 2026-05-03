import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from pathlib import Path
from app import create_app, db
from app.models import Student
from app.services.face_service import FaceRecognitionService

app = create_app()

# ─── MODIFIE CES VALEURS ────────────────────────────────
NUMERO_APOGEE = "21000120"
DOSSIER_PHOTOS = "data/photos/21000120"
# ────────────────────────────────────────────────────────

with app.app_context():
    student = Student.query.filter_by(student_number=NUMERO_APOGEE).first()
    if not student:
        print(f"❌ Étudiant {NUMERO_APOGEE} introuvable en base.")
        sys.exit(1)

    photos_path = Path(DOSSIER_PHOTOS)
    images = list(photos_path.glob("*.jpg")) + \
             list(photos_path.glob("*.jpeg")) + \
             list(photos_path.glob("*.png"))

    if not images:
        print(f"❌ Aucune image trouvée dans {DOSSIER_PHOTOS}")
        sys.exit(1)

    print(f"📸 {len(images)} photo(s) trouvée(s)")

    embeddings = []
    best_photo = None

    for img_path in images:
        print(f"  → {img_path.name}")
        photo_bytes = img_path.read_bytes()
        vec = FaceRecognitionService.encode_face_from_bytes(photo_bytes)
        if vec is not None:
            embeddings.append(vec)
            if best_photo is None:
                best_photo = photo_bytes
            print(f"     ✅ Embedding OK")
        else:
            print(f"     ⚠️  Visage non détecté")

    if not embeddings:
        print("❌ Aucun embedding valide.")
        sys.exit(1)

    # Moyenne + normalisation L2
    mean_vec = np.mean(embeddings, axis=0).astype(np.float32)
    norm = np.linalg.norm(mean_vec)
    if norm > 0:
        mean_vec = mean_vec / norm

    print(f"\n💾 Sauvegarde en base...")

    # Sauvegarde directe dans la session active
    student.set_face_encoding(mean_vec.tobytes())
    if best_photo:
        student.set_face_photo(best_photo)

    db.session.add(student)
    db.session.commit()

    # Vérification immédiate
    db.session.refresh(student)
    if student.face_encoding_enc is not None:
        print(f"✅ Embedding sauvegardé avec succès !")
        print(f"   Taille vecteur  : {len(mean_vec)} dimensions")
        print(f"   Taille chiffrée : {len(student.face_encoding_enc)} bytes")
        print(f"   Enrôlé le       : {student.face_enrolled_at}")
    else:
        print("❌ Échec : l'embedding n'est pas en base.")