"""
Script d'enrôlement facial — MTCNN + FaceNet-128 → SQLite (AES-256-GCM)
============================================================================

Usage :
    python scripts/enroll_from_photos.py enroll --student-number 22000777 --photos data/photos
    python scripts/enroll_from_photos.py verify --student-number 22000777 --photo data/test_photos/haytam_test.jpg
    python scripts/enroll_from_photos.py check  --student-number 22000777

Structure attendue du dossier --photos :
    data/
    ├── photos/
    │   └── 22000777/          ← dossier nommé exactement par le matricule
    │       ├── photo1.jpg     ← UNIQUEMENT les photos d'enrôlement
    │       ├── photo2.jpg
    │       └── photo3.jpg
    └── test_photos/
        └── haytam_test.jpg    ← photo SÉPARÉE pour tester (verify)

CORRECTIONS apportées vs version originale :
  - Ajout de db.session.add(student) avant commit (fix bug persistance BDD)
  - Vérification post-commit avec db.session.refresh() 
  - Commande `check` pour diagnostiquer l'état BDD d'un étudiant
  - Avertissement si photo de verify provient du dossier d'enrôlement
  - Messages d'erreur plus explicites
"""

import sys
import os
import numpy as np
from pathlib import Path
import click

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import create_app, db
from app.models import Student
from app.services.face_service import FaceRecognitionService


# ══════════════════════════════════════════════════════════════
#  Commande : enroll
# ══════════════════════════════════════════════════════════════

@click.command()
@click.option("--student-number", "-s", default=None,
              help="Matricule étudiant. Si absent, traite TOUS les sous-dossiers.")
@click.option("--photos", "-p", default="data/photos",
              help="Dossier racine des photos (défaut: data/photos/)")
@click.option("--min-confidence", default=0.90, type=float,
              help="Confiance MTCNN minimale (défaut: 0.90)")
@click.option("--dry-run", is_flag=True,
              help="Simuler sans écrire en base de données")
