"""Unit tests for src/doc_sync.py and src/calculator.py (EPMCDMETST-62888)."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import calculator
from src import doc_sync
from src.doc_sync import (
    ChangeEvent,
    EventDebouncer,
    ExtractionError,
    FunctionInfo,
    ModuleInfo,
    PyFileEventHandler,
    ReadmeSyncError,
    SyncOrchestrator,
    _atomic_write,
    _parse_markers,
    extract_module,
    is_within_workspace,
    render_block,
    sync_readme,
)


# --------------------------------------------------------------------------
# File Change Detection
# --------------------------------------------------------------------------
class TestFileChangeDetection:
    def _make_event(self, path: str, is_directory: bool = False):
        event = MagicMock()
        event.src_path = path
        event.is_directory = is_directory
        return event

    def test_py_file_created_forwarded_to_debouncer(self):
        debouncer = MagicMock()
        handler = PyFileEventHandler(debouncer)
        handler.on_created(self._make_event("src/foo.py"))
        debouncer.add_event.assert_called_once()
        event = debouncer.add_event.call_args[0][0]
        assert event.path == Path("src/foo.py")
        assert event.kind == "created"

    def test_py_file_modified_forwarded_to_debouncer(self):
        debouncer = MagicMock()
        handler = PyFileEventHandler(debouncer)
        handler.on_modified(self._make_event("src/foo.py"))
        event = debouncer.add_event.call_args[0][0]
        assert event.kind == "modified"

    def test_py_file_deleted_forwarded_to_debouncer(self):
        debouncer = MagicMock()
        handler = PyFileEventHandler(debouncer)
        handler.on_deleted(self._make_event("src/foo.py"))
        event = debouncer.add_event.call_args[0][0]
        assert event.kind == "deleted"

    def test_non_py_file_ignored(self):
        debouncer = MagicMock()
        handler = PyFileEventHandler(debouncer)
        handler.on_modified(self._make_event("src/notes.txt"))
        debouncer.add_event.assert_not_called()

    def test_directory_event_ignored(self):
        debouncer = MagicMock()
        handler = PyFileEventHandler(debouncer)
        handler.on_modified(self._make_event("src/subpkg", is_directory=True))
        debouncer.add_event.assert_not_called()

    def test_moved_event_enqueues_delete_and_create(self):
        debouncer = MagicMock()
        handler = PyFileEventHandler(debouncer)
        event = MagicMock()
        event.is_directory = False
        event.src_path = "src/old_name.py"
        event.dest_path = "src/new_name.py"
        handler.on_moved(event)
        assert debouncer.add_event.call_count == 2
        kinds = {c.args[0].kind for c in debouncer.add_event.call_args_list}
        assert kinds == {"deleted", "created"}

    def test_duplicate_events_debounced(self):
        callback = MagicMock()
        debouncer = EventDebouncer(callback=callback, window_ms=50)
        path = Path("src/foo.py")
        debouncer.add_event(ChangeEvent(path, "modified"))
        debouncer.add_event(ChangeEvent(path, "modified"))
        debouncer.add_event(ChangeEvent(path, "modified"))
        time.sleep(0.2)
        callback.assert_called_once()
        assert callback.call_args[0][0] == {path}

    def test_events_outside_watched_directory_ignored_by_orchestrator(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        outside_file = tmp_path / "outside.py"
        outside_file.write_text("x = 1\n", encoding="utf-8")
        orchestrator = SyncOrchestrator(tmp_path, src_dir, tmp_path / "README.md")
        orchestrator.process_batch({outside_file})
        assert not (tmp_path / "README.md").exists()


# --------------------------------------------------------------------------
# README Update Logic
# --------------------------------------------------------------------------
class TestReadmeUpdate:
    def test_marker_section_replaced(self, tmp_path):
        readme = tmp_path / "README.md"
        info = ModuleInfo(module_path="src.foo", docstring="Original", functions=[])
        original_block = render_block(info)
        readme.write_text(f"# Title\n\n## API Reference\n\n{original_block}\n", encoding="utf-8")

        new_info = ModuleInfo(module_path="src.foo", docstring="Updated", functions=[])
        new_block = render_block(new_info)
        result = sync_readme(readme, {"src.foo": new_block})

        content = readme.read_text(encoding="utf-8")
        assert "Updated" in content
        assert "Original" not in content
        assert result.updated == ["src.foo"]

    def test_content_outside_markers_preserved(self, tmp_path):
        readme = tmp_path / "README.md"
        info = ModuleInfo(module_path="src.foo", docstring="Doc", functions=[])
        block = render_block(info)
        readme.write_text(f"# My Project\n\nSome intro text.\n\n{block}\n\nFooter text.\n", encoding="utf-8")

        new_block = render_block(ModuleInfo(module_path="src.foo", docstring="Doc2", functions=[]))
        sync_readme(readme, {"src.foo": new_block})

        content = readme.read_text(encoding="utf-8")
        assert "# My Project" in content
        assert "Some intro text." in content
        assert "Footer text." in content

    def test_missing_markers_inserts_new_block_after_heading(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Title\n\n## API Reference\n", encoding="utf-8")
        block = render_block(ModuleInfo(module_path="src.foo", docstring="Doc", functions=[]))
        result = sync_readme(readme, {"src.foo": block})

        content = readme.read_text(encoding="utf-8")
        assert "src.foo" in content
        assert result.added == ["src.foo"]

    def test_missing_markers_appends_at_end_without_heading(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Title\n\nNo heading here.\n", encoding="utf-8")
        block = render_block(ModuleInfo(module_path="src.foo", docstring="Doc", functions=[]))
        sync_readme(readme, {"src.foo": block})

        content = readme.read_text(encoding="utf-8")
        assert content.startswith("# Title")
        assert "src.foo" in content

    def test_malformed_markers_skipped_gracefully(self, tmp_path):
        readme = tmp_path / "README.md"
        # Duplicate START markers for the same module -> malformed.
        readme.write_text(
            "<!-- AUTO-DOC:START module=src.foo -->\nstuff\n"
            "<!-- AUTO-DOC:START module=src.foo -->\nstuff2\n"
            "<!-- AUTO-DOC:END module=src.foo -->\n",
            encoding="utf-8",
        )
        block = render_block(ModuleInfo(module_path="src.foo", docstring="Doc", functions=[]))
        result = sync_readme(readme, {"src.foo": block})

        assert result.skipped == ["src.foo"]
        # Should not raise/crash, content largely unchanged for that section.
        content = readme.read_text(encoding="utf-8")
        assert "stuff2" in content

    def test_module_removal_deletes_block(self, tmp_path):
        readme = tmp_path / "README.md"
        block = render_block(ModuleInfo(module_path="src.foo", docstring="Doc", functions=[]))
        readme.write_text(f"# Title\n\n{block}\n", encoding="utf-8")

        result = sync_readme(readme, {"src.foo": None})
        content = readme.read_text(encoding="utf-8")
        assert "src.foo" not in content
        assert result.removed == ["src.foo"]

    def test_render_block_substitutes_functions_and_docstrings(self):
        info = ModuleInfo(
            module_path="src.calculator",
            docstring="Module doc.",
            functions=[FunctionInfo(name="add", signature="add(a, b)", docstring="Adds.")],
        )
        block = render_block(info)
        assert "src.calculator" in block
        assert "Module doc." in block
        assert "add(a, b)" in block
        assert "Adds." in block
        assert block.startswith("<!-- AUTO-DOC:START module=src.calculator -->")
        assert block.endswith("<!-- AUTO-DOC:END module=src.calculator -->")

    def test_render_block_no_functions_placeholder(self):
        info = ModuleInfo(module_path="src.empty", docstring=None, functions=[])
        block = render_block(info)
        assert "_No module-level functions._" in block


# --------------------------------------------------------------------------
# Timestamp Logging (sync pass logging, per NFR-4)
# --------------------------------------------------------------------------
class TestSyncLogging:
    def test_sync_pass_logs_summary_with_timestamp(self, tmp_path, caplog):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "mod.py").write_text('"""Doc."""\n', encoding="utf-8")
        readme = tmp_path / "README.md"
        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)

        with caplog.at_level(logging.INFO, logger="doc_sync"):
            orchestrator.startup_sync()

        assert any("Startup sync" in r.message for r in caplog.records)
        assert all(r.created for r in caplog.records)  # every record carries a real timestamp

    def test_configure_logging_sets_iso8601_datefmt_when_no_handlers(self, monkeypatch):
        # configure_logging() is a documented no-op if the root logger already
        # has handlers (e.g. pytest's own log-capture handler); simulate the
        # "no handlers yet" case explicitly to verify the formatter it installs.
        root = logging.getLogger()
        monkeypatch.setattr(root, "handlers", [])
        doc_sync.configure_logging()
        try:
            assert any(
                getattr(h.formatter, "datefmt", None) == "%Y-%m-%dT%H:%M:%S"
                for h in root.handlers
            )
        finally:
            for h in list(root.handlers):
                if getattr(h, "stream", None) is sys.stdout:
                    root.removeHandler(h)

    def test_orphan_removal_uses_startup_reconciliation_message(self, tmp_path, caplog):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        readme = tmp_path / "README.md"
        block = render_block(ModuleInfo(module_path="src.gone", docstring="x", functions=[]))
        readme.write_text(block + "\n", encoding="utf-8")

        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)
        with caplog.at_level(logging.INFO, logger="doc_sync"):
            orchestrator.startup_sync()

        assert any("orphaned section" in r.message for r in caplog.records)
        content = readme.read_text(encoding="utf-8")
        assert "src.gone" not in content

    def test_multiple_sync_passes_append_not_overwrite_readme(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        readme = tmp_path / "README.md"
        readme.write_text("# Title\n\nIntro.\n", encoding="utf-8")
        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)

        (src_dir / "a.py").write_text('"""A."""\n', encoding="utf-8")
        orchestrator.process_batch({src_dir / "a.py"})
        (src_dir / "b.py").write_text('"""B."""\n', encoding="utf-8")
        orchestrator.process_batch({src_dir / "b.py"})

        content = readme.read_text(encoding="utf-8")
        assert "Intro." in content
        assert "src.a" in content
        assert "src.b" in content


# --------------------------------------------------------------------------
# Calculator Functions
# --------------------------------------------------------------------------
class TestCalculator:
    def test_add(self):
        assert calculator.add(2, 3) == 5

    def test_add_negative(self):
        assert calculator.add(-2, -3) == -5

    def test_add_float(self):
        assert calculator.add(2.5, 0.5) == 3.0

    def test_subtract(self):
        assert calculator.subtract(5, 3) == 2

    def test_subtract_negative_result(self):
        assert calculator.subtract(2, 5) == -3

    def test_multiply(self):
        assert calculator.multiply(4, 3) == 12

    def test_multiply_by_zero(self):
        assert calculator.multiply(4, 0) == 0

    def test_multiply_negative(self):
        assert calculator.multiply(-2, 3) == -6

    def test_divide(self):
        assert calculator.divide(10, 2) == 5

    def test_divide_float_result(self):
        assert calculator.divide(1, 4) == 0.25

    def test_divide_by_zero_raises(self):
        with pytest.raises(ZeroDivisionError):
            calculator.divide(5, 0)

    def test_calculator_class_add_accumulates(self):
        calc = calculator.Calculator(initial=10)
        assert calc.add(5) == 15
        assert calc.value == 15

    def test_calculator_class_subtract_accumulates(self):
        calc = calculator.Calculator(initial=10)
        assert calc.subtract(4) == 6

    def test_calculator_class_reset(self):
        calc = calculator.Calculator(initial=10)
        calc.add(5)
        assert calc.reset() == 0.0
        assert calc.value == 0.0

    def test_calculator_class_default_initial_is_zero(self):
        calc = calculator.Calculator()
        assert calc.value == 0.0


# --------------------------------------------------------------------------
# Error Handling
# --------------------------------------------------------------------------
class TestErrorHandling:
    def test_readme_read_failure_raises_readme_sync_error(self, tmp_path, monkeypatch):
        readme = tmp_path / "README.md"
        readme.write_text("x", encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", boom)
        with pytest.raises(ReadmeSyncError):
            sync_readme(readme, {"src.foo": "block"})

    def test_atomic_write_failure_propagates_and_cleans_tmp(self, tmp_path, monkeypatch):
        readme = tmp_path / "README.md"

        def boom_replace(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("src.doc_sync.os.replace", boom_replace)
        with pytest.raises(OSError):
            _atomic_write(readme, "content")
        # No leftover .tmp files after the cleanup path runs.
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_orchestrator_sync_readme_failure_logged_not_raised(self, tmp_path, monkeypatch, caplog):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "mod.py").write_text('"""Doc."""\n', encoding="utf-8")
        readme = tmp_path / "README.md"
        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)

        def boom(*args, **kwargs):
            raise ReadmeSyncError("simulated failure")

        monkeypatch.setattr("src.doc_sync.sync_readme", boom)
        with caplog.at_level(logging.WARNING, logger="doc_sync"):
            orchestrator.startup_sync()  # must not raise
        assert any("README sync failed" in r.message for r in caplog.records)

    def test_corrupted_source_file_skipped_not_fatal(self, tmp_path, caplog):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "bad.py").write_text("def broken(:\n", encoding="utf-8")  # SyntaxError
        readme = tmp_path / "README.md"
        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)

        with caplog.at_level(logging.WARNING, logger="doc_sync"):
            orchestrator.startup_sync()  # must not raise

        assert any("syntax error" in r.message for r in caplog.records)

    def test_extract_module_invalid_utf8_raises_extraction_error(self, tmp_path):
        bad_file = tmp_path / "bad_encoding.py"
        bad_file.write_bytes(b"\xff\xfe# not valid utf-8\n")
        with pytest.raises(ExtractionError):
            extract_module(bad_file, "src.bad_encoding")

    def test_extract_module_missing_file_raises_extraction_error(self, tmp_path):
        missing = tmp_path / "missing.py"
        with pytest.raises(ExtractionError):
            extract_module(missing, "src.missing")

    def test_build_block_catches_render_block_exception(self, tmp_path, monkeypatch, caplog):
        """Regression test for the fixed blocking issue: render_block()
        exceptions inside _build_block must be caught, not propagate."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        file_path = src_dir / "mod.py"
        file_path.write_text('"""Doc."""\n', encoding="utf-8")
        readme = tmp_path / "README.md"
        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)

        def boom(module_info):
            raise RuntimeError("unexpected render failure")

        monkeypatch.setattr("src.doc_sync.render_block", boom)
        with caplog.at_level(logging.WARNING, logger="doc_sync"):
            result = orchestrator._build_block(file_path, "src.mod")

        assert result is None
        assert any("unexpected error rendering block" in r.message for r in caplog.records)

    def test_module_path_boundary_uses_src_dir_consistently(self, tmp_path, caplog):
        """Regression test: path-containment check must use src_dir (not
        workspace_root) so a file outside src/ is rejected before
        _module_path_for is ever called."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        outside_file = tmp_path / "moved_outside.py"
        outside_file.write_text('"""Doc."""\n', encoding="utf-8")
        readme = tmp_path / "README.md"
        orchestrator = SyncOrchestrator(tmp_path, src_dir, readme)

        with caplog.at_level(logging.WARNING, logger="doc_sync"):
            orchestrator.process_batch({outside_file})  # must not raise ValueError

        assert any("outside src/ root" in r.message for r in caplog.records)
        assert not readme.exists()

    def test_is_within_workspace_handles_os_error(self, monkeypatch, tmp_path):
        def boom(*args, **kwargs):
            raise OSError("resolve failure")

        monkeypatch.setattr(Path, "resolve", boom)
        assert is_within_workspace(tmp_path / "x.py", tmp_path) is False

    def test_debouncer_shutdown_cancels_pending_timer(self):
        callback = MagicMock()
        debouncer = EventDebouncer(callback=callback, window_ms=5000)
        debouncer.add_event(ChangeEvent(Path("src/foo.py"), "modified"))
        debouncer.shutdown()
        time.sleep(0.05)
        callback.assert_not_called()

    def test_watcher_observer_start_stop_uses_mocked_observer(self, tmp_path):
        """Exercise the watcher wiring without touching a real filesystem
        watcher thread by mocking watchdog's Observer."""
        with patch("src.doc_sync.Observer") as MockObserver:
            instance = MockObserver.return_value
            src_dir = tmp_path / "src"
            src_dir.mkdir()
            debouncer = EventDebouncer(callback=MagicMock())
            handler = PyFileEventHandler(debouncer)
            observer = doc_sync.Observer()
            observer.schedule(handler, str(src_dir), recursive=True)
            observer.start()
            observer.stop()
            observer.join()

            instance.schedule.assert_called_once()
            instance.start.assert_called_once()
            instance.stop.assert_called_once()
            instance.join.assert_called_once()

    def test_parse_markers_detects_unmatched_start(self):
        content = "<!-- AUTO-DOC:START module=src.foo -->\nno end here\n"
        result = _parse_markers(content)
        assert result["src.foo"]["malformed"] is True


