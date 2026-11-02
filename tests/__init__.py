"""Test package.

Puts ``src`` on the import path so the suite runs from the repository root
with ``python -m unittest discover -s tests -t .`` and no installation step.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
