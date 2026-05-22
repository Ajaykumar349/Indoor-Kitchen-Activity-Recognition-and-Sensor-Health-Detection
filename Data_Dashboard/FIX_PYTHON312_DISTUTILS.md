# Fix: Python 3.12 distutils ModuleNotFoundError

## Problem
```
ModuleNotFoundError: No module named 'distutils'
```

Python 3.12 removed the deprecated `distutils` module. Streamlit and some other packages need it.

---

## ✅ Solution 1: Quick Fix (Recommended)

### Step 1: Clean virtual environment
```bash
# Deactivate current environment
deactivate

# Delete old venv
rm -rf venv  # Linux/Mac
rmdir /s venv  # Windows (or delete manually)
```

### Step 2: Reinstall with Python 3.12 compatible versions
```bash
# Create fresh venv
python3 -m venv venv

# Activate
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Install updated requirements
pip install --upgrade pip setuptools wheel
pip install -r requirements_python312.txt
```

**That's it!** The updated `requirements_python312.txt` includes:
- ✅ Streamlit 1.31.1+ (fixes distutils issue)
- ✅ setuptools (restores distutils compatibility)
- ✅ All compatible versions for Python 3.12

---

## ✅ Solution 2: Manual Fix (If you want to keep current venv)

```bash
# Install setuptools to restore distutils
pip install --upgrade setuptools

# Upgrade Streamlit
pip install --upgrade streamlit

# Reinstall other packages
pip install flask==3.0.0 flask-sock==0.7.0 pandas==2.1.0 plotly==5.17.0
```

---

## ✅ Solution 3: Install specific Streamlit version

```bash
pip install streamlit==1.31.1
```

This version fixed the distutils compatibility issue.

---

## Why This Happens

| Python Version | Status |
|---|---|
| Python 3.10 | ✅ Works fine |
| Python 3.11 | ✅ Works fine |
| Python 3.12 | ⚠️ distutils removed |

**The fix:** Streamlit 1.31.1+ removed its dependency on distutils. Upgrading solves it.

---

## Verify Fix

After fixing, test with:

```bash
# Test 1: Python should find distutils
python -c "from setuptools import setup; print('✓ setuptools OK')"

# Test 2: Streamlit should start without errors
streamlit run --version

# Test 3: Import Streamlit
python -c "import streamlit; print(f'✓ Streamlit {streamlit.__version__} OK')"

# Test 4: Run dashboard
streamlit run streamlit_dashboard_flask.py
```

---

## If Still Having Issues

### Check your Python version
```bash
python --version
# Should show: Python 3.12.x
```

### Completely clean install
```bash
# 1. Deactivate
deactivate

# 2. Delete venv
rm -rf venv

# 3. Delete pip cache
pip cache purge

# 4. Create new venv
python3 -m venv venv

# 5. Activate
source venv/bin/activate

# 6. Install fresh
pip install --upgrade pip setuptools wheel
pip install -r requirements_python312.txt

# 7. Verify
python -c "import streamlit; print('OK')"
```

### Alternative: Use Python 3.11
If you have Python 3.11 available:
```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Files to Use

### For Python 3.12:
- Use: **requirements_python312.txt** (updated)
- Run: `pip install -r requirements_python312.txt`

### For Python 3.11 or earlier:
- Use: **requirements.txt** (original)
- Run: `pip install -r requirements.txt`

---

## Summary

| Method | Time | Recommendation |
|---|---|---|
| Solution 1 (Clean install) | 5 min | ✅ Best |
| Solution 2 (Upgrade packages) | 2 min | ✅ Good |
| Solution 3 (Update Streamlit only) | 1 min | ⚠️ Minimal |

---

## Next Steps

After fixing, your setup will work:

```bash
# Terminal 1: Flask backend
python flask_backend_enhanced.py

# Terminal 2: Streamlit dashboard
streamlit run streamlit_dashboard_flask.py

# Terminal 3 (optional): Test data
python test_flask_data.py --stream
```

---

## Questions?

- Stuck? Try Solution 1 (clean install) - it always works
- Still issues? Check Python version with `python --version`
- Need older Python? Install Python 3.11 alongside 3.12

Good luck! 🚀
