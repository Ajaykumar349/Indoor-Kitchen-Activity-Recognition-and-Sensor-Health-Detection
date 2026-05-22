#!/bin/bash
# Automatic fix for Python 3.12 distutils error
# This script rebuilds your virtual environment with compatible versions

set -e

echo "╔════════════════════════════════════════════════════╗"
echo "║  Python 3.12 distutils Fix                        ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check Python version
echo "📋 Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "   Found: Python $python_version"
echo ""

# Deactivate if active
echo "🔧 Deactivating current environment..."
if [ -n "$VIRTUAL_ENV" ]; then
    deactivate 2>/dev/null || true
fi

# Remove old venv
if [ -d "venv" ]; then
    echo "🗑️  Removing old virtual environment..."
    rm -rf venv
    echo "   ✓ Removed"
else
    echo "   (No existing venv found)"
fi

echo ""
echo "📦 Creating fresh virtual environment..."
python3 -m venv venv
echo "   ✓ Created"

echo ""
echo "🔗 Activating virtual environment..."
source venv/bin/activate
echo "   ✓ Activated"

echo ""
echo "🔄 Upgrading pip, setuptools, and wheel..."
pip install --quiet --upgrade pip setuptools wheel
echo "   ✓ Upgraded"

echo ""
echo "📚 Installing Python 3.12 compatible packages..."
echo "   (This may take a minute...)"

# Install with specific versions
pip install --quiet \
    flask==3.0.0 \
    flask-sock==0.7.0 \
    requests==2.31.0 \
    pandas==2.1.0 \
    numpy==1.24.3 \
    plotly==5.17.0 \
    streamlit==1.31.1 \
    gevent==23.9.1 \
    gevent-websocket==0.10.1 \
    gunicorn==21.2.0 \
    python-dotenv==1.0.0 \
    Pillow==10.0.0 \
    pytest==7.4.0 \
    pytest-asyncio==0.21.0

if [ $? -eq 0 ]; then
    echo "   ✓ All packages installed"
else
    echo -e "   ${RED}✗ Installation failed${NC}"
    exit 1
fi

echo ""
echo "✅ Verifying installation..."

# Test imports
echo ""
echo "Testing imports:"

python -c "import streamlit; print('   ✓ Streamlit ' + streamlit.__version__)" 2>/dev/null || {
    echo -e "   ${RED}✗ Streamlit import failed${NC}"
    exit 1
}

python -c "import flask; print('   ✓ Flask ' + flask.__version__)" 2>/dev/null || {
    echo -e "   ${RED}✗ Flask import failed${NC}"
    exit 1
}

python -c "import pandas; print('   ✓ Pandas ' + pandas.__version__)" 2>/dev/null || {
    echo -e "   ${RED}✗ Pandas import failed${NC}"
    exit 1
}

python -c "import plotly; print('   ✓ Plotly ' + plotly.__version__)" 2>/dev/null || {
    echo -e "   ${RED}✗ Plotly import failed${NC}"
    exit 1
}

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║          ✅ Fix Complete!                          ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✓ Virtual environment ready${NC}"
echo -e "${GREEN}✓ All packages compatible with Python 3.12${NC}"
echo ""

echo "Next steps:"
echo ""
echo "1️⃣  Terminal 1 - Start Flask backend:"
echo "   python flask_backend_enhanced.py"
echo ""
echo "2️⃣  Terminal 2 - Start Streamlit dashboard:"
echo "   streamlit run streamlit_dashboard_flask.py"
echo ""
echo "3️⃣  Open: http://localhost:8501"
echo ""
echo "Troubleshooting:"
echo "   • If needed, deactivate with: deactivate"
echo "   • Reactivate with: source venv/bin/activate"
echo ""
