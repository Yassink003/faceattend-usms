"""
Script d'enrôlement facial — MTCNN + FaceNet-128 → PostgreSQL (AES-256-GCM)
============================================================================

Usage :
    python scripts/enroll_from_photos.py --student-number CNE12345 --photos data/photos/moi/

Structure attendue du dossier --photos :
    data/photos/
    ├── CNE12345/          ← dossier nommé par le numéro étudiant
    │   ├── photo1.jpg
    │   ├── photo2.jpg
    │   └── photo3.jpg     ← plusieurs photos améliorent la robustesse
    └── CNE67890/
        └── photo1.jpg

Le script :
  1. Lit chaque image du dossier
  2. Détecte le visage via MTCNN (rejette si 0 ou >1 visage)
  3. Calcule l'embedding FaceNet-128
  4. Fait la moyenne des embeddings (si plusieurs photos)
  5. Chiffre le vecteur AES-256-GCM
  6. Stocke dans PostgreSQL
"""

import sys
import os
import io
import click
import numpy as np
from pathlib import Path
from loguru import logger

# Ajouter la racine du projet au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app, db
from app.models import Student, User
from app.services.face_service import FaceRecognitionService


@click.command()
@click.option("--student-number", "-s", default=None,
              help="Numéro étudiant (CNE/matricule). Si absent, traite TOUS les sous-dossiers.")
@click.option("--photos", "-p", default="data/photos",
              help="Dossier racine des photos (défaut: data/photos/)")
@click.option("--min-confidence", default=0.90, type=float,
              help="Confiance MTCNN minimale (défaut: 0.90)")
@click.option("--dry-run", is_flag=True,
              help="Simuler sans écrire en base de données")
def enroll(student_number, photos, min_confidence, dry_run):
    """
    Enrôle un ou plusieurs étudiants depuis leurs photos.
    Utilise MTCNN pour la détection et FaceNet-128 pour l'encodage.
    Les embeddings sont chiffrés AES-256-GCM avant stockage PostgreSQL.
    """
    if not FaceRecognitionService.is_available():
        click.echo("❌ MTCNN / FaceNet non disponibles. Installez les dépendances :")
        click.echo("   pip install mtcnn keras-facenet tensorflow opencv-python Pillow")
        sys.exit(1)

    app = create_app()
    photos_root = Path(photos)

    if not photos_root.exists():
        click.echo(f"❌ Dossier introuvable : {photos_root}")
        sys.exit(1)

    # Déterminer les dossiers à traiter
    if student_number:
        dirs_to_process = [photos_root / student_number]
    else:
        dirs_to_process = [d for d in photos_root.iterdir() if d.is_dir()]

    if not dirs_to_process:
        click.echo("⚠️  Aucun sous-dossier trouvé dans le dossier photos.")
        sys.exit(0)

    with app.app_context():
        total_ok = 0
        total_fail = 0

        for student_dir in sorted(dirs_to_process):
            snum = student_dir.name
            click.echo(f"\n{'='*55}")
            click.echo(f"  Étudiant : {snum}")
            click.echo(f"{'='*55}")

            # Chercher l'étudiant en base
            student = Student.query.filter_by(student_number=snum).first()
            if student is None:
                click.echo(f"  ⚠️  Étudiant '{snum}' introuvable en base — ignoré.")
                total_fail += 1
                continue

            # Lister les images
            exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
            images = sorted([f for f in student_dir.iterdir()
                             if f.suffix.lower() in exts])
            if not images:
                click.echo(f"  ⚠️  Aucune image dans {student_dir} — ignoré.")
                total_fail += 1
                continue

            click.echo(f"  {len(images)} image(s) trouvée(s)")

            # Encoder chaque photo
            embeddings = []
            best_photo_bytes = None

            for img_path in images:
                click.echo(f"  → Traitement : {img_path.name}")
                try:
                    photo_bytes = img_path.read_bytes()
                    vec = FaceRecognitionService.encode_face_from_bytes(photo_bytes)
                    if vec is not None:
                        embeddings.append(vec)
                        if best_photo_bytes is None:
                            best_photo_bytes = photo_bytes
                        click.echo(f"     ✅ Embedding OK (dim={vec.shape[0]})")
                    else:
                        click.echo(f"     ⚠️  Aucun visage détecté / confiance insuffisante")
                except Exception as e:
                    click.echo(f"     ❌ Erreur : {e}")

            if not embeddings:
                click.echo(f"  ❌ Aucun embedding valide pour {snum}.")
                total_fail += 1
                continue

            # Moyenne des embeddings + renormalisation L2
            mean_vec = np.mean(embeddings, axis=0).astype(np.float32)
            norm = np.linalg.norm(mean_vec)
            if norm > 0:
                mean_vec = mean_vec / norm

            click.echo(f"  📐 Embedding final : moyenne de {len(embeddings)} photo(s)")

            if dry_run:
                click.echo(f"  🔍 [DRY RUN] Pas d'écriture en base.")
                total_ok += 1
                continue

            # Chiffrement AES-256-GCM et stockage PostgreSQL
            try:
                student.set_face_encoding(mean_vec.tobytes())
                if best_photo_bytes:
                    student.set_face_photo(best_photo_bytes)
                db.session.commit()
                click.echo(f"  ✅ {student.full_name} ({snum}) enrôlé avec succès.")
                click.echo(f"     Encodage chiffré AES-256-GCM → PostgreSQL")
                total_ok += 1
            except Exception as e:
                db.session.rollback()
                click.echo(f"  ❌ Erreur DB : {e}")
                total_fail += 1

    click.echo(f"\n{'='*55}")
    click.echo(f"  Résumé : ✅ {total_ok} enrôlé(s)  ❌ {total_fail} échec(s)")
    click.echo(f"{'='*55}")


