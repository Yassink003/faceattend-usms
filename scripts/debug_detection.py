import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from app import create_app
from app.services.face_service import FaceRecognitionService, _get_detector, _get_embedder, _align_face, _embed_face

app = create_app()

with app.app_context():
    # 1. Charger l'encodage de référence depuis la BDD
    print("=== Chargement encodage BDD ===")
    encodings = FaceRecognitionService.load_all_encodings()
    print(f"Encodages trouvés : {len(encodings)}")
    if not encodings:
        print("ERREUR : aucun encodage en base")
        sys.exit(1)

    ref_vec = encodings[0]["encoding"]
    print(f"Vecteur référence : dim={ref_vec.shape}, norme={np.linalg.norm(ref_vec):.4f}")

    # 2. Capturer un frame depuis la webcam
    print("\n=== Capture webcam ===")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    print("Place-toi devant la caméra et appuie sur ESPACE pour capturer, Q pour quitter")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        cv2.imshow("Debug - ESPACE pour capturer", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(' '):
            print("\n=== Analyse du frame capturé ===")
            img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # 3. Détection MTCNN
            detector = _get_detector()
            faces = detector.detect_faces(img_rgb)
            print(f"Visages détectés : {len(faces)}")

            if len(faces) == 0:
                print("AUCUN visage détecté — améliore l'éclairage")
                continue

            for i, face in enumerate(faces):
                print(f"\nVisage {i+1} :")
                print(f"  Confiance MTCNN : {face['confidence']:.4f}")
                print(f"  Box             : {face['box']}")

                # 4. Alignement
                aligned = _align_face(img_rgb, face["box"], face["keypoints"])
                if aligned is None:
                    print("  ERREUR alignement")
                    continue

                # 5. Embedding FaceNet
                query_vec = _embed_face(aligned)
                if query_vec is None:
                    print("  ERREUR embedding")
                    continue

                print(f"  Embedding dim   : {query_vec.shape}")
                print(f"  Norme           : {np.linalg.norm(query_vec):.4f}")

                # 6. Distance L2 vs référence BDD
                distance = float(np.linalg.norm(ref_vec - query_vec))
                confidence = max(0.0, 1.0 - distance / 2.0)

                print(f"\n  === RÉSULTAT ===")
                print(f"  Distance L2  : {distance:.4f}")
                print(f"  Confiance    : {confidence:.1%}")
                print(f"  Seuil actuel : 0.90")
                if distance <= 0.90:
                    print(f"  Décision     : RECONNU ✅")
                else:
                    print(f"  Décision     : NON RECONNU ❌")
                    print(f"  → Seuil nécessaire pour reconnaître : {distance:.2f}")
                    print(f"  → Ajoute dans .env : FACE_RECOGNITION_TOLERANCE={distance + 0.05:.2f}")

        elif key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()