"""CLI interface for orx orchestrator."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated

import structlog
import typer

from orx import __version__
from orx.config import EngineType, OrxConfig
from orx.paths import RunPaths
from orx.runner import create_runner
from orx.state import StateManager

# Configure structlog for CLI output
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

app = typer.Typer(
    name="orx",
    help="Local CLI Agent Orchestrator for Codex and Gemini",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"orx version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """orx - Local CLI Agent Orchestrator."""
    pass


@app.command()
def run(
    task: Annotated[
        str,
        typer.Argument(help="Task description or path to task file (prefix with @)"),
    ],
    base_dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            "-d",
            help="Base directory for the project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = Path.cwd(),
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to orx.yaml config file",
            exists=True,
            file_okay=True,
            resolve_path=True,
        ),
    ] = None,
    engine: Annotated[
        EngineType | None,
        typer.Option(
            "--engine",
            "-e",
            help="Engine to use (codex, gemini, fake)",
        ),
    ] = None,
    base_branch: Annotated[
        str | None,
        typer.Option(
            "--base-branch",
            "-b",
            help="Base branch to create worktree from",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Don't execute commands, just log them",
        ),
    ] = False,
) -> None:
    """Run a new orchestration task.

    The task can be provided as a string or as a path to a file
    (prefix with @ to read from file, e.g., @task.md).
    """
    log = logger.bind(command="run")
    log.info("Starting orx run")

    # Parse task
    if task.startswith("@"):
        task_path = Path(task[1:])
        if not task_path.exists():
            typer.echo(f"Error: Task file not found: {task_path}", err=True)
            raise typer.Exit(1)
        task_content: str | Path = task_path
    else:
        task_content = task

    # Check for config file
    config_path = config
    if config_path is None:
        default_config = base_dir / "orx.yaml"
        if default_config.exists():
            config_path = default_config

    try:
        runner = create_runner(
            base_dir,
            config_path=config_path,
            engine=engine,
            base_branch=base_branch,
            dry_run=dry_run,
        )

        typer.echo(f"Run ID: {runner.paths.run_id}")
        typer.echo(f"Engine: {runner.config.engine.type.value}")
        typer.echo(f"Base branch: {runner.config.git.base_branch}")
        typer.echo("")

        success = runner.run(task_content)

        if success:
            typer.echo("")
            typer.echo(
                typer.style("Run completed successfully!", fg=typer.colors.GREEN)
            )
            typer.echo(f"Artifacts: {runner.paths.run_dir}")
        else:
            typer.echo("")
            typer.echo(typer.style("Run failed.", fg=typer.colors.RED))
            raise typer.Exit(1)

    except Exception as e:
        log.error("Run failed", error=str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


@app.command()
def resume(
    run_id: Annotated[
        str,
        typer.Argument(help="Run ID to resume"),
    ],
    base_dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            "-d",
            help="Base directory for the project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = Path.cwd(),
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to orx.yaml config file",
            exists=True,
            file_okay=True,
            resolve_path=True,
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Don't execute commands, just log them",
        ),
    ] = False,
) -> None:
    """Resume a previously started run."""
    log = logger.bind(command="resume", run_id=run_id)
    log.info("Resuming orx run")

    # Validate run exists
    try:
        RunPaths.from_existing(base_dir, run_id)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e

    # Check for config file
    config_path = config
    if config_path is None:
        default_config = base_dir / "orx.yaml"
        if default_config.exists():
            config_path = default_config

    try:
        runner = create_runner(
            base_dir,
            config_path=config_path,
            run_id=run_id,
            dry_run=dry_run,
        )

        typer.echo(f"Resuming run: {run_id}")
        typer.echo(f"Current stage: {runner.state.load().current_stage.value}")
        typer.echo("")

        success = runner.resume()

        if success:
            typer.echo("")
            typer.echo(
                typer.style("Run completed successfully!", fg=typer.colors.GREEN)
            )
        else:
            typer.echo("")
            typer.echo(typer.style("Run failed.", fg=typer.colors.RED))
            raise typer.Exit(1)

    except Exception as e:
        log.error("Resume failed", error=str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


@app.command()
def status(
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run ID to check (optional, lists all if omitted)"),
    ] = None,
    base_dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            "-d",
            help="Base directory for the project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = Path.cwd(),
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output as JSON",
        ),
    ] = False,
    follow: Annotated[
        bool,
        typer.Option(
            "--follow",
            "-f",
            help="Follow status updates (requires run_id)",
        ),
    ] = False,
) -> None:
    """Show status of runs."""
    runs_dir = base_dir / "runs"

    if not runs_dir.exists():
        typer.echo("No runs found.")
        return

    if follow and not run_id:
        typer.echo("Error: --follow requires a run_id", err=True)
        raise typer.Exit(1)

    if run_id:
        # Show specific run
        try:
            paths = RunPaths.from_existing(base_dir, run_id)
            state_mgr = StateManager(paths)

            if follow:
                # Follow mode: continuously update status
                import time

                last_stage = None
                last_iteration = None
                try:
                    while True:
                        state = state_mgr.load()

                        # Only print updates when something changes
                        if state.current_stage != last_stage or state.current_iteration != last_iteration:
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            typer.echo(f"[{timestamp}] Stage: {state.current_stage.value}", nl=False)
                            if state.current_item_id:
                                typer.echo(f" | Item: {state.current_item_id} (iteration {state.current_iteration})")
                            else:
                                typer.echo("")

                            last_stage = state.current_stage
                            last_iteration = state.current_iteration

                        # Check if run is complete or failed
                        if state.current_stage.value in ["completed", "failed"]:
                            typer.echo(f"\nRun {state.current_stage.value}!")
                            break

                        time.sleep(3)  # Poll every 3 seconds

                except KeyboardInterrupt:
                    typer.echo("\nStopped following.")
                    return
            else:
                # Normal mode: show status once
                state = state_mgr.load()

                if json_output:
                    typer.echo(json.dumps(state.to_dict(), indent=2))
                else:
                    typer.echo(f"Run ID: {state.run_id}")
                    typer.echo(f"Stage: {state.current_stage.value}")
                    typer.echo(f"Created: {state.created_at}")
                    typer.echo(f"Updated: {state.updated_at}")

                    if state.baseline_sha:
                        typer.echo(f"Baseline SHA: {state.baseline_sha[:8]}")

                    if state.current_item_id:
                        typer.echo(f"Current item: {state.current_item_id}")
                        typer.echo(f"Iteration: {state.current_iteration}")

                    typer.echo("")
                    typer.echo("Stage statuses:")
                    for stage_key, status_obj in state.stage_statuses.items():
                        status_str = status_obj.status
                        if status_obj.status == "completed":
                            status_str = typer.style(status_str, fg=typer.colors.GREEN)
                        elif status_obj.status == "failed":
                            status_str = typer.style(status_str, fg=typer.colors.RED)
                        elif status_obj.status == "running":
                            status_str = typer.style(status_str, fg=typer.colors.YELLOW)
                        typer.echo(f"  {stage_key}: {status_str}")

        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1) from e
    else:
        # List all runs
        run_dirs = sorted(runs_dir.iterdir(), reverse=True)

        if not run_dirs:
            typer.echo("No runs found.")
            return

        runs_info = []
        for run_dir in run_dirs[:10]:  # Show last 10
            if not run_dir.is_dir():
                continue

            rid = run_dir.name
            state_file = run_dir / "state.json"

            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text())
                    stage = data.get("current_stage", "unknown")
                    updated = data.get("updated_at", "")[:19]
                    runs_info.append(
                        {
                            "run_id": rid,
                            "stage": stage,
                            "updated": updated,
                        }
                    )
                except Exception:
                    runs_info.append(
                        {
                            "run_id": rid,
                            "stage": "error",
                            "updated": "",
                        }
                    )
            else:
                runs_info.append(
                    {
                        "run_id": rid,
                        "stage": "no state",
                        "updated": "",
                    }
                )

        if json_output:
            typer.echo(json.dumps(runs_info, indent=2))
        else:
            typer.echo("Recent runs:")
            typer.echo("")
            for info in runs_info:
                stage = info["stage"]
                if stage == "done":
                    stage = typer.style(stage, fg=typer.colors.GREEN)
                elif stage == "failed":
                    stage = typer.style(stage, fg=typer.colors.RED)
                typer.echo(f"  {info['run_id']}  {stage:20s}  {info['updated']}")


@app.command()
def init(
    base_dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            "-d",
            help="Directory to initialize",
            resolve_path=True,
        ),
    ] = Path.cwd(),
    engine: Annotated[
        EngineType,
        typer.Option(
            "--engine",
            "-e",
            help="Default engine to use",
        ),
    ] = EngineType.CODEX,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite existing config",
        ),
    ] = False,
) -> None:
    """Initialize orx configuration in a directory."""
    config_path = base_dir / "orx.yaml"

    if config_path.exists() and not force:
        typer.echo(f"Config already exists: {config_path}")
        typer.echo("Use --force to overwrite.")
        raise typer.Exit(1)

    config = OrxConfig.default(engine)
    config.save(config_path)

    typer.echo(f"Created config: {config_path}")
    typer.echo(f"Engine: {engine.value}")
    typer.echo("")
    typer.echo("Edit orx.yaml to customize settings.")


@app.command()
def clean(
    run_id: Annotated[
        str | None,
        typer.Argument(help="Run ID to clean (or 'all' for all runs)"),
    ] = None,
    base_dir: Annotated[
        Path,
        typer.Option(
            "--dir",
            "-d",
            help="Base directory for the project",
            exists=True,
            file_okay=False,
            resolve_path=True,
        ),
    ] = Path.cwd(),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Don't prompt for confirmation",
        ),
    ] = False,
) -> None:
    """Clean up run artifacts and worktrees."""
    import shutil

    runs_dir = base_dir / "runs"
    worktrees_dir = base_dir / ".worktrees"

    if run_id == "all":
        if not force:
            confirm = typer.confirm("Delete ALL runs and worktrees?")
            if not confirm:
                raise typer.Abort()

        if runs_dir.exists():
            shutil.rmtree(runs_dir)
            typer.echo(f"Removed: {runs_dir}")

        if worktrees_dir.exists():
            shutil.rmtree(worktrees_dir)
            typer.echo(f"Removed: {worktrees_dir}")

        typer.echo("Cleaned all runs.")

    elif run_id:
        run_dir = runs_dir / run_id
        worktree_dir = worktrees_dir / run_id

        if not run_dir.exists():
            typer.echo(f"Run not found: {run_id}")
            raise typer.Exit(1)

        if not force:
            confirm = typer.confirm(f"Delete run {run_id}?")
            if not confirm:
                raise typer.Abort()

        if run_dir.exists():
            shutil.rmtree(run_dir)
            typer.echo(f"Removed: {run_dir}")

        if worktree_dir.exists():
            shutil.rmtree(worktree_dir)
            typer.echo(f"Removed: {worktree_dir}")

        typer.echo(f"Cleaned run: {run_id}")

    else:
        typer.echo("Specify a run ID or 'all' to clean.")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
