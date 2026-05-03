"""
run.py — Point d'entrée de l'application FaceAttend.
Usage :
  flask run                  # Serveur de développement
  flask seed-db              # Données de test
  flask create-admin         # Créer un admin interactif
  flask enroll-student <id>  # Enrôler un étudiant (photo depuis webcam)
"""
import os
import click
from flask.cli import with_appcontext
from app import create_app, db
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
app = create_app()

# ── Seed command ──────────────────────────────────────────
from scripts.seed import seed_db
app.cli.add_command(seed_db)


# ── Create admin command ──────────────────────────────────
@app.cli.command("create-admin")
@click.option("--email",    prompt="Email admin")
@click.option("--password", prompt="Mot de passe", hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_admin(email, password):
    """Crée un compte administrateur."""
    from werkzeug.security import generate_password_hash
    from app.models import User, RoleEnum
    if User.query.filter_by(email=email).first():
        click.echo("❌ Cet email existe déjà.")
        return
    u = User(email=email, password_hash=generate_password_hash(password),
             role=RoleEnum.ADMIN, consent_given=True)
    db.session.add(u)
    db.session.commit()
    click.echo(f"✅ Admin créé : {email}")


# ── Enroll student from webcam ────────────────────────────
@app.cli.command("enroll-student")
@click.argument("student_id", type=int)
@with_appcontext
def enroll_student(student_id):
    """Capture la photo d'un étudiant et l'enrôle (depuis Raspberry Pi)."""
    import cv2
    from app.models import Student
    from app.services.face_service import FaceRecognitionService

    student = Student.query.get(student_id)
    if not student:
        click.echo(f"❌ Étudiant #{student_id} introuvable.")
        return

    click.echo(f"📸 Enrôlement de {student.full_name} — Appuyez sur ESPACE pour capturer, Q pour quitter.")

    cap = cv2.VideoCapture(app.config["CAMERA_INDEX"])
    while True:
        ret, frame = cap.read()
        if not ret:
            click.echo("❌ Caméra inaccessible.")
            break
        cv2.imshow(f"Enrôlement — {student.full_name}", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):
            _, buf = cv2.imencode(".jpg", frame)
            photo_bytes = buf.tobytes()
            success = FaceRecognitionService.enroll_student(student, photo_bytes)
            if success:
                click.echo(f"✅ Étudiant {student.full_name} enrôlé avec succès !")
            else:
                click.echo("⚠️  Aucun visage détecté. Réessayez.")
        elif key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


# ── CNDP : purge old data ─────────────────────────────────
@app.cli.command("purge-expired-data")
@with_appcontext
def purge_expired_data():
    """Supprime les données biométriques expirées (CNDP Art. 9)."""
    from datetime import datetime, timezone, timedelta
    from app.models import Student
    retention = app.config["DATA_RETENTION_DAYS"]
    cutoff    = datetime.now(timezone.utc) - timedelta(days=retention)

    expired = Student.query.filter(
        Student.face_enrolled_at < cutoff,
        Student.face_encoding_enc.isnot(None),
    ).all()

    for s in expired:
        s.face_encoding_enc   = None
        s.face_encoding_nonce = None
        s.face_encoding_tag   = None
        s.face_photo_enc      = None
        s.face_photo_nonce    = None
        s.face_photo_tag      = None
        click.echo(f"🗑  Données biométriques supprimées : {s.student_number}")

    db.session.commit()
    click.echo(f"✅ {len(expired)} enrôlement(s) expiré(s) purgé(s).")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
