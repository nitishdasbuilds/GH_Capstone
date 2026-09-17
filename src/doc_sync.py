"""Documentation-sync watcher tool (EPMCDMETST-62888).

Watches ``src/`` for changes to ``.py`` files and keeps auto-generated
sections of ``README.md`` in sync with the current code, per
``artifacts/requirements.md`` (FR-1..FR-5, NFR-1..NFR-5),
``artifacts/architecture.md`` (component design), and
``artifacts/impl-plan.md`` (31-task breakdown across 6 layers).

This single-file module is organized into the components described in
Architecture section 2.3 (a single-file layout is explicitly called out
as acceptable for this scope in Architecture section 12.1):

- Constants & configuration (T008)
- Exception hierarchy (T005)
- Data models: ``FunctionInfo`` / ``ModuleInfo`` (T006)
- Logger bootstrap (T003)
- Path Validator (T007) -- resolves design-review finding H-1 by
  defining a single call-site contract, invoked only from
  ``SyncOrchestrator`` immediately before a file is opened.
- AST Extractor (T012-T014)
- Markdown Renderer (T015)
- README Sync Writer (T016-T017)
- Event Debouncer (T010) -- thread-safe, resolving finding H-2.
- File Watcher (T009)
- Sync Orchestrator (T018-T019) -- includes startup full sync plus
  orphaned-section reconciliation (resolves finding C-1), using the
  D001-decided log message: "Startup reconciliation removed orphaned
  section for module no longer present: {module}".
- CLI entry point (T011, T020-T021): ``python -m src.doc_sync --watch``

Only ``src/`` is read and only ``README.md`` is written; source files are
parsed via ``ast.parse`` only, never executed or imported (NFR-2).
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import re
import signal
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# --------------------------------------------------------------------------
# Constants & configuration (T008)
# --------------------------------------------------------------------------

MARKER_START_TMPL = "<!-- AUTO-DOC:START module={module} -->"
MARKER_END_TMPL = "<!-- AUTO-DOC:END module={module} -->"
MARKER_START_RE = re.compile(r"<!--\s*AUTO-DOC:START module=([\w.]+)\s*-->")
MARKER_END_RE = re.compile(r"<!--\s*AUTO-DOC:END module=([\w.]+)\s*-->")
API_REFERENCE_HEADING_RE = re.compile(r"^##\s+API Reference\s*$", re.MULTILINE)

# Overridable via EventDebouncer's constructor (see L-1 resolution); this is
# only the default used when no explicit window_ms is supplied.
DEFAULT_DEBOUNCE_WINDOW_MS = 400

SRC_DIRNAME = "src"
README_FILENAME = "README.md"

# D001 (resolved 2026-09-03, Option 2): distinct startup-reconciliation
# log message, as opposed to reusing the live on_deleted message.
STARTUP_ORPHAN_LOG_TMPL = (
    "Startup reconciliation removed orphaned section for module no longer "
    "present: %s"
)


# --------------------------------------------------------------------------
# Exception hierarchy (T005)
# --------------------------------------------------------------------------


class DocSyncError(Exception):
    """Base exception for all doc_sync errors."""


class ExtractionError(DocSyncError):
    """Raised when a ``.py`` file cannot be parsed into a ``ModuleInfo``."""


class ReadmeSyncError(DocSyncError):
    """Raised when ``README.md`` cannot be safely read or written."""


# --------------------------------------------------------------------------
# Data models (T006)
# --------------------------------------------------------------------------


@dataclass
class FunctionInfo:
    """A single module-level function's extracted structure."""

    name: str
    signature: str
    docstring: Optional[str]


@dataclass
class ModuleInfo:
    """A single module's extracted structure."""

    module_path: str
    docstring: Optional[str]
    functions: list[FunctionInfo] = field(default_factory=list)


@dataclass
class SyncResult:
    """Outcome of a single ``sync_readme`` call, for logging (NFR-4)."""

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Logger (T003)
# --------------------------------------------------------------------------

logger = logging.getLogger("doc_sync")


