# core/modules/lod_auditor/tests/conftest.py
#
# Makes lod_auditor importable when pytest runs from any working directory.

import sys
from pathlib import Path

# core/modules/ must be on sys.path so "from lod_auditor.X import Y" resolves.
_MODULES_DIR = Path(__file__).resolve().parent.parent.parent
if str(_MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULES_DIR))
