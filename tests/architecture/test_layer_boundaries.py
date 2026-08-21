"""Dependency direction, enforced rather than trusted.

ARCHITECTURE.md defines the layering. A convention that is only written down erodes;
this test reads the actual import statements, so a violation fails the build.

Imports are found by parsing the source rather than by importing modules, so the
check does not depend on import side effects and covers code no test exercises.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "learning_platform"

# Frameworks and drivers that must not reach the inner layers.
FRAMEWORK_PACKAGES = frozenset(
    {
        "flask",
        "werkzeug",
        "jinja2",
        "sqlalchemy",
        "alembic",
        "psycopg",
        "pydantic",
        "pydantic_settings",
        "structlog",
    }
)

# Which internal layers each layer may import from.
ALLOWED_INTERNAL_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "application": frozenset({"domain", "application"}),
    "infrastructure": frozenset({"domain", "application", "infrastructure"}),
    "integrations": frozenset({"domain", "application", "integrations"}),
    "worker": frozenset({"domain", "application", "worker"}),
    # web is the composition root: it wires adapters into use cases.
    "web": frozenset({"domain", "application", "infrastructure", "integrations", "worker", "web"}),
}

# Layers that must stay free of any framework import.
FRAMEWORK_FREE_LAYERS = frozenset({"domain", "application"})


def _python_files(layer: str) -> list[Path]:
    layer_root = SOURCE_ROOT / layer
    if not layer_root.exists():
        return []
    return sorted(layer_root.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Return every module name imported by a file, including inside functions.

    Read as utf-8-sig, because a file created by a Windows editor or by PowerShell
    may carry a byte-order mark. Reading it as plain utf-8 would raise a SyntaxError
    that looks like a boundary violation while actually checking nothing.
    """
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        # level > 0 is a relative import, which ruff bans project-wide.
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _layer_of(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "learning_platform":
        return parts[1]
    return None


ALL_LAYERS = sorted(ALLOWED_INTERNAL_IMPORTS)


class TestPackageNaming:
    def test_the_package_does_not_shadow_a_standard_library_module(self) -> None:
        """A package named 'platform' is picked up instead of the stdlib module
        whenever src reaches the front of sys.path, which breaks dependencies that
        import platform, including Alembic and SQLAlchemy."""
        assert SOURCE_ROOT.name == "learning_platform"
        assert not (SOURCE_ROOT.parent / "platform").exists()

    def test_the_source_root_exists_and_has_content(self) -> None:
        assert list(SOURCE_ROOT.rglob("*.py"))


class TestFrameworkIndependence:
    @pytest.mark.parametrize("layer", sorted(FRAMEWORK_FREE_LAYERS))
    def test_inner_layers_import_no_framework(self, layer: str) -> None:
        files = _python_files(layer)
        # Guard against a vacuous pass: a missing or empty layer would otherwise
        # satisfy this test without checking anything.
        assert files, f"the {layer} layer has no source files to check"

        violations: list[str] = []
        for path in files:
            for module in _imported_modules(path):
                root = module.split(".")[0]
                if root in FRAMEWORK_PACKAGES:
                    violations.append(f"{path.relative_to(SOURCE_ROOT.parent)} imports {module}")
        assert not violations, f"the {layer} layer must stay framework-neutral: " + "; ".join(
            violations
        )


class TestInternalDependencyDirection:
    @pytest.mark.parametrize("layer", ALL_LAYERS)
    def test_a_layer_imports_only_what_it_may(self, layer: str) -> None:
        allowed = ALLOWED_INTERNAL_IMPORTS[layer]
        violations: list[str] = []
        for path in _python_files(layer):
            for module in _imported_modules(path):
                imported_layer = _layer_of(module)
                if imported_layer is not None and imported_layer not in allowed:
                    violations.append(f"{path.relative_to(SOURCE_ROOT.parent)} imports {module}")
        assert not violations, f"the {layer} layer may import only {sorted(allowed)}: " + "; ".join(
            violations
        )


class TestFlaskGlobals:
    """Only the web layer may read request-scoped Flask state.

    Anything below it must receive what it needs as an argument, or the same code
    could not run inside a background handler or a test.
    """

    FLASK_GLOBALS = frozenset({"request", "session", "g", "current_app"})

    @pytest.mark.parametrize("layer", [name for name in ALL_LAYERS if name not in {"web"}])
    def test_no_layer_below_web_touches_request_globals(self, layer: str) -> None:
        violations: list[str] = []
        for path in _python_files(layer):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "flask":
                    imported = {alias.name for alias in node.names}
                    leaked = imported & self.FLASK_GLOBALS
                    if leaked:
                        violations.append(
                            f"{path.relative_to(SOURCE_ROOT.parent)} imports "
                            f"{sorted(leaked)} from flask"
                        )
        assert not violations, "; ".join(violations)


class TestInstitutionNeutrality:
    """No deployment-specific identifier may appear in application code.

    CLAUDE.md forbids hard-coding CTS, its branches, or a semester count into domain
    logic. Those are configuration, and the platform must stay institution-neutral so
    a future BTech deployment is a configuration change rather than a rewrite.
    """

    FORBIDDEN_TOKENS = ("cts", "dcst", "dme", "dee", "dce")

    def test_no_deployment_identifiers_appear_in_source(self) -> None:
        violations: list[str] = []
        for path in SOURCE_ROOT.rglob("*.py"):
            for number, line in enumerate(
                path.read_text(encoding="utf-8-sig").splitlines(), start=1
            ):
                # Compare against identifier-like words only, so ordinary prose
                # containing these letters inside a longer word is not flagged.
                words = {word.lower() for word in line.replace(".", " ").replace("_", " ").split()}
                found = words & set(self.FORBIDDEN_TOKENS)
                if found:
                    violations.append(
                        f"{path.relative_to(SOURCE_ROOT.parent)}:{number} mentions {sorted(found)}"
                    )
        assert not violations, (
            "deployment-specific identifiers belong in configuration: " + "; ".join(violations)
        )