def configure_logging(level: int = logging.INFO) -> None:
    """Configure a single stdout ``StreamHandler`` with a plain formatter.

    Matches NFR-4: log output must clearly state pass start, changed
    files, and added/updated/removed sections.
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)


# --------------------------------------------------------------------------
# Path Validator (T007) -- resolves H-1
# --------------------------------------------------------------------------


def is_within_workspace(path: Path, root: Path) -> bool:
    """Return ``True`` if ``path`` resolves to a location inside ``root``.

    Single shared call-site contract (NFR-2): this function is invoked
    only by ``SyncOrchestrator``, once per file, immediately before that
    file is opened -- for both watchdog-triggered and startup-enumerated
    paths. It is never wired directly into the File Watcher or Event
    Debouncer (design-review finding H-1).
    """
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
    except OSError:
        return False
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


# --------------------------------------------------------------------------
# AST Extractor (T012-T014)
# --------------------------------------------------------------------------


def _render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render a function signature string from its ``ast.arguments``.

    Handles all five ``ast.arguments`` component groups: ``posonlyargs``
    (trailing ``/``), ``args``/``defaults``, ``vararg``/bare ``*``,
    ``kwonlyargs``/``kw_defaults``, and ``kwarg`` (resolves M-3).
    """
    args = node.args
    parts: list[str] = []

    positional = list(args.posonlyargs) + list(args.args)
    defaults = list(args.defaults)
    num_no_default = len(positional) - len(defaults)
    for idx, arg in enumerate(positional):
        piece = arg.arg
        if arg.annotation is not None:
            piece += f": {ast.unparse(arg.annotation)}"
        default_idx = idx - num_no_default
        if default_idx >= 0:
            piece += f" = {ast.unparse(defaults[default_idx])}"
        parts.append(piece)
        if args.posonlyargs and idx == len(args.posonlyargs) - 1:
            parts.append("/")

    if args.vararg is not None:
        piece = f"*{args.vararg.arg}"
        if args.vararg.annotation is not None:
            piece += f": {ast.unparse(args.vararg.annotation)}"
        parts.append(piece)
    elif args.kwonlyargs:
        parts.append("*")

    for kwonly_arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
        piece = kwonly_arg.arg
        if kwonly_arg.annotation is not None:
            piece += f": {ast.unparse(kwonly_arg.annotation)}"
        if kw_default is not None:
            piece += f" = {ast.unparse(kw_default)}"
        parts.append(piece)

    if args.kwarg is not None:
        piece = f"**{args.kwarg.arg}"
        if args.kwarg.annotation is not None:
            piece += f": {ast.unparse(args.kwarg.annotation)}"
        parts.append(piece)

    signature = f"{node.name}({', '.join(parts)})"
    if node.returns is not None:
        signature += f" -> {ast.unparse(node.returns)}"
    return signature


def extract_module(path: Path, module_path: str) -> ModuleInfo:
    """Statically parse ``path`` into a ``ModuleInfo`` (never executes it).

    Raises ``ExtractionError`` on decode failure (strict UTF-8, resolves
    M-2), unreadable file, or ``SyntaxError`` -- callers must catch this
    and log a warning rather than letting it propagate (FR-5).
    """
    try:
        source = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"{path}: invalid UTF-8 encoding ({exc})") from exc
    except OSError as exc:
        raise ExtractionError(f"{path}: unable to read file ({exc})") from exc

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ExtractionError(f"{path}: syntax error ({exc})") from exc

    docstring = ast.get_docstring(tree)
    functions: list[FunctionInfo] = []
    for node in tree.body:
        # Only module-level defs; nested functions and class bodies are
        # never visited since we only walk tree.body (FR-2).
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                FunctionInfo(
                    name=node.name,
                    signature=_render_signature(node),
                    docstring=ast.get_docstring(node),
                )
            )

    return ModuleInfo(module_path=module_path, docstring=docstring, functions=functions)


# --------------------------------------------------------------------------
# Markdown Renderer (T015)
# --------------------------------------------------------------------------


