# ══════════════════════════════════════════════════════════════
# Installation des dépendances anti-spoofing
# ══════════════════════════════════════════════════════════════
# Coller dans requirements.txt :

        # dist.euclidean pour EAR (déjà peut-être installé)

# OpenCV est déjà installé (opencv-python)
# Pas de nouvelles dépendances lourdes — tout est basé sur NumPy + OpenCV


# ══════════════════════════════════════════════════════════════
# Script de test — scripts/test_antispoof.py
# ══════════════════════════════════════════════════════════════
"""
Test de l'anti-spoofing en conditions réelles.
Lance la caméra et affiche le score en temps réel.

Usage :
    python scripts/test_antispoof.py
"""

import sys, os
sys.path.insert(0, os.getcwd())

import cv2
import numpy as np
from mtcnn import MTCNN

from app import create_app
from app.services.anti_spoofing import AntiSpoofingService


def test_antispoof():
    app = create_app()
    with app.app_context():
        detector = MTCNN()
        spoof    = AntiSpoofingService()

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("❌ Caméra inaccessible")
            return

        print("✅ Test anti-spoofing démarré")
        print("   Montrez un vrai visage → score élevé")
        print("   Montrez une photo      → score bas")
        print("   Appuyez sur Q pour quitter")

        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            display = frame.copy()

            # Analyser toutes les 3 frames
            if frame_count % 3 == 0:
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                small   = cv2.resize(img_rgb, (0, 0), fx=0.7, fy=0.7)
                faces   = detector.detect_faces(small)

                for face in faces:
                    # Remettre à l'échelle
                    box = [int(v / 0.7) for v in face["box"]]
                    kps = {k: (int(v[0]/0.7), int(v[1]/0.7))
                           for k, v in face["keypoints"].items()}
                    face["box"]       = box
                    face["keypoints"] = kps

                    # Anti-spoofing
                    result = spoof.check_frame(frame, face)

                    x, y, bw, bh = box
                    score = result["score"]

                    # Couleur selon le score
                    if result["is_live"]:
                        color = (0, 220, 90)     # vert
                        label = f"VIVANT {score:.0%}"
                    else:
                        color = (0, 0, 255)      # rouge
                        label = f"SPOOF {score:.0%}"

                    # Bounding box
                    cv2.rectangle(display, (x, y), (x+bw, y+bh), color, 2)
                    cv2.rectangle(display, (x, y-32), (x+bw, y), color, cv2.FILLED)
                    cv2.putText(display, label, (x+6, y-10),
                                cv2.FONT_HERSHEY_DUPLEX, 0.6, (255,255,255), 1)

                    # Détail des scores
                    cv2.putText(display,
                                f"LBP:{result['score_lbp']:.2f} "
                                f"Blink:{result['score_blink']:.2f} "
                                f"Motion:{result['score_motion']:.2f}",
                                (x, y+bh+18),
                                cv2.FONT_HERSHEY_PLAIN, 0.9, color, 1)

                    print(f"\r  Score={score:.2f} | LBP={result['score_lbp']:.2f} "
                          f"| Blink={result['score_blink']:.2f} "
                          f"| Motion={result['score_motion']:.2f} "
                          f"| {result['reason']}          ", end="")

            cv2.imshow("FaceAttend — Test Anti-Spoofing", display)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()
        print("\n\n✅ Test terminé")


if __name__ == "__main__":
    test_antispoof()
