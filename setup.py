#!/usr/bin/env python3
"""
setup.py — Script de configuration automatique pour VSCode
Lance ce script UNE SEULE FOIS après avoir cloné/dézippé le projet.

Usage :
    python setup.py
"""

import os
import sys
import subprocess
import secrets
import platform

# ── Couleurs terminal ──────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):   print(f"{GREEN}  ✅ {msg}{RESET}")
def info(msg): print(f"{CYAN}  ℹ️  {msg}{RESET}")
def warn(msg): print(f"{YELLOW}  ⚠️  {msg}{RESET}")
def err(msg):  print(f"{RED}  ❌ {msg}{RESET}")
def title(msg):print(f"\n{BOLD}{CYAN}{'═'*50}\n  {msg}\n{'═'*50}{RESET}")


def run(cmd, check=True, capture=False):
    """Exécute une commande shell."""
    kwargs = dict(shell=True, check=check)
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    return subprocess.run(cmd, **kwargs)


def check_python():
    title("1. Vérification Python")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        err(f"Python 3.10+ requis. Version actuelle : {v.major}.{v.minor}")
        sys.exit(1)
    ok(f"Python {v.major}.{v.minor}.{v.micro}")


def create_venv():
    title("2. Environnement virtuel")
    if os.path.exists("venv"):
        warn("venv/ existe déjà — ignoré.")
        return
    run(f"{sys.executable} -m venv venv")
    ok("venv/ créé")


def get_pip():
    """Retourne le chemin pip selon l'OS."""
    if platform.system() == "Windows":
        return os.path.join("venv", "Scripts", "pip.exe")
    return os.path.join("venv", "bin", "pip")


def get_python():
    if platform.system() == "Windows":
        return os.path.join("venv", "Scripts", "python.exe")
    return os.path.join("venv", "bin", "python")


def install_deps():
    title("3. Installation des dépendances")
    pip = get_pip()

    info("Mise à jour pip…")
    run(f"{pip} install --upgrade pip", check=False)

    info("Installation cmake (requis pour dlib)…")
    run(f"{pip} install cmake", check=False)

    info("Installation dlib (peut prendre 5-15 min la première fois)…")
    r = run(f"{pip} install dlib", check=False)
    if r.returncode != 0:
        warn("dlib non compilé. Sur Windows, essayez :")
        warn("  pip install dlib --find-links https://github.com/jloh02/dlib/releases/")
        warn("  ou installez Visual Studio Build Tools")

    info("Installation des autres dépendances…")
    run(f"{pip} install -r requirements.txt", check=False)
    ok("Dépendances installées")


def create_env():
    title("4. Fichier .env")
    if os.path.exists(".env"):
        warn(".env existe déjà — ignoré.")
        return

    # Générer des clés sécurisées automatiquement
    aes_key    = secrets.token_hex(32)
    secret_key = secrets.token_urlsafe(32)
    jwt_key    = secrets.token_urlsafe(32)

    env_content = f"""# FaceAttend — Configuration locale (généré automatiquement)
FLASK_APP=run.py
FLASK_ENV=development
FLASK_DEBUG=1

SECRET_KEY={secret_key}

# SQLite par défaut (pas besoin de PostgreSQL pour commencer)
DATABASE_URL=sqlite:///faceattend.db

# Clé AES-256-GCM générée automatiquement
AES_MASTER_KEY={aes_key}

JWT_SECRET_KEY={jwt_key}

FACE_RECOGNITION_TOLERANCE=0.50
FACE_DETECTION_MODEL=hog
MAX_PHOTO_SIZE_MB=5
PHOTO_STORAGE_PATH=./data/photos

CAMERA_INDEX=0
CAMERA_WIDTH=640
CAMERA_HEIGHT=480
CAMERA_FPS=30
CAPTURE_INTERVAL_SECONDS=3

DATA_RETENTION_DAYS=365
CONSENT_REQUIRED=True
ANONYMIZE_AFTER_DAYS=730

LOGIN_MAX_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
"""
    with open(".env", "w") as f:
        f.write(env_content)
    ok(".env créé avec des clés sécurisées générées automatiquement")
    info(f"AES_MASTER_KEY = {aes_key[:16]}…  (stockée dans .env)")


def create_dirs():
    title("5. Dossiers de données")
    dirs = ["data/photos", "migrations", "logs"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        ok(f"Dossier : {d}/")


def init_db():
    title("6. Initialisation base de données")
    python = get_python()

    r = run(f"{python} -m flask db init", check=False)
    if r.returncode == 0:
        ok("flask db init")
    else:
        warn("migrations/ existe peut-être déjà")

    r = run(f"{python} -m flask db migrate -m \"Initial schema\"", check=False)
    if r.returncode == 0:
        ok("flask db migrate")

    r = run(f"{python} -m flask db upgrade", check=False)
    if r.returncode == 0:
        ok("flask db upgrade")
    else:
        err("Erreur lors du db upgrade. Vérifiez DATABASE_URL dans .env")
        return False
    return True


def seed():
    title("7. Données de test")
    python = get_python()
    r = run(f"{python} -m flask seed-db", check=False)
    if r.returncode == 0:
        ok("Données de test insérées")
    else:
        warn("Seed échoué — la BDD sera vide")


def print_summary():
    title("✨ Installation terminée !")
    print(f"""
{BOLD}▶ Pour lancer le projet :{RESET}

  {CYAN}# Activez le venv :{RESET}
  {GREEN}Windows :{RESET}   venv\\Scripts\\activate
  {GREEN}Linux/Mac :{RESET} source venv/bin/activate

  {CYAN}# Lancez Flask :{RESET}
  {GREEN}python run.py{RESET}
  {GREEN}  — ou —{RESET}
  Appuyez sur F5 dans VSCode (launch.json configuré ✅)

  {CYAN}# Ouvrez dans le navigateur :{RESET}
  {GREEN}http://localhost:5000{RESET}

{BOLD}📋 Comptes de test :{RESET}
  Admin      → admin@univ.ma          / Admin@1234
  Enseignant → prof.alami@univ.ma     / Prof@1234
  Étudiant   → etudiant1@univ.ma      / Etu@1234

{BOLD}📸 Enrôlement (webcam PC) :{RESET}
  flask enroll-student 1   {CYAN}# enrôle l'étudiant ID=1{RESET}
  → Appuyez ESPACE pour capturer, Q pour quitter

{YELLOW}⚠️  dlib non installé ?{RESET}
  La reconnaissance faciale sera désactivée automatiquement.
  Les autres fonctionnalités (dashboard, présences manuelles) fonctionnent.
    """)


if __name__ == "__main__":
    print(f"\n{BOLD}{CYAN}🎓 FaceAttend — Setup automatique VSCode{RESET}\n")
    check_python()
    create_venv()
    install_deps()
    create_env()
    create_dirs()
    db_ok = init_db()
    if db_ok:
        seed()
    print_summary()
