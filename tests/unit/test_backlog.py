"""Tests for Backlog and WorkItem."""

from pathlib import Path

import pytest

from orx.context.backlog import Backlog, WorkItem, WorkItemStatus


class TestWorkItem:
    """Tests for WorkItem."""

    def test_create_minimal(self) -> None:
        """Test creating a minimal work item."""
        item = WorkItem(
            id="W001",
            title="Test item",
            objective="Test objective",
            acceptance=["Test passes"],
        )

        assert item.id == "W001"
        assert item.status == WorkItemStatus.TODO
        assert item.attempts == 0

    def test_create_full(self) -> None:
        """Test creating a fully specified work item."""
        item = WorkItem(
            id="W002",
            title="Full item",
            objective="Full objective",
            acceptance=["Criterion 1", "Criterion 2"],
            files_hint=["src/app.py", "tests/test_app.py"],
            depends_on=["W001"],
            status=WorkItemStatus.IN_PROGRESS,
            attempts=1,
            notes="Some notes",
        )

        assert item.id == "W002"
        assert len(item.acceptance) == 2
        assert len(item.files_hint) == 2
        assert item.depends_on == ["W001"]
        assert item.status == WorkItemStatus.IN_PROGRESS
        assert item.attempts == 1
        assert item.notes == "Some notes"

    def test_invalid_id_format(self) -> None:
        """Test that invalid ID format is rejected."""
        with pytest.raises(ValueError):
            WorkItem(
                id="invalid",
                title="Test",
                objective="Test",
                acceptance=["Test"],
            )

    def test_mark_in_progress(self) -> None:
        """Test marking item as in progress."""
        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )

        item.mark_in_progress()
        assert item.status == WorkItemStatus.IN_PROGRESS

    def test_mark_done(self) -> None:
        """Test marking item as done."""
        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )

        item.mark_done()
        assert item.status == WorkItemStatus.DONE

    def test_mark_failed(self) -> None:
        """Test marking item as failed."""
        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )

        item.mark_failed("Reason for failure")
        assert item.status == WorkItemStatus.FAILED
        assert item.notes == "Reason for failure"

    def test_increment_attempts(self) -> None:
        """Test incrementing attempts."""
        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )

        assert item.attempts == 0
        item.increment_attempts()
        assert item.attempts == 1
        item.increment_attempts()
        assert item.attempts == 2


