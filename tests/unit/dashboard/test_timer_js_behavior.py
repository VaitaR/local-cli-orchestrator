from __future__ import annotations

import subprocess
from pathlib import Path


def test_timer_does_not_tick_for_completed_runs() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    timer_js = repo_root / "src/orx/dashboard/static/js/timer.js"

    script = r"""
import { pathToFileURL } from 'url';

const timerPath = process.argv.at(-1);
if (!timerPath) {
  throw new Error(`missing timer path argv: ${JSON.stringify(process.argv)}`);
}
const { default: RunTimer } = await import(pathToFileURL(timerPath).href);

const completed = {
  _attrs: {
    'data-started-at': '2025-01-15T10:00:00Z',
    'data-run-status': 'success',
  },
  textContent: '30m 45s',
  getAttribute(name) { return this._attrs[name] ?? null; },
};

RunTimer.trackElement(completed);
if (completed.textContent !== '30m 45s') {
  throw new Error(`completed timer changed: ${completed.textContent}`);
}

const now = new Date();
const startedAt = new Date(now.getTime() - 65_000).toISOString();
const running = {
  _attrs: {
    'data-started-at': startedAt,
    'data-run-status': 'running',
  },
  textContent: '',
  getAttribute(name) { return this._attrs[name] ?? null; },
};

RunTimer.trackElement(running);
if (!running.textContent || running.textContent === '-') {
  throw new Error('running timer not updated');
}
"""

    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(timer_js)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
