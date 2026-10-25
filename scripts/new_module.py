#!/usr/bin/env python
"""Scaffold a new level-two University module from templates/module/.

Usage::

    python scripts/new_module.py social --description "Posts, comments, reactions and follows."

Creates packages/university-<name>/ (underscores become hyphens) with a working app (model, service,
selector, API, admin, event handler, permissions, tests) that follows every
platform convention. Then:

    pip install -e packages/university-<name>
    cd packages/university-<name>
    DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=. python -m django makemigrations university_<name>
    pytest
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "module"
PACKAGES = ROOT / "packages"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
RESERVED = {"core", "users", "security", "permissions", "audit", "common", "api", "settings"}


def render(text: str, name: str, description: str) -> str:
    camel = "".join(part.title() for part in name.split("_"))
    return (
        text.replace("__module_dist__", name.replace("_", "-"))
        .replace("__module__", name)
        .replace("__Module__", camel)
        .replace("__MODULE__", name.upper())
        .replace("__description__", description)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="Module name, e.g. social, anonymous, events")
    parser.add_argument("--description", default="An optional University platform module.")
    args = parser.parse_args()

    name = args.name.strip().lower()
    if not NAME_RE.match(name) or name in RESERVED:
        print(f"Invalid or reserved module name: {name!r}", file=sys.stderr)
        return 1
    target = PACKAGES / f"university-{name.replace('_', '-')}"
    if target.exists():
        print(f"{target} already exists.", file=sys.stderr)
        return 1

    for source in TEMPLATE.rglob("*"):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        relative = Path(render(str(source.relative_to(TEMPLATE)), name, args.description))
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render(source.read_text(encoding="utf-8"), name, args.description), encoding="utf-8")
    license_file = PACKAGES / "university-core" / "LICENSE"
    if license_file.exists():
        shutil.copy(license_file, target / "LICENSE")
    # Import order depends on the module name; let ruff tidy it if available.
    for command in (["ruff", "check", "--fix", "--quiet", str(target)], ["ruff", "format", "--quiet", str(target)]):
        try:
            subprocess.run(command, check=False, cwd=ROOT)
        except FileNotFoundError:
            break
    print(f"Created {target.relative_to(ROOT)}")
    print("Next: pip install -e, makemigrations, pytest (see this script's docstring).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
