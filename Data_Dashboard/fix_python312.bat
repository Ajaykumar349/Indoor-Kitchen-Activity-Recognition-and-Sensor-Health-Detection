@echo off
REM Automatic fix for Python 3.12 distutils error
REM This script rebuilds your virtual environment with compatible versions

setlocal enabledelayedexpansion

echo.
echo ╔════════════════════════════════════════════════════╗
echo ║  Python 3.12 distutils Fix                        ║
echo ╚════════════════════════════════════════════════════╝
echo.

REM Check Python version
echo 📋 Checking Python version...
python --version
echo.

REM Deactivate if active
echo 🔧 Deactivating current environment...
call deactivate 2>nul
echo Done
echo.

REM Remove old venv
if exist venv (
    echo 🗑️  Removing old virtual environment...
    rmdir /s /q venv
    echo    ✓ Removed
) else (
    echo    (No existing venv found)
)

echo.
echo 📦 Creating fresh virtual environment...
python -m venv venv
echo    ✓ Created
echo.

echo 🔗 Activating virtual environment...
call venv\Scripts\activate.bat
echo    ✓ Activated
echo.

echo 🔄 Upgrading pip, setuptools, and wheel...
python -m pip install --quiet --upgrade pip setuptools wheel
echo    ✓ Upgraded
echo.

echo 📚 Installing Python 3.12 compatible packages...
echo    (This may take a minute...)
echo.

REM Install packages with specific versions
python -m pip install --quiet ^
    flask==3.0.0 ^
    flask-sock==0.7.0 ^
    requests==2.31.0 ^
    pandas==2.1.0 ^
    numpy==1.24.3 ^
    plotly==5.17.0 ^
    streamlit==1.31.1 ^
    gevent==23.9.1 ^
    gevent-websocket==0.10.1 ^
    gunicorn==21.2.0 ^
    python-dotenv==1.0.0 ^
    Pillow==10.0.0 ^
    pytest==7.4.0 ^
    pytest-asyncio==0.21.0

if errorlevel 1 (
    echo ✗ Installation failed
    pause
    exit /b 1
)

echo    ✓ All packages installed
echo.

echo ✅ Verifying installation...
echo.
echo Testing imports:
echo.

python -c "import streamlit; print('   ✓ Streamlit ' + streamlit.__version__)" 2>nul || (
    echo    ✗ Streamlit import failed
    pause
    exit /b 1
)

python -c "import flask; print('   ✓ Flask ' + flask.__version__)" 2>nul || (
    echo    ✗ Flask import failed
    pause
    exit /b 1
)

python -c "import pandas; print('   ✓ Pandas ' + pandas.__version__)" 2>nul || (
    echo    ✗ Pandas import failed
    pause
    exit /b 1
)

python -c "import plotly; print('   ✓ Plotly ' + plotly.__version__)" 2>nul || (
    echo    ✗ Plotly import failed
    pause
    exit /b 1
)

echo.
echo ╔════════════════════════════════════════════════════╗
echo ║          ✅ Fix Complete!                          ║
echo ╚════════════════════════════════════════════════════╝
echo.

echo ✓ Virtual environment ready
echo ✓ All packages compatible with Python 3.12
echo.

echo Next steps:
echo.
echo 1️⃣  Command Prompt 1 - Start Flask backend:
echo    python flask_backend_enhanced.py
echo.
echo 2️⃣  Command Prompt 2 - Start Streamlit dashboard:
echo    streamlit run streamlit_dashboard_flask.py
echo.
echo 3️⃣  Open browser: http://localhost:8501
echo.
echo Troubleshooting:
echo    • If needed, deactivate with: deactivate
echo    • Reactivate with: venv\Scripts\activate
echo.

pause
