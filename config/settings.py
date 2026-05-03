"""Configuration — supporte SQLite (dev rapide) ET PostgreSQL."""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DEBUG = False
    TESTING = False

    # ── Database : SQLite par défaut si DATABASE_URL absent ──
    _db_url = os.getenv("DATABASE_URL", "sqlite:///faceattend.db")
    # Compatibilité SQLAlchemy 2.x avec postgres:// de certains hébergeurs
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-dev-secret")
    JWT_ACCESS_TOKEN_EXPIRES  = timedelta(seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES",  3600)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", 604800)))

    # ── AES-256-GCM ──────────────────────────────────────────
    _raw_key = os.getenv("AES_MASTER_KEY", "0" * 64)
    try:
        AES_MASTER_KEY = bytes.fromhex(_raw_key)
        assert len(AES_MASTER_KEY) == 32
    except Exception:
        # Clé invalide → utiliser une clé de dev (JAMAIS en prod)
        import hashlib
        AES_MASTER_KEY = hashlib.sha256(b"dev-fallback-key").digest()

    FACE_RECOGNITION_TOLERANCE = float(os.getenv("FACE_RECOGNITION_TOLERANCE", 0.90))
    FACE_DETECTION_MODEL       = os.getenv("FACE_DETECTION_MODEL", "mtcnn")
    MAX_PHOTO_SIZE_MB          = int(os.getenv("MAX_PHOTO_SIZE_MB", 5))
    PHOTO_STORAGE_PATH         = os.getenv("PHOTO_STORAGE_PATH", "./data/photos")

    DATA_RETENTION_DAYS   = int(os.getenv("DATA_RETENTION_DAYS", 365))
    CONSENT_REQUIRED      = os.getenv("CONSENT_REQUIRED", "True") == "True"
    ANONYMIZE_AFTER_DAYS  = int(os.getenv("ANONYMIZE_AFTER_DAYS", 730))

    CAMERA_INDEX    = int(os.getenv("CAMERA_INDEX", 0))
    CAMERA_WIDTH    = int(os.getenv("CAMERA_WIDTH", 640))
    CAMERA_HEIGHT   = int(os.getenv("CAMERA_HEIGHT", 480))
    CAMERA_FPS      = int(os.getenv("CAMERA_FPS", 30))
    CAPTURE_INTERVAL = int(os.getenv("CAPTURE_INTERVAL_SECONDS", 3))

    CORS_ORIGINS = ["http://localhost:5000", "http://127.0.0.1:5000"]

    LOGIN_MAX_ATTEMPTS    = int(os.getenv("LOGIN_MAX_ATTEMPTS", 5))
    LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", 15))

    WTF_CSRF_ENABLED = False   # Désactivé en dev pour simplifier


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_ECHO = False   # Passer à True pour voir les requêtes SQL


class ProductionConfig(BaseConfig):
    DEBUG = False
    WTF_CSRF_ENABLED = True
    CORS_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


config_map = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "testing":     TestingConfig,
}
