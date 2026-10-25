#!/usr/bin/env python
"""Run every package's test suite in isolation (each has its own settings).

Usage::

    python scripts/test_all.py              # all packages
    python scripts/test_all.py institution  # packages whose name contains "institution"
    python scripts/test_all.py -- -x -q     # extra args forwarded to pytest
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    filters, pytest_args = argv, []
    if "--" in argv:
        index = argv.index("--")
        filters, pytest_args = argv[:index], argv[index + 1 :]
    packages = sorted(p for p in (ROOT / "packages").iterdir() if (p / "tests").is_dir())
    # Cross-module suite: every package installed together.
    if (ROOT / "integration_tests" / "tests").is_dir():
        packages.append(ROOT / "integration_tests")
    if filters:
        packages = [p for p in packages if any(f in p.name for f in filters)]
    failures: list[str] = []
    for package in packages:
        print(f"\n=== {package.name} ===", flush=True)
        result = subprocess.run([sys.executable, "-m", "pytest", *pytest_args], cwd=package, check=False)
        if result.returncode != 0:
            failures.append(package.name)
    print("\n" + ("All packages passed." if not failures else f"FAILED: {', '.join(failures)}"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
