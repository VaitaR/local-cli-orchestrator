"""Tests for the Smart Context Intelligence module (tree-sitter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orx.context.intelligence.bundle import SmartBundler
from orx.context.intelligence.graph import RepoGraph
from orx.context.intelligence.parser import (
    Definition,
    FileAnalysis,
    RepoParser,
    detect_language,
)
from orx.context.intelligence.skeleton import SkeletonGenerator

# ---------------------------------------------------------------------------
# parser.py tests
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language(Path("foo.py")) == "python"

    def test_javascript(self) -> None:
        assert detect_language(Path("foo.js")) == "javascript"

    def test_typescript(self) -> None:
        assert detect_language(Path("foo.ts")) == "typescript"

    def test_tsx(self) -> None:
        assert detect_language(Path("component.tsx")) == "tsx"

    def test_unknown(self) -> None:
        assert detect_language(Path("readme.md")) is None


class TestRepoParserPython:
    def test_parse_simple_file(self, tmp_path: Path) -> None:
        src = tmp_path / "example.py"
        src.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "class MyClass:\n"
            "    def method(self, x: int) -> str:\n"
            "        return str(x)\n"
            "\n"
            "def standalone(p: Path) -> bool:\n"
            "    return p.exists()\n"
        )

        parser = RepoParser()
        result = parser.parse_file(src, root=tmp_path)

        assert result is not None
        assert result.language == "python"
        assert result.path == "example.py"

        # Check imports
        assert len(result.imports) == 2
        assert result.imports[0].module == "os"
        assert result.imports[1].module == "pathlib"

        # Check definitions
        names = {d.name for d in result.definitions}
        assert "MyClass" in names
        assert "method" in names
        assert "standalone" in names

    def test_parse_class_methods(self, tmp_path: Path) -> None:
        src = tmp_path / "cls.py"
        src.write_text(
            "class Foo:\n"
            "    def __init__(self):\n"
            "        pass\n"
            "\n"
            "    def bar(self) -> int:\n"
            "        return 42\n"
        )

        parser = RepoParser()
        result = parser.parse_file(src, root=tmp_path)
        assert result is not None

        methods = [d for d in result.definitions if d.kind == "method"]
        assert len(methods) == 2
        assert all(d.parent == "Foo" for d in methods)

    def test_parse_from_import(self, tmp_path: Path) -> None:
        src = tmp_path / "imp.py"
        src.write_text("from orx.config import OrxConfig, EngineType\n")

        parser = RepoParser()
        result = parser.parse_file(src, root=tmp_path)
        assert result is not None
        assert len(result.imports) == 1
        assert result.imports[0].module == "orx.config"

    def test_returns_none_for_unsupported(self, tmp_path: Path) -> None:
        src = tmp_path / "readme.md"
        src.write_text("# Hello")

        parser = RepoParser()
        assert parser.parse_file(src) is None

    def test_parse_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def foo(): pass\n")
        (tmp_path / "b.py").write_text("class Bar: pass\n")
        (tmp_path / "readme.md").write_text("# Readme\n")

        parser = RepoParser()
        results = parser.parse_directory(tmp_path)
        assert len(results) == 2

    def test_excludes_pycache(self, tmp_path: Path) -> None:
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.py").write_text("x = 1\n")
        (tmp_path / "real.py").write_text("def real(): pass\n")

        parser = RepoParser()
        results = parser.parse_directory(tmp_path)
        paths = {r.path for r in results}
        assert "real.py" in paths
        assert "__pycache__/cached.py" not in paths


class TestRepoParserJavaScript:
    def test_parse_js_file(self, tmp_path: Path) -> None:
        src = tmp_path / "app.js"
        src.write_text(
            "import { useState } from 'react';\n"
            "\n"
            "function App() {\n"
            "  return null;\n"
            "}\n"
        )

        parser = RepoParser()
        result = parser.parse_file(src, root=tmp_path)
        assert result is not None
        assert result.language == "javascript"
        assert len(result.imports) == 1
        assert result.imports[0].module == "react"
        assert "useState" in result.imports[0].names

        funcs = [d for d in result.definitions if d.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "App"


class TestRepoParserTypeScript:
    def test_parse_ts_file(self, tmp_path: Path) -> None:
        src = tmp_path / "service.ts"
        src.write_text(
            "import { Config } from './config';\n"
            "\n"
            "interface ServiceOptions {\n"
            "  timeout: number;\n"
            "}\n"
            "\n"
            "class Service {\n"
            "  constructor(private opts: ServiceOptions) {}\n"
            "\n"
            "  async fetch(url: string): Promise<string> {\n"
            "    return '';\n"
            "  }\n"
            "}\n"
        )

        parser = RepoParser()
        result = parser.parse_file(src, root=tmp_path)
        assert result is not None
        assert result.language == "typescript"

        names = {d.name for d in result.definitions}
        assert "ServiceOptions" in names
        assert "Service" in names


# ---------------------------------------------------------------------------
# graph.py tests
# ---------------------------------------------------------------------------


class TestRepoGraph:
    def test_build_graph(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "config.py").write_text(
            "class Config:\n    pass\n"
        )
        (src / "runner.py").write_text(
            "from src.config import Config\n\n"
            "class Runner:\n    pass\n"
        )

        graph = RepoGraph.build(tmp_path)
        assert len(graph.analyses) >= 2

    def test_get_neighbours(self, tmp_path: Path) -> None:  # noqa: ARG002
        # Build a small graph manually
        graph = RepoGraph()
        graph.analyses["a.py"] = FileAnalysis(path="a.py", language="python")
        graph.analyses["b.py"] = FileAnalysis(path="b.py", language="python")
        graph.analyses["c.py"] = FileAnalysis(path="c.py", language="python")

        graph.edges_out["a.py"].add("b.py")
        graph.edges_in["b.py"].add("a.py")
        graph.edges_out["b.py"].add("c.py")
        graph.edges_in["c.py"].add("b.py")

        # Depth 1: a.py's neighbours should include b.py
        neighbours = graph.get_neighbours("a.py", depth=1)
        assert "b.py" in neighbours
        assert "c.py" not in neighbours

        # Depth 2: should also include c.py
        neighbours_2 = graph.get_neighbours("a.py", depth=2)
        assert "b.py" in neighbours_2
        assert "c.py" in neighbours_2

    def test_get_relevant_context(self) -> None:
        graph = RepoGraph()
        for name in ("a.py", "b.py", "c.py", "d.py"):
            graph.analyses[name] = FileAnalysis(path=name, language="python")

        graph.edges_out["a.py"].add("b.py")
        graph.edges_in["b.py"].add("a.py")

        neighbours, remaining = graph.get_relevant_context(["a.py"])
        assert "b.py" in neighbours
        assert "a.py" not in neighbours
        assert "c.py" in remaining
        assert "d.py" in remaining

    def test_render_tags_map(self) -> None:
        graph = RepoGraph()
        analysis = FileAnalysis(path="config.py", language="python")
        analysis.definitions.append(
            Definition(
                name="Config",
                kind="class",
                line=1,
                end_line=10,
                signature="class Config",
            )
        )
        analysis.definitions.append(
            Definition(
                name="load",
                kind="function",
                line=12,
                end_line=15,
                signature="def load() -> Config",
            )
        )
        graph.analyses["config.py"] = analysis

        tags = graph.render_tags_map()
        assert "config.py" in tags
        assert "class Config" in tags
        assert "def load() -> Config" in tags

    def test_path_to_module(self) -> None:
        assert RepoGraph._path_to_module("src/orx/config.py") == "orx.config"
        assert RepoGraph._path_to_module("src/orx/__init__.py") == "orx"
        assert RepoGraph._path_to_module("orx/stages/plan.py") == "orx.stages.plan"
        assert RepoGraph._path_to_module("readme.md") is None


# ---------------------------------------------------------------------------
# skeleton.py tests
# ---------------------------------------------------------------------------


class TestSkeletonGenerator:
    def test_python_skeleton(self, tmp_path: Path) -> None:
        src = tmp_path / "example.py"
        src.write_text(
            "import os\n"
            "\n"
            "def hello(name: str) -> str:\n"
            '    """Say hello."""\n'
            '    return f"Hello, {name}!"\n'
            "\n"
            "class Greeter:\n"
            "    def greet(self, x: int) -> None:\n"
            "        print(x)\n"
            "        print(x + 1)\n"
        )

        gen = SkeletonGenerator()
        skeleton = gen.generate(src)
        assert skeleton is not None

        # Imports should be preserved
        assert "import os" in skeleton

        # Function signature preserved
        assert "def hello(name: str) -> str:" in skeleton

        # Docstring preserved
        assert '"""Say hello."""' in skeleton

        # Body replaced with ...
        assert "..." in skeleton

        # Should NOT contain the implementation
        assert 'f"Hello, {name}!"' not in skeleton

    def test_returns_none_for_unsupported(self, tmp_path: Path) -> None:
        src = tmp_path / "readme.md"
        src.write_text("# Hello")

        gen = SkeletonGenerator()
        assert gen.generate(src) is None

    def test_preserves_class_structure(self, tmp_path: Path) -> None:
        src = tmp_path / "cls.py"
        src.write_text(
            "class Foo:\n"
            "    def method_a(self) -> int:\n"
            "        x = 1\n"
            "        return x + 1\n"
            "\n"
            "    def method_b(self) -> str:\n"
            '        return "hello"\n'
        )

        gen = SkeletonGenerator()
        skeleton = gen.generate(src)
        assert skeleton is not None
        assert "class Foo:" in skeleton
        assert "def method_a(self) -> int:" in skeleton
        assert "def method_b(self) -> str:" in skeleton
        assert "..." in skeleton


# ---------------------------------------------------------------------------
# bundle.py tests
# ---------------------------------------------------------------------------


class TestSmartBundler:
    def _build_test_repo(self, tmp_path: Path) -> Path:
        """Create a minimal test repo."""
        (tmp_path / "config.py").write_text(
            "class Config:\n"
            "    def __init__(self):\n"
            "        self.x = 1\n"
            "\n"
            "    def get_value(self) -> int:\n"
            "        return self.x\n"
        )
        (tmp_path / "runner.py").write_text(
            "from config import Config\n"
            "\n"
            "class Runner:\n"
            "    def __init__(self, cfg: Config):\n"
            "        self.cfg = cfg\n"
            "\n"
            "    def run(self) -> bool:\n"
            "        return True\n"
        )
        (tmp_path / "utils.py").write_text(
            "def helper() -> str:\n"
            '    return "help"\n'
        )
        return tmp_path

    def test_build_repo_map(self, tmp_path: Path) -> None:
        root = self._build_test_repo(tmp_path)
        graph = RepoGraph.build(root)
        bundler = SmartBundler(root, graph)

        repo_map = bundler.build_repo_map()
        assert "config.py" in repo_map
        assert "runner.py" in repo_map
        assert "utils.py" in repo_map

    def test_bundle_produces_tiers(self, tmp_path: Path) -> None:
        root = self._build_test_repo(tmp_path)
        graph = RepoGraph.build(root)
        bundler = SmartBundler(root, graph)

        result = bundler.bundle(target_files=["runner.py"])

        # Should have target files section
        assert result.target_count >= 1
        assert "Target Files" in result.smart_context
        assert "runner.py" in result.smart_context

        # Should have a repo map
        assert result.repo_map

    def test_bundle_empty_targets(self, tmp_path: Path) -> None:
        root = self._build_test_repo(tmp_path)
        graph = RepoGraph.build(root)
        bundler = SmartBundler(root, graph)

        result = bundler.bundle(target_files=[])
        assert result.target_count == 0

    def test_bundle_respects_budget(self, tmp_path: Path) -> None:
        root = self._build_test_repo(tmp_path)
        graph = RepoGraph.build(root)
        bundler = SmartBundler(root, graph, max_target_chars=10)

        result = bundler.bundle(target_files=["runner.py"])
        # With a tiny budget, should limit target content
        assert result.total_chars < 1000  # Should be small


# ---------------------------------------------------------------------------
# Integration test: end-to-end on real orx source
# ---------------------------------------------------------------------------


class TestIntegrationSelfParse:
    """Parse the orx source tree itself as an integration test."""

    def test_parse_orx_source(self) -> None:
        orx_src = Path(__file__).resolve().parents[2] / "src" / "orx"
        if not orx_src.exists():
            pytest.skip("orx source not found")

        parser = RepoParser()
        results = parser.parse_directory(orx_src)
        assert len(results) > 10  # Should find many files

        # Check we found key definitions
        all_defs = {d.name for r in results for d in r.definitions}
        assert "Runner" in all_defs or "RunPaths" in all_defs

    def test_build_graph_on_orx(self) -> None:
        orx_root = Path(__file__).resolve().parents[2]
        src = orx_root / "src"
        if not src.exists():
            pytest.skip("orx source not found")

        graph = RepoGraph.build(src)
        assert len(graph.analyses) > 5
        assert sum(len(v) for v in graph.edges_out.values()) > 0

    def test_skeleton_on_orx_file(self) -> None:
        config_path = (
            Path(__file__).resolve().parents[2] / "src" / "orx" / "config.py"
        )
        if not config_path.exists():
            pytest.skip("config.py not found")

        gen = SkeletonGenerator()
        skeleton = gen.generate(config_path)
        assert skeleton is not None
        assert "class" in skeleton
        assert "..." in skeleton
        # Should be shorter than the original
        original = config_path.read_text()
        assert len(skeleton) < len(original)
