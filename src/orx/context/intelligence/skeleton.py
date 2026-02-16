"""Skeleton generator — strips function/method bodies via Tree-sitter.

Produces a compact version of a source file that preserves:
- All imports
- Class/function signatures with type annotations
- Docstrings (first string in body)
- ``...`` as placeholder for bodies
"""

from __future__ import annotations

from pathlib import Path

import structlog
import tree_sitter as ts

from orx.context.intelligence.parser import LangId, _get_language, detect_language

logger = structlog.get_logger()


class SkeletonGenerator:
    """Generate skeleton (signature-only) versions of source files."""

    def __init__(self) -> None:
        self._parsers: dict[LangId, ts.Parser] = {}

    def _get_parser(self, lang_id: LangId) -> ts.Parser:
        if lang_id not in self._parsers:
            language = _get_language(lang_id)
            self._parsers[lang_id] = ts.Parser(language)
        return self._parsers[lang_id]

    def generate(self, path: Path) -> str | None:
        """Generate a skeleton for a source file.

        Args:
            path: Path to the source file.

        Returns:
            Skeleton source code string, or None if not parseable.
        """
        lang_id = detect_language(path)
        if lang_id is None:
            return None

        try:
            source = path.read_text()
        except OSError:
            return None

        source_bytes = source.encode()
        parser = self._get_parser(lang_id)
        tree = parser.parse(source_bytes)

        lines = source.split("\n")

        if lang_id == "python":
            return self._skeleton_python(tree.root_node, lines)
        return self._skeleton_js_ts(tree.root_node, lines)

    def _skeleton_python(self, root: ts.Node, lines: list[str]) -> str:
        """Generate Python skeleton by replacing function bodies with `...`."""
        # Collect ranges to replace: (start_line, end_line) -> replacement
        replacements: list[tuple[int, int, str]] = []

        self._collect_python_body_replacements(root, lines, replacements)

        if not replacements:
            return "\n".join(lines)

        # Sort by start line descending to replace from bottom up
        replacements.sort(key=lambda r: r[0], reverse=True)

        result_lines = list(lines)
        for start, end, replacement in replacements:
            result_lines[start:end + 1] = [replacement]

        return "\n".join(result_lines)

    def _collect_python_body_replacements(
        self,
        node: ts.Node,
        lines: list[str],
        replacements: list[tuple[int, int, str]],
    ) -> None:
        """Recursively collect body ranges to replace in Python."""
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                self._process_python_definition(child, lines, replacements)
            elif child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        self._process_python_definition(sub, lines, replacements)

    def _process_python_definition(
        self,
        node: ts.Node,
        lines: list[str],
        replacements: list[tuple[int, int, str]],
    ) -> None:
        """Process a single Python function/class definition."""
        body = node.child_by_field_name("body")
        if not body:
            return

        if node.type == "class_definition":
            # For classes: recurse into methods but keep class structure
            for child in body.children:
                if child.type in ("function_definition", "decorated_definition"):
                    if child.type == "decorated_definition":
                        for sub in child.children:
                            if sub.type == "function_definition":
                                self._replace_function_body(sub, lines, replacements)
                    else:
                        self._replace_function_body(child, lines, replacements)
        else:
            # For functions: replace entire body
            self._replace_function_body(node, lines, replacements)

    def _replace_function_body(
        self,
        func_node: ts.Node,
        lines: list[str],
        replacements: list[tuple[int, int, str]],
    ) -> None:
        """Replace a function body with docstring + `...`."""
        body = func_node.child_by_field_name("body")
        if not body:
            return

        body_start = body.start_point[0]  # 0-indexed line
        body_end = body.end_point[0]

        # Determine indentation from first body line
        if body_start < len(lines):
            first_line = lines[body_start]
            indent = first_line[: len(first_line) - len(first_line.lstrip())]
        else:
            indent = "    "

        # Check if body starts with a docstring
        docstring_lines: list[str] = []
        docstring_end = body_start - 1

        for child in body.children:
            if child.type == "expression_statement":
                expr = child.children[0] if child.children else None
                if expr and expr.type == "string":
                    # This is a docstring
                    docstring_end = child.end_point[0]
                    for i in range(child.start_point[0], docstring_end + 1):
                        if i < len(lines):
                            docstring_lines.append(lines[i])
            break  # Only check first statement

        if docstring_lines:
            # Replace from after docstring to end of body
            if docstring_end + 1 <= body_end:
                replacements.append((docstring_end + 1, body_end, indent + "..."))
        else:
            replacements.append((body_start, body_end, indent + "..."))

    def _skeleton_js_ts(self, root: ts.Node, lines: list[str]) -> str:
        """Generate JS/TS skeleton by replacing function bodies."""
        replacements: list[tuple[int, int, str]] = []
        self._collect_js_body_replacements(root, lines, replacements)

        if not replacements:
            return "\n".join(lines)

        replacements.sort(key=lambda r: r[0], reverse=True)
        result_lines = list(lines)
        for start, end, replacement in replacements:
            result_lines[start:end + 1] = [replacement]

        return "\n".join(result_lines)

    def _collect_js_body_replacements(
        self,
        node: ts.Node,
        lines: list[str],
        replacements: list[tuple[int, int, str]],
    ) -> None:
        """Recursively collect body replacements for JS/TS."""
        for child in node.children:
            ntype = child.type

            if ntype in ("function_declaration", "method_definition"):
                body = child.child_by_field_name("body")
                if body and body.type == "statement_block":
                    indent = self._get_indent(lines, body.start_point[0])
                    replacements.append(
                        (body.start_point[0], body.end_point[0], indent + "{ /* ... */ }")
                    )
            elif ntype == "class_declaration":
                body = child.child_by_field_name("body")
                if body:
                    # Recurse into class body for methods
                    self._collect_js_body_replacements(body, lines, replacements)
            elif ntype in ("export_statement", "export_default_declaration"):
                self._collect_js_body_replacements(child, lines, replacements)
            elif ntype == "lexical_declaration":
                for decl in child.children:
                    if decl.type == "variable_declarator":
                        value = decl.child_by_field_name("value")
                        if value and value.type == "arrow_function":
                            body = value.child_by_field_name("body")
                            if body and body.type == "statement_block":
                                indent = self._get_indent(lines, body.start_point[0])
                                replacements.append(
                                    (body.start_point[0], body.end_point[0], indent + "{ /* ... */ }")
                                )

    @staticmethod
    def _get_indent(lines: list[str], line_idx: int) -> str:
        """Get indentation of a line."""
        if line_idx < len(lines):
            line = lines[line_idx]
            return line[: len(line) - len(line.lstrip())]
        return ""
