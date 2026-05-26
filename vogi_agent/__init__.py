"""Compatibility shim for running Vogi from the nested app folder.

This lets commands like
python -m uvicorn vogi_agent.Vogi.backend.app:app
work even when the current directory is vogi_agent/Vogi.
"""

from __future__ import annotations

from pathlib import Path

_real_package_root = Path(__file__).resolve().parents[2]
__path__ = [str(_real_package_root)]
