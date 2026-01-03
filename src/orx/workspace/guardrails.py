"""Guardrails for detecting forbidden file modifications."""

from __future__ import annotations

import fnmatch
from pathlib import Path

import structlog

from orx.config import GuardrailConfig
from orx.exceptions import GuardrailError

logger = structlog.get_logger()


class Guardrails:
    """Checks for forbidden file modifications.

    Guardrails prevent agents from modifying sensitive files like
    .env, secrets, or .git contents.

    Example:
        >>> config = GuardrailConfig()
        >>> guardrails = Guardrails(config)
        >>> guardrails.check_files([".env", "src/app.py"])
        Traceback (most recent call last):
            ...
        orx.exceptions.GuardrailError: ...
    """

    def __init__(self, config: GuardrailConfig) -> None:
        """Initialize guardrails.

        Args:
            config: Guardrail configuration.
        """
        self.config = config
        self.enabled = config.enabled

    def check_files(self, changed_files: list[str]) -> None:
        """Check if any changed files violate guardrails.

        Args:
            changed_files: List of file paths that were modified.

        Raises:
            GuardrailError: If any file violates guardrails.
        """
        if not self.enabled:
            logger.debug("Guardrails disabled")
            return

        log = logger.bind(file_count=len(changed_files))
        log.debug("Checking guardrails")

        violations: list[str] = []

        # Use is_file_allowed which handles both allowlist and blacklist modes
        for file_path in changed_files:
            if not self.is_file_allowed(file_path):
                violations.append(file_path)
                log.warning(
                    "Guardrail violation: file not allowed",
                    file=file_path,
                    mode=self.config.mode,
                )

        # Check total file count
        if len(changed_files) > self.config.max_files_changed:
            msg = (
                f"Too many files changed: {len(changed_files)} "
                f"(max: {self.config.max_files_changed})"
            )
            raise GuardrailError(
                msg,
                violated_files=changed_files,
                rule="max_files_changed",
            )

        if violations:
            if self.config.mode == "allowlist":
                msg = f"Files not in allowlist: {', '.join(violations)}"
            else:
                msg = f"Forbidden files modified: {', '.join(violations)}"
            raise GuardrailError(
                msg,
                violated_files=violations,
                rule="forbidden_files",
            )

        log.debug("Guardrails passed")

    def _matches_pattern(self, file_path: str, pattern: str) -> bool:
        """Check if a file path matches a glob pattern.

        Supports patterns like:
        - src/**/*.py (matches any .py file under src/ or src/subdir/)
        - *.env (matches any .env file)
        - src/app.py (exact match)

        Args:
            file_path: The file path to check.
            pattern: The glob pattern.

        Returns:
            True if the path matches the pattern.
        """
        import re

        # Normalize path separators
        normalized_path = file_path.replace("\\", "/")
        normalized_pattern = pattern.replace("\\", "/")

        # For patterns with **, convert to regex for proper matching
        if "**" in normalized_pattern:
            # Convert glob pattern to regex
            # src/**/*.py -> src/(.*/)?[^/]*\.py
            regex_pattern = normalized_pattern.replace(".", r"\.")  # Escape dots
            regex_pattern = regex_pattern.replace("**/", "(.*/)?")  # ** matches 0+ dirs
            regex_pattern = regex_pattern.replace("/**", "(/.*)?")  # ** at end
            regex_pattern = regex_pattern.replace("*", "[^/]*")  # * matches within segment
            regex_pattern = f"^{regex_pattern}$"

            if re.match(regex_pattern, normalized_path):
                return True

        # Check direct match (for patterns without **)
        if fnmatch.fnmatch(normalized_path, normalized_pattern):
            return True

        # Check basename match
        basename = Path(file_path).name
        if fnmatch.fnmatch(basename, normalized_pattern):
            return True

        # Check if any path component matches
        parts = normalized_path.split("/")
        return any(fnmatch.fnmatch(part, normalized_pattern) for part in parts)

    def is_file_allowed(self, file_path: str) -> bool:
        """Check if a file is allowed to be modified.

        Args:
            file_path: The file path to check.

        Returns:
            True if the file is allowed.
        """
        if not self.enabled:
            return True

        # Allowlist mode: only files matching allowed_patterns are permitted
        if self.config.mode == "allowlist":
            if not self.config.allowed_patterns:
                # Empty allowlist means nothing is allowed
                return False
            # File must match at least one allowed pattern
            for pattern in self.config.allowed_patterns:
                if self._matches_pattern(file_path, pattern):
                    return True
            return False

        # Blacklist mode (default): check forbidden patterns and paths
        # Check forbidden patterns
        for pattern in self.config.forbidden_patterns:
            if self._matches_pattern(file_path, pattern):
                return False

        # Check forbidden paths
        return file_path not in self.config.forbidden_paths

    def filter_allowed_files(self, files: list[str]) -> list[str]:
        """Filter a list of files to only allowed ones.

        Args:
            files: List of file paths.

        Returns:
            List of allowed file paths.
        """
        if not self.enabled:
            return files

        return [f for f in files if self.is_file_allowed(f)]

    def get_violations(self, changed_files: list[str]) -> list[str]:
        """Get list of files that violate guardrails.

        Args:
            changed_files: List of file paths that were modified.

        Returns:
            List of violating file paths.
        """
        if not self.enabled:
            return []

        violations: list[str] = []
        for file_path in changed_files:
            if not self.is_file_allowed(file_path):
                violations.append(file_path)
        return violations

    def check_new_files(self, new_files: list[str], worktree_root: Path) -> None:
        """Check if any new files violate forbidden_new_files rules.

        This is typically used to prevent artifact files (like pr_body.md)
        from being created in the worktree root.

        Args:
            new_files: List of newly created file paths.
            worktree_root: The root path of the worktree.

        Raises:
            GuardrailError: If any new file violates the rules.
        """
        if not self.enabled:
            logger.debug("Guardrails disabled")
            return

        log = logger.bind(new_file_count=len(new_files))
        log.debug("Checking new files against forbidden_new_files")

        violations: list[str] = []

        for file_path in new_files:
            # Convert to relative path from worktree root
            try:
                rel_path = Path(file_path).relative_to(worktree_root)
            except ValueError:
                # If path is not relative to worktree, use as-is
                rel_path = Path(file_path)

            rel_path_str = str(rel_path)

            # Check against forbidden_new_files patterns
            for pattern in self.config.forbidden_new_files:
                if self._matches_pattern(rel_path_str, pattern):
                    violations.append(rel_path_str)
                    log.warning(
                        "Guardrail violation: forbidden new file",
                        file=rel_path_str,
                        pattern=pattern,
                    )
                    break

        if violations:
            msg = (
                f"Forbidden new files created: {', '.join(violations)}. "
                "These files should be written to the artifacts directory, not the worktree."
            )
            raise GuardrailError(
                msg,
                violated_files=violations,
                rule="forbidden_new_files",
            )

        log.debug("New files check passed")
