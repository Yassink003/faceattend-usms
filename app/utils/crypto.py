"""
CryptoService — Chiffrement AES-256-GCM (mode Galois/Counter)
Conforme CNDP : chiffrement authentifié, nonce unique par opération.

AES-GCM fournit :
  • Confidentialité  (chiffrement AES-CTR)
  • Intégrité        (tag d'authentification Galois 128 bits)
  • Authenticité     (toute modification du texte chiffré est détectée)
"""

import os
import struct
import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app
from loguru import logger


class CryptoService:
    """Chiffrement/déchiffrement AES-256-GCM pour les données biométriques."""

    NONCE_SIZE = 12    # 96 bits — recommandation NIST SP 800-38D
    TAG_SIZE   = 16    # 128 bits — taille du tag d'authentification GCM

    @classmethod
    def _get_key(cls) -> bytes:
        """Récupère la clé maître depuis la configuration Flask."""
        key = current_app.config.get("AES_MASTER_KEY")
        if not key or len(key) != 32:
            raise ValueError(
                "AES_MASTER_KEY doit être exactement 32 bytes (256 bits). "
                "Générez-en une avec: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return key

    @classmethod
    def encrypt(cls, plaintext: bytes) -> tuple[bytes, bytes, bytes]:
        """
        Chiffre des données avec AES-256-GCM.

        Retourne : (ciphertext, nonce, tag)
        Le nonce (96 bits) est généré aléatoirement à chaque appel.
        Le tag (128 bits) permet de vérifier l'intégrité au déchiffrement.
        """
        key   = cls._get_key()
        nonce = os.urandom(cls.NONCE_SIZE)
        aesgcm = AESGCM(key)

        # AESGCM.encrypt() retourne ciphertext + tag (tag en fin de buffer)
        ct_with_tag = aesgcm.encrypt(nonce, plaintext, associated_data=None)

        # Séparer ciphertext et tag
        ciphertext = ct_with_tag[:-cls.TAG_SIZE]
        tag        = ct_with_tag[-cls.TAG_SIZE:]

        return ciphertext, nonce, tag

    @classmethod
    def decrypt(cls, ciphertext: bytes, nonce: bytes, tag: bytes) -> bytes:
        """
        Déchiffre et vérifie l'intégrité AES-256-GCM.

        Lève InvalidTag si les données ont été altérées.
        """
        key    = cls._get_key()
        aesgcm = AESGCM(key)

        ct_with_tag = ciphertext + tag
        try:
            plaintext = aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)
            return plaintext
        except Exception as exc:
            logger.error(f"[CRYPTO] Échec déchiffrement AES-GCM : {exc}")
            raise

    # ── Helpers spécifiques aux encodages faciaux ────────────

    @classmethod
    def encrypt_face_encoding(cls, encoding: np.ndarray) -> tuple[bytes, bytes, bytes]:
        """
        Sérialise un vecteur numpy FaceNet-128 (float32, 512 bytes) puis chiffre.
        Compatible aussi avec les anciens vecteurs float64 128D (dlib).
        """
        raw = encoding.astype(np.float32).tobytes()   # 128 × 4 = 512 bytes (FaceNet)
        return cls.encrypt(raw)

    @classmethod
    def decrypt_face_encoding(cls, ciphertext: bytes, nonce: bytes, tag: bytes) -> np.ndarray:
        """Déchiffre et désérialise en vecteur numpy float32 (FaceNet-128)."""
        raw = cls.decrypt(ciphertext, nonce, tag)
        # Détecter automatiquement le type selon la taille
        n = len(raw)
        if n == 512:
            return np.frombuffer(raw, dtype=np.float32)   # FaceNet float32
        elif n == 1024:
            return np.frombuffer(raw, dtype=np.float64)   # legacy dlib float64
        else:
            raise ValueError(f"Taille d'encodage inattendue : {n} bytes")

    # ── Pseudonymisation ────────────────────────────────────

    @classmethod
    def pseudonymize(cls, student_id: int) -> str:
        """
        Génère un pseudonyme déterministe pour un étudiant (CNDP Art. 8).
        Utilise HMAC-SHA256 tronqué à 32 hex chars.
        """
        import hmac, hashlib
        key = cls._get_key()
        h = hmac.new(key, str(student_id).encode(), hashlib.sha256)
        return h.hexdigest()[:32]
