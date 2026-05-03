"""
FaceRecognitionService — MTCNN (détection) + FaceNet-128 (encodage).
Remplace l'ancienne implémentation dlib/face_recognition.

Pipeline :
  1. MTCNN    → détecte et aligne les visages (boîtes + landmarks)
  2. FaceNet  → produit un vecteur d'embedding 128-float32 par visage
  3. Distance euclidienne (L2) normalisée → identification

Avantages vs dlib HOG :
  • Meilleure précision sur visages partiels / mal éclairés
  • Alignement automatique via landmarks (yeux, nez, bouche)
  • Embeddings FaceNet stables et robustes
"""

import io
import numpy as np
from loguru import logger

# ── Imports optionnels (gracieux si modèles non installés) ──
try:
    from mtcnn import MTCNN
    import cv2
    from PIL import Image
    MTCNN_AVAILABLE = True
except ImportError as e:
    MTCNN_AVAILABLE = False
    logger.warning(f"[FACE] MTCNN non disponible ({e}). Mode dégradé actif.")

try:
    from keras_facenet import FaceNet
    FACENET_AVAILABLE = True
except ImportError as e:
    FACENET_AVAILABLE = False
    logger.warning(f"[FACE] FaceNet non disponible ({e}). Mode dégradé actif.")

FACE_LIB_AVAILABLE = MTCNN_AVAILABLE and FACENET_AVAILABLE

# ── Singletons (chargés une seule fois) ─────────────────────
_detector = None
_embedder = None

FACE_IMG_SIZE    = 160       # FaceNet attend des patches 160×160
DEFAULT_TOLERANCE = 0.90     # Distance L2 max (seuil de reconnaissance)


def _get_detector():
    global _detector
    if _detector is None:
        _detector = MTCNN()
        logger.info("[FACE] MTCNN chargé.")
    return _detector


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = FaceNet()
        logger.info("[FACE] FaceNet-128 chargé.")
    return _embedder


def _align_face(img_rgb, box, keypoints, target_size=FACE_IMG_SIZE):
    """
    Aligne un visage via les landmarks MTCNN (yeux) puis le redimensionne.
    Retourne un patch RGB (target_size × target_size × 3) ou None si échec.
    """
    try:
        left_eye  = np.array(keypoints["left_eye"],  dtype=np.float32)
        right_eye = np.array(keypoints["right_eye"], dtype=np.float32)

        dy = right_eye[1] - left_eye[1]
        dx = right_eye[0] - left_eye[0]
        angle = float(np.degrees(np.arctan2(dy, dx)))

        eye_center = ((left_eye + right_eye) / 2)
        h, w = img_rgb.shape[:2]
        center_tuple = (float(eye_center[0]), float(eye_center[1]))
        M = cv2.getRotationMatrix2D(center_tuple, angle, scale=1.0)
        aligned = cv2.warpAffine(img_rgb, M, (w, h), flags=cv2.INTER_LINEAR)

        x, y, bw, bh = box
        x1 = max(0, x); y1 = max(0, y)
        x2 = min(w, x + bw); y2 = min(h, y + bh)
        face_crop = aligned[y1:y2, x1:x2]

        if face_crop.size == 0:
            return None

        face_resized = cv2.resize(face_crop, (target_size, target_size),
                                  interpolation=cv2.INTER_AREA)
        return face_resized
    except Exception as exc:
        logger.error(f"[FACE] Alignement échoué : {exc}")
        return None


def _embed_face(face_rgb):
    """Calcule l'embedding FaceNet-128 d'un patch 160×160 RGB."""
    try:
        embedder = _get_embedder()
        batch = np.expand_dims(face_rgb, axis=0)
        embs  = embedder.embeddings(batch)   # shape (1, 128)
        vec   = embs[0].astype(np.float32)
        norm  = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec
    except Exception as exc:
        logger.error(f"[FACE] Embedding FaceNet échoué : {exc}")
        return None


