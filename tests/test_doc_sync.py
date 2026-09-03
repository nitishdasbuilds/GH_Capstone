"""Unit tests for src/doc_sync.py and src/calculator.py."""

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import doc_sync  # noqa: E402
from calculator import Calculator, add, divide, multiply, subtract  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_module_logger(monkeypatch):
    """Redirect doc_sync's module-level logger so tests never touch the real logs/ dir."""
    test_logger = logging.getLogger("doc_sync_under_test")
    test_logger.handlers.clear()
    test_logger.setLevel(logging.INFO)
    monkeypatch.setattr(doc_sync, "logger", test_logger)
    yield test_logger


@pytest.fixture
def readme_path(tmp_path, monkeypatch):
    path = tmp_path / "README.md"
    monkeypatch.setattr(doc_sync, "README_PATH", path)
    return path


def _make_py_file(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# --- File Change Detection ---
class TestFileChangeDetection:
    def test_py_file_modification_triggers_sync(self):
        handler = doc_sync.PythonFileChangeHandler()
        handler._schedule = MagicMock()
        event = MagicMock(is_directory=False, src_path="src/calculator.py")

        handler.on_modified(event)

        handler._schedule.assert_called_once_with(str(Path("src/calculator.py")))

    def test_non_py_file_ignored(self):
        handler = doc_sync.PythonFileChangeHandler()
        handler._schedule = MagicMock()
        event = MagicMock(is_directory=False, src_path="src/README.md")

        handler.on_modified(event)

        handler._schedule.assert_not_called()

    def test_directory_events_ignored(self):
        handler = doc_sync.PythonFileChangeHandler()
        handler._schedule = MagicMock()
        event = MagicMock(is_directory=True, src_path="src/subpkg")

        handler.on_modified(event)

        handler._schedule.assert_not_called()

    def test_duplicate_events_debounced(self, tmp_path):
        handler = doc_sync.PythonFileChangeHandler()
        py_file = _make_py_file(tmp_path, "mod.py", "def foo():\n    pass\n")

        # Two rapid events for the same file should collapse to a single pending entry.
        handler._schedule(str(py_file))
        handler._schedule(str(py_file))
        assert len(handler._pending) == 1

        with patch.object(doc_sync, "sync_readme") as mock_sync:
            handler._flush()

        mock_sync.assert_called_once()
        (modules,), _ = mock_sync.call_args
        assert len(modules) == 1

    def test_flush_with_no_pending_events_does_nothing(self):
        handler = doc_sync.PythonFileChangeHandler()
        with patch.object(doc_sync, "sync_readme") as mock_sync:
            handler._flush()
        mock_sync.assert_not_called()


# --- README Update Logic ---
class TestReadmeUpdate:
    def test_marker_section_replaced(self):
        content = (
            "<!-- AUTO-GENERATED:START:api_usage -->\nold content\n"
            "<!-- AUTO-GENERATED:END:api_usage -->\n"
        )
        result = doc_sync.apply_section(content, "api_usage", "new content\n")
        assert "old content" not in result
        assert "new content" in result
        assert "<!-- AUTO-GENERATED:START:api_usage -->" in result
        assert "<!-- AUTO-GENERATED:END:api_usage -->" in result

    def test_content_outside_markers_preserved(self):
        content = (
            "# My Project\n\nSome intro text.\n\n"
            "<!-- AUTO-GENERATED:START:api_usage -->\nold\n"
            "<!-- AUTO-GENERATED:END:api_usage -->\n\nFooter text.\n"
        )
        result = doc_sync.apply_section(content, "api_usage", "new\n")
        assert "# My Project" in result
        assert "Some intro text." in result
        assert "Footer text." in result

    def test_missing_markers_handled_gracefully(self, caplog):
        content = "# My Project\n\nNo markers here.\n"
        with caplog.at_level(logging.WARNING, logger="doc_sync_under_test"):
            result = doc_sync.apply_section(content, "api_usage", "new content\n")

        assert "not found" in caplog.text
        assert "No markers here." in result
        assert "<!-- AUTO-GENERATED:START:api_usage -->" in result
        assert "new content" in result

    def test_malformed_markers_start_after_end_treated_as_missing(self, caplog):
        # END marker appears before START -> treated as missing rather than crashing.
        content = (
            "<!-- AUTO-GENERATED:END:api_usage -->\n"
            "<!-- AUTO-GENERATED:START:api_usage -->\n"
        )
        with caplog.at_level(logging.WARNING, logger="doc_sync_under_test"):
            result = doc_sync.apply_section(content, "api_usage", "new content\n")

        assert result.count("<!-- AUTO-GENERATED:START:api_usage -->") == 2

    def test_template_content_substituted_into_readme(self, readme_path):
        readme_path.write_text(
            "<!-- AUTO-GENERATED:START:api_usage -->\nstale\n"
            "<!-- AUTO-GENERATED:END:api_usage -->\n"
            "<!-- AUTO-GENERATED:START:configuration -->\nstale\n"
            "<!-- AUTO-GENERATED:END:configuration -->\n",
            encoding="utf-8",
        )
        module = doc_sync.ParsedModule(
            module_name="mymod",
            functions=[doc_sync.ParsedFunction(name="foo", signature="foo()", docstring="Does foo.")],
        )

        doc_sync.sync_readme([module])

        updated = readme_path.read_text(encoding="utf-8")
        assert "`foo()`" in updated
        assert "Does foo." in updated
        assert "stale" not in updated

    def test_readme_preserves_prior_content_on_parse_failure(self, readme_path, tmp_path):
        """Regression test for code-review.md Blocking Issue #1.

        When analyze_module() fails to parse a changed file, sync_readme() is
        expected to keep previously-generated content instead of wiping it with
        an empty placeholder. This currently fails: it documents a real,
        known defect rather than a test bug.
        """
        readme_path.write_text(
            "<!-- AUTO-GENERATED:START:api_usage -->\n"
            "- `foo()` — Does foo.\n"
            "<!-- AUTO-GENERATED:END:api_usage -->\n",
            encoding="utf-8",
        )

        broken_file = _make_py_file(tmp_path, "broken.py", "def foo(:\n    pass\n")
        handler = doc_sync.PythonFileChangeHandler()

        handler._process_batch([str(broken_file)])

        updated = readme_path.read_text(encoding="utf-8")
        assert "Does foo." in updated, (
            "sync_readme() wiped previously-generated content after a parse "
            "failure instead of preserving it (see code-review.md Blocking Issue #1)"
        )


# --- Timestamp Logging ---
class TestSyncLogging:
    def test_iso_now_returns_parseable_iso8601(self):
        value = doc_sync._iso_now()
        datetime.fromisoformat(value)  # raises if not valid ISO-8601

    def test_log_directory_created_if_missing(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        log_file = log_dir / "sync.log"
        monkeypatch.setattr(doc_sync, "LOG_DIR", log_dir)
        monkeypatch.setattr(doc_sync, "LOG_FILE", log_file)

        real_logger = logging.getLogger("doc_sync")
        saved_handlers = real_logger.handlers[:]
        real_logger.handlers.clear()
        try:
            doc_sync._configure_logging()
            assert log_dir.is_dir()
            assert log_file.exists()
        finally:
            for h in real_logger.handlers:
                h.close()
            real_logger.handlers.clear()
            real_logger.handlers.extend(saved_handlers)

    def test_log_appends_not_overwrites(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        log_file = log_dir / "sync.log"
        monkeypatch.setattr(doc_sync, "LOG_DIR", log_dir)
        monkeypatch.setattr(doc_sync, "LOG_FILE", log_file)

        real_logger = logging.getLogger("doc_sync")
        saved_handlers = real_logger.handlers[:]
        real_logger.handlers.clear()
        try:
            configured = doc_sync._configure_logging()
            configured.info("first sync")
            configured.info("second sync")
            for h in configured.handlers:
                h.flush()

            lines = [
                line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
            assert len(lines) == 2
        finally:
            for h in real_logger.handlers:
                h.close()
            real_logger.handlers.clear()
            real_logger.handlers.extend(saved_handlers)

    def test_log_entry_has_iso8601_timestamp(self, tmp_path, monkeypatch):
        """Regression test for code-review.md Blocking Issue #2.

        The implementation spec requires ISO-8601 timestamps in logs/sync.log.
        The default logging.Formatter asctime is NOT ISO-8601 (space separator,
        comma milliseconds, no offset). This is expected to fail, documenting
        a real, known defect rather than a test bug.
        """
        log_dir = tmp_path / "logs"
        log_file = log_dir / "sync.log"
        monkeypatch.setattr(doc_sync, "LOG_DIR", log_dir)
        monkeypatch.setattr(doc_sync, "LOG_FILE", log_file)

        real_logger = logging.getLogger("doc_sync")
        saved_handlers = real_logger.handlers[:]
        real_logger.handlers.clear()
        try:
            configured = doc_sync._configure_logging()
            configured.info("test message")
            for h in configured.handlers:
                h.flush()

            line = log_file.read_text(encoding="utf-8").splitlines()[0]
            timestamp_str = line.split(" INFO ")[0]
            # Should be parseable as ISO-8601 (e.g. 2026-09-02T14:40:08+00:00)
            datetime.fromisoformat(timestamp_str)
        finally:
            for h in real_logger.handlers:
                h.close()
            real_logger.handlers.clear()
            real_logger.handlers.extend(saved_handlers)


# --- Calculator Functions ---
class TestCalculator:
    def test_add(self):
        assert add(2, 3) == 5
        assert add(-2, 3) == 1
        assert add(2.5, 0.5) == 3.0

    def test_subtract(self):
        assert subtract(5, 3) == 2
        assert subtract(3, 5) == -2

    def test_multiply(self):
        assert multiply(4, 3) == 12
        assert multiply(-4, 3) == -12
        assert multiply(0, 5) == 0

    def test_divide(self):
        assert divide(10, 2) == 5
        assert divide(-10, 2) == -5
        assert divide(5, 2) == 2.5

    def test_divide_by_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            divide(10, 0)

    def test_calculator_running_total(self):
        calc = Calculator()
        calc.add(10)
        calc.multiply(3)
        calc.subtract(5)
        assert calc.total == 25

    def test_calculator_reset(self):
        calc = Calculator(initial=5)
        calc.add(10)
        calc.reset()
        assert calc.total == 0.0

    def test_calculator_divide_by_zero_raises(self):
        calc = Calculator(initial=10)
        with pytest.raises(ZeroDivisionError):
            calc.divide(0)

    @pytest.mark.xfail(
        reason=(
            "Known defect per code-review.md Non-Blocking Recommendation #1: "
            "square() duplicates multiply() instead of squaring the total."
        ),
        strict=True,
    )
    def test_square_actually_squares_the_total(self):
        calc = Calculator(initial=4)
        calc.square(2)
        assert calc.total == 16


# --- Error Handling ---
class TestErrorHandling:
    def test_readme_write_failure_does_not_crash(self, tmp_path, monkeypatch):
        # Point README_PATH at a directory so write_text() raises IsADirectoryError (OSError).
        bad_path = tmp_path / "readme_dir"
        bad_path.mkdir()
        monkeypatch.setattr(doc_sync, "README_PATH", bad_path)

        py_file = _make_py_file(tmp_path, "mod.py", "def foo():\n    pass\n")
        handler = doc_sync.PythonFileChangeHandler()

        handler._process_batch([str(py_file)])  # should not raise

    def test_log_write_failure_handled(self, isolate_module_logger, tmp_path):
        handler = logging.FileHandler(tmp_path / "temp.log")
        isolate_module_logger.addHandler(handler)
        handler.stream.close()

        logging.raiseExceptions = False
        try:
            isolate_module_logger.error("this should not raise even though the stream is closed")
        finally:
            logging.raiseExceptions = True

    def test_corrupted_source_file_skipped(self, tmp_path):
        good_file = _make_py_file(tmp_path, "good.py", 'def foo():\n    """Does foo."""\n    pass\n')
        bad_file = _make_py_file(tmp_path, "bad.py", "def bar(:\n    pass\n")
        handler = doc_sync.PythonFileChangeHandler()

        with patch.object(doc_sync, "sync_readme") as mock_sync:
            handler._process_batch([str(good_file), str(bad_file)])

        mock_sync.assert_called_once()
        (modules,), _ = mock_sync.call_args
        assert len(modules) == 1
        assert modules[0].module_name == "good"

    def test_deleted_file_skipped_without_crashing(self, tmp_path):
        missing_file = tmp_path / "gone.py"
        handler = doc_sync.PythonFileChangeHandler()

        with patch.object(doc_sync, "sync_readme") as mock_sync:
            handler._process_batch([str(missing_file)])

        mock_sync.assert_called_once_with([])

    def test_keyboard_interrupt_exits_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(doc_sync, "WATCH_DIRECTORY", tmp_path)

        mock_observer = MagicMock()
        mock_observer.is_alive.return_value = True
        mock_observer.join.side_effect = [KeyboardInterrupt(), None]

        with patch.object(doc_sync, "Observer", return_value=mock_observer):
            doc_sync.main()  # should not raise

        mock_observer.stop.assert_called_once()
        assert mock_observer.join.call_count == 2  # once to raise, once in finally
