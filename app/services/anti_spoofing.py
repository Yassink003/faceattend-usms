"""
AntiSpoofingService — Détection de vivacité en 4 couches
=========================================================

Couche 1 : LBP (Local Binary Patterns)    — texture d'écran/photo
Couche 2 : Blink Detection (EAR)          — clignement des yeux
Couche 3 : Optical Flow (Lucas-Kanade)    — micro-mouvements naturels
Couche 4 : Score combiné pondéré          — décision finale

Usage dans face_service.py :
    from app.services.anti_spoofing import AntiSpoofingService

    spoof_result = AntiSpoofingService.check(
        frame_history,          # liste des 10-15 derniers frames BGR
        face_box,               # [x, y, w, h] du visage détecté
        face_keypoints,         # landmarks MTCNN
    )
    if not spoof_result["is_live"]:
        logger.warning(f"SPOOF détecté — score={spoof_result['score']:.2f}")
        continue   # ne pas pointer
"""

import numpy as np
from collections import deque
from loguru import logger

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("[ANTISPOOF] OpenCV non disponible")

from scipy.spatial import distance as dist


# ══════════════════════════════════════════════════════════════
#  CONSTANTES
# ══════════════════════════════════════════════════════════════

# Seuil en dessous duquel on refuse (0.0 = mort / 1.0 = vivant certain)
LIVENESS_THRESHOLD    = 0.60

# Poids de chaque couche dans le score final
WEIGHT_LBP    = 0.40
WEIGHT_BLINK  = 0.40
WEIGHT_MOTION = 0.20

# EAR (Eye Aspect Ratio) — en dessous = œil fermé
EAR_THRESHOLD        = 0.20
EAR_CONSEC_FRAMES    = 3      # frames consécutifs pour valider un clignement

# LBP — variance minimale pour une texture "vivante"
LBP_VARIANCE_THRESHOLD = 50.0

# Optical flow — mouvement minimal attendu entre frames
FLOW_MIN_MAGNITUDE = 0.3
FLOW_MAX_MAGNITUDE = 8.0     # au-delà = secousse anormale (vidéo accélérée)


# ══════════════════════════════════════════════════════════════
#  COUCHE 1 — LBP (Local Binary Patterns)
# ══════════════════════════════════════════════════════════════

def _compute_lbp(gray_face):
    """
    Calcule le LBP d'un visage en niveaux de gris.
    Un écran/photo a une texture uniforme (variance LBP faible).
    Un vrai visage a une texture riche (variance LBP élevée).
    """
    if not CV2_AVAILABLE:
        return 1.0   # on ne peut pas juger → on ne pénalise pas

    h, w = gray_face.shape
    lbp = np.zeros_like(gray_face, dtype=np.uint8)

    # Calcul LBP sur chaque pixel (voisinage 8 pixels)
    for cy in range(1, h - 1):
        for cx in range(1, w - 1):
            center = gray_face[cy, cx]
            code   = 0
            neighbors = [
                gray_face[cy-1, cx-1], gray_face[cy-1, cx], gray_face[cy-1, cx+1],
                gray_face[cy,   cx+1],
                gray_face[cy+1, cx+1], gray_face[cy+1, cx], gray_face[cy+1, cx-1],
                gray_face[cy,   cx-1],
            ]
            for i, n in enumerate(neighbors):
                if n >= center:
                    code |= (1 << (7 - i))
            lbp[cy, cx] = code

    # Histogramme LBP → variance
    hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
    hist    = hist.astype(np.float32) / (hist.sum() + 1e-7)
    variance = float(np.var(hist) * 1e6)   # amplifier pour lisibilité

    logger.debug(f"[ANTISPOOF] LBP variance={variance:.1f} (seuil={LBP_VARIANCE_THRESHOLD})")

    # Normaliser en score 0→1
    score = min(1.0, variance / (LBP_VARIANCE_THRESHOLD * 2))
    return score


# ══════════════════════════════════════════════════════════════
#  COUCHE 2 — Blink Detection (Eye Aspect Ratio)
# ══════════════════════════════════════════════════════════════

def _eye_aspect_ratio(eye_points):
    """
    EAR = (||p2-p6|| + ||p3-p5||) / (2 * ||p1-p4||)
    Valeur ≈ 0.3 yeux ouverts, < 0.2 yeux fermés.
    """
    A = dist.euclidean(eye_points[1], eye_points[5])
    B = dist.euclidean(eye_points[2], eye_points[4])
    C = dist.euclidean(eye_points[0], eye_points[3])
    return (A + B) / (2.0 * C + 1e-7)