class FaceRecognitionService:
    """
    Interface publique identique à l'ancienne (dlib/face_recognition).
    Les méthodes retournent des valeurs neutres si les libs sont absentes.
    """

    @classmethod
    def is_available(cls):
        return FACE_LIB_AVAILABLE

    # ── Encodage depuis bytes d'image ────────────────────────

    @classmethod
    def encode_face_from_bytes(cls, image_bytes):
        """
        Détecte, aligne et encode le visage depuis des bytes JPEG/PNG.
        Retourne un vecteur numpy float32 de dimension 128, ou None.
        """
        if not FACE_LIB_AVAILABLE:
            logger.warning("[FACE] Bibliothèques MTCNN/FaceNet non installées.")
            return None
        try:
            pil     = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_rgb = np.array(pil)

            detector = _get_detector()
            faces    = detector.detect_faces(img_rgb)

            if len(faces) == 0:
                logger.warning("[FACE] Aucun visage détecté.")
                return None
            if len(faces) > 1:
                logger.warning(f"[FACE] {len(faces)} visages — attendu 1 seul par photo.")
                return None

            face_info = faces[0]
            if face_info["confidence"] < 0.90:
                logger.warning(f"[FACE] Confiance MTCNN trop basse : {face_info['confidence']:.2f}")
                return None

            aligned = _align_face(img_rgb, face_info["box"], face_info["keypoints"])
            if aligned is None:
                return None

            return _embed_face(aligned)

        except Exception as exc:
            logger.error(f"[FACE] Erreur encode_face_from_bytes : {exc}")
            return None

    # ── Enrôlement ───────────────────────────────────────────
    @classmethod
    def enroll_student(cls, student, photo_bytes):
            if not FACE_LIB_AVAILABLE:
               logger.error("[FACE] Impossible d'enrôler : MTCNN/FaceNet non installés.")
               return False

            from app import db
            encoding = cls.encode_face_from_bytes(photo_bytes)
            if encoding is None:
               logger.error(f"[FACE] Enrôlement échoué pour {student.student_number}.")
               return False

            try:
               student.set_face_encoding(encoding.astype(np.float32).tobytes())
               student.set_face_photo(photo_bytes)
               db.session.add(student)
               db.session.flush()   # force l'écriture sans fermer la transaction
               logger.info(f"[FACE] Étudiant {student.student_number} enrôlé (FaceNet-128).")
               return True
            except Exception as e:
               db.session.rollback()
               logger.error(f"[FACE] Erreur sauvegarde embedding : {e}")
               return False

    # ── Chargement de tous les encodages depuis BDD ──────────

    
    @classmethod
    def load_all_encodings(cls):
        if not FACE_LIB_AVAILABLE:
            return []

        from app.models import Student
        students = Student.query.filter(Student.face_encoding_enc.isnot(None)).all()
        result   = []
        for s in students:
            enc_bytes = s.get_face_encoding()
            if enc_bytes:
                try:
                    # Détecter automatiquement la dimension (128 ou 512)
                    for dtype in [np.float32, np.float64]:
                        item_size = np.dtype(dtype).itemsize
                        if len(enc_bytes) % item_size == 0:
                            arr = np.frombuffer(enc_bytes, dtype=dtype).copy()
                            if arr.shape[0] in (128, 512):
                                norm = np.linalg.norm(arr)
                                if norm > 0:
                                    arr = arr / norm
                                result.append({"student_id": s.id, "encoding": arr})
                                logger.info(f"[FACE] Etudiant {s.id} chargé (dim={arr.shape[0]})")
                                break
                except Exception as e:
                    logger.error(f"[FACE] Erreur déchiffrement étudiant {s.id}: {e}")

        logger.info(f"[FACE] {len(result)} encodages FaceNet chargés.")
        return result

    # ── Identification dans un frame OpenCV ─────────────────

    @classmethod
    def identify_faces_in_frame(cls, frame, known_encodings):
        """
        Détecte et identifie les visages dans un frame OpenCV BGR.
        Retourne une liste de dicts {student_id, confidence, location, box}.
        """
        if not FACE_LIB_AVAILABLE or not known_encodings:
            return []

        try:
            from flask import current_app
            tolerance = current_app.config.get("FACE_RECOGNITION_TOLERANCE", DEFAULT_TOLERANCE)

            img_rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            detector = _get_detector()

            # Réduire la taille pour accélérer MTCNN
            scale = 0.7
            small_frame = cv2.resize(img_rgb, (0, 0), fx=scale, fy=scale)
            faces = detector.detect_faces(small_frame)

            # Remettre les coordonnées à l'échelle originale
            for face in faces:
                face["box"] = [int(v / scale) for v in face["box"]]
                face["keypoints"] = {
                    k: (int(v[0] / scale), int(v[1] / scale))
                    for k, v in face["keypoints"].items()
                }
            known_vecs = np.array([d["encoding"] for d in known_encodings], dtype=np.float32)
            known_ids  = [d["student_id"] for d in known_encodings]

            detections = []
            for face_info in faces:
                if face_info["confidence"] < 0.85:
                    continue

                aligned   = _align_face(img_rgb, face_info["box"], face_info["keypoints"])
                if aligned is None:
                    continue

                query_vec = _embed_face(aligned)
                if query_vec is None:
                    continue

                diffs     = known_vecs - query_vec
                distances = np.linalg.norm(diffs, axis=1)
                best_idx  = int(np.argmin(distances))
                best_dist = float(distances[best_idx])
                confidence = max(0.0, 1.0 - best_dist / 2.0)

                x, y, bw, bh = face_info["box"]
                location = (y, x + bw, y + bh, x)   # top,right,bottom,left

                detections.append({
                    "student_id": known_ids[best_idx] if best_dist <= tolerance else None,
                    "confidence": round(confidence, 4),
                    "location":   location,
                    "box":        face_info["box"],
                    "distance":   round(best_dist, 4),
                })
            return detections

        except Exception as e:
            logger.error(f"[FACE] Erreur identification : {e}")
            return []

    # ── Rendu visuel sur frame ───────────────────────────────

    @classmethod
    def draw_results(cls, frame, detections, student_map):
        """Dessine les boîtes et labels sur le frame BGR."""
        if not FACE_LIB_AVAILABLE:
            return frame
        for d in detections:
            x, y, bw, bh = d["box"]
            sid   = d["student_id"]
            label = student_map.get(sid, "Inconnu") if sid else "Inconnu"
            color = (0, 220, 90) if sid else (0, 60, 220)
            cv2.rectangle(frame, (x, y), (x + bw, y + bh), color, 2)
            cv2.rectangle(frame, (x, y + bh - 28), (x + bw, y + bh), color, cv2.FILLED)
            cv2.putText(
                frame, f"{label} ({d['confidence']:.0%})",
                (x + 6, y + bh - 8),
                cv2.FONT_HERSHEY_DUPLEX, 0.55, (255, 255, 255), 1,
            )
        return frame
