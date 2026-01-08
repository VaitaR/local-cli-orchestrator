"""TypeScript/JavaScript project extractor.

Extracts configuration from TypeScript/JavaScript projects including:
- package.json (scripts, engines, type)
- tsconfig.json (compiler options)
- ESLint config (JSON formats)
- Prettier config (JSON formats)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from orx.context.repo_context.blocks import ContextBlock, ContextPriority

logger = structlog.get_logger()


def _parse_jsonc(path: Path) -> dict[str, Any]:
    """Parse a JSONC file (JSON with comments), returning empty dict on failure.
    
    Handles:
    - Single-line comments (// ...)
    - Multi-line comments (/* ... */)
    - Trailing commas in objects and arrays
    """
    if not path.exists():
        return {}
    
    try:
        text = path.read_text()
        
        # Remove single-line comments (but not in strings)
        lines = []
        for line in text.split('\n'):
            in_string = False
            escape_next = False
            result = []
            i = 0
            while i < len(line):
                char = line[i]
                if escape_next:
                    result.append(char)
                    escape_next = False
                elif char == '\\':
                    result.append(char)
                    escape_next = True
                elif char == '"' and not in_string:
                    in_string = True
                    result.append(char)
                elif char == '"' and in_string:
                    in_string = False
                    result.append(char)
                elif i < len(line) - 1 and line[i:i+2] == '//' and not in_string:
                    # Found comment, stop processing this line
                    break
                else:
                    result.append(char)
                i += 1
            lines.append(''.join(result))
        
        text = '\n'.join(l              
        # Remove multi-line comments
        while '/*            result = []
       text.find('/*')
            end = text.find('*/', start)
            if end == -1:
                # Unclosed comment
                text = text[:start]
                break
            text = text[:start] + text[end+2:]
        
        # Remove trailing commas before ] or }
        text = text.replace(',\n]', '\n]').replace(',\n}', '\n}')
        text = text.replace(', ]', ' ]').replace(', }', ' }')
        
        return json.loads(text)
    except E                    in_string = False
         parse JSONC", path=str(path), error=str(e))
        return {}


def _parse_json(path: Path) -> dict[str, Any]:
    """Parse a JSON file, returning empty dict on failure.
    
    Note: This now uses JSONC parsing for better compatibility.
    """
    return _parse_jsonc(path)


class TypeScriptExtractor:
    """Extracts TypeScript/JavaScript project configuration."""

    def __init__(self, worktree: Path) -> None:
        """Initialize the extractor.

        Args:
            worktree: Path to the repository worktree.
        """
        self.worktree = worktree
        self._package_json: dict[str, Any] | None = None
        self._tsconfig: dict[str, Any] | None = None

    @property
    def package_json(self) -> dict[str, Any]:
        """Lazy-load package.json."""
        if self._package_json is None:
            self._package_json = _parse_jsonc(self.worktree / "package.json")
        return self._package_json

    @property
    def tsconfig(self) -> dict[str, Any]:
        """Lazy-load tsconfig.json."""
        if self._tsconfig is None:
            self._tsconfig = _parse_jsonc(self.worktree / "tsconfig.json")
        return self._tsconfig

    def is_ts_project(self) -> bool:
        """Check if this is a TypeScript/JavaScript project."""
        indicators = [
            self.worktree / "package.json",
            self.worktree / "tsconfig.json",
            self.worktree / "jsconfig.json",
        ]
        return any(p.exists() for p in indicators)

    def extract_all(self) -> list[ContextBlock]:
        """Extract all TypeScript tooling context blocks.

        Returns:
            List of context blocks for TypeScript configuration.
        """
        if not self.is_ts_project():
            return []

        blocks: list[ContextBlock] = []

        # Profile/stack info
        profile = self._extract_profile()
        if profile:
            blocks.append(profile)

        # Scripts
        scripts = self._extract_scripts()
        if scripts:
            blocks.append(scripts)

        # TypeScript config
        tsconfig = self._extract_tsconfig()
        if tsconfig:
            blocks.append(tsconfig)

        # ESLint config
        eslint = self._extract_eslint()
        if eslint:
            blocks.append(eslint)

        # Prettier config
        prettier = self._extract_prettier()
        if prettier:
            blocks.append(prettier)

        return blocks

    def extract_profile_only(self) -> ContextBlock | None:
        """Extract only the stack/profile block (for plan/spec stages).

        Returns:
            Profile context block or None.
        """
        if not self.is_ts_project():
            return None
        return self._extract_profile()

    def _extract_profile(self) -> ContextBlock | None:
        """Extract project profile (stack overview)."""
        facts: list[str] = []
        sources: list[str] = []

        pkg = self.package_json
        if not pkg:
            return None

        sources.append("package.json")

        # Package type
        pkg_type = pkg.get("type")
        if pkg_type:
            facts.append(f"- Module type: {pkg_type}")

        # Engine requirements
        engines = pkg.get("engines", {})
        if engines.get("node"):
            facts.append(f"- Node.js: {engines['node']}")

        # Package manager detection
        if (self.worktree / "pnpm-lock.yaml").exists():
            facts.append("- Package manager: pnpm")
            sources.append("pnpm-lock.yaml")
        elif (self.worktree / "yarn.lock").exists():
            facts.append("- Package manager: yarn")
            sources.append("yarn.lock")
        elif (self.worktree / "bun.lockb").exists():
            facts.append("- Package manager: bun")
            sources.append("bun.lockb")
        elif (self.worktree / "package-lock.json").exists():
            facts.append("- Package manager: npm")
            sources.append("package-lock.json")

        # Framework detection from dependencies
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

        frameworks: list[str] = []
        if "next" in deps:
            frameworks.append("Next.js")
        if "react" in deps:
            frameworks.append("React")
        if "vue" in deps:
            frameworks.append("Vue")
        if "@angular/core" in deps:
            frameworks.append("Angular")
        if "express" in deps:
            frameworks.append("Express")
        if "fastify" in deps:
            frameworks.append("Fastify")

        if frameworks:
            facts.append(f"- Frameworks: {', '.join(frameworks)}")

        # TypeScript detection
        if "typescript" in deps or self.tsconfig:
            facts.append("- TypeScript: enabled")
            sources.append("tsconfig.json")

        if not facts:
            return None

        return ContextBlock(
            priority=ContextPriority.LAYOUT,
            title="TypeScript/JS Project Profile",
            body="\n".join(facts),
            sources=sources,
            category="typescript",
        )

    def _extract_scripts(self) -> ContextBlock | None:
        """Extract relevant npm scripts."""
        scripts = self.package_json.get("scripts", {})
        if not scripts:
            return None

        # Focus on quality/build scripts
        relevant_keys = [
            "lint",
            "test",
            "typecheck",
            "type-check",
            "format",
            "check",
            "build",
            "dev",
            "start",
        ]

        facts: list[str] = []
        for key in relevant_keys:
            if key in scripts:
                cmd = scripts[key]
                # Truncate long commands
                if len(cmd) > 60:
                    cmd = cmd[:57] + "..."
                facts.append(f"- `{key}`: `{cmd}`")

        if not facts:
            return None

        return ContextBlock(
            priority=ContextPriority.TS_CORE,
            title="NPM Scripts",
            body="\n".join(facts),
            sources=["package.json"],
            category="typescript",
        )

    def _extract_tsconfig(self) -> ContextBlock | None:
        """Extract TypeScript compiler configuration."""
        config = self.tsconfig
        if not config:
            return None

        compiler = config.get("compilerOptions", {})
        if not compiler:
            return ContextBlock(
                priority=ContextPriority.TS_CORE,
                title="TypeScript Configuration",
                body="- tsconfig.json present (default settings)",
                sources=["tsconfig.json"],
                category="typescript",
            )

        facts: list[str] = []

        # Strictness
        if compiler.get("strict"):
            facts.append("- strict: true")
        else:
            # Check individual strict flags
            strict_flags = [
                "noImplicitAny",
                "strictNullChecks",
                "strictFunctionTypes",
                "noUncheckedIndexedAccess",
            ]
            enabled_strict = [f for f in strict_flags if compiler.get(f)]
            if enabled_strict:
                facts.append(f"- Strict flags: {', '.join(enabled_strict)}")

        # Module settings
        if compiler.get("module"):
            facts.append(f"- module: {compiler['module']}")
        if compiler.get("moduleResolution"):
            facts.append(f"- moduleResolution: {compiler['moduleResolution']}")
        if compiler.get("target"):
            facts.append(f"- target: {compiler['target']}")

        # Path mappings
        if compiler.get("baseUrl"):
            facts.append(f"- baseUrl: {compiler['baseUrl']}")
        if compiler.get("paths"):
            paths = compiler["paths"]
            facts.append(f"- paths: {len(paths)} aliases")

        # JSX
        if compiler.get("jsx"):
            facts.append(f"- jsx: {compiler['jsx']}")

        # Include/exclude
        include = config.get("include")
        if include:
            if len(include) <= 3:
                facts.append(f"- include: {', '.join(include)}")
            else:
                facts.append(f"- include: {len(include)} patterns")

        if not facts:
            facts.append("- tsconfig.json present")

        return ContextBlock(
            priority=ContextPriority.TS_CORE,
            title="TypeScript Configuration",
            body="\n".join(facts),
            sources=["tsconfig.json"],
            category="typescript",
        )

    def _extract_eslint(self) -> ContextBlock | None:
        """Extract ESLint configuration."""
        # Check for JSON configs first
        config: dict[str, Any] = {}
        source = ""

        for path in [
            ".eslintrc.json",
            ".eslintrc",
        ]:
            full_path = self.worktree / path
            if full_path.exists():
                config = _parse_jsonc(full_path)
                if config:
                    source = path
                    break

        # Check package.json eslintConfig
        if not config:
            config = self.package_json.get("eslintConfig", {})
            if config:
                source = "package.json (eslintConfig)"

        # Check for JS config files (we can't parse them but note their presence)
        js_configs = [
            "eslint.config.js",
            "eslint.config.mjs",
            ".eslintrc.js",
            ".eslintrc.cjs",
        ]
        js_config_found = None
        for js_cfg in js_configs:
            if (self.worktree / js_cfg).exists():
                js_config_found = js_cfg
                break

        if not config and js_config_found:
            return ContextBlock(
                priority=ContextPriority.TS_CORE - 5,
                title="ESLint Configuration",
                body=f"- Config file: {js_config_found} (JS config, details not parsed)",
                sources=[js_config_found],
                category="typescript",
            )

        if not config:
            return None

        facts: list[str] = []

        # Extends
        extends = config.get("extends", [])
        if isinstance(extends, str):
            extends = [extends]
        if extends:
            if len(extends) <= 4:
                facts.append(f"- extends: {', '.join(extends)}")
            else:
                facts.append(f"- extends: {', '.join(extends[:2])}... ({len(extends)} configs)")

        # Parser
        parser = config.get("parser")
        if parser:
            facts.append(f"- parser: {parser}")

        # Key plugins
        plugins = config.get("plugins", [])
        if plugins:
            facts.append(f"- plugins: {', '.join(plugins[:5])}")

        if not facts:
            facts.append("- ESLint enabled")

        return ContextBlock(
            priority=ContextPriority.TS_CORE,
            title="ESLint Configuration",
            body="\n".join(facts),
            sources=[source] if source else [],
            category="typescript",
        )

    def _extract_prettier(self) -> ContextBlock | None:
        """Extract Prettier configuration."""
        config: dict[str, Any] = {}
        source = ""

        for path in [
            ".prettierrc.json",
            ".prettierrc",
            "prettier.config.json",
        ]:
            full_path = self.worktree / path
            if full_path.exists():
                config = _parse_jsonc(full_path)
                if config:
                    source = path
                    break

        # Check package.json prettier key
        if not config:
            config = self.package_json.get("prettier", {})
            if config:
                source = "package.json (prettier)"

        # Check for JS config
        js_configs = ["prettier.config.js", "prettier.config.mjs", ".prettierrc.js"]
        js_config_found = None
        for js_cfg in js_configs:
            if (self.worktree / js_cfg).exists():
                js_config_found = js_cfg
                break

        if not config and js_config_found:
            return ContextBlock(
                priority=ContextPriority.FORMATTER,
                title="Prettier Configuration",
                body=f"- Config file: {js_config_found} (JS config)",
                sources=[js_config_found],
                category="typescript",
            )

        if not config:
            return None

        facts: list[str] = []

        # Key settings
        if "printWidth" in config:
            facts.append(f"- printWidth: {config['printWidth']}")
        if "tabWidth" in config:
            facts.append(f"- tabWidth: {config['tabWidth']}")
        if "semi" in config:
            facts.append(f"- semi: {config['semi']}")
        if "singleQuote" in config:
            facts.append(f"- singleQuote: {config['singleQuote']}")
        if "trailingComma" in config:
            facts.append(f"- trailingComma: {config['trailingComma']}")

        if not facts:
            facts.append("- Prettier enabled")

        return ContextBlock(
            priority=ContextPriority.FORMATTER,
            title="Prettier Configuration",
            body="\n".join(facts),
            sources=[source] if source else [],
            category="typescript",
        )
