"""
generate_env.py — Genere le fichier .env en UTF-8 sans BOM
Lancez : python generate_env.py
"""
import secrets, os

# Supprimer l'ancien .env s'il existe
if os.path.exists(".env"):
    os.remove(".env")
    print("[INFO] Ancien .env supprime")

aes_key    = secrets.token_hex(32)
secret_key = secrets.token_urlsafe(32)
jwt_key    = secrets.token_urlsafe(32)

content = (
    "FLASK_APP=run.py\n"
    "FLASK_ENV=development\n"
    "FLASK_DEBUG=1\n"
    "\n"
    f"SECRET_KEY={secret_key}\n"
    "\n"
    "DATABASE_URL=sqlite:///faceattend.db\n"
    "\n"
    f"AES_MASTER_KEY={aes_key}\n"
    "\n"
    f"JWT_SECRET_KEY={jwt_key}\n"
    "\n"
    "FACE_RECOGNITION_TOLERANCE=0.50\n"
    "FACE_DETECTION_MODEL=hog\n"
    "MAX_PHOTO_SIZE_MB=5\n"
    "PHOTO_STORAGE_PATH=./data/photos\n"
    "\n"
    "CAMERA_INDEX=0\n"
    "CAMERA_WIDTH=640\n"
    "CAMERA_HEIGHT=480\n"
    "CAMERA_FPS=30\n"
    "CAPTURE_INTERVAL_SECONDS=3\n"
    "\n"
    "DATA_RETENTION_DAYS=365\n"
    "CONSENT_REQUIRED=True\n"
    "ANONYMIZE_AFTER_DAYS=730\n"
    "\n"
    "LOGIN_MAX_ATTEMPTS=5\n"
    "LOGIN_LOCKOUT_MINUTES=15\n"
)

# IMPORTANT : encoding='utf-8' sans BOM
with open(".env", "w", encoding="utf-8", newline="\n") as f:
    f.write(content)

print("[OK] .env cree en UTF-8 !")
print(f"     AES_MASTER_KEY = {aes_key[:16]}...")
print(f"     SECRET_KEY     = {secret_key[:16]}...")
print()
print("Prochaines etapes :")
print("  python -m flask db init")
print("  python -m flask db migrate -m init")
print("  python -m flask db upgrade")
print("  python -m flask seed-db")
print("  python run.py")
