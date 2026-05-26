"""Local Vogi entrypoint.

Run from this folder with:
python -m uvicorn main:app --host 127.0.0.1 --port 5000 --reload
"""

try:
    from .backend.app import app
except ImportError:
    from backend.app import app
