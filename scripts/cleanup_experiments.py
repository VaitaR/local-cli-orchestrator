#!/usr/bin/env python3
"""Remove experiment artifacts while preserving metrics directories."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _has_metrics_dir(path: Path) -> bool:
    for candidate in path.rglob("metrics"):
        if candidate.is_dir():
            return True
    return False


def _remove_path(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        print(f"would remove: {path}")
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _prune_dir(root: Path, *, dry_run: bool) -> None:
    for child in root.iterdir():
        if child.name in {".gitignore", "README.md"}:
            continue
        if child.is_dir():
            if child.name == "metrics":
                continue
            if _has_metrics_dir(child):
                _prune_dir(child, dry_run=dry_run)
            else:
                _remove_path(child, dry_run=dry_run)
        else:
            _remove_path(child, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove experiment artifacts while preserving metrics directories."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("experiments"),
        help="Path to experiments directory (default: experiments/).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions. Without this flag, runs in dry-run mode.",
    )
    args = parser.parse_args()

    root = args.path
    if not root.exists():
        print(f"Nothing to clean: {root} does not exist.")
        return 0
    if not root.is_dir():
        print(f"Not a directory: {root}")
        return 1

    _prune_dir(root, dry_run=not args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