def _get_eye_points_from_landmarks(keypoints):
    """
    Reconstruit 6 points approximatifs par œil depuis les landmarks MTCNN.
    MTCNN ne donne que le centre des yeux — on les étend artificiellement.
    """
    le = np.array(keypoints["left_eye"],  dtype=np.float32)
    re = np.array(keypoints["right_eye"], dtype=np.float32)

    # Estimer la largeur de l'œil (≈ distance inter-oculaire / 4)
    eye_w = np.linalg.norm(re - le) / 4.0

    # 6 points approximatifs autour du centre de chaque œil
    def expand(center, w):
        cx, cy = center
        return [
            (cx - w, cy),           # coin gauche
            (cx - w/2, cy - w/3),   # haut gauche
            (cx + w/2, cy - w/3),   # haut droite
            (cx + w, cy),           # coin droit
            (cx + w/2, cy + w/3),   # bas droite
            (cx - w/2, cy + w/3),   # bas gauche
        ]

    return expand(le, eye_w), expand(re, eye_w)


class BlinkTracker:
    """
    Suit le clignement sur une séquence de frames.
    Doit être instancié une fois par session de caméra.
    """
    def __init__(self):
        self.blink_count  = 0
        self.frame_below  = 0     # frames consécutifs avec EAR bas
        self.ear_history  = deque(maxlen=30)

    def update(self, keypoints):
        """
        Met à jour le tracker avec les landmarks du frame courant.
        Retourne le score de vivacité basé sur les clignements.
        """
        try:
            left_eye, right_eye = _get_eye_points_from_landmarks(keypoints)
            ear_l = _eye_aspect_ratio(left_eye)
            ear_r = _eye_aspect_ratio(right_eye)
            ear   = (ear_l + ear_r) / 2.0

            self.ear_history.append(ear)

            if ear < EAR_THRESHOLD:
                self.frame_below += 1
            else:
                if self.frame_below >= EAR_CONSEC_FRAMES:
                    self.blink_count += 1
                    logger.debug(f"[ANTISPOOF] Clignement #{self.blink_count} détecté (EAR={ear:.3f})")
                self.frame_below = 0

            # Score : 0 clignement = 0, 1 = 0.6, 2+ = 1.0
            if self.blink_count == 0:
                return 0.0
            elif self.blink_count == 1:
                return 0.6
            else:
                return 1.0

        except Exception as e:
            logger.error(f"[ANTISPOOF] BlinkTracker.update erreur : {e}")
            return 0.5   # incertain → neutre


# ══════════════════════════════════════════════════════════════
#  COUCHE 3 — Optical Flow (Lucas-Kanade)
# ══════════════════════════════════════════════════════════════

class MotionTracker:
    """
    Détecte les micro-mouvements naturels d'un visage vivant.
    Une photo/vidéo figée a un flow ≈ 0.
    """
    def __init__(self):
        self.prev_gray   = None
        self.prev_points = None
        self.flow_history = deque(maxlen=20)

        self.lk_params = dict(
            winSize=(15, 15),
            maxLevel=2,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03)
        ) if CV2_AVAILABLE else {}

        self.feature_params = dict(
            maxCorners=50,
            qualityLevel=0.3,
            minDistance=7,
            blockSize=7
        ) if CV2_AVAILABLE else {}

    def update(self, frame_gray, face_box):
        """
        Met à jour le tracker avec le frame courant (niveaux de gris).
        Retourne un score de mouvement 0.0→1.0.
        """
        if not CV2_AVAILABLE:
            return 0.5

        try:
            x, y, bw, bh = face_box
            # ROI = zone du visage uniquement
            roi = frame_gray[max(0,y):y+bh, max(0,x):x+bw]
            if roi.size == 0:
                return 0.5

            roi_resized = cv2.resize(roi, (80, 80))

            if self.prev_gray is None or self.prev_points is None or len(self.prev_points) < 5:
                # Initialisation — trouver les points à suivre
                self.prev_gray   = roi_resized
                self.prev_points = cv2.goodFeaturesToTrack(
                    roi_resized, mask=None, **self.feature_params
                )
                return 0.5   # pas encore de mesure

            # Calcul optical flow
            next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
                self.prev_gray, roi_resized,
                self.prev_points, None, **self.lk_params
            )

            if next_pts is None or status is None:
                self.prev_gray   = roi_resized
                self.prev_points = None
                return 0.5

            good_new = next_pts[status.flatten() == 1]
            good_old = self.prev_points[status.flatten() == 1]

            if len(good_new) < 3:
                self.prev_gray   = roi_resized
                self.prev_points = cv2.goodFeaturesToTrack(roi_resized, mask=None, **self.feature_params)
                return 0.5

            # Magnitude moyenne des déplacements
            deltas    = good_new - good_old
            magnitudes = np.linalg.norm(deltas, axis=1)
            mean_mag  = float(np.mean(magnitudes))

            self.flow_history.append(mean_mag)
            self.prev_gray   = roi_resized
            self.prev_points = good_new.reshape(-1, 1, 2)

            logger.debug(f"[ANTISPOOF] Optical flow mean_mag={mean_mag:.3f}")

            # Score selon la magnitude
            if mean_mag < FLOW_MIN_MAGNITUDE:
                # Trop immobile → photo/vidéo figée
                return 0.1
            elif mean_mag > FLOW_MAX_MAGNITUDE:
                # Trop agité → vidéo accélérée ou secousse
                return 0.3
            else:
                # Mouvement naturel
                return 1.0

        except Exception as e:
            logger.error(f"[ANTISPOOF] MotionTracker.update erreur : {e}")
            return 0.5


