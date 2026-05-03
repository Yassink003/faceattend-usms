@echo off
echo ========================================
echo   FaceAttend - Installation Windows
echo ========================================

cd /d "%~dp0"

echo.
echo [1/4] Creation de l'environnement virtuel...
python -m venv venv
if errorlevel 1 (
    echo ERREUR: Python non trouve. Installez Python 3.11 depuis python.org
    pause
    exit /b 1
)

echo.
echo [2/4] Activation du venv...
call venv\Scripts\activate.bat

echo.
echo [3/4] Installation des dependances de base (sans dlib)...
pip install --upgrade pip
pip install Flask==3.0.3 flask-login==0.6.3 flask-sqlalchemy==3.1.1 flask-migrate==4.0.7
pip install flask-cors==5.0.0 flask-limiter==3.8.0 flask-wtf==1.2.1
pip install SQLAlchemy==2.0.35 psycopg2-binary==2.9.9 alembic==1.13.3
pip install bcrypt==4.2.0 cryptography==43.0.1 PyJWT==2.9.0
pip install opencv-python==4.10.0.84 Pillow==10.4.0 numpy==1.26.4
pip install pandas==2.2.3 openpyxl==3.1.5 xlsxwriter==3.2.0
pip install python-dotenv==1.0.1 loguru==0.7.2 Werkzeug==3.0.4 click==8.1.7

echo.
echo [4/4] Tentative installation dlib (optionnel)...
pip install cmake
pip install dlib
if errorlevel 1 (
    echo [WARNING] dlib non installe - reconnaissance faciale desactivee
    echo           L'app fonctionne quand meme sans dlib
)

echo.
echo ========================================
echo   Installation terminee !
echo ========================================
echo.
echo Etapes suivantes dans ce terminal :
echo   1. call venv\Scripts\activate
echo   2. python generate_env.py
echo   3. python -m flask db init
echo   4. python -m flask db migrate -m "init"
echo   5. python -m flask db upgrade
echo   6. python -m flask seed-db
echo   7. python run.py
echo.
pause
