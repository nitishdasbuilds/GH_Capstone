"""Documentation sync file watcher.

Monitors the ``src/`` directory for changes to Python (.py) files and
automatically regenerates the auto-generated sections of README.md using a
simple template-based approach.

Traceability:
    - FR-1: File watching and change detection (watches src/, debounced)
    - FR-2: Template-based documentation generation (docstring/signature extraction)
    - FR-3: README documentation sync (API usage examples, Configuration options)
    - NFR-1: Performance (debounce + batching to avoid redundant work)
    - NFR-3: Reliability (errors are logged, watcher keeps running)
    - NFR-4: Usability (clear console output, Ctrl+C to stop)

Design decisions from artifacts/impl-plan.md:
    - D002: Auto-generated sections are delimited by
      ``<!-- AUTO-GENERATED:START:section_name -->`` /
      ``<!-- AUTO-GENERATED:END:section_name -->`` marker pairs.
    - D003: Rapid successive changes are batched within a 2 second window,
      capped at 20 files per batch (excess files spill into the next batch).
"""

from __future__ import annotations

import ast
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

# --- Configuration -----------------------------------------------------

WATCH_DIRECTORY = Path("src")
README_PATH = Path("README.md")
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "sync.log"

DEBOUNCE_SECONDS = 0.3  # avoid double-processing on save (per-file debounce)
BATCH_WINDOW_SECONDS = 2.0  # D003: window to collect related changes
BATCH_MAX_FILES = 20  # D003: max files processed per sync batch

SECTION_API_USAGE = "api_usage"
SECTION_CONFIGURATION = "configuration"

START_MARKER = r"<!-- AUTO-GENERATED:START:{name} -->"
END_MARKER = r"<!-- AUTO-GENERATED:END:{name} -->"


def _configure_logging() -> logging.Logger:
    """Create the logs/ directory and configure the module logger."""
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger("doc_sync")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    return logger


logger = _configure_logging()


def _iso_now() -> str:
    """Return the current time as an ISO-8601 timestamp."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# --- Code analysis -------------------------------------------------------


@dataclass
class ParsedFunction:
    """A function or method extracted from a Python module."""

    name: str
    signature: str
    docstring: str


@dataclass
class ParsedModule:
    """The public API extracted from a single Python module."""

    module_name: str
    functions: list[ParsedFunction] = field(default_factory=list)


def analyze_module(file_path: Path) -> Optional[ParsedModule]:
    """Parse a Python file and extract its public functions and docstrings.

    Args:
        file_path: Path to the ``.py`` file to analyze.

    Returns:
        A `ParsedModule` describing the public API, or ``None`` if the file
        could not be read or parsed (e.g. syntax error).
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (OSError, SyntaxError) as exc:
        logger.error("Failed to analyze %s: %s", file_path, exc)
        return None

    module = ParsedModule(module_name=file_path.stem)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            args = [a.arg for a in node.args.args]
            signature = f"{node.name}({', '.join(args)})"
            docstring = ast.get_docstring(node) or ""
            module.functions.append(
                ParsedFunction(name=node.name, signature=signature, docstring=docstring)
            )
    return module


# --- Documentation generation (template-based) ---------------------------


def render_api_usage_section(modules: list[ParsedModule]) -> str:
    """Render the API usage examples section from parsed modules (FR-2, FR-4)."""
    lines = ["### API Usage Examples", ""]
    for module in modules:
        if not module.functions:
            continue
        lines.append(f"**`{module.module_name}`**")
        lines.append("")
        for func in module.functions:
            summary = func.docstring.strip().splitlines()[0] if func.docstring else "No description."
            lines.append(f"- `{func.signature}` — {summary}")
        lines.append("")
    if len(lines) == 2:
        lines.append("_No public functions found yet._")
    return "\n".join(lines).rstrip() + "\n"