@click.command()
@click.option("--student-number", "-s", required=True,
              help="Numéro étudiant à tester")
@click.option("--photo", "-p", required=True,
              help="Chemin vers la photo de test")
def verify(student_number, photo):
    """
    Vérifie si une photo correspond à l'encodage stocké pour un étudiant.
    Utile pour tester l'enrôlement avant de démarrer une session.
    """
    if not FaceRecognitionService.is_available():
        click.echo("❌ MTCNN / FaceNet non disponibles.")
        sys.exit(1)

    app = create_app()
    with app.app_context():
        student = Student.query.filter_by(student_number=student_number).first()
        if student is None:
            click.echo(f"❌ Étudiant '{student_number}' introuvable.")
            sys.exit(1)

        enc_bytes = student.get_face_encoding()
        if enc_bytes is None:
            click.echo(f"⚠️  {student.full_name} n'est pas encore enrôlé.")
            sys.exit(1)

        stored_vec = np.frombuffer(enc_bytes, dtype=np.float32).copy()
        norm = np.linalg.norm(stored_vec)
        if norm > 0:
            stored_vec = stored_vec / norm

        photo_bytes = Path(photo).read_bytes()
        query_vec   = FaceRecognitionService.encode_face_from_bytes(photo_bytes)
        if query_vec is None:
            click.echo("❌ Aucun visage détecté dans la photo de test.")
            sys.exit(1)

        distance   = float(np.linalg.norm(stored_vec - query_vec))
        confidence = max(0.0, 1.0 - distance / 2.0)

        click.echo(f"\n{'='*55}")
        click.echo(f"  Étudiant : {student.full_name} ({student_number})")
        click.echo(f"  Distance L2     : {distance:.4f}")
        click.echo(f"  Confiance       : {confidence:.1%}")
        click.echo(f"  Seuil tolérance : 0.90")
        if distance <= 0.90:
            click.echo(f"  Résultat        : ✅ RECONNU")
        else:
            click.echo(f"  Résultat        : ❌ NON RECONNU (distance trop grande)")
        click.echo(f"{'='*55}")


@click.group()
def cli():
    """Outils d'enrôlement facial USMS — MTCNN + FaceNet-128"""
    pass


cli.add_command(enroll)
cli.add_command(verify)


if __name__ == "__main__":
    cli()
