"""
FaceAttend — Application Factory
Système de reconnaissance faciale pour la gestion des présences universitaires
Conforme CNDP (Commission Nationale de protection des Données Personnelles - Maroc)
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from loguru import logger
import os
from flask_caching import Cache


# ─── Extensions ──────────────────────────────────────────────
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()


def create_app(config_name: str = None) -> Flask:
    """Application factory — crée et configure l'instance Flask."""

    app = Flask(
        __name__,
        template_folder="../frontend/templates",
        static_folder="../frontend/static",
    )

    # ─── Config ──────────────────────────────────────────────
    env = config_name or os.getenv("FLASK_ENV", "development")
    from config.settings import config_map
    app.config.from_object(config_map[env])

    # ─── Extensions init ─────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    limiter.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})

    # ─── Login Manager ───────────────────────────────────────
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Veuillez vous connecter."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # ─── Blueprints ──────────────────────────────────────────
    _register_blueprints(app)

    # ─── Shell context ───────────────────────────────────────
    @app.shell_context_processor
    def make_shell_context():
        from app.models import User, Student, Teacher, Course, Session, Attendance
        return dict(db=db, User=User, Student=Student,
                    Teacher=Teacher, Course=Course,
                    Session=Session, Attendance=Attendance)

    logger.info(f"FaceAttend démarré en mode [{env}]")
    return app


def _register_blueprints(app: Flask):
    from app.api.auth      import auth_bp
    from app.api.admin     import admin_bp
    from app.api.teacher   import teacher_bp
    from app.api.student   import student_bp
    from app.api.camera    import camera_bp
    from app.api.attendance import attendance_bp

    app.register_blueprint(auth_bp,       url_prefix="/")
    app.register_blueprint(admin_bp,      url_prefix="/admin")
    app.register_blueprint(teacher_bp,    url_prefix="/teacher")
    app.register_blueprint(student_bp,    url_prefix="/student")
    app.register_blueprint(camera_bp,     url_prefix="/api/camera")
    app.register_blueprint(attendance_bp, url_prefix="/api/attendance")
