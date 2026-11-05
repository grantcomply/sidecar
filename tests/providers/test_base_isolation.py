"""``source.providers.base`` must stay a standalone leaf module (ADR-015 D1).

Checked in a fresh interpreter so modules already imported by other tests
don't hide a regression.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SCRIPT = """
import sys
import source.providers.base  # noqa: F401
forbidden = [
    m for m in sys.modules
    if m == "mutagen" or m.startswith("mutagen.")
    or m.startswith("source.providers.serato")
    or m in ("source.providers.registry", "source.services.crate_parser")
]
print(",".join(sorted(forbidden)))
"""


def test_importing_base_loads_no_provider_parser_or_mutagen():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