class TestBacklog:
    """Tests for Backlog."""

    def test_create_empty(self) -> None:
        """Test creating an empty backlog."""
        backlog = Backlog(run_id="test_run", items=[])

        assert backlog.run_id == "test_run"
        assert len(backlog.items) == 0

    def test_add_item(self) -> None:
        """Test adding items to backlog."""
        backlog = Backlog(run_id="test_run", items=[])

        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )
        backlog.add_item(item)

        assert len(backlog.items) == 1
        assert backlog.items[0].id == "W001"

    def test_add_duplicate_item(self) -> None:
        """Test that duplicate IDs are rejected."""
        backlog = Backlog(run_id="test_run", items=[])

        item1 = WorkItem(
            id="W001",
            title="First",
            objective="Test",
            acceptance=["Test"],
        )
        item2 = WorkItem(
            id="W001",
            title="Duplicate",
            objective="Test",
            acceptance=["Test"],
        )

        backlog.add_item(item1)
        with pytest.raises(ValueError, match="already exists"):
            backlog.add_item(item2)

    def test_get_item(self) -> None:
        """Test getting item by ID."""
        backlog = Backlog(run_id="test_run", items=[])

        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )
        backlog.add_item(item)

        found = backlog.get_item("W001")
        assert found is not None
        assert found.id == "W001"

        not_found = backlog.get_item("W999")
        assert not_found is None

    def test_get_next_todo(self) -> None:
        """Test getting next TODO item."""
        backlog = Backlog(run_id="test_run", items=[])

        item1 = WorkItem(
            id="W001",
            title="First",
            objective="Test",
            acceptance=["Test"],
        )
        item2 = WorkItem(
            id="W002",
            title="Second",
            objective="Test",
            acceptance=["Test"],
        )

        backlog.add_item(item1)
        backlog.add_item(item2)

        next_item = backlog.get_next_todo()
        assert next_item is not None
        assert next_item.id == "W001"

    def test_get_next_todo_respects_dependencies(self) -> None:
        """Test that get_next_todo respects dependencies."""
        backlog = Backlog(run_id="test_run", items=[])

        item1 = WorkItem(
            id="W001",
            title="First",
            objective="Test",
            acceptance=["Test"],
        )
        item2 = WorkItem(
            id="W002",
            title="Second",
            objective="Test",
            acceptance=["Test"],
            depends_on=["W001"],
        )

        backlog.add_item(item1)
        backlog.add_item(item2)

        # First should be W001
        next_item = backlog.get_next_todo()
        assert next_item is not None
        assert next_item.id == "W001"

        # Mark W001 as done
        item1.mark_done()

        # Now W002 should be available
        next_item = backlog.get_next_todo()
        assert next_item is not None
        assert next_item.id == "W002"

    def test_all_done(self) -> None:
        """Test all_done check."""
        backlog = Backlog(run_id="test_run", items=[])

        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )
        backlog.add_item(item)

        assert not backlog.all_done()

        item.mark_done()
        assert backlog.all_done()

    def test_counts(self) -> None:
        """Test item count methods."""
        backlog = Backlog(run_id="test_run", items=[])

        item1 = WorkItem(
            id="W001",
            title="First",
            objective="Test",
            acceptance=["Test"],
        )
        item2 = WorkItem(
            id="W002",
            title="Second",
            objective="Test",
            acceptance=["Test"],
        )
        item3 = WorkItem(
            id="W003",
            title="Third",
            objective="Test",
            acceptance=["Test"],
        )

        backlog.add_item(item1)
        backlog.add_item(item2)
        backlog.add_item(item3)

        assert backlog.todo_count() == 3
        assert backlog.done_count() == 0
        assert backlog.failed_count() == 0

        item1.mark_done()
        item2.mark_failed()

        assert backlog.todo_count() == 1
        assert backlog.done_count() == 1
        assert backlog.failed_count() == 1

    def test_validate_dependencies(self) -> None:
        """Test dependency validation."""
        backlog = Backlog(run_id="test_run", items=[])

        item1 = WorkItem(
            id="W001",
            title="First",
            objective="Test",
            acceptance=["Test"],
        )
        item2 = WorkItem(
            id="W002",
            title="Second",
            objective="Test",
            acceptance=["Test"],
            depends_on=["W001"],
        )

        backlog.add_item(item1)
        backlog.add_item(item2)

        errors = backlog.validate_dependencies()
        assert len(errors) == 0

    def test_validate_dependencies_missing(self) -> None:
        """Test validation catches missing dependencies."""
        backlog = Backlog(run_id="test_run", items=[])

        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
            depends_on=["W999"],  # Doesn't exist
        )
        backlog.add_item(item)

        errors = backlog.validate_dependencies()
        assert len(errors) == 1
        assert "W999" in errors[0]

    def test_to_yaml(self) -> None:
        """Test YAML serialization."""
        backlog = Backlog(run_id="test_run", items=[])

        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test objective",
            acceptance=["Test passes"],
        )
        backlog.add_item(item)

        yaml_content = backlog.to_yaml()

        assert "run_id: test_run" in yaml_content
        assert "W001" in yaml_content
        assert "Test objective" in yaml_content

    def test_from_yaml(self) -> None:
        """Test YAML parsing."""
        yaml_content = """
run_id: test_run
items:
  - id: "W001"
    title: "Test item"
    objective: "Test objective"
    acceptance:
      - "Test passes"
    files_hint: []
    depends_on: []
    status: "todo"
    attempts: 0
    notes: ""
"""
        backlog = Backlog.from_yaml(yaml_content)

        assert backlog.run_id == "test_run"
        assert len(backlog.items) == 1
        assert backlog.items[0].id == "W001"

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Test save and load roundtrip."""
        backlog = Backlog(run_id="test_run", items=[])

        item = WorkItem(
            id="W001",
            title="Test",
            objective="Test",
            acceptance=["Test"],
        )
        backlog.add_item(item)

        path = tmp_path / "backlog.yaml"
        backlog.save(path)

        loaded = Backlog.load(path)

        assert loaded.run_id == backlog.run_id
        assert len(loaded.items) == 1
        assert loaded.items[0].id == "W001"