def render_configuration_section() -> str:
    """Render the configuration options section (FR-3)."""
    lines = [
        "### Configuration Options",
        "",
        f"- Watch directory: `{WATCH_DIRECTORY.as_posix()}`",
        f"- README target: `{README_PATH.as_posix()}`",
        f"- Batch window: {BATCH_WINDOW_SECONDS}s, max {BATCH_MAX_FILES} files per batch",
        f"- Log file: `{LOG_FILE.as_posix()}`",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def apply_section(content: str, section_name: str, body: str) -> str:
    """Replace the contents between AUTO-GENERATED markers for one section.

    If the markers are missing, they are appended to the end of the document
    (per D002: missing markers should not silently drop content).
    """
    start_pat = re.compile(START_MARKER.format(name=section_name))
    end_pat = re.compile(END_MARKER.format(name=section_name))

    start_match = start_pat.search(content)
    end_match = end_pat.search(content)

    replacement = (
        f"<!-- AUTO-GENERATED:START:{section_name} -->\n"
        f"{body}"
        f"<!-- AUTO-GENERATED:END:{section_name} -->"
    )

    if start_match and end_match and start_match.start() < end_match.start():
        return content[: start_match.start()] + replacement + content[end_match.end() :]

    logger.warning("Markers for section '%s' not found; appending section", section_name)
    separator = "\n\n" if content and not content.endswith("\n\n") else ""
    return content + separator + replacement + "\n"


def sync_readme(modules: list[ParsedModule]) -> None:
    """Regenerate the auto-generated sections of README.md (FR-3)."""
    content = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else "# Project\n"

    content = apply_section(content, SECTION_API_USAGE, render_api_usage_section(modules))
    content = apply_section(content, SECTION_CONFIGURATION, render_configuration_section())

    README_PATH.write_text(content, encoding="utf-8")

    timestamp = _iso_now()
    logger.info("README.md synced (%d module(s) analyzed)", len(modules))
    print(f"[SYNCED] README.md updated at {timestamp}")


# --- File watching & batching ---------------------------------------------


class PythonFileChangeHandler(FileSystemEventHandler):
    """Watches src/ for .py file changes and schedules debounced sync runs (FR-1)."""

    def __init__(self) -> None:
        super().__init__()
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def _schedule(self, path: str) -> None:
        with self._lock:
            self._pending[path] = time.monotonic()
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(BATCH_WINDOW_SECONDS, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            paths = list(self._pending.keys())
            self._pending.clear()

        if not paths:
            return

        # D003: cap batch size, process the rest on the next event cycle.
        batch, overflow = paths[:BATCH_MAX_FILES], paths[BATCH_MAX_FILES:]
        if overflow:
            logger.warning(
                "Large refactoring detected: %d files pending, processing first %d",
                len(paths),
                BATCH_MAX_FILES,
            )
            with self._lock:
                for path in overflow:
                    self._pending[path] = time.monotonic()

        self._process_batch(batch)

    def _process_batch(self, paths: list[str]) -> None:
        modules = []
        for raw_path in sorted(set(paths)):
            path = Path(raw_path)
            if not path.exists():
                logger.info("File deleted: %s", path)
                continue
            module = analyze_module(path)
            if module is not None:
                modules.append(module)

        try:
            sync_readme(modules)
        except OSError as exc:
            logger.error("Failed to sync README.md: %s", exc)

    def _handle_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".py":
            return
        self._schedule(str(path))

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle_event(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle_event(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle_event(event)


def main() -> None:
    """Start the file watcher and run until interrupted with Ctrl+C."""
    WATCH_DIRECTORY.mkdir(exist_ok=True)

    handler = PythonFileChangeHandler()
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIRECTORY), recursive=True)
    observer.start()

    logger.info("doc_sync started, watching '%s'", WATCH_DIRECTORY.as_posix())
    print(f"Watching '{WATCH_DIRECTORY.as_posix()}' for changes. Press Ctrl+C to stop.")

    try:
        while observer.is_alive():
            observer.join(timeout=1.0)
    except KeyboardInterrupt:
        print("\nStopping doc_sync...")
        logger.info("doc_sync stopped by user (Ctrl+C)")
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()
