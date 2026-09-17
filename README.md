# Automated Documentation Sync for Code Changes

<!-- AUTO-DOC:START module=src.__init__ -->
### src.__init__

_No module-level functions._
<!-- AUTO-DOC:END module=src.__init__ -->

<!-- AUTO-DOC:START module=src.calculator -->
### src.calculator

A small sample application used to exercise the doc_sync watcher.

This module intentionally contains simple, well-documented arithmetic
functions and a ``Calculator`` class so that ``src/doc_sync.py`` has
meaningful module/function structure to extract and render into
``README.md``. It has no dependency on ``doc_sync.py``.

#### `add(a: float, b: float) -> float`

Return the sum of ``a`` and ``b``.

#### `subtract(a: float, b: float) -> float`

Return the result of subtracting ``b`` from ``a``.

#### `multiply(a: float, b: float) -> float`

Return the product of ``a`` and ``b``.

#### `divide(a: float, b: float) -> float`

Return the result of dividing ``a`` by ``b``.

Raises:
    ZeroDivisionError: If ``b`` is zero.
<!-- AUTO-DOC:END module=src.calculator -->

<!-- AUTO-DOC:START module=src.doc_sync -->
### src.doc_sync

Documentation-sync watcher tool (EPMCDMETST-62888).

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

#### `configure_logging(level: int = logging.INFO) -> None`

Configure a single stdout ``StreamHandler`` with a plain formatter.

Matches NFR-4: log output must clearly state pass start, changed
files, and added/updated/removed sections.

#### `is_within_workspace(path: Path, root: Path) -> bool`

Return ``True`` if ``path`` resolves to a location inside ``root``.

Single shared call-site contract (NFR-2): this function is invoked
only by ``SyncOrchestrator``, once per file, immediately before that
file is opened -- for both watchdog-triggered and startup-enumerated
paths. It is never wired directly into the File Watcher or Event
Debouncer (design-review finding H-1).

#### `_render_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str`

Render a function signature string from its ``ast.arguments``.

Handles all five ``ast.arguments`` component groups: ``posonlyargs``
(trailing ``/``), ``args``/``defaults``, ``vararg``/bare ``*``,
``kwonlyargs``/``kw_defaults``, and ``kwarg`` (resolves M-3).

#### `extract_module(path: Path, module_path: str) -> ModuleInfo`

Statically parse ``path`` into a ``ModuleInfo`` (never executes it).

Raises ``ExtractionError`` on decode failure (strict UTF-8, resolves
M-2), unreadable file, or ``SyntaxError`` -- callers must catch this
and log a warning rather than letting it propagate (FR-5).

#### `render_block(module_info: ModuleInfo) -> str`

Render a full, marker-delimited, deterministic block for a module.

Identical ``ModuleInfo`` input always produces byte-identical output
(FR-3's no-diff-on-rerun requirement).

#### `_parse_markers(content: str) -> dict[str, dict]`

Locate AUTO-DOC marker pairs, keyed by module.

Returns a dict mapping module -> {"malformed": bool, "span": (s, e) |
None}. A module is malformed if it has an unmatched or duplicated
start/end marker (per the requirements' Risks mitigation).

#### `_append_blocks(content: str, blocks: list[str]) -> str`

Append new blocks under '## API Reference' if present, else at end.

#### `_atomic_write(path: Path, content: str) -> None`

Write ``content`` to ``path`` atomically (temp file + os.replace).

#### `sync_readme(readme_path: Path, blocks: dict[str, Optional[str]]) -> SyncResult`

Insert/replace/remove marker blocks in ``README.md``, atomically.

``blocks`` maps module path -> full rendered block text (insert or
replace) or ``None`` (remove that module's block entirely). Malformed
existing marker pairs are skipped-with-warning rather than guessed at.

#### `build_arg_parser() -> argparse.ArgumentParser`

#### `main(argv: Optional[list[str]] = None) -> int`
<!-- AUTO-DOC:END module=src.doc_sync -->