def enroll(student_number, photos, min_confidence, dry_run):
    """
    Enrôle un ou plusieurs étudiants depuis leurs photos.
    Les embeddings sont moyennés (robustesse), chiffrés AES-256-GCM, puis stockés.
    """
    if not FaceRecognitionService.is_available():
        click.echo("❌ MTCNN / FaceNet non disponibles. Installez les dépendances :")
        click.echo("   pip install mtcnn keras-facenet tensorflow opencv-python Pillow")
        sys.exit(1)

    app = create_app()
    photos_root = Path(photos)

    if not photos_root.exists():
        click.echo(f"❌ Dossier introuvable : {photos_root.resolve()}")
        click.echo(f"   Créez-le avec : mkdir -p {photos_root}/{student_number or 'MATRICULE'}")
        sys.exit(1)

    # Déterminer les dossiers à traiter
    if student_number:
        target = photos_root / student_number
        if not target.exists():
            click.echo(f"❌ Dossier étudiant introuvable : {target.resolve()}")
            click.echo(f"   Placez les photos dans : {target}/")
            sys.exit(1)
        dirs_to_process = [target]
    else:
        dirs_to_process = sorted([d for d in photos_root.iterdir() if d.is_dir()])

    if not dirs_to_process:
        click.echo("⚠️  Aucun sous-dossier trouvé dans le dossier photos.")
        sys.exit(0)

    with app.app_context():
        total_ok   = 0
        total_fail = 0

        for student_dir in dirs_to_process:
            snum = student_dir.name
            click.echo(f"\n{'='*58}")
            click.echo(f"  Étudiant : {snum}")
            click.echo(f"{'='*58}")

            # ── Vérifier existence en BDD ──────────────────────────
            student = Student.query.filter_by(student_number=snum).first()
            if student is None:
                click.echo(f"  ❌ Matricule '{snum}' introuvable en BDD.")
                click.echo(f"     → Créez d'abord le compte : python scripts/create_student.py")
                total_fail += 1
                continue

            click.echo(f"  Nom : {student.full_name}  (id={student.id})")

            # ── Déjà enrôlé ? ─────────────────────────────────────
            if student.face_encoding_enc is not None:
                click.echo(f"  ℹ️  Déjà enrôlé ({len(student.face_encoding_enc)} bytes chiffrés).")
                click.echo(f"     → L'enrôlement va REMPLACER l'encodage existant.")

            # ── Lister les images ──────────────────────────────────
            exts   = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
            images = sorted([f for f in student_dir.iterdir()
                             if f.suffix.lower() in exts])
            if not images:
                click.echo(f"  ❌ Aucune image ({', '.join(exts)}) dans {student_dir}")
                total_fail += 1
                continue

            click.echo(f"  {len(images)} image(s) trouvée(s) : {[f.name for f in images]}")

            # ── Encoder chaque photo ───────────────────────────────
            embeddings       = []
            best_photo_bytes = None
            rejected         = 0

            for img_path in images:
                click.echo(f"  → {img_path.name} ...", nl=False)
                try:
                    photo_bytes = img_path.read_bytes()
                    vec = FaceRecognitionService.encode_face_from_bytes(photo_bytes)
                    if vec is not None:
                        embeddings.append(vec)
                        if best_photo_bytes is None:
                            best_photo_bytes = photo_bytes
                        click.echo(f" ✅  (dim={vec.shape[0]})")
                    else:
                        click.echo(f" ⚠️  aucun visage / confiance < {min_confidence}")
                        rejected += 1
                except Exception as e:
                    click.echo(f" ❌ Erreur lecture : {e}")
                    rejected += 1

            if not embeddings:
                click.echo(f"  ❌ Aucun embedding valide ({rejected} photo(s) rejetée(s)).")
                click.echo(f"     Conseils : visage de face, bonne luminosité, 1 seul visage par photo.")
                total_fail += 1
                continue

            # ── Moyenne + normalisation L2 ─────────────────────────
            mean_vec = np.mean(embeddings, axis=0).astype(np.float32)
            norm     = np.linalg.norm(mean_vec)
            if norm > 0:
                mean_vec = mean_vec / norm

            click.echo(f"  📐 Embedding final : moyenne de {len(embeddings)}/{len(images)} photo(s) valides")

            if dry_run:
                click.echo(f"  🔍 [DRY RUN] Simulation OK — rien écrit en BDD.")
                total_ok += 1
                continue

            # ── Chiffrement AES-256-GCM + persistance BDD ─────────
            try:
                student.set_face_encoding(mean_vec.tobytes())
                if best_photo_bytes:
                    student.set_face_photo(best_photo_bytes)

                # FIX CRITIQUE : db.session.add() force SQLAlchemy à tracker
                # les modifications sur les colonnes LargeBinary
                db.session.add(student)
                db.session.flush()  # écrit dans la transaction sans commit définitif

                # Vérification en mémoire avant commit
                if student.face_encoding_enc is None:
                    raise RuntimeError(
                        "face_encoding_enc est NULL après set_face_encoding() — "
                        "vérifiez CryptoService et AES_MASTER_KEY dans .env"
                    )

                db.session.commit()

                # ── Vérification post-commit : re-lire depuis la BDD ──
                db.session.refresh(student)
                if student.face_encoding_enc is None:
                    raise RuntimeError(
                        "face_encoding_enc est NULL après commit — "
                        "les données n'ont PAS été persistées en BDD !"
                    )

                enc_size   = len(student.face_encoding_enc)
                nonce_size = len(student.face_encoding_nonce) if student.face_encoding_nonce else 0
                tag_size   = len(student.face_encoding_tag)   if student.face_encoding_tag   else 0

                click.echo(f"  ✅ {student.full_name} ({snum}) enrôlé avec succès !")
                click.echo(f"     face_encoding_enc   : {enc_size} bytes")
                click.echo(f"     face_encoding_nonce : {nonce_size} bytes (attendu: 12)")
                click.echo(f"     face_encoding_tag   : {tag_size} bytes  (attendu: 16)")
                total_ok += 1

            except Exception as e:
                db.session.rollback()
                click.echo(f"  ❌ Erreur BDD — rollback effectué : {e}")
                total_fail += 1

    click.echo(f"\n{'='*58}")
    click.echo(f"  Résumé : ✅ {total_ok} enrôlé(s)   ❌ {total_fail} échec(s)")
    click.echo(f"{'='*58}")
    if total_ok > 0:
        click.echo(f"\n👉 Vérifiez avec une photo EXTERNE (pas du dossier d'enrôlement) :")
        click.echo(f"   python scripts/enroll_from_photos.py verify \\")
        click.echo(f"       --student-number MATRICULE \\")
        click.echo(f"       --photo data/test_photos/MATRICULE_test.jpg")


