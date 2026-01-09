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

metrics_app = typer.Typer(
    name="metrics",
    help="Metrics aggregation and analysis",
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
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="Model to use (overrides engine default)",
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
            model=model,
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
                        if (
                            state.current_stage != last_stage
                            or state.current_iteration != last_iteration
                        ):
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            typer.echo(
                                f"[{timestamp}] Stage: {state.current_stage.value}",
                                nl=False,
                            )
                            if state.current_item_id:
                                typer.echo(
                                    f" | Item: {state.current_item_id} (iteration {state.current_iteration})"
                                )
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


# ============================================================================
# Metrics subcommands
# ============================================================================


@metrics_app.command("rebuild")
def metrics_rebuild(
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
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output directory for aggregate report",
            file_okay=False,
            resolve_path=True,
        ),
    ] = None,
) -> None:
    """Rebuild aggregate metrics from all runs.

    Scans all run directories and builds a combined metrics report.
    """
    from orx.metrics import MetricsAggregator

    log = logger.bind(command="metrics rebuild")
    log.info("Rebuilding metrics")

    try:
        aggregator = MetricsAggregator(base_dir)
        if output:
            aggregator.output_dir = output

        count = aggregator.scan_runs()
        if count == 0:
            typer.echo("No runs with metrics found.")
            return

        report = aggregator.build_report()
        report_path = aggregator.save_report(report)

        typer.echo(f"Scanned {count} runs")
        typer.echo(f"Report saved to: {report_path}")

    except Exception as e:
        log.error("Rebuild failed", error=str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


@metrics_app.command("report")
def metrics_report(
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
            help="Output as JSON instead of human-readable format",
        ),
    ] = False,
) -> None:
    """Generate and display a metrics summary report.

    Shows aggregated statistics across all runs including:
    - Success rates
    - Duration breakdowns
    - Stage performance
    - Gate pass rates
    - Top failure reasons
    """
    from orx.metrics import MetricsAggregator

    log = logger.bind(command="metrics report")

    try:
        aggregator = MetricsAggregator(base_dir)
        count = aggregator.scan_runs()

        if count == 0:
            typer.echo("No runs with metrics found.")
            return

        report = aggregator.build_report()

        if json_output:
            typer.echo(json.dumps(report.to_dict(), indent=2))
        else:
            summary = aggregator.generate_summary_report()
            typer.echo(summary)

    except Exception as e:
        log.error("Report failed", error=str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


@metrics_app.command("show")
def metrics_show(
    run_id: Annotated[
        str,
        typer.Argument(help="Run ID to show metrics for"),
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
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output as JSON",
        ),
    ] = False,
    stages: Annotated[
        bool,
        typer.Option(
            "--stages",
            "-s",
            help="Show per-stage metrics",
        ),
    ] = False,
) -> None:
    """Show metrics for a specific run.

    Displays run-level metrics or detailed per-stage metrics.
    """
    from orx.metrics.writer import MetricsWriter

    log = logger.bind(command="metrics show", run_id=run_id)

    try:
        paths = RunPaths.from_existing(base_dir, run_id)
        writer = MetricsWriter(paths)

        if stages:
            # Show per-stage metrics
            stage_metrics = writer.read_stages()

            if not stage_metrics:
                typer.echo(f"No stage metrics found for run: {run_id}")
                return

            if json_output:
                typer.echo(json.dumps([m.to_dict() for m in stage_metrics], indent=2))
            else:
                typer.echo(f"Stage metrics for run: {run_id}")
                typer.echo("-" * 50)
                for m in stage_metrics:
                    status_color = (
                        typer.colors.GREEN
                        if m.status.value == "success"
                        else typer.colors.RED
                    )
                    status_str = typer.style(m.status.value, fg=status_color)
                    typer.echo(
                        f"{m.stage:15} | {status_str:10} | "
                        f"{m.duration_ms:>6}ms | "
                        f"attempt {m.attempt}"
                    )
                    if m.gates:
                        for g in m.gates:
                            gate_status = "✓" if g.passed else "✗"
                            typer.echo(f"    {gate_status} {g.name}: {g.duration_ms}ms")
        else:
            # Show run-level metrics
            run_metrics = writer.read_run()

            if run_metrics is None:
                typer.echo(f"No run metrics found for: {run_id}")
                return

            if json_output:
                typer.echo(json.dumps(run_metrics.to_dict(), indent=2))
            else:
                typer.echo(f"Run metrics: {run_id}")
                typer.echo("=" * 50)
                typer.echo(f"Status: {run_metrics.final_status.value}")
                typer.echo(f"Total Duration: {run_metrics.total_duration_ms}ms")
                typer.echo(f"Total Stages: {run_metrics.stages_total}")
                typer.echo(f"Fix Attempts: {run_metrics.fix_attempts_total}")
                typer.echo(f"Gates Passed: {run_metrics.gates_passed}")
                typer.echo(f"Gates Failed: {run_metrics.gates_failed}")

                if run_metrics.stage_breakdown:
                    typer.echo("")
                    typer.echo("Time breakdown by stage:")
                    for stage, duration in run_metrics.stage_breakdown.items():
                        pct = (
                            duration / run_metrics.total_duration_ms * 100
                            if run_metrics.total_duration_ms
                            else 0
                        )
                        bar = "█" * int(pct / 5)
                        typer.echo(f"  {stage:15} {duration:>6}ms ({pct:>5.1f}%) {bar}")

    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e
    except Exception as e:
        log.error("Show failed", error=str(e))
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


# Register metrics sub-app
app.add_typer(metrics_app, name="metrics")


if __name__ == "__main__":
    app()
