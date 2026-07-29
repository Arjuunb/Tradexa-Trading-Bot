"""What actually ships in the deployed container.

This file exists because of a bug it would have caught. ``pyproject.toml``
listed only ``bot*`` under ``packages.find``, so ``pip install -e .`` — the one
install the Dockerfile runs — never made ``tradexa`` importable. The backend
starts from ``automation-hub/``, where the repo root is not on ``sys.path``, so
every ``import tradexa...`` in production failed:

    the risk-engine veto           → self.risk_engine = None, no veto applied
    the shared sizing arithmetic   → fell back to its inline copy
    the portfolio endpoints        → 500

None of it surfaced. The guarded imports are written to degrade quietly, which
is right for resilience and exactly wrong for noticing. And the whole test suite
passed, because ``conftest.py`` appends the repo root to ``sys.path`` — so every
one of those imports resolved under pytest and only under pytest.

The lesson generalises past this one bug: a test suite that manipulates the
import path is testing a different program from the one that deploys. These
tests read the packaging configuration instead, which is what the container
obeys.
"""
from __future__ import annotations

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Top-level packages the backend imports at runtime and therefore must be
#: installed, not merely present in the repository.
REQUIRED_PACKAGES = ("bot", "tradexa")


def _config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def _include_patterns() -> list[str]:
    find = (_config().get("tool", {}).get("setuptools", {})
            .get("packages", {}).get("find", {}))
    return list(find.get("include") or [])


def test_every_runtime_package_is_installed_by_the_build():
    """The regression itself."""
    patterns = _include_patterns()
    for package in REQUIRED_PACKAGES:
        assert any(p in (package, f"{package}*") for p in patterns), (
            f"'{package}' is imported by the backend but is not in "
            f"pyproject.toml packages.find include={patterns} — it will be "
            "missing from the deployed container while every test still passes")


def test_the_required_packages_exist_as_real_packages():
    """Guards the guard: an entry for a package that does not exist would make
    the test above pass while shipping nothing."""
    for package in REQUIRED_PACKAGES:
        assert (ROOT / package / "__init__.py").is_file(), (
            f"{package}/__init__.py is missing — the include pattern would "
            "match nothing")


def test_the_backend_imports_only_installed_top_level_packages():
    """Every repo-root package the backend imports must be in the install list.

    This is the general form of the bug: adding a new top-level package and
    importing it from automation-hub works locally, works under pytest, and
    fails in the container. Discovering it means reading the include list, which
    nobody does — so the test does.
    """
    import ast

    backend = ROOT / "automation-hub"
    # Directories at the repo root that are importable packages.
    root_packages = {p.name for p in ROOT.iterdir()
                     if p.is_dir() and (p / "__init__.py").is_file()}
    installed = {p.rstrip("*") for p in _include_patterns()}

    used: dict[str, str] = {}
    for path in backend.rglob("*.py"):
        if "/tests/" in str(path) or path.name == "conftest.py":
            continue          # tests legitimately extend sys.path
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:   # pragma: no cover - not this test's business
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for name in names:
                head = name.split(".")[0]
                if head in root_packages:
                    used.setdefault(head, str(path.relative_to(ROOT)))

    missing = {pkg: where for pkg, where in used.items() if pkg not in installed}
    assert not missing, (
        "the backend imports repo-root package(s) that the build does not "
        f"install: {missing} — add them to pyproject.toml packages.find include")


def test_conftest_extends_sys_path_and_that_is_why_this_file_exists():
    """States the trap in the place someone would look after this file fails.

    ``automation-hub/conftest.py`` appending the repo root is correct — the suite
    has to import both trees. It also means an import that only works because of
    that line looks healthy in CI. That gap is what these tests cover, and
    deleting them because "the imports obviously work" is how the bug comes back.
    """
    conftest = ROOT / "automation-hub" / "conftest.py"
    assert conftest.is_file(), "the backend conftest moved — re-check this trap"
    assert "sys.path" in conftest.read_text()
