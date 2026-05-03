# 🎓 FaceAttend — Système de Présences par Reconnaissance Faciale

Système intelligent de gestion des présences universitaires par reconnaissance faciale, développé avec Flask + FastAPI, PostgreSQL, et chiffrement AES-256-GCM. **Conforme CNDP (Maroc).**

---

## 📐 Architecture du projet

```
facial_attendance/
├── app/
│   ├── __init__.py            # Application factory Flask
│   ├── api/
│   │   ├── auth.py            # Login / Logout
│   │   ├── admin.py           # Dashboard admin, exports, analytics
│   │   ├── teacher.py         # Séances, présences en temps réel
│   │   ├── student.py         # Historique, justifications
│   │   ├── camera.py          # Streaming MJPEG + snapshot API
│   │   └── attendance.py      # API REST JSON (polling live)
│   ├── models/
│   │   └── __init__.py        # User, Student, Teacher, Course, Session, Attendance, Justification, AuditLog
│   ├── services/
│   │   ├── face_service.py    # Encodage, enrôlement, identification faciale
│   │   └── attendance_service.py  # Logique métier présences + analytics
│   ├── utils/
│   │   └── crypto.py          # AES-256-GCM encrypt/decrypt + pseudonymisation
│   └── middleware/            # (à étendre : JWT, CORS avancé)
├── frontend/
│   ├── static/
│   │   ├── css/main.css       # Design dark futuriste
│   │   └── js/main.js         # Polling live, charts, utils UI
│   └── templates/
│       ├── base.html          # Layout principal + sidebar
│       ├── auth/login.html    # Page de connexion (3 rôles)
│       ├── admin/             # Dashboard, étudiants, décrochage
│       ├── teacher/           # Dashboard, séance live, justifications
│       └── student/           # Dashboard, historique, justification
├── migrations/                # Alembic migrations
├── scripts/
│   └── seed.py                # Données de test
├── config/
│   └── settings.py            # Dev / Prod / Test config
├── run.py                     # Entry point + CLI commands
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## ⚙️ Installation

### 1. Prérequis système

```bash
# Ubuntu / Debian (y compris Raspberry Pi OS 64-bit)
sudo apt-get update && sudo apt-get install -y \
  python3.11 python3.11-venv python3-pip \
  postgresql postgresql-contrib \
  redis-server \
  build-essential cmake libopenblas-dev liblapack-dev \
  libx11-dev libgtk-3-dev libboost-python-dev \
  libatlas-base-dev gfortran libgl1 libglib2.0-0
```

### 2. Environnement virtuel

```bash
cd facial_attendance
python3.11 -m venv venv
source venv/bin/activate          # Linux/macOS
# venv\Scripts\activate           # Windows
pip install --upgrade pip
pip install -r requirements.txt
```

> ⚠️ `face_recognition` requiert `dlib` qui se compile (≈10 min sur Raspberry Pi 4).
> Pour accélérer : `pip install dlib --no-build-isolation` après avoir installé cmake.

### 3. Base de données PostgreSQL

```sql
-- Connectez-vous en tant que postgres
sudo -u postgres psql

CREATE USER attendance_user WITH PASSWORD 'strongpassword';
CREATE DATABASE facial_attendance_db OWNER attendance_user;
GRANT ALL PRIVILEGES ON DATABASE facial_attendance_db TO attendance_user;
\q
```

### 4. Configuration

```bash
cp .env.example .env
# Éditez .env avec vos vraies valeurs :
# - Générer AES_MASTER_KEY : python -c "import secrets; print(secrets.token_hex(32))"
# - Générer SECRET_KEY     : python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 5. Initialiser la BDD & seed

```bash
export FLASK_APP=run.py

flask db init
flask db migrate -m "Initial schema"
flask db upgrade

flask seed-db        # Insère les données de test
```

### 6. Lancer l'application

```bash
flask run --host=0.0.0.0 --port=5000
# ou
python run.py
```

Ouvrez http://localhost:5000

---

## 🔐 Comptes de test (après seed)

| Rôle       | Email                        | Mot de passe |
|------------|------------------------------|--------------|
| Admin      | admin@univ.ma                | Admin@1234   |
| Enseignant | prof.alami@univ.ma           | Prof@1234    |
| Étudiant   | etudiant1@univ.ma            | Etu@1234     |

---

## 📸 Enrôlement des visages

```bash
# Sur le Raspberry Pi avec caméra connectée
flask enroll-student <student_id>
# Appuyez sur ESPACE pour capturer, Q pour quitter
```

---

## 🔒 Chiffrement AES-256-GCM (CNDP)

Chaque encodage facial (vecteur 128-float64) et chaque photo sont chiffrés individuellement :

```python
ciphertext, nonce, tag = CryptoService.encrypt(encoding_bytes)
# nonce : 96 bits aléatoire (NIST SP 800-38D)
# tag   : 128 bits (authentification Galois)
```

Les 3 composantes sont stockées dans des colonnes séparées de la BDD. Même si la BDD est compromise, les données biométriques sont inaccessibles sans la clé maître.

---

## 🛡️ Conformité CNDP

| Mesure                        | Implémentation                              |
|-------------------------------|---------------------------------------------|
| Chiffrement biométrique       | AES-256-GCM par enregistrement              |
| Pseudonymisation              | HMAC-SHA256 tronqué (colonne `pseudonym`)   |
| Consentement explicite        | Champ `consent_given` + `consent_date`      |
| Droit à l'oubli               | Soft delete (`deleted_at`) + purge CLI      |
| Durée de conservation         | `flask purge-expired-data` (configurable)   |
| Traçabilité                   | Table `audit_logs` (toutes les actions)     |
| Limitation des tentatives     | Lockout après N échecs (`locked_until`)     |

---

## 🖥️ Interfaces utilisateur

### Admin
- Dashboard global (stats, graphiques Chart.js)
- Liste et recherche des étudiants
- Détection décrochage (seuil configurable)
- Export Excel global

### Enseignant
- Ouverture/fermeture de séances
- Flux caméra live avec overlay reconnaissance faciale
- Marquage manuel des présences
- Validation des justifications
- Export Excel par séance

### Étudiant
- Tableau de bord personnel avec graphique donut
- Historique complet des présences
- Soumission de justifications d'absence

---

## 🚀 Commandes CLI utiles

```bash
flask seed-db                   # Données de test
flask create-admin              # Créer un admin interactif
flask enroll-student <id>       # Enrôler un étudiant via webcam
flask purge-expired-data        # Purger données expirées (CNDP)
flask db migrate -m "message"   # Créer une migration
flask db upgrade                # Appliquer les migrations
```

---

## 📦 Stack technique

| Composant         | Technologie                        |
|-------------------|------------------------------------|
| Framework web     | Flask 3.0 + Blueprints             |
| ORM               | SQLAlchemy 2.0 + Flask-Migrate     |
| Base de données   | PostgreSQL 16                      |
| Cache/Queue       | Redis + Celery                     |
| Reconnaissance    | face_recognition (dlib) + OpenCV   |
| Chiffrement       | AES-256-GCM (cryptography lib)     |
| Auth              | Flask-Login + bcrypt               |
| Frontend          | Jinja2 + CSS custom + Chart.js     |
| Export            | pandas + xlsxwriter                |
