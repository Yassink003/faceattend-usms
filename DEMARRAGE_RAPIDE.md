# FaceAttend — Démarrage rapide
## MTCNN + FaceNet-128 | PostgreSQL | AES-256-GCM | @usms.ac.ma

---

## 1. Prérequis

- Python 3.10 ou 3.11
- PostgreSQL 14+ installé et en cours d'exécution
- Webcam (index 0 par défaut)

---

## 2. Installation des dépendances

```bash
# Créer l'environnement virtuel
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# Installer les dépendances
# IMPORTANT : tensorflow doit s'installer en premier
pip install tensorflow==2.15.1
pip install mtcnn==0.1.1 keras-facenet==0.3.2
pip install -r requirements.txt
```

> 💡 **Sans GPU ?** Remplacer `tensorflow` par `tensorflow-cpu` dans requirements.txt
> C'est suffisant pour la reconnaissance faciale en temps réel.

---

## 3. Configuration PostgreSQL

```sql
-- Dans psql ou pgAdmin
CREATE USER faceattend WITH PASSWORD 'faceattend';
CREATE DATABASE faceattend_db OWNER faceattend;
GRANT ALL PRIVILEGES ON DATABASE faceattend_db TO faceattend;
```

Le `.env` est déjà configuré pour cette connexion :
```
DATABASE_URL=postgresql://faceattend:faceattend@localhost:5432/faceattend_db
```

---

## 4. Initialiser la base de données

```bash
# Créer les tables
flask db upgrade

# (Optionnel) Créer les utilisateurs de test @usms.ac.ma
python scripts/seed.py

# Comptes créés :
#   Admin    : admin@usms.ac.ma          / Admin@1234
#   Enseignant: prof.alami@usms.ac.ma    / Prof@1234
#   Étudiant : etudiant1@usms.ac.ma      / Etu@1234
```

---

## 5. Enrôler votre visage (MTCNN + FaceNet-128)

### Préparer vos photos

```
data/photos/
└── VOTRE_CNE/          ← renommez ce dossier avec votre numéro étudiant
    ├── photo1.jpg      ← prenez 3 à 5 photos sous différents angles
    ├── photo2.jpg      ← bonne lumière, visage bien cadré, 1 seul visage
    └── photo3.jpg
```

**Conseils pour de meilleures photos :**
- Lumière frontale uniforme (éviter le contre-jour)
- Visage centré, regard vers la caméra
- Une photo de face + une légèrement de profil gauche + une de profil droit
- Sans chapeau, lunettes de soleil ou masque
- Résolution minimale : 480×480 px

### Lancer l'enrôlement

```bash
# Enrôler un seul étudiant
python scripts/enroll_from_photos.py enroll --student-number VOTRE_CNE --photos data/photos/

# Enrôler TOUS les étudiants (tous les sous-dossiers de data/photos/)
python scripts/enroll_from_photos.py enroll --photos data/photos/

# Simuler sans écrire en base (test)
python scripts/enroll_from_photos.py enroll --student-number VOTRE_CNE --dry-run

# Vérifier qu'une photo est bien reconnue
python scripts/enroll_from_photos.py verify --student-number VOTRE_CNE --photo data/photos/VOTRE_CNE/test.jpg
```

L'embedding FaceNet-128 est automatiquement :
- Calculé comme **moyenne** de toutes les photos valides
- **Chiffré AES-256-GCM** avant stockage
- Stocké dans PostgreSQL (table `students`)

---

## 6. Démarrer l'application

```bash
python run.py
```

Ouvrir : **http://localhost:5000**

---

## 7. Tester la détection de votre visage

1. Connectez-vous avec `admin@usms.ac.ma` / `Admin@1234`
2. Allez dans **Administration → Étudiants** → vérifiez que votre visage est enrôlé (✅)
3. Connectez-vous comme enseignant → **Ouvrir une séance** pour un cours
4. Cliquez **Démarrer la caméra** — le flux MJPEG s'active
5. Placez-vous devant la webcam → votre nom apparaît en vert si reconnu

**Paramètres de reconnaissance (dans .env) :**
```
FACE_RECOGNITION_TOLERANCE=0.90   # Distance L2 max (0.80 = strict, 1.00 = souple)
FACE_DETECTION_MODEL=mtcnn        # Détecteur utilisé
CAPTURE_INTERVAL_SECONDS=3        # Fréquence de marquage des présences
```

---

## 8. Architecture de la reconnaissance

```
Webcam frame (BGR)
       │
       ▼
  MTCNN Detector
  • Localise les visages (boîtes)
  • Détecte 5 landmarks (yeux, nez, bouche)
  • Score de confiance (seuil : 0.85)
       │
       ▼
  Alignement (rotation via landmarks yeux)
  + Recadrage 160×160 px
       │
       ▼
  FaceNet-128 Embedder
  • Vecteur 128 float32
  • Normalisé L2
       │
       ▼
  Distance L2 vs encodages PostgreSQL
  (déchiffrés AES-256-GCM à la volée)
       │
       ▼
  Seuil FACE_RECOGNITION_TOLERANCE
  ├─ distance ≤ seuil → PRÉSENT ✅
  └─ distance >  seuil → INCONNU ❌
```

---

## 9. Domaine email USMS

Tous les comptes utilisent désormais `@usms.ac.ma` :
- `admin@usms.ac.ma`
- `prof.nom@usms.ac.ma`
- `etudiant@usms.ac.ma`

Le placeholder de la page de connexion a été mis à jour en conséquence.

---

## Dépannage

| Problème | Solution |
|----------|----------|
| `ModuleNotFoundError: mtcnn` | `pip install mtcnn keras-facenet tensorflow` |
| `psycopg2 connection refused` | Vérifier que PostgreSQL tourne : `pg_ctl status` |
| `AES_MASTER_KEY invalide` | La clé doit faire exactement 64 caractères hex |
| Visage non détecté | Améliorer l'éclairage, rapprocher de la caméra |
| Distance trop grande | Ajouter plus de photos d'enrôlement ou augmenter le seuil |
| GPU non détecté | `pip install tensorflow-cpu` à la place de `tensorflow` |