def render_block(module_info: ModuleInfo) -> str:
    """Render a full, marker-delimited, deterministic block for a module.

    Identical ``ModuleInfo`` input always produces byte-identical output
    (FR-3's no-diff-on-rerun requirement).
    """
    lines: list[str] = [MARKER_START_TMPL.format(module=module_info.module_path)]
    lines.append(f"### {module_info.module_path}")
    lines.append("")

    if module_info.docstring:
        lines.append(module_info.docstring.strip())
        lines.append("")

    if module_info.functions:
        for fn in module_info.functions:
            lines.append(f"#### `{fn.signature}`")
            lines.append("")
            if fn.docstring:
                lines.append(fn.docstring.strip())
                lines.append("")
    else:
        lines.append("_No module-level functions._")
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    lines.append(MARKER_END_TMPL.format(module=module_info.module_path))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# README Sync Writer (T016-T017)
# --------------------------------------------------------------------------


def _parse_markers(content: str) -> dict[str, dict]:
    """Locate AUTO-DOC marker pairs, keyed by module.

    Returns a dict mapping module -> {"malformed": bool, "span": (s, e) |
    None}. A module is malformed if it has an unmatched or duplicated
    start/end marker (per the requirements' Risks mitigation).
    """
    starts: dict[str, list[re.Match]] = {}
    ends: dict[str, list[re.Match]] = {}
    for m in MARKER_START_RE.finditer(content):
        starts.setdefault(m.group(1), []).append(m)
    for m in MARKER_END_RE.finditer(content):
        ends.setdefault(m.group(1), []).append(m)

    result: dict[str, dict] = {}
    for module in set(starts) | set(ends):
        s_list = starts.get(module, [])
        e_list = ends.get(module, [])
        if len(s_list) != 1 or len(e_list) != 1 or e_list[0].start() < s_list[0].end():
            result[module] = {"malformed": True, "span": None}
            continue
        result[module] = {"malformed": False, "span": (s_list[0].start(), e_list[0].end())}
    return result


