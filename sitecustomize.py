"""Make Vogi runnable from this nested app folder.

When Python starts from vogi_agent/Vogi, the repository root is not on
sys.path, so imports like vogi_agent.Vogi.backend.app cannot resolve.
Python automatically imports sitecustomize when it is present on sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
repo_root_text = str(repo_root)

if repo_root_text not in sys.path:
    sys.path.insert(0, repo_root_text)

