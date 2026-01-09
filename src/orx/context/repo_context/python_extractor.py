"""Python tooling extractor.

Extracts configuration from Python projects including:
- pyproject.toml (ruff, mypy, pytest, black, isort)
- ruff.toml
- pytest.ini / setup.cfg
- mypy.ini
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from orx.context.repo_context.blocks import ContextBlock, ContextPriority

logger = structlog.get_logger()


def _parse_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, returning empty dict on failure."""
    if not path.exists():
        return {}
    try:
        import tomllib

        return tomllib.loads(path.read_text())
    except Exception as e:
        logger.debug("Failed to parse TOML", path=str(path), error=str(e))
        return {}


def _parse_ini(path: Path) -> dict[str, Any]:
    """Parse an INI file, returning empty dict on failure."""
    if not path.exists():
        return {}
    try:
        import configparser

        parser = configparser.ConfigParser()
        parser.read(path)
        return {s: dict(parser.items(s)) for s in parser.sections()}
    except Exception as e:
        logger.debug("Failed to parse INI", path=str(path), error=str(e))
        return {}


class PythonExtractor:
    """Extracts Python project tooling configuration."""

    def __init__(self, worktree: Path) -> None:
        """Initialize the extractor.

        Args:
            worktree: Path to the repository worktree.
        """
        self.worktree = worktree
        self._pyproject: dict[str, Any] | None = None
        self._ruff_toml: dict[str, Any] | None = None

    @property
    def pyproject(self) -> dict[str, Any]:
        """Lazy-load pyproject.toml."""
        if self._pyproject is None:
            self._pyproject = _parse_toml(self.worktree / "pyproject.toml")
        return self._pyproject

    @property
    def ruff_toml(self) -> dict[str, Any]:
        """Lazy-load ruff.toml."""
        if self._ruff_toml is None:
            self._ruff_toml = _parse_toml(self.worktree / "ruff.toml")
        return self._ruff_toml

    def is_python_project(self) -> bool:
        """Check if this is a Python project."""
        indicators = [
            self.worktree / "pyproject.toml",
            self.worktree / "setup.py",
            self.worktree / "setup.cfg",
            self.worktree / "requirements.txt",
            self.worktree / "Pipfile",
        ]
        return any(p.exists() for p in indicators)

    def extract_all(self) -> list[ContextBlock]:
        """Extract all Python tooling context blocks.

        Returns:
            List of context blocks for Python configuration.
        """
        if not self.is_python_project():
            return []

        blocks: list[ContextBlock] = []

        # Profile/stack info
        profile = self._extract_profile()
        if profile:
            blocks.append(profile)

        # Dependencies (important for understanding available libraries)
        deps = self._extract_dependencies()
        if deps:
            blocks.append(deps)

        # Ruff configuration
        ruff = self._extract_ruff()
        if ruff:
            blocks.append(ruff)

        # Mypy configuration
        mypy = self._extract_mypy()
        if mypy:
            blocks.append(mypy)

        # Pytest configuration
        pytest = self._extract_pytest()
        if pytest:
            blocks.append(pytest)

        return blocks

    def extract_profile_only(self) -> ContextBlock | None:
        """Extract only the stack/profile block (for plan/spec stages).

        Returns:
            Profile context block or None.
        """
        if not self.is_python_project():
            return None
        return self._extract_profile()

    def _extract_profile(self) -> ContextBlock | None:
        """Extract project profile (stack overview)."""
        facts: list[str] = []
        sources: list[str] = []

        # Check pyproject.toml for project info
        project = self.pyproject.get("project", {})
        requires_python = project.get("requires-python")
        if requires_python:
            facts.append(f"- Python: {requires_python}")

        # Package manager detection
        if (self.worktree / "poetry.lock").exists():
            facts.append("- Package manager: Poetry")
            sources.append("poetry.lock")
        elif (self.worktree / "uv.lock").exists():
            facts.append("- Package manager: uv")
            sources.append("uv.lock")
        elif (self.worktree / "Pipfile.lock").exists():
            facts.append("- Package manager: Pipenv")
            sources.append("Pipfile.lock")
        elif (self.worktree / "requirements.txt").exists():
            facts.append("- Package manager: pip")
            sources.append("requirements.txt")

        # Build system
        build_backend = self.pyproject.get("build-system", {}).get("build-backend", "")
        if "hatchling" in build_backend:
            facts.append("- Build: hatchling")
        elif "setuptools" in build_backend:
            facts.append("- Build: setuptools")
        elif "poetry" in build_backend:
            facts.append("- Build: poetry-core")
        elif "flit" in build_backend:
            facts.append("- Build: flit")

        # Layout detection
        if (self.worktree / "src").is_dir():
            facts.append("- Layout: src/")
            sources.append("src/")
        elif any((self.worktree).glob("*/py.typed")):
            facts.append("- Layout: flat (namespace package detected)")

        if self.pyproject:
            sources.insert(0, "pyproject.toml")

        if not facts:
            return None

        return ContextBlock(
            priority=ContextPriority.LAYOUT,
            title="Python Project Profile",
            body="\n".join(facts),
            sources=sources,
            category="python",
        )

    def _extract_dependencies(self) -> ContextBlock | None:
        """Extract project dependencies from pyproject.toml or requirements.txt."""
        facts: list[str] = []
        sources: list[str] = []

        # Try pyproject.toml first
        project = self.pyproject.get("project", {})
        dependencies = project.get("dependencies", [])

        if dependencies:
            sources.append("pyproject.toml")
            # List key dependencies (skip version specifiers for brevity)
            deps_list = []
            for dep in dependencies[:20]:  # Limit to 20 deps
                # Extract just the package name
                dep_name = (
                    dep.split("[")[0]
                    .split(">")[0]
                    .split("<")[0]
                    .split("=")[0]
                    .split("~")[0]
                    .strip()
                )
                if dep_name:
                    deps_list.append(dep_name)
            if deps_list:
                facts.append("**Core dependencies:**")
                facts.append(", ".join(deps_list))

        # Optional dependencies (dev, test, etc.)
        optional_deps = project.get("optional-dependencies", {})
        for group, deps in list(optional_deps.items())[:3]:
            if deps:
                deps_list = []
                for dep in deps[:10]:
                    dep_name = (
                        dep.split("[")[0]
                        .split(">")[0]
                        .split("<")[0]
                        .split("=")[0]
                        .split("~")[0]
                        .strip()
                    )
                    if dep_name:
                        deps_list.append(dep_name)
                if deps_list:
                    facts.append(f"**{group} dependencies:**")
                    facts.append(", ".join(deps_list))

        # Fallback to requirements.txt
        if not facts:
            req_path = self.worktree / "requirements.txt"
            if req_path.exists():
                sources.append("requirements.txt")
                try:
                    lines = req_path.read_text().splitlines()
                    deps_list = []
                    for line in lines[:20]:
                        line = line.strip()
                        if (
                            line
                            and not line.startswith("#")
                            and not line.startswith("-")
                        ):
                            dep_name = (
                                line.split("[")[0]
                                .split(">")[0]
                                .split("<")[0]
                                .split("=")[0]
                                .split("~")[0]
                                .strip()
                            )
                            if dep_name:
                                deps_list.append(dep_name)
                    if deps_list:
                        facts.append("**Dependencies:**")
                        facts.append(", ".join(deps_list))
                except Exception:
                    pass

        if not facts:
            return None

        return ContextBlock(
            priority=ContextPriority.PYTHON_CORE - 5,  # Slightly lower than core config
            title="Project Dependencies",
            body="\n".join(facts),
            sources=sources,
            category="python",
        )

    def _extract_ruff(self) -> ContextBlock | None:
        """Extract ruff linter/formatter configuration."""
        # Try ruff.toml first, then pyproject.toml
        ruff_config = self.ruff_toml or self.pyproject.get("tool", {}).get("ruff", {})

        if not ruff_config:
            return None

        facts: list[str] = []
        source = "ruff.toml" if self.ruff_toml else "pyproject.toml"

        # Line length
        line_length = ruff_config.get("line-length")
        if line_length:
            facts.append(f"- line-length: {line_length}")

        # Target version
        target = ruff_config.get("target-version")
        if target:
            facts.append(f"- target-version: {target}")

        # Lint settings
        lint = ruff_config.get("lint", {})

        # Selected rules
        select = lint.get("select") or ruff_config.get("select")
        if select:
            if len(select) <= 8:
                facts.append(f"- select: {', '.join(select)}")
            else:
                facts.append(
                    f"- select: {', '.join(select[:5])}... ({len(select)} rules)"
                )

        # Ignored rules
        ignore = lint.get("ignore") or ruff_config.get("ignore")
        if ignore:
            if len(ignore) <= 5:
                facts.append(f"- ignore: {', '.join(ignore)}")
            else:
                facts.append(
                    f"- ignore: {', '.join(ignore[:3])}... ({len(ignore)} rules)"
                )

        # Per-file ignores (common gotcha)
        pfi = lint.get("per-file-ignores") or ruff_config.get("per-file-ignores")
        if pfi:
            for pattern, rules in list(pfi.items())[:3]:
                if isinstance(rules, list):
                    rules = ", ".join(rules[:3])
                facts.append(f"- per-file-ignores[{pattern}]: {rules}")

        # Format settings
        fmt = ruff_config.get("format", {})
        if fmt.get("quote-style"):
            facts.append(f"- format.quote-style: {fmt['quote-style']}")

        if not facts:
            return None

        return ContextBlock(
            priority=ContextPriority.PYTHON_CORE,
            title="Ruff Configuration",
            body="\n".join(facts),
            sources=[source],
            category="python",
        )

    def _extract_mypy(self) -> ContextBlock | None:
        """Extract mypy type checking configuration."""
        # Try pyproject.toml first
        mypy_config = self.pyproject.get("tool", {}).get("mypy", {})
        source = "pyproject.toml"

        # Try mypy.ini if not in pyproject
        if not mypy_config:
            ini_data = _parse_ini(self.worktree / "mypy.ini")
            mypy_config = ini_data.get("mypy", {})
            if mypy_config:
                source = "mypy.ini"

        # Try setup.cfg
        if not mypy_config:
            cfg_data = _parse_ini(self.worktree / "setup.cfg")
            mypy_config = cfg_data.get("mypy", {})
            if mypy_config:
                source = "setup.cfg"

        if not mypy_config:
            return None

        facts: list[str] = []

        # Key strictness flags
        strict_flags = [
            "strict",
            "disallow_untyped_defs",
            "disallow_any_generics",
            "warn_return_any",
            "no_implicit_optional",
            "strict_equality",
        ]

        for flag in strict_flags:
            val = mypy_config.get(flag)
            if val is True or val == "True" or val == "true":
                facts.append(f"- {flag}: true")

        # Python version
        py_version = mypy_config.get("python_version")
        if py_version:
            facts.append(f"- python_version: {py_version}")

        if not facts:
            facts.append("- mypy enabled (default settings)")

        return ContextBlock(
            priority=ContextPriority.PYTHON_CORE,
            title="Mypy Configuration",
            body="\n".join(facts),
            sources=[source],
            category="python",
        )

    def _extract_pytest(self) -> ContextBlock | None:
        """Extract pytest configuration."""
        # Try pyproject.toml first
        pytest_config = (
            self.pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
        )
        source = "pyproject.toml"

        # Try pytest.ini
        if not pytest_config:
            ini_data = _parse_ini(self.worktree / "pytest.ini")
            pytest_config = ini_data.get("pytest", {})
            if pytest_config:
                source = "pytest.ini"

        # Try setup.cfg
        if not pytest_config:
            cfg_data = _parse_ini(self.worktree / "setup.cfg")
            pytest_config = cfg_data.get("tool:pytest", {})
            if pytest_config:
                source = "setup.cfg"

        if not pytest_config:
            # Check if pytest is a dependency (indicates it's used)
            deps = self.pyproject.get("project", {}).get("dependencies", [])
            dev_deps = (
                self.pyproject.get("project", {})
                .get("optional-dependencies", {})
                .get("dev", [])
            )
            all_deps = deps + dev_deps

            if any("pytest" in str(d).lower() for d in all_deps):
                return ContextBlock(
                    priority=ContextPriority.PYTHON_CORE - 10,
                    title="Pytest",
                    body="- pytest in dependencies (default settings)",
                    sources=["pyproject.toml"],
                    category="python",
                )
            return None

        facts: list[str] = []

        # Test paths
        testpaths = pytest_config.get("testpaths")
        if testpaths:
            if isinstance(testpaths, list):
                facts.append(f"- testpaths: {', '.join(testpaths)}")
            else:
                facts.append(f"- testpaths: {testpaths}")

        # Addopts
        addopts = pytest_config.get("addopts")
        if addopts:
            facts.append(f"- addopts: {addopts}")

        # Markers
        markers = pytest_config.get("markers")
        if markers and isinstance(markers, list):
            marker_names = [m.split(":")[0].strip() for m in markers[:5]]
            facts.append(f"- markers: {', '.join(marker_names)}")

        # Python files/classes/functions patterns
        for pattern_key in ["python_files", "python_classes", "python_functions"]:
            val = pytest_config.get(pattern_key)
            if val:
                facts.append(f"- {pattern_key}: {val}")

        if not facts:
            facts.append("- pytest enabled")

        return ContextBlock(
            priority=ContextPriority.PYTHON_CORE,
            title="Pytest Configuration",
            body="\n".join(facts),
            sources=[source],
            category="python",
        )
