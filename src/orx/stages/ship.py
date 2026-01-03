"""Ship stage implementation."""

from __future__ import annotations

import structlog

from orx.infra.command import CommandRunner
from orx.stages.base import BaseStage, StageContext, StageResult

logger = structlog.get_logger()


class ShipStage(BaseStage):
    """Stage that commits, pushes, and optionally creates a PR.

    Handles the final delivery of the implementation.
    """

    @property
    def name(self) -> str:
        """Name of the stage."""
        return "ship"

    def execute(self, ctx: StageContext) -> StageResult:
        """Execute the ship stage.

        Args:
            ctx: Stage context.

        Returns:
            StageResult indicating success/failure.
        """
        log = logger.bind(stage=self.name)
        log.info("Executing ship stage")

        git_config = ctx.config.get("git", {})
        auto_commit = git_config.get("auto_commit", True)
        auto_push = git_config.get("auto_push", False)
        create_pr = git_config.get("create_pr", False)
        pr_draft = git_config.get("pr_draft", True)
        remote = git_config.get("remote", "origin")
        base_branch = git_config.get("base_branch", "main")

        results: dict[str, str] = {}

        # Capture final diff (exclude artifact files that shouldn't be in the patch)
        log.info("Capturing final diff")
        exclude_artifacts = [
            "pr_body.md",
            "review.md",
            "*.orx.md",  # Any orx-specific temporary files
            ".orx-*",    # Any orx-specific temporary files
        ]
        ctx.workspace.diff_to(ctx.paths.patch_diff, exclude_patterns=exclude_artifacts)

        if ctx.workspace.diff_empty():
            log.warning("No changes to ship")
            return self._success("No changes to ship", data={"shipped": False})

        # Commit changes
        if auto_commit:
            log.info("Committing changes")
            task = ctx.pack.read_task() or "Implementation changes"
            commit_msg = f"feat: {task[:50]}"
            try:
                sha = ctx.workspace.commit_all(commit_msg)
                results["commit_sha"] = sha
                log.info("Changes committed", sha=sha[:8])
            except Exception as e:
                log.error("Commit failed", error=str(e))
                return self._failure(f"Commit failed: {e}")

        # Push changes
        if auto_push:
            log.info("Pushing changes")
            branch_name = f"orx/{ctx.paths.run_id}"
            try:
                ctx.workspace.push(remote, branch_name)
                results["branch"] = branch_name
                log.info("Changes pushed", branch=branch_name)
            except Exception as e:
                log.error("Push failed", error=str(e))
                return self._failure(f"Push failed: {e}")

        # Create PR
        if create_pr and auto_push:
            log.info("Creating PR")
            try:
                pr_url = self._create_pr(
                    ctx,
                    base_branch=base_branch,
                    head_branch=results.get("branch", ""),
                    draft=pr_draft,
                )
                if pr_url:
                    results["pr_url"] = pr_url
                    log.info("PR created", url=pr_url)
            except Exception as e:
                log.error("PR creation failed", error=str(e))
                # Don't fail the stage for PR creation failure
                results["pr_error"] = str(e)

        log.info("Ship stage completed", results=results)
        return self._success(
            "Changes shipped successfully",
            data={"shipped": True, **results},
        )

    def _create_pr(
        self,
        ctx: StageContext,
        base_branch: str,
        head_branch: str,
        draft: bool = True,
    ) -> str | None:
        """Create a pull request using gh CLI.

        Args:
            ctx: Stage context.
            base_branch: Base branch for the PR.
            head_branch: Head branch with changes.
            draft: Whether to create as draft.

        Returns:
            PR URL if created, None otherwise.
        """
        log = logger.bind(base=base_branch, head=head_branch)

        # Read PR body
        pr_body = ctx.pack.read_pr_body() or "Implementation changes"
        task = ctx.pack.read_task() or "Implementation"

        # Build gh command
        cmd_runner = CommandRunner()
        command = [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            head_branch,
            "--title",
            f"feat: {task[:50]}",
            "--body",
            pr_body,
        ]

        if draft:
            command.append("--draft")

        # Run gh pr create
        log_path = ctx.paths.log_path("gh_pr_create")
        result = cmd_runner.run(
            command,
            cwd=ctx.workspace.worktree_path,
            stdout_path=log_path,
            stderr_path=log_path.with_suffix(".stderr.log"),
        )

        if result.returncode != 0:
            log.error("gh pr create failed")
            return None

        # Parse PR URL from output
        if log_path.exists():
            output = log_path.read_text().strip()
            if output.startswith("https://"):
                return output

        return None
