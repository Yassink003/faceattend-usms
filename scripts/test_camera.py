import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from app import create_app
from app.services.face_service import FaceRecognitionService

app = create_app()

with app.app_context():

    # 1. Charger les encodages depuis la base
    print("Chargement des encodages...")
    encodings = FaceRecognitionService.load_all_encodings()
    print(f"  → {len(encodings)} encodage(s) charge(s)")

    if not encodings:
        print("❌ Aucun encodage en base. Lance d'abord enroll_direct.py")
        sys.exit(1)

    from app.models import Student
    students = Student.query.all()
    student_map = {s.id: s.full_name for s in students}

    # 2. Ouvrir la webcam avec DirectShow
    print("\nOuverture webcam (appuie sur Q pour quitter)...")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("❌ Webcam introuvable")
        sys.exit(1)

    print("✅ Webcam ouverte — place-toi devant la caméra")

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("⚠️  Frame vide")
            continue

        # 3. Détecter et identifier
        detections = FaceRecognitionService.identify_faces_in_frame(frame, encodings)

        for d in detections:
            sid  = d["student_id"]
            name = student_map.get(sid, "Inconnu") if sid else "Inconnu"
            dist = d["distance"]
            conf = d["confidence"]
            print(f"  Visage → {name} | distance={dist:.4f} | confiance={conf:.1%}")

        # 4. Afficher le frame
        frame = FaceRecognitionService.draw_results(frame, detections, student_map)
        cv2.imshow("Test Detection - Q pour quitter", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Caméra fermée.")