"""Tree-sitter based source code parser.

Extracts definitions (classes, functions), imports, and references
from Python, JavaScript, and TypeScript files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog
import tree_sitter as ts

logger = structlog.get_logger()

# Supported language extensions
LangId = Literal["python", "javascript", "typescript", "tsx"]

_EXTENSION_MAP: dict[str, LangId] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


@dataclass(frozen=True)
class Definition:
    """A symbol definition extracted from source code."""

    name: str
    kind: str  # "class", "function", "method", "variable"
    line: int
    end_line: int
    signature: str  # e.g. "def foo(x: int) -> str"
    parent: str | None = None  # enclosing class name if method


@dataclass(frozen=True)
class ImportRef:
    """An import statement extracted from source code."""

    module: str  # e.g. "os.path" or "orx.config"
    names: tuple[str, ...] = ()  # e.g. ("Path",) for "from pathlib import Path"
    is_relative: bool = False


@dataclass
class FileAnalysis:
    """Analysis result for a single file."""

    path: str
    language: LangId
    definitions: list[Definition] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    lines_total: int = 0


def _get_language(lang_id: LangId) -> ts.Language:
    """Get a tree-sitter Language object for the given language ID."""
    if lang_id == "python":
        import tree_sitter_python as tsp

        return ts.Language(tsp.language())
    elif lang_id in ("javascript",):
        import tree_sitter_javascript as tsjs

        return ts.Language(tsjs.language())
    elif lang_id in ("typescript", "tsx"):
        import tree_sitter_typescript as tsts

        if lang_id == "tsx":
            return ts.Language(tsts.language_tsx())
        return ts.Language(tsts.language_typescript())
    msg = f"Unsupported language: {lang_id}"
    raise ValueError(msg)


def detect_language(path: Path) -> LangId | None:
    """Detect language from file extension."""
    return _EXTENSION_MAP.get(path.suffix.lower())


class RepoParser:
    """Parse source files using Tree-sitter to extract structure.

    Caches parsers per language for efficiency.
    """

    def __init__(self) -> None:
        self._parsers: dict[LangId, ts.Parser] = {}

    def _get_parser(self, lang_id: LangId) -> ts.Parser:
        if lang_id not in self._parsers:
            language = _get_language(lang_id)
            self._parsers[lang_id] = ts.Parser(language)
        return self._parsers[lang_id]

    def parse_file(self, path: Path, *, root: Path | None = None) -> FileAnalysis | None:
        """Parse a single file and extract definitions and imports.

        Args:
            path: Absolute path to the file.
            root: If provided, store relative path in FileAnalysis.

        Returns:
            FileAnalysis or None if file cannot be parsed.
        """
        lang_id = detect_language(path)
        if lang_id is None:
            return None

        try:
            source = path.read_bytes()
        except OSError:
            return None

        parser = self._get_parser(lang_id)
        tree = parser.parse(source)

        rel_path = str(path.relative_to(root)) if root else str(path)
        lines_total = source.count(b"\n") + 1

        analysis = FileAnalysis(
            path=rel_path,
            language=lang_id,
            lines_total=lines_total,
        )

        if lang_id == "python":
            self._extract_python(tree.root_node, analysis)
        else:
            self._extract_js_ts(tree.root_node, analysis)

        return analysis

    def parse_directory(
        self,
        root: Path,
        *,
        max_files: int = 500,
        exclude_dirs: frozenset[str] | None = None,
    ) -> list[FileAnalysis]:
        """Parse all supported files under a directory.

        Args:
            root: Root directory to scan.
            max_files: Maximum number of files to parse.
            exclude_dirs: Directory names to skip.

        Returns:
            List of FileAnalysis results.
        """
        if exclude_dirs is None:
            exclude_dirs = frozenset({
                "node_modules",
                ".git",
                "__pycache__",
                ".venv",
                "venv",
                ".tox",
                "dist",
                "build",
                ".mypy_cache",
                ".ruff_cache",
                ".pytest_cache",
                "runs",
                ".conda",
            })

        results: list[FileAnalysis] = []
        count = 0

        for ext in _EXTENSION_MAP:
            for file_path in root.rglob(f"*{ext}"):
                if count >= max_files:
                    break
                # Skip excluded directories
                if any(part in exclude_dirs for part in file_path.parts):
                    continue
                analysis = self.parse_file(file_path, root=root)
                if analysis:
                    results.append(analysis)
                    count += 1

        return results

    # ---- Python extraction ----

    def _extract_python(self, root: ts.Node, analysis: FileAnalysis) -> None:
        """Extract definitions and imports from a Python AST."""
        for node in root.children:
            if node.type == "import_statement":
                self._extract_python_import(node, analysis)
            elif node.type == "import_from_statement":
                self._extract_python_import_from(node, analysis)
            elif node.type == "function_definition":
                self._extract_python_func(node, analysis, parent=None)
            elif node.type == "class_definition":
                self._extract_python_class(node, analysis)
            elif node.type == "decorated_definition":
                for child in node.children:
                    if child.type == "function_definition":
                        self._extract_python_func(child, analysis, parent=None)
                    elif child.type == "class_definition":
                        self._extract_python_class(child, analysis)

    def _extract_python_import(self, node: ts.Node, analysis: FileAnalysis) -> None:
        """Extract `import X` statement."""
        for child in node.children:
            if child.type == "dotted_name":
                module_name = child.text.decode() if child.text else ""
                analysis.imports.append(ImportRef(module=module_name))

    def _extract_python_import_from(self, node: ts.Node, analysis: FileAnalysis) -> None:
        """Extract `from X import Y` statement."""
        module_name = ""
        names: list[str] = []
        is_relative = False

        for child in node.children:
            if child.type == "dotted_name":
                if not module_name:
                    module_name = child.text.decode() if child.text else ""
                else:
                    names.append(child.text.decode() if child.text else "")
            elif child.type == "relative_import":
                is_relative = True
                for sub in child.children:
                    if sub.type == "dotted_name":
                        module_name = sub.text.decode() if sub.text else ""
            elif child.type == "import_prefix":
                is_relative = True
            elif child.type == "wildcard_import":
                names.append("*")

        analysis.imports.append(
            ImportRef(module=module_name, names=tuple(names), is_relative=is_relative)
        )

    def _extract_python_func(
        self,
        node: ts.Node,
        analysis: FileAnalysis,
        *,
        parent: str | None,
    ) -> None:
        """Extract a function/method definition."""
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        name = name_node.text.decode()
        kind = "method" if parent else "function"

        # Build signature from first line up to the colon
        sig = self._python_signature(node)

        analysis.definitions.append(
            Definition(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=sig,
                parent=parent,
            )
        )

    def _extract_python_class(self, node: ts.Node, analysis: FileAnalysis) -> None:
        """Extract a class definition and its methods."""
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        class_name = name_node.text.decode()

        # Build class signature
        sig = self._python_class_signature(node)
        analysis.definitions.append(
            Definition(
                name=class_name,
                kind="class",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=sig,
            )
        )

        # Extract methods from class body
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "function_definition":
                    self._extract_python_func(child, analysis, parent=class_name)
                elif child.type == "decorated_definition":
                    for sub in child.children:
                        if sub.type == "function_definition":
                            self._extract_python_func(sub, analysis, parent=class_name)

    @staticmethod
    def _python_signature(node: ts.Node) -> str:
        """Extract function signature (up to and including return type)."""
        parts: list[str] = []

        for child in node.children:
            if child.type == "block":
                break
            if child.type == ":":
                break
            text = child.text.decode() if child.text else ""
            parts.append(text)

        sig = " ".join(parts).strip()
        return sig if sig else "def ???()"

    @staticmethod
    def _python_class_signature(node: ts.Node) -> str:
        """Extract class signature (class Name(bases):)."""
        parts: list[str] = []

        for child in node.children:
            if child.type in ("block", ":"):
                break
            text = child.text.decode() if child.text else ""
            parts.append(text)

        sig = " ".join(parts).strip()
        return sig if sig else "class ???"

    # ---- JS/TS extraction ----

    def _extract_js_ts(self, root: ts.Node, analysis: FileAnalysis) -> None:
        """Extract definitions and imports from JS/TS AST."""
        for node in root.children:
            self._walk_js_ts_node(node, analysis, parent=None)

    def _walk_js_ts_node(
        self,
        node: ts.Node,
        analysis: FileAnalysis,
        *,
        parent: str | None,
    ) -> None:
        ntype = node.type

        if ntype == "import_statement":
            self._extract_js_import(node, analysis)
        elif ntype == "function_declaration":
            self._extract_js_func(node, analysis, parent=parent)
        elif ntype == "class_declaration":
            self._extract_js_class(node, analysis)
        elif ntype in ("export_statement", "export_default_declaration"):
            for child in node.children:
                self._walk_js_ts_node(child, analysis, parent=parent)
        elif ntype == "lexical_declaration":
            # const foo = () => { ... } or const Foo = class { ... }
            for child in node.children:
                if child.type == "variable_declarator":
                    self._extract_js_variable(child, analysis, parent=parent)
        elif ntype == "interface_declaration":
            self._extract_js_interface(node, analysis)
        elif ntype == "type_alias_declaration":
            self._extract_js_type_alias(node, analysis)

    def _extract_js_import(self, node: ts.Node, analysis: FileAnalysis) -> None:
        """Extract ES6 import."""
        source_node = node.child_by_field_name("source")
        if source_node and source_node.text:
            module = source_node.text.decode().strip("'\"")
            names: list[str] = []
            # Extract imported names
            for child in node.children:
                if child.type == "import_clause":
                    for sub in child.children:
                        if sub.type == "identifier" and sub.text:
                            names.append(sub.text.decode())
                        elif sub.type == "named_imports":
                            for spec in sub.children:
                                if spec.type == "import_specifier":
                                    name_node = spec.child_by_field_name("name")
                                    if name_node and name_node.text:
                                        names.append(name_node.text.decode())
            is_relative = module.startswith(".")
            analysis.imports.append(
                ImportRef(module=module, names=tuple(names), is_relative=is_relative)
            )

    def _extract_js_func(
        self,
        node: ts.Node,
        analysis: FileAnalysis,
        *,
        parent: str | None,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        name = name_node.text.decode()
        kind = "method" if parent else "function"

        # Build signature
        sig_parts: list[str] = []
        for child in node.children:
            if child.type in ("statement_block", "{"):
                break
            sig_parts.append(child.text.decode() if child.text else "")

        analysis.definitions.append(
            Definition(
                name=name,
                kind=kind,
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=" ".join(sig_parts).strip(),
                parent=parent,
            )
        )

    def _extract_js_class(self, node: ts.Node, analysis: FileAnalysis) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        class_name = name_node.text.decode()

        # Signature
        sig_parts: list[str] = []
        for child in node.children:
            if child.type == "class_body":
                break
            sig_parts.append(child.text.decode() if child.text else "")

        analysis.definitions.append(
            Definition(
                name=class_name,
                kind="class",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=" ".join(sig_parts).strip(),
            )
        )

        # Extract methods
        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type in ("method_definition", "public_field_definition"):
                    self._extract_js_method(child, analysis, class_name=class_name)

    def _extract_js_method(
        self,
        node: ts.Node,
        analysis: FileAnalysis,
        *,
        class_name: str,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        name = name_node.text.decode()
        sig_parts: list[str] = []
        for child in node.children:
            if child.type in ("statement_block", "{"):
                break
            sig_parts.append(child.text.decode() if child.text else "")

        analysis.definitions.append(
            Definition(
                name=name,
                kind="method",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=" ".join(sig_parts).strip(),
                parent=class_name,
            )
        )

    def _extract_js_variable(
        self,
        node: ts.Node,
        analysis: FileAnalysis,
        *,
        parent: str | None,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        name = name_node.text.decode()
        # Check if it's an arrow function or function expression
        value = node.child_by_field_name("value")
        if value and value.type in ("arrow_function", "function"):
            kind = "function"
            sig = f"const {name} = (...) => ..."
            if value.type == "arrow_function":
                params = value.child_by_field_name("parameters")
                if params and params.text:
                    sig = f"const {name} = {params.text.decode()} => ..."
            analysis.definitions.append(
                Definition(
                    name=name,
                    kind=kind,
                    line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=sig,
                    parent=parent,
                )
            )

    def _extract_js_interface(self, node: ts.Node, analysis: FileAnalysis) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        name = name_node.text.decode()
        analysis.definitions.append(
            Definition(
                name=name,
                kind="class",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=f"interface {name}",
            )
        )

    def _extract_js_type_alias(self, node: ts.Node, analysis: FileAnalysis) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node or not name_node.text:
            return

        name = name_node.text.decode()
        analysis.definitions.append(
            Definition(
                name=name,
                kind="variable",
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                signature=f"type {name} = ...",
            )
        )