# ══════════════════════════════════════════════════════════════
#  Commande : verify
# ══════════════════════════════════════════════════════════════

@click.command()
@click.option("--student-number", "-s", required=True,
              help="Matricule de l'étudiant à tester")
@click.option("--photo", "-p", required=True,
              help="Chemin vers la photo de test (doit être DIFFÉRENTE des photos d'enrôlement)")
def verify(student_number, photo):
    """
    Teste la reconnaissance d'une photo contre l'encodage stocké en BDD.

    IMPORTANT : utilisez une photo différente de celles d'enrôlement
    pour obtenir un score représentatif de la vraie précision du système.
    """
    if not FaceRecognitionService.is_available():
        click.echo("❌ MTCNN / FaceNet non disponibles.")
        sys.exit(1)

    photo_path  = Path(photo)
    enroll_dir  = Path("data/photos") / student_number

    # ── Avertissement photo d'enrôlement ──────────────────────
    try:
        photo_path.resolve().relative_to(enroll_dir.resolve())
        in_enroll_dir = True
    except ValueError:
        in_enroll_dir = False

    if in_enroll_dir:
        click.echo("⚠️  ─────────────────────────────────────────────────────")
        click.echo("   ATTENTION : cette photo vient du dossier d'enrôlement.")
        click.echo("   Le score sera ARTIFICIELLEMENT ÉLEVÉ — ce n'est pas")
        click.echo("   un test fiable de la reconnaissance en conditions réelles.")
        click.echo("   Utilisez une photo prise séparément (data/test_photos/).")
        click.echo("⚠️  ─────────────────────────────────────────────────────\n")

    if not photo_path.exists():
        click.echo(f"❌ Fichier introuvable : {photo_path.resolve()}")
        sys.exit(1)

    app = create_app()
    with app.app_context():

        # ── Vérifier étudiant en BDD ───────────────────────────
        student = Student.query.filter_by(student_number=student_number).first()
        if student is None:
            click.echo(f"❌ Matricule '{student_number}' introuvable en BDD.")
            sys.exit(1)

        # ── Vérifier que l'enrôlement est présent ─────────────
        enc_bytes = student.get_face_encoding()
        if enc_bytes is None:
            click.echo(f"❌ {student.full_name} n'est PAS enrôlé (face_encoding_enc = NULL en BDD).")
            click.echo(f"   → Enrôlez d'abord :")
            click.echo(f"     python scripts/enroll_from_photos.py enroll --student-number {student_number} --photos data/photos")
            sys.exit(1)

        # ── Charger le vecteur stocké ──────────────────────────
        stored_vec = np.frombuffer(enc_bytes, dtype=np.float32).copy()
        norm = np.linalg.norm(stored_vec)
        if norm > 0:
            stored_vec = stored_vec / norm

        # ── Encoder la photo de test ───────────────────────────
        click.echo(f"  Encodage de la photo de test : {photo_path.name} ...")
        photo_bytes = photo_path.read_bytes()
        query_vec   = FaceRecognitionService.encode_face_from_bytes(photo_bytes)

        if query_vec is None:
            click.echo("❌ Aucun visage détecté dans la photo de test.")
            click.echo("   Vérifiez : visage de face, bonne luminosité, 1 seul visage.")
            sys.exit(1)

        # ── Calcul de la distance L2 ───────────────────────────
        distance   = float(np.linalg.norm(stored_vec - query_vec))
        confidence = max(0.0, 1.0 - distance / 2.0)

        # ── Affichage résultat ─────────────────────────────────
        click.echo(f"\n{'='*58}")
        click.echo(f"  Étudiant        : {student.full_name} ({student_number})")
        click.echo(f"  Photo testée    : {photo_path.name}")
        click.echo(f"  {'(⚠️  photo d enrôlement — score non représentatif)' if in_enroll_dir else '(photo externe — score fiable)'}")
        click.echo(f"  ──────────────────────────────────────────────────")
        click.echo(f"  Distance L2     : {distance:.4f}  (seuil : ≤ 0.90)")
        click.echo(f"  Confiance       : {confidence:.1%}")
        click.echo(f"  ──────────────────────────────────────────────────")

        if distance <= 0.90:
            click.echo(f"  Résultat        : ✅ RECONNU")
            if distance <= 0.50:
                click.echo(f"  Qualité         : 🟢 Excellente (distance < 0.50)")
            elif distance <= 0.70:
                click.echo(f"  Qualité         : 🟡 Bonne (distance 0.50–0.70)")
            else:
                click.echo(f"  Qualité         : 🟠 Limite (distance 0.70–0.90) — envisagez de meilleures photos")
        else:
            click.echo(f"  Résultat        : ❌ NON RECONNU")
            click.echo(f"  Conseils        :")
            click.echo(f"    • Vérifiez éclairage et angle de la photo de test")
            click.echo(f"    • Ré-enrôlez avec des photos variées (lumière, angle, expression)")
            click.echo(f"    • Abaissez FACE_RECOGNITION_TOLERANCE dans .env (ex: 1.00)")

        click.echo(f"{'='*58}")


