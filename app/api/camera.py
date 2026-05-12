"""
Blueprint Camera — streaming MJPEG + détection faciale en thread séparé.
"""

import base64
import io
import threading
import time
from flask import Blueprint, Response, jsonify, request, current_app, stream_with_context
from flask_login import login_required, current_user
from app.models import RoleEnum
from loguru import logger
import psutil
from app.services.anti_spoofing import AntiSpoofingService
camera_bp = Blueprint("camera", __name__)

# ── Cache séance ─────────────────────────────────────────────
_known_encodings   = []
_student_names     = {}
_active_session_id = None

# ── Dernière frame traitée (partagée entre threads) ──────────
_latest_frame      = None
_frame_lock        = threading.Lock()

# ── Imports optionnels ───────────────────────────────────────
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("[CAMERA] OpenCV non installé")

try:
    from app.services.face_service import FaceRecognitionService
    from app.services.attendance_service import AttendanceService
    from app.models import Student
    FACE_AVAILABLE = True
except Exception:
    FACE_AVAILABLE = False
    logger.warning("[CAMERA] FaceService non disponible")


# ── Thread de capture + détection ────────────────────────────

class CameraThread(threading.Thread):
    def __init__(self, session_id, camera_index, width,app, height, process_every=8):
        super().__init__(daemon=True)

        self.session_id    = session_id
        self.camera_index  = camera_index
        self.width         = width
        self.height        = height
        self.process_every = process_every
        self.running       = True
        self.app           = app
        self._frame_count = 0
        self.spoof_service = AntiSpoofingService()

    def run(self):
        global _latest_frame

        with self.app.app_context():  
            logger.info(f"[CAMERA] Thread démarré — encodages disponibles : {len(_known_encodings)}") 
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, 15)

            if not cap.isOpened():
                logger.error("[CAMERA] Impossible d'ouvrir la webcam")
                return

            logger.info("[CAMERA] Thread caméra démarré")
            frame_count = 0

            while self.running:
                ret, frame = cap.read()
                if not ret or frame is None:
                    time.sleep(0.05)
                    continue

                frame_count += 1
                try:
        
                   cpu = psutil.cpu_percent(interval=0)
                   interval = 4 if cpu < 40 else 8 if cpu < 70 else 16
                except ImportError:
                   interval = self.process_every   # fallback valeur fixe

                if FACE_AVAILABLE and frame_count % interval == 0:
                    try:
                        if _known_encodings:
                            detections = AttendanceService.process_camera_frame(
                                frame, self.session_id, _known_encodings,
                                spoof_service=self.spoof_service
                            )
                            frame = FaceRecognitionService.draw_results(
                                frame, detections, _student_names
                            )
                        else:
                            cv2.putText(
                                frame, "Aucun visage enrole - Mode manuel",
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (0, 200, 255), 2
                            )
                    except Exception as e:
                        logger.error(f"[CAMERA] Erreur détection : {e}")

                cv2.putText(
                    frame, f"Session #{self.session_id}",
                    (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 245, 160), 1
                )

                _, buffer = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
                )

                with _frame_lock:
                    _latest_frame = buffer.tobytes()

                time.sleep(0.03)

            cap.release()
            logger.info("[CAMERA] Thread caméra arrêté")


# Instance du thread caméra
_camera_thread = None


def _stop_camera():
    global _camera_thread, _latest_frame
    if _camera_thread and _camera_thread.is_alive():
        _camera_thread.running = False
        _camera_thread.join(timeout=2)
    _camera_thread = None
    with _frame_lock:
        _latest_frame = None


# ── Routes ───────────────────────────────────────────────────

@camera_bp.route("/start/<int:session_id>", methods=["POST"])
@login_required
def start_session_camera(session_id):
    global _known_encodings, _student_names, _active_session_id, _camera_thread

    if current_user.role not in (RoleEnum.TEACHER, RoleEnum.ADMIN):
        return jsonify({"error": "Unauthorized"}), 403

    # Arrêter l'ancienne caméra si active
    _stop_camera()

    _active_session_id = session_id

    if FACE_AVAILABLE:
        _known_encodings = FaceRecognitionService.load_all_encodings()
        students = Student.query.all()
        _student_names = {s.id: s.full_name for s in students}
        logger.info(f"[CAMERA] {len(_known_encodings)} encodages chargés")

    # Démarrer le thread caméra
    from flask import current_app
    _camera_thread = CameraThread(
        session_id   = session_id,
        camera_index = current_app.config["CAMERA_INDEX"],
        width        = current_app.config["CAMERA_WIDTH"],
        height       = current_app.config["CAMERA_HEIGHT"],
        app          = current_app._get_current_object(),
        process_every= 8,
    )
    _camera_thread.start()

    return jsonify({
        "loaded":           len(_known_encodings),
        "session_id":       session_id,
        "face_recognition": FACE_AVAILABLE,
    })


@camera_bp.route("/stream/<int:session_id>")
@login_required
def video_stream(session_id):
    if current_user.role not in (RoleEnum.TEACHER, RoleEnum.ADMIN):
        return "Unauthorized", 403

    if not CV2_AVAILABLE:
        return Response(
            _placeholder_stream(),
            mimetype="multipart/x-mixed-replace; boundary=frame"
        )

    def generate():
        while True:
            with _frame_lock:
                frame_bytes = _latest_frame

            if frame_bytes:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + frame_bytes + b"\r\n"
                )
            else:
                time.sleep(0.05)

    return Response(
        stream_with_context(generate()),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@camera_bp.route("/stop/<int:session_id>", methods=["POST"])
@login_required
def stop_camera(session_id):
    _stop_camera()
    return jsonify({"stopped": True})


@camera_bp.route("/snapshot", methods=["POST"])
@login_required
def process_snapshot():
    if not CV2_AVAILABLE or not FACE_AVAILABLE:
        return jsonify({"error": "non disponible", "detections": []}), 503

    data       = request.json or {}
    image_b64  = data.get("image", "")
    session_id = data.get("session_id")

    if not image_b64 or not session_id:
        return jsonify({"error": "Données manquantes"}), 400

    try:
        img_bytes = base64.b64decode(image_b64.split(",")[-1])
        np_arr    = np.frombuffer(img_bytes, np.uint8)
        frame     = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    detections = AttendanceService.process_camera_frame(
        frame, session_id, _known_encodings
    )
    return jsonify({"detections": [
        {"student_id": d["student_id"], "confidence": d["confidence"]}
        for d in detections
     ]})
def status():
    cam_ok = _camera_thread is not None and _camera_thread.is_alive()
    return jsonify({
        "opencv":           CV2_AVAILABLE,
        "face_recognition": FACE_AVAILABLE,
        "camera_active":    cam_ok,
        "encodings_loaded": len(_known_encodings),
        "active_session":   _active_session_id,
    })


# ── Placeholder ──────────────────────────────────────────────

def _placeholder_stream():
    try:
        from PIL import Image, ImageDraw
        img  = Image.new("RGB", (640, 360), color=(13, 27, 42))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 620, 340], outline=(0, 100, 80), width=2)
        draw.text((220, 165), "Caméra non disponible", fill=(0, 245, 160))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        frame_bytes = buf.getvalue()
    except Exception:
        frame_bytes = b""

    while True:
        yield (
            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
            + frame_bytes + b"\r\n"
        )
        time.sleep(2)