def _append_blocks(content: str, blocks: list[str]) -> str:
    """Append new blocks under '## API Reference' if present, else at end."""
    text_to_add = "\n\n".join(blocks)
    heading_match = API_REFERENCE_HEADING_RE.search(content)
    if heading_match:
        insert_at = heading_match.end()
        return content[:insert_at] + "\n\n" + text_to_add + "\n" + content[insert_at:]
    if not content:
        return text_to_add + "\n"
    if not content.endswith("\n"):
        content += "\n"
    return content + "\n" + text_to_add + "\n"


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (temp file + os.replace)."""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def sync_readme(readme_path: Path, blocks: dict[str, Optional[str]]) -> SyncResult:
    """Insert/replace/remove marker blocks in ``README.md``, atomically.

    ``blocks`` maps module path -> full rendered block text (insert or
    replace) or ``None`` (remove that module's block entirely). Malformed
    existing marker pairs are skipped-with-warning rather than guessed at.
    """
    try:
        content = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    except OSError as exc:
        raise ReadmeSyncError(f"Failed to read {readme_path}: {exc}") from exc

    existing = _parse_markers(content)
    result = SyncResult()
    edits: list[tuple[int, int, str]] = []
    appends: list[str] = []

    for module, new_block in blocks.items():
        info = existing.get(module)
        if info is not None and info["malformed"]:
            logger.warning(
                "Skipping module '%s': malformed AUTO-DOC marker pair in %s",
                module,
                readme_path.name,
            )
            result.skipped.append(module)
            continue

        if new_block is None:
            if info is not None:
                start, end = info["span"]
                edits.append((start, end, ""))
                result.removed.append(module)
            continue

        if info is not None:
            start, end = info["span"]
            edits.append((start, end, new_block))
            result.updated.append(module)
        else:
            appends.append(new_block)
            result.added.append(module)

    edits.sort(key=lambda e: e[0], reverse=True)
    for start, end, replacement in edits:
        content = content[:start] + replacement + content[end:]

    if appends:
        content = _append_blocks(content, appends)

    try:
        _atomic_write(readme_path, content)
    except OSError as exc:
        raise ReadmeSyncError(f"Failed to write {readme_path}: {exc}") from exc

    return result


# --------------------------------------------------------------------------
# Event Debouncer (T010) -- resolves H-2 (thread-safety) and L-1 (injectable window)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangeEvent:
    """A normalized filesystem change event for a single ``.py`` file."""

    path: Path
    kind: str  # "created" | "modified" | "deleted"


class EventDebouncer:
    """Coalesce bursts of rapid ``ChangeEvent``s into one batched callback.

    All access to shared state (``_pending``, ``_timer``) is guarded by a
    single lock, since events arrive from the watchdog background thread
    while the debounce timer fires on its own thread (resolves H-2).
    """

    def __init__(
        self,
        callback: Callable[[set[Path]], None],
        window_ms: int = DEFAULT_DEBOUNCE_WINDOW_MS,
    ) -> None:
        self._callback = callback
        self._window_s = window_ms / 1000.0
        self._lock = threading.Lock()
        self._pending: dict[Path, ChangeEvent] = {}
        self._timer: Optional[threading.Timer] = None

    def add_event(self, event: ChangeEvent) -> None:
        """Buffer an event, deduplicating by path, and (re)start the timer."""
        with self._lock:
            self._pending[event.path] = event
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._window_s, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            batch = set(self._pending.keys())
            self._pending.clear()
            self._timer = None
        if batch:
            self._callback(batch)

    def shutdown(self) -> None:
        """Cancel any pending timer and discard buffered events."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()


# --------------------------------------------------------------------------
# File Watcher (T009)
# --------------------------------------------------------------------------


class PyFileEventHandler(FileSystemEventHandler):
    """Filters watchdog events to ``.py`` files and forwards to the debouncer.

    Feeds the Event Debouncer only; path validation happens later, in the
    Sync Orchestrator (see H-1 resolution) -- this handler never opens files.
    """

    def __init__(self, debouncer: EventDebouncer) -> None:
        self._debouncer = debouncer

    def on_created(self, event) -> None:
        self._handle(event, "created")

    def on_modified(self, event) -> None:
        self._handle(event, "modified")

    def on_deleted(self, event) -> None:
        self._handle(event, "deleted")

    def on_moved(self, event) -> None:
        if event.is_directory:
            return
        src_path = Path(event.src_path)
        if src_path.suffix == ".py":
            self._debouncer.add_event(ChangeEvent(src_path, "deleted"))
        dest_path = Path(getattr(event, "dest_path", ""))
        if dest_path.suffix == ".py":
            self._debouncer.add_event(ChangeEvent(dest_path, "created"))

    def _handle(self, event, kind: str) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".py":
            return
        self._debouncer.add_event(ChangeEvent(path, kind))


# --------------------------------------------------------------------------
# Sync Orchestrator (T018-T019) -- resolves H-1 (single validator call-site)
# and C-1 (startup orphan reconciliation, per D001)
# --------------------------------------------------------------------------


class SyncOrchestrator:
    """Coordinates a sync pass: extraction, rendering, and README writing."""

    def __init__(self, workspace_root: Path, src_dir: Path, readme_path: Path) -> None:
        self.workspace_root = workspace_root
        self.src_dir = src_dir
        self.readme_path = readme_path

    def _enumerate_py_files(self) -> list[Path]:
        return sorted(self.src_dir.rglob("*.py"))

    def _module_path_for(self, file_path: Path) -> str:
        try:
            rel = file_path.resolve().relative_to(self.src_dir.resolve())
        except ValueError as exc:
            raise ExtractionError(f"{file_path}: not under src/ root ({exc})") from exc
        return ".".join([SRC_DIRNAME, *rel.with_suffix("").parts])

    def _existing_readme_modules(self) -> set[str]:
        if not self.readme_path.exists():
            return set()
        content = self.readme_path.read_text(encoding="utf-8")
        return set(_parse_markers(content).keys())

    def _build_block(self, file_path: Path, module_path: str) -> Optional[str]:
        try:
            module_info = extract_module(file_path, module_path)
            return render_block(module_info)
        except ExtractionError as exc:
            logger.warning("Skipping %s: %s", file_path, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - never let one file crash the watcher
            logger.warning("Skipping %s: unexpected error rendering block (%s)", file_path, exc)
            return None

    def _apply(self, blocks: dict[str, Optional[str]]) -> Optional[SyncResult]:
        if not blocks:
            return None
        try:
            return sync_readme(self.readme_path, blocks)
        except ReadmeSyncError as exc:
            logger.warning("README sync failed: %s", exc)
            return None

    def startup_sync(self) -> None:
        """Full sync of every ``.py`` file under ``src/`` plus orphan cleanup.

        Resolves C-1: after the full sync, any module whose marker block
        already exists in README.md but has no corresponding file on disk
        is removed in the same pass, using the D001-decided log message.
        """
        logger.info("Startup sync pass: scanning %s", self.src_dir)
        py_files = self._enumerate_py_files()
        blocks: dict[str, Optional[str]] = {}
        current_modules: set[str] = set()

        for file_path in py_files:
            if not is_within_workspace(file_path, self.src_dir):
                logger.warning("Skipping path outside src/ root: %s", file_path)
                continue
            try:
                module_path = self._module_path_for(file_path)
            except ExtractionError as exc:
                logger.warning("Skipping %s: %s", file_path, exc)
                continue
            current_modules.add(module_path)
            block = self._build_block(file_path, module_path)
            if block is not None:
                blocks[module_path] = block

        orphaned = self._existing_readme_modules() - current_modules
        for module in orphaned:
            blocks[module] = None
            logger.info(STARTUP_ORPHAN_LOG_TMPL, module)

        result = self._apply(blocks)
        if result is not None:
            logger.info(
                "Startup sync complete: %d file(s) scanned, %d added, %d updated, "
                "%d removed, %d skipped",
                len(py_files),
                len(result.added),
                len(result.updated),
                len(result.removed),
                len(result.skipped),
            )

    def process_batch(self, paths: set[Path]) -> None:
        """Targeted sync for a debounced batch of changed/deleted paths."""
        logger.info("Sync pass: %d changed path(s)", len(paths))
        blocks: dict[str, Optional[str]] = {}

        for file_path in paths:
            if not is_within_workspace(file_path, self.src_dir):
                logger.warning("Skipping path outside src/ root: %s", file_path)
                continue
            try:
                module_path = self._module_path_for(file_path)
            except ExtractionError as exc:
                logger.warning("Skipping %s: %s", file_path, exc)
                continue
            if file_path.exists():
                block = self._build_block(file_path, module_path)
                if block is not None:
                    blocks[module_path] = block
            else:
                blocks[module_path] = None
                logger.info("Module deleted, removing section: %s", module_path)

        result = self._apply(blocks)
        if result is not None:
            logger.info(
                "Sync pass complete: %d added, %d updated, %d removed, %d skipped",
                len(result.added),
                len(result.updated),
                len(result.removed),
                len(result.skipped),
            )


# --------------------------------------------------------------------------
# CLI entry point (T011, T020-T021)
# --------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.doc_sync",
        description="Watch src/ for .py changes and keep README.md's auto-generated sections in sync.",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run an initial full sync, then watch src/ for changes until Ctrl+C.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    configure_logging()
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.watch:
        parser.print_usage(sys.stderr)
        logger.error("No mode specified; use --watch.")
        return 1

    workspace_root = Path(__file__).resolve().parent.parent
    src_dir = workspace_root / SRC_DIRNAME
    readme_path = workspace_root / README_FILENAME

    if not src_dir.is_dir():
        logger.error("src/ directory not found at %s", src_dir)
        return 1

    orchestrator = SyncOrchestrator(workspace_root, src_dir, readme_path)
    orchestrator.startup_sync()

    debouncer = EventDebouncer(callback=orchestrator.process_batch)
    handler = PyFileEventHandler(debouncer)
    observer = Observer()
    observer.schedule(handler, str(src_dir), recursive=True)
    observer.start()
    logger.info("Watching %s for changes... Press Ctrl+C to stop.", src_dir)

    stop_event = threading.Event()

    def _handle_sigint(signum, frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_sigint)

    try:
        while not stop_event.is_set():
            stop_event.wait(0.5)
    finally:
        debouncer.shutdown()
        observer.stop()
        observer.join()
        logger.info("Watcher stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
