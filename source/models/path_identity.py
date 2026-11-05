"""File-path identity shared by the model and the library merge (ADR-015 D6).

Leaf module: stdlib only, so ``models`` never has to import ``services``.
"""

from __future__ import annotations

import os
import unicodedata


def path_key(p: str) -> str:
    """Identity key for a file path: NFC + OS case rules + normalised separators."""
    return unicodedata.normalize("NFC", os.path.normcase(os.path.normpath(p)))