# ══════════════════════════════════════════════════════════════
#  Commande : check  (NOUVELLE — diagnostic BDD)
# ══════════════════════════════════════════════════════════════

@click.command()
@click.option("--student-number", "-s", required=True,
              help="Matricule de l'étudiant à diagnostiquer")
def check(student_number):
    """
    Diagnostique l'état d'enrôlement d'un étudiant en BDD.
    Permet de vérifier si les données biométriques sont réellement persistées.
    """
    app = create_app()
    with app.app_context():
        student = Student.query.filter_by(student_number=student_number).first()

        click.echo(f"\n{'='*58}")
        click.echo(f"  Diagnostic BDD — Matricule : {student_number}")
        click.echo(f"{'='*58}")

        if student is None:
            click.echo(f"  ❌ Matricule introuvable en BDD.")
            click.echo(f"     → python scripts/create_student.py")
            sys.exit(1)

        click.echo(f"  Nom              : {student.full_name}")
        click.echo(f"  ID BDD           : {student.id}")
        click.echo(f"  Filière          : {student.program} — Année {student.year_of_study}")
        click.echo(f"  Pseudonyme CNDP  : {student.pseudonym or '(non défini)'}")
        click.echo(f"  ──────────────────────────────────────────────────")

        # Vérification colonne par colonne
        fields = [
            ("face_encoding_enc",   student.face_encoding_enc),
            ("face_encoding_nonce", student.face_encoding_nonce),
            ("face_encoding_tag",   student.face_encoding_tag),
            ("face_photo_enc",      student.face_photo_enc),
            ("face_enrolled_at",    student.face_enrolled_at),
        ]

        all_ok = True
        for name, value in fields:
            if value is None:
                click.echo(f"  {name:25s} : ❌ NULL")
                all_ok = False
            else:
                size = len(value) if isinstance(value, (bytes, bytearray)) else str(value)
                click.echo(f"  {name:25s} : ✅ {size} bytes" if isinstance(value, (bytes, bytearray)) else f"  {name:25s} : ✅ {value}")

        click.echo(f"  ──────────────────────────────────────────────────")

        if all_ok:
            # Tester le déchiffrement
            try:
                enc_bytes = student.get_face_encoding()
                vec = np.frombuffer(enc_bytes, dtype=np.float32)
                click.echo(f"  Déchiffrement    : ✅ OK")
                click.echo(f"  Dimension vecteur: {vec.shape[0]} (attendu: 128)")
                click.echo(f"\n  🟢 Étudiant correctement enrôlé — prêt pour la reconnaissance.")
            except Exception as e:
                click.echo(f"  Déchiffrement    : ❌ ÉCHEC — {e}")
                click.echo(f"\n  🔴 Données corrompues — ré-enrôlez l'étudiant.")
        else:
            click.echo(f"\n  🔴 Enrôlement incomplet — relancez :")
            click.echo(f"     python scripts/enroll_from_photos.py enroll --student-number {student_number} --photos data/photos")

        click.echo(f"{'='*58}")


# ══════════════════════════════════════════════════════════════
#  CLI principal
# ══════════════════════════════════════════════════════════════

@click.group()
def cli():
    """Outils d'enrôlement facial USMS — MTCNN + FaceNet-128"""
    pass


cli.add_command(enroll)
cli.add_command(verify)
cli.add_command(check)


if __name__ == "__main__":
    cli()