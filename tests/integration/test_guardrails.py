"""Integration test: Guardrails.

Scenario F from design doc:
- Executor tries to modify .env or secrets.txt
- Orchestrator must fail the item before commit
- Run fails with explicit guardrail error, evidence includes file list
"""

from pathlib import Path

import pytest

from orx.config import EngineType, GuardrailConfig, OrxConfig
from orx.exceptions import GuardrailError
from orx.executors.fake import FakeAction, FakeExecutor, FakeScenario
from orx.runner import Runner
from orx.workspace.guardrails import Guardrails


class TestGuardrails:
    """Tests for the Guardrails class."""

    def test_check_forbidden_pattern(self) -> None:
        """Test that forbidden patterns are detected."""
        config = GuardrailConfig()
        guardrails = Guardrails(config)

        with pytest.raises(GuardrailError) as exc_info:
            guardrails.check_files([".env"])

        assert ".env" in str(exc_info.value)
        assert ".env" in exc_info.value.violated_files

    def test_check_forbidden_path(self) -> None:
        """Test that forbidden paths are detected."""
        config = GuardrailConfig()
        guardrails = Guardrails(config)

        with pytest.raises(GuardrailError) as exc_info:
            guardrails.check_files(["secrets.yaml"])

        assert "secrets.yaml" in str(exc_info.value)

    def test_check_allowed_files(self) -> None:
        """Test that allowed files pass."""
        config = GuardrailConfig()
        guardrails = Guardrails(config)

        # Should not raise
        guardrails.check_files(["src/app.py", "tests/test_app.py", "README.md"])

    def test_check_max_files(self) -> None:
        """Test that max file count is enforced."""
        config = GuardrailConfig(max_files_changed=3)
        guardrails = Guardrails(config)

        with pytest.raises(GuardrailError) as exc_info:
            guardrails.check_files(["a.py", "b.py", "c.py", "d.py"])

        assert "Too many files" in str(exc_info.value)
        assert exc_info.value.rule == "max_files_changed"

    def test_disabled_guardrails(self) -> None:
        """Test that disabled guardrails allow everything."""
        config = GuardrailConfig(enabled=False)
        guardrails = Guardrails(config)

        # Should not raise even for forbidden files
        guardrails.check_files([".env", "secrets.yaml", ".git/config"])

    def test_is_file_allowed(self) -> None:
        """Test is_file_allowed method."""
        config = GuardrailConfig()
        guardrails = Guardrails(config)

        assert guardrails.is_file_allowed("src/app.py")
        assert guardrails.is_file_allowed("tests/test.py")
        assert not guardrails.is_file_allowed(".env")
        assert not guardrails.is_file_allowed("secrets.yaml")
        assert not guardrails.is_file_allowed(".git/config")

    def test_filter_allowed_files(self) -> None:
        """Test filtering to allowed files only."""
        config = GuardrailConfig()
        guardrails = Guardrails(config)

        files = ["src/app.py", ".env", "tests/test.py", "secrets.yaml"]
        allowed = guardrails.filter_allowed_files(files)

        assert "src/app.py" in allowed
        assert "tests/test.py" in allowed
        assert ".env" not in allowed
        assert "secrets.yaml" not in allowed

    def test_get_violations(self) -> None:
        """Test getting violations without raising."""
        config = GuardrailConfig()
        guardrails = Guardrails(config)

        files = ["src/app.py", ".env", "tests/test.py", "secrets.yaml"]
        violations = guardrails.get_violations(files)

        assert ".env" in violations
        assert "secrets.yaml" in violations
        assert "src/app.py" not in violations

    def test_pattern_matching(self) -> None:
        """Test pattern matching for various patterns."""
        config = GuardrailConfig(
            forbidden_patterns=["*.env", "*.env.*", "*.pem", "*secrets*"],
            forbidden_paths=[],
        )
        guardrails = Guardrails(config)

        assert not guardrails.is_file_allowed(".env")
        assert not guardrails.is_file_allowed(".env.local")
        assert not guardrails.is_file_allowed("config/.env.production")
        assert not guardrails.is_file_allowed("key.pem")
        assert not guardrails.is_file_allowed("my_secrets.json")
        assert not guardrails.is_file_allowed("secrets_config.yaml")

        assert guardrails.is_file_allowed("environment.py")
        assert guardrails.is_file_allowed("src/config.py")


@pytest.fixture
def malicious_executor() -> FakeExecutor:
    """Create executor that tries to modify forbidden files."""
    return FakeExecutor(
        scenarios=[
            FakeScenario(name="plan", text_output="# Plan"),
            FakeScenario(name="spec", text_output="# Spec\n## Acceptance\n- Done"),
            FakeScenario(
                name="decompose",
                text_output="""run_id: "test"
items:
  - id: "W001"
    title: "Task"
    objective: "Do task"
    acceptance: ["Done"]
    files_hint: []
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
""",
            ),
            # Try to modify .env
            FakeScenario(
                name="implement",
                actions=[
                    FakeAction(".env", "SECRET_KEY=stolen"),
                    FakeAction("src/app.py", "# Legitimate code"),
                ],
            ),
            FakeScenario(name="review", text_output="# Review"),
        ]
    )


@pytest.mark.integration
def test_guardrail_blocks_forbidden_files(
    tmp_git_repo: Path,
    malicious_executor: FakeExecutor,
) -> None:
    """Test that guardrails block forbidden file modifications."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False
    config.guardrails.enabled = True
    config.run.stop_on_first_failure = True

    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = malicious_executor

    success = runner.run("Try to steal secrets")

    # Should fail due to guardrail violation
    assert not success

    # State should show failure
    runner.state.load()
    assert runner.state.current_stage.value == "failed"


@pytest.mark.integration
def test_guardrail_disabled_allows_all(
    tmp_git_repo: Path,
    malicious_executor: FakeExecutor,
) -> None:
    """Test that disabled guardrails allow forbidden files."""
    config = OrxConfig.default(EngineType.FAKE)
    config.git.base_branch = "main"
    config.git.auto_commit = False
    config.guardrails.enabled = False  # Disable guardrails

    runner = Runner(config, base_dir=tmp_git_repo, dry_run=False)
    runner.executor = malicious_executor

    # This should not raise guardrail error
    # (though may fail for other reasons like empty diff after gates)
    try:
        runner.run("Try to modify files")
        # If it succeeds or fails for non-guardrail reasons, that's fine
    except GuardrailError:
        pytest.fail("GuardrailError should not be raised when guardrails disabled")