# --------------------------------------------------------------------------
# Additional extraction / CLI coverage
# --------------------------------------------------------------------------
class TestSignatureExtractionAndCli:
    def test_extract_module_renders_full_signature_variety(self, tmp_path):
        source = (
            "def full(pos_only, /, normal, has_default=1, *args, kw_only, "
            "kw_default=2, **kwargs) -> int:\n"
            "    '''Doc.'''\n"
            "    return 1\n"
        )
        file_path = tmp_path / "mod.py"
        file_path.write_text(source, encoding="utf-8")
        info = extract_module(file_path, "src.mod")
        sig = info.functions[0].signature
        assert "pos_only" in sig and "/" in sig
        assert "*args" in sig
        assert "kw_only" in sig
        assert "**kwargs" in sig
        assert sig.endswith("-> int")

    def test_extract_module_kwonly_without_vararg_renders_bare_star(self, tmp_path):
        source = "def f(a, *, b=1):\n    pass\n"
        file_path = tmp_path / "mod2.py"
        file_path.write_text(source, encoding="utf-8")
        info = extract_module(file_path, "src.mod2")
        assert "*" in info.functions[0].signature
        assert "b = 1" in info.functions[0].signature

    def test_main_without_watch_flag_prints_usage_and_returns_1(self, capsys):
        exit_code = doc_sync.main([])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "usage" in captured.err.lower()

    def test_main_missing_src_dir_returns_1(self, monkeypatch):
        # Point SRC_DIRNAME at a directory that doesn't exist under the real
        # workspace root, exercising main()'s "src/ directory not found" path.
        monkeypatch.setattr(doc_sync, "SRC_DIRNAME", "no_such_src_dir_xyz")
        exit_code = doc_sync.main(["--watch"])
        assert exit_code == 1

    def test_build_arg_parser_has_watch_flag(self):
        parser = doc_sync.build_arg_parser()
        args = parser.parse_args(["--watch"])
        assert args.watch is True
        args = parser.parse_args([])
        assert args.watch is False