# ══════════════════════════════════════════════════════════════
#  SERVICE PRINCIPAL
# ══════════════════════════════════════════════════════════════

class AntiSpoofingService:
    """
    Gestionnaire de vivacité par session caméra.
    Une instance par thread caméra (CameraThread).

    Usage :
        spoof = AntiSpoofingService()

        # Dans la boucle de frames :
        result = spoof.check_frame(frame, face_info)

        if result["is_live"]:
            # autoriser la reconnaissance
        else:
            # bloquer + logger
    """

    def __init__(self):
        self.blink_tracker  = BlinkTracker()
        self.motion_tracker = MotionTracker()
        self._liveness_threshold = LIVENESS_THRESHOLD
        logger.info("[ANTISPOOF] Service initialisé (LBP + Blink + Optical Flow)")

    def reset(self):
        """Réinitialise les trackers pour une nouvelle personne."""
        self.blink_tracker  = BlinkTracker()
        self.motion_tracker = MotionTracker()

    def check_frame(self, frame_bgr, face_info):
        """
        Analyse un frame et retourne le résultat de vivacité.

        Args:
            frame_bgr : frame OpenCV BGR
            face_info : dict MTCNN {"box": [...], "keypoints": {...}, "confidence": ...}

        Returns:
            dict {
                "is_live":      bool,
                "score":        float (0.0 → 1.0),
                "score_lbp":    float,
                "score_blink":  float,
                "score_motion": float,
                "reason":       str,
            }
        """
        if not CV2_AVAILABLE:
            return self._result(True, 1.0, 1.0, 1.0, 1.0, "OpenCV absent — bypass")

        try:
            box       = face_info["box"]
            keypoints = face_info["keypoints"]

            # ── Couche 1 : LBP ──────────────────────────────
            img_rgb  = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            x, y, bw, bh = box
            face_roi = img_rgb[max(0,y):y+bh, max(0,x):x+bw]
            if face_roi.size == 0:
                return self._result(False, 0.0, 0.0, 0.0, 0.0, "ROI vide")

            gray_face    = cv2.cvtColor(face_roi, cv2.COLOR_RGB2GRAY)
            gray_face_64 = cv2.resize(gray_face, (64, 64))
            score_lbp    = _compute_lbp(gray_face_64)

            # ── Couche 2 : Blink ────────────────────────────
            score_blink = self.blink_tracker.update(keypoints)

            # ── Couche 3 : Optical Flow ──────────────────────
            gray_frame   = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            score_motion = self.motion_tracker.update(gray_frame, box)

            # ── Couche 4 : Score combiné ─────────────────────
            score = (
                score_lbp    * WEIGHT_LBP    +
                score_blink  * WEIGHT_BLINK  +
                score_motion * WEIGHT_MOTION
            )

            is_live = score >= self._liveness_threshold

            reason = self._explain(score_lbp, score_blink, score_motion, score)

            logger.info(
                f"[ANTISPOOF] score={score:.2f} "
                f"(LBP={score_lbp:.2f} Blink={score_blink:.2f} Motion={score_motion:.2f}) "
                f"→ {'VIVANT' if is_live else '⚠️ SPOOF'}"
            )

            return self._result(is_live, score, score_lbp, score_blink, score_motion, reason)

        except Exception as e:
            logger.error(f"[ANTISPOOF] Erreur check_frame : {e}")
            # En cas d'erreur → on refuse par défaut (fail-secure)
            return self._result(False, 0.0, 0.0, 0.0, 0.0, f"Erreur : {e}")

    @staticmethod
    def _result(is_live, score, lbp, blink, motion, reason):
        return {
            "is_live":      is_live,
            "score":        round(score, 3),
            "score_lbp":    round(lbp, 3),
            "score_blink":  round(blink, 3),
            "score_motion": round(motion, 3),
            "reason":       reason,
        }

    @staticmethod
    def _explain(lbp, blink, motion, total):
        """Génère une explication lisible du résultat."""
        if total >= LIVENESS_THRESHOLD:
            return "Vivacité confirmée"
        reasons = []
        if lbp < 0.4:
            reasons.append("texture plate (photo/écran)")
        if blink < 0.3:
            reasons.append("aucun clignement détecté")
        if motion < 0.3:
            reasons.append("aucun mouvement naturel")
        return "SPOOF probable : " + ", ".join(reasons) if reasons else "Score insuffisant"
