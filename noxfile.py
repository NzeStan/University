"""Automation for the University monorepo (https://nox.thea.codes).

nox -s lint                       # ruff lint + format check
nox -s typecheck                  # mypy
nox -s tests                      # full Python x Django matrix, every package
nox -s "tests-3.13(django='6.1')" # one cell of the matrix
nox -s security                   # bandit + pip-audit
nox -s build                      # build sdists/wheels and validate metadata
"""

from __future__ import annotations

from pathlib import Path

import nox

ROOT = Path(__file__).parent
PACKAGES = sorted(p for p in (ROOT / "packages").iterdir() if (p / "pyproject.toml").exists())
nox.options.sessions = ["lint", "tests"]
nox.options.reuse_existing_virtualenvs = True

# Supported combinations (Django 6.x requires Python >= 3.12).
MATRIX = [
    ("3.11", "5.2"),
    ("3.12", "5.2"),
    ("3.12", "6.0"),
    ("3.13", "6.0"),
    ("3.13", "6.1"),
    ("3.14", "6.1"),
]


def install_packages(session: nox.Session) -> None:
    # One call, so sibling packages resolve locally rather than from PyPI.
    session.install(*(arg for package in PACKAGES for arg in ("-e", f"{package}[test]")))


@nox.session(python="3.13")
def lint(session: nox.Session) -> None:
    session.install("ruff>=0.6")
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session(python="3.13")
def typecheck(session: nox.Session) -> None:
    session.install("mypy>=1.10", "django-stubs>=5", "djangorestframework-stubs>=3.15")
    install_packages(session)
    session.run("mypy", *[str(p / "src") for p in PACKAGES])


@nox.session
@nox.parametrize(("python", "django"), MATRIX)
def tests(session: nox.Session, django: str) -> None:
    install_packages(session)
    session.install(f"Django~={django}.0")
    for package in PACKAGES:
        if (package / "tests").is_dir():
            with session.chdir(package):
                session.run("pytest", "--cov", "--cov-report=term-missing:skip-covered", *session.posargs)


@nox.session(python="3.13")
def security(session: nox.Session) -> None:
    session.install("bandit[toml]>=1.7", "pip-audit>=2.7")
    install_packages(session)
    session.run("bandit", "-c", "pyproject.toml", "-r", *[str(p / "src") for p in PACKAGES])
    session.run("pip-audit", "--skip-editable")


@nox.session(python="3.13")
def build(session: nox.Session) -> None:
    session.install("build>=1.2", "twine>=5")
    for package in PACKAGES:
        session.run("python", "-m", "build", "--outdir", str(ROOT / "dist"), str(package))
    session.run("twine", "check", "--strict", *[str(p) for p in (ROOT / "dist").glob("*")])
