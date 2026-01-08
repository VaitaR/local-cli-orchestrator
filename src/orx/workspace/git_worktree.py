"""Git worktree management for isolated workspaces."""

from __future__ import annotations

from pathlib import Path

import structlog

from orx.exceptions import WorkspaceError
from orx.infra.command import CommandRunner
from orx.paths import RunPaths

logger = structlog.get_logger()


class WorkspaceGitWorktree:
    """Manages a git worktree for isolated run execution.

    Each run gets its own worktree, allowing changes to be made in
    isolation from the main working directory.

    Example:
        >>> workspace = WorkspaceGitWorktree(paths, CommandRunner())
        >>> workspace.create("main")
        >>> workspace.baseline_sha()
        'abc123...'
    """

    def __init__(
        self,
        paths: RunPaths,
        cmd: CommandRunner,
        repo_root: Path | None = None,
    ) -> None:
        """Initialize the workspace manager.

        Args:
            paths: RunPaths for this run.
            cmd: CommandRunner instance.
            repo_root: Root of the git repository (defaults to paths.base_dir).
        """
        self.paths = paths
        self.cmd = cmd
        self.repo_root = repo_root or paths.base_dir
        self._baseline_sha: str | None = None

    @property
    def worktree_path(self) -> Path:
        """Path to the worktree directory."""
        return self.paths.worktree_path

    def create(self, base_branch: str) -> Path:
        """Create a new worktree from the base branch.

        Args:
            base_branch: The branch to create the worktree from.

        Returns:
            Path to the created worktree.

        Raises:
            WorkspaceError: If worktree creation fails.
        """
        log = logger.bind(base_branch=base_branch, worktree=str(self.worktree_path))
        log.info("Creating git worktree")

        # Ensure parent directory exists
        self.paths.worktrees_dir.mkdir(parents=True, exist_ok=True)

        # Check if worktree already exists
        if self.worktree_path.exists():
            log.warning("Worktree already exists, removing")
            self.remove()

        # Get the current SHA before creating worktree
        returncode, stdout, stderr = self.cmd.run_git(
            ["rev-parse", base_branch],
            cwd=self.repo_root,
            check=False,
        )
        if returncode != 0:
            msg = f"Failed to resolve base branch '{base_branch}': {stderr}"
            raise WorkspaceError(msg, operation="create", path=self.worktree_path)

        self._baseline_sha = stdout.strip()

        # Create the worktree
        # Use a detached HEAD to avoid branch conflicts
        returncode, stdout, stderr = self.cmd.run_git(
            ["worktree", "add", "--detach", str(self.worktree_path), base_branch],
            cwd=self.repo_root,
            check=False,
        )

        if returncode != 0:
            msg = f"Failed to create worktree: {stderr}"
            raise WorkspaceError(msg, operation="create", path=self.worktree_path)

        log.info("Worktree created", baseline_sha=self._baseline_sha)
        return self.worktree_path

    def baseline_sha(self) -> str:
        """Get the baseline SHA for this worktree.

        Returns:
            The SHA of the commit the worktree was created from.

        Raises:
            WorkspaceError: If baseline SHA is not available.
        """
        if self._baseline_sha:
            return self._baseline_sha

        # Try to get it from HEAD
        if not self.worktree_path.exists():
            msg = "Worktree does not exist"
            raise WorkspaceError(msg, operation="baseline_sha", path=self.worktree_path)

        returncode, stdout, stderr = self.cmd.run_git(
            ["rev-parse", "HEAD"],
            cwd=self.worktree_path,
            check=False,
        )

        if returncode != 0:
            msg = f"Failed to get baseline SHA: {stderr}"
            raise WorkspaceError(msg, operation="baseline_sha", path=self.worktree_path)

        self._baseline_sha = stdout.strip()
        return self._baseline_sha

    def get_branch_for_sha(self, sha: str) -> list[str]:
        """Get branches that contain a given SHA.

        Args:
            sha: The commit SHA to check.

        Returns:
            List of branch names that contain this SHA.

        Raises:
            WorkspaceError: If git command fails.
        """
        returncode, stdout, stderr = self.cmd.run_git(
            ["branch", "-r", "--contains", sha],
            cwd=self.repo_root,
            check=False,
        )

        if returncode != 0:
            msg = f"Failed to get branches for SHA {sha}: {stderr}"
            raise WorkspaceError(
                msg, operation="get_branch_for_sha", path=self.repo_root
            )

        # Parse branch names (strip "origin/" prefix and whitespace)
        branches = []
        for line in stdout.strip().split("\n"):
            if line:
                branch = line.strip()
                if branch.startswith("origin/"):
                    branch = branch[7:]  # Remove "origin/" prefix
                branches.append(branch)

        return branches

    def validate_base_branch(self, expected_base_branch: str) -> bool:
        """Validate that the worktree was created from the expected base branch.

        Args:
            expected_base_branch: The branch that should be the base.

        Returns:
            True if validation passes.

        Raises:
            WorkspaceError: If validation fails.
        """
        baseline = self.baseline_sha()
        branches = self.get_branch_for_sha(baseline)

        log = logger.bind(
            baseline_sha=baseline[:8],
            expected_branch=expected_base_branch,
            actual_branches=branches,
        )

        if expected_base_branch not in branches:
            log.warning("Base branch validation failed")
            msg = (
                f"Worktree baseline SHA {baseline[:8]} is not from expected branch "
                f"'{expected_base_branch}'. Found in branches: {', '.join(branches)}"
            )
            raise WorkspaceError(
                msg,
                operation="validate_base_branch",
                path=self.worktree_path,
            )

        log.info("Base branch validation passed")
        return True

    def reset(self, sha: str | None = None) -> None:
        """Reset the worktree to a specific SHA.

        Args:
            sha: The SHA to reset to (defaults to baseline).

        Raises:
            WorkspaceError: If reset fails.
        """
        target_sha = sha or self._baseline_sha
        if not target_sha:
            msg = "No SHA specified and no baseline available"
            raise WorkspaceError(msg, operation="reset", path=self.worktree_path)

        log = logger.bind(sha=target_sha)
        log.info("Resetting worktree")

        returncode, _, stderr = self.cmd.run_git(
            ["reset", "--hard", target_sha],
            cwd=self.worktree_path,
            check=False,
        )

        if returncode != 0:
            msg = f"Failed to reset worktree: {stderr}"
            raise WorkspaceError(msg, operation="reset", path=self.worktree_path)

        # Clean untracked files
        self.cmd.run_git(["clean", "-fd"], cwd=self.worktree_path, check=False)

        log.info("Worktree reset complete")

    def diff_to(
        self, out_path: Path, *, exclude_patterns: list[str] | None = None
    ) -> None:
        """Write the diff to a file.

        Includes both modified tracked files and new untracked files.

        Args:
            out_path: Path to write the diff to.
            exclude_patterns: Optional list of file patterns to exclude from diff
                             (e.g., ["pr_body.md", "review.md"]).

        Raises:
            WorkspaceError: If diff fails.
        """
        log = logger.bind(out_path=str(out_path))
        log.info("Capturing diff", exclude_patterns=exclude_patterns)

        # Ensure the output directory exists
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Stage all changes first so new files are included
        self.cmd.run_git(["add", "-A"], cwd=self.worktree_path, check=False)

        # Build diff command with exclusions
        diff_cmd = ["git", "diff", "--cached", "--patch", "--no-color"]

        # Add exclusions using git pathspec syntax
        if exclude_patterns:
            diff_cmd.append("--")
            for pattern in exclude_patterns:
                diff_cmd.append(f":(exclude){pattern}")

        # Run git diff against HEAD with patch format (shows staged changes)
        result = self.cmd.run(
            diff_cmd,
            cwd=self.worktree_path,
            stdout_path=out_path,
        )

        # Unstage changes (keep working tree intact)
        self.cmd.run_git(
            ["reset", "--mixed", "HEAD"], cwd=self.worktree_path, check=False
        )

        if result.returncode != 0:
            msg = "Failed to capture diff"
            raise WorkspaceError(msg, operation="diff_to", path=self.worktree_path)

        log.info("Diff captured")

    def diff_empty(self) -> bool:
        """Check if there are no changes in the worktree.

        Returns:
            True if there are no changes (diff is empty).
        """
        returncode, stdout, _ = self.cmd.run_git(
            ["diff", "--stat"],
            cwd=self.worktree_path,
            check=False,
        )

        # Also check for untracked files
        _, untracked, _ = self.cmd.run_git(
            ["status", "--porcelain"],
            cwd=self.worktree_path,
            check=False,
        )

        return returncode == 0 and not stdout.strip() and not untracked.strip()

    def get_changed_files(self) -> list[str]:
        """Get a list of changed files.

        Returns:
            List of file paths that have been modified.
        """
        files: list[str] = []

        # Get modified files
        _, stdout, _ = self.cmd.run_git(
            ["diff", "--name-only"],
            cwd=self.worktree_path,
            check=False,
        )
        files.extend(line for line in stdout.strip().split("\n") if line)

        # Get untracked files
        _, stdout, _ = self.cmd.run_git(
            ["status", "--porcelain"],
            cwd=self.worktree_path,
            check=False,
        )
        for line in stdout.strip().split("\n"):
            if line.startswith("??"):
                files.append(line[3:].strip())

        return files

    def commit_all(self, message: str) -> str:
        """Stage all changes and commit.

        Args:
            message: Commit message.

        Returns:
            The commit SHA.

        Raises:
            WorkspaceError: If commit fails.
        """
        log = logger.bind(message=message[:50])
        log.info("Committing changes")

        # Stage all changes
        self.cmd.run_git(["add", "-A"], cwd=self.worktree_path, check=True)

        # Check if there's anything to commit
        returncode, stdout, _ = self.cmd.run_git(
            ["status", "--porcelain"],
            cwd=self.worktree_path,
            check=False,
        )

        if not stdout.strip():
            log.warning("Nothing to commit")
            return self.baseline_sha()

        # Commit
        returncode, _, stderr = self.cmd.run_git(
            ["commit", "-m", message],
            cwd=self.worktree_path,
            check=False,
        )

        if returncode != 0:
            msg = f"Failed to commit: {stderr}"
            raise WorkspaceError(msg, operation="commit", path=self.worktree_path)

        # Get the new SHA
        _, sha, _ = self.cmd.run_git(
            ["rev-parse", "HEAD"],
            cwd=self.worktree_path,
            check=True,
        )

        log.info("Changes committed", sha=sha.strip()[:8])
        return sha.strip()

    def push(self, remote: str, branch: str) -> None:
        """Push to remote.

        Args:
            remote: Remote name (e.g., 'origin').
            branch: Branch name to push to.

        Raises:
            WorkspaceError: If push fails.
        """
        log = logger.bind(remote=remote, branch=branch)
        log.info("Pushing to remote")

        # Push with force to handle rebases
        returncode, _, stderr = self.cmd.run_git(
            ["push", "--force", remote, f"HEAD:{branch}"],
            cwd=self.worktree_path,
            check=False,
        )

        if returncode != 0:
            msg = f"Failed to push: {stderr}"
            raise WorkspaceError(msg, operation="push", path=self.worktree_path)

        log.info("Push complete")

    def remove(self) -> None:
        """Remove the worktree.

        Raises:
            WorkspaceError: If removal fails.
        """
        log = logger.bind(worktree=str(self.worktree_path))
        log.info("Removing worktree")

        if not self.worktree_path.exists():
            log.debug("Worktree does not exist, nothing to remove")
            return

        # Use git worktree remove
        returncode, _, stderr = self.cmd.run_git(
            ["worktree", "remove", "--force", str(self.worktree_path)],
            cwd=self.repo_root,
            check=False,
        )

        if returncode != 0:
            # Try manual removal as fallback
            log.warning("Git worktree remove failed, trying manual removal")
            import shutil

            try:
                shutil.rmtree(self.worktree_path)
            except OSError as e:
                msg = f"Failed to remove worktree: {e}"
                raise WorkspaceError(
                    msg, operation="remove", path=self.worktree_path
                ) from e

        log.info("Worktree removed")

    def exists(self) -> bool:
        """Check if the worktree exists."""
        return self.worktree_path.exists()
