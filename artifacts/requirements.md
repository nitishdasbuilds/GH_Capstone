# Requirements Document

## Project Overview
An automated documentation sync tool that watches the `src/` directory for changes to Python source files and automatically updates `README.md` so that documentation stays in sync with the latest code. The tool detects changes via a filesystem watcher, extracts structure (module docstring and function signatures/docstrings) via Python's `ast` module, and rewrites clearly-delimited auto-generated sections of `README.md` using rule-based templates — without using an LLM and without touching manually-authored prose elsewhere in the file.

## Functional Requirements

### FR-1: File Watcher for Source Changes
**Description**: The tool continuously monitors the `src/` directory for create/modify/delete events on `.py` files using the `watchdog` library.
**User Story**: As a developer, I want the tool to detect changes to Python files in `src/` automatically, so that I don't have to manually trigger documentation updates.
**Acceptance Criteria**:
- [ ] The tool recursively watches all `.py` files under `src/`.
- [ ] Create, modify, and delete events on `.py` files trigger a doc sync pass.
- [ ] Non-`.py` file events are ignored.
- [ ] The watcher runs as a long-lived process started via `python -m src.doc_sync --watch` and stops cleanly on `Ctrl+C` (SIGINT).

**Priority**: High
**Dependencies**: `watchdog` library

### FR-2: AST-Based Code Structure Extraction
**Description**: On each triggered sync, the tool parses each `.py` file in `src/` using Python's built-in `ast` module to extract: the module-level docstring, and each module-level function's name, signature (parameter names, defaults, `*args`/`**kwargs`, return annotation if present), and docstring.
**User Story**: As a developer, I want the tool to understand my code's structure, so that the generated docs accurately reflect current functions and their signatures.
**Acceptance Criteria**:
- [ ] Module-level docstring is extracted (or treated as absent if missing).
- [ ] Every module-level `def` (sync) is extracted with name, full signature, and docstring (first line + full text separately available).
- [ ] Nested functions (defined inside another function) are NOT extracted.
- [ ] Classes and methods are NOT extracted in this iteration (out of scope; see below).
- [ ] A `.py` file with a syntax error is skipped for that pass, and a warning is logged (see FR-5) without crashing the watcher.

**Priority**: High
**Dependencies**: FR-1

### FR-3: Auto-Generated Markdown Section Sync in README.md
**Description**: The tool writes/updates one auto-generated block per watched Python module inside `README.md`, delimited by HTML comment markers (e.g. `<!-- AUTO-DOC:START module=src.foo -->` ... `<!-- AUTO-DOC:END module=src.foo -->`), rendering the module docstring and a list of its functions with signatures and docstrings. Content outside these markers is never modified.
**User Story**: As a developer, I want auto-generated docs to live in clearly marked sections of README.md, so that my own hand-written prose is preserved.
**Acceptance Criteria**:
- [ ] Each tracked module gets exactly one marker block, identified by a stable key (its dotted module path relative to `src/`).
- [ ] If a marker block for a module doesn't yet exist in `README.md`, it is appended (at end of file, or under a designated `## API Reference` heading if present).
- [ ] If a marker block already exists, only the content between its start/end markers is replaced; surrounding content is untouched.
- [ ] Re-running the sync with no code changes produces no diff (idempotent).
- [ ] Formatting of a block: module dotted path as a subheading, module docstring below it, then a bulleted or subheading list of functions with their signature (as a code span) and docstring text.

**Priority**: High
**Dependencies**: FR-2

### FR-4: Removal of Stale Documentation
**Description**: When a function is deleted or renamed, or a module file is deleted, the corresponding auto-generated content is removed from `README.md` on the next sync pass.
**User Story**: As a developer, I want stale docs for removed/renamed code to disappear automatically, so that README.md never describes functions that no longer exist.
**Acceptance Criteria**:
- [ ] If a function no longer appears in a module's AST, its entry is removed from that module's marker block on next sync.
- [ ] If a module `.py` file is deleted from `src/`, its entire marker block is removed from `README.md`.
- [ ] A renamed function is treated as: old name removed, new name added (no diffing/rename-tracking required).

**Priority**: Medium
**Dependencies**: FR-2, FR-3

### FR-5: Warning Logging on Failure
**Description**: When the tool cannot process a file (e.g. parse error, unreadable file, encoding issue) it logs a warning to stderr/console (including file path and reason) and skips only that file, continuing to process the rest of `src/` and leaving that module's existing doc block (if any) unchanged.
**User Story**: As a developer, I want the tool to keep running and tell me what it couldn't process, so that one bad file doesn't stop documentation sync for the rest of the project.
**Acceptance Criteria**:
- [ ] Errors for one file do not stop the watcher process or block processing of other files.
- [ ] A warning-level log line includes the offending file path and the exception message.
- [ ] The tool's exit code remains 0 in this scenario (the watcher itself isn't considered "failed").

**Priority**: Medium
**Dependencies**: FR-1, FR-2

## Non-Functional Requirements

### NFR-1: Performance
- A sync pass for a single changed file must complete in under 2 seconds for files up to 2,000 lines, so the watcher feels responsive during active development.
- The watcher must not busy-loop or poll the filesystem in a tight loop (must use `watchdog`'s event-driven API).

### NFR-2: Security
- The tool only reads files under `src/` and only writes to `README.md`; it must not execute or `import` the source files it scans (parsing is via `ast.parse`, never `exec`/`import`).
- File paths derived from watcher events must be validated to remain within the workspace root before being opened (no path traversal outside the project directory).

### NFR-3: Scalability
- The tool must handle at least 100 Python files under `src/` without a full-project sync pass exceeding 10 seconds.

### NFR-4: Usability
- Running `python -m src.doc_sync --watch` with no extra configuration must work out of the box against this repo's `src/` and `README.md`.
- Log output must clearly state when a sync pass starts, which files changed, and which doc sections were added/updated/removed.

### NFR-5: Reliability
- The watcher process must keep running across repeated file-save events (e.g. editor autosave, `git checkout`) without crashing or leaking file handles/watches.
- A single malformed file must never crash the watcher (see FR-5).

## Technical Requirements

### Data Models
- **ModuleInfo**: `module_path` (str, dotted path relative to `src/`), `docstring` (str | None), `functions: list[FunctionInfo]`.
- **FunctionInfo**: `name` (str), `signature` (str, rendered from `ast` parameter/return info), `docstring` (str | None).

### API Specifications
- No network/HTTP API in this iteration. The tool exposes a CLI entry point: `python -m src.doc_sync --watch` (continuous) as the only supported invocation for this iteration.

### Technology Stack
- Python 3.x standard library `ast` module for code parsing.
- `watchdog` library for filesystem event watching.
- No LLM or external network calls.

## Constraints and Assumptions

### Constraints
- Only Python (`.py`) files under `src/` are in scope; no other languages.
- Only `README.md` is updated; no per-module `docs/*.md` files in this iteration.
- No AI/LLM-generated content — all doc content is rule-based/templated from AST data.
- Classes and methods are not extracted in this iteration.

### Assumptions
- `README.md` already exists in the repo root and may contain existing hand-written content that must be preserved outside auto-generated marker blocks.
- Developers will not manually edit content inside `<!-- AUTO-DOC:START -->` / `<!-- AUTO-DOC:END -->` blocks, since it will be overwritten on the next sync.
- The tool runs locally on a developer machine (not inside CI) for this iteration, per the "standalone script/tool in this repo only" scope decision.

## Out of Scope
- CI/CD pipeline integration (GitHub Actions, etc.).
- Git hooks (pre-commit/post-commit) as a trigger mechanism.
- JIRA or GitHub PR bot integrations.
- LLM-based documentation summarization.
- Class and method documentation extraction.
- Support for languages other than Python.
- Per-module Markdown files under a `docs/` folder (only `README.md` is updated).
- Rename detection/diffing between old and new function names.

## Success Criteria
- Running the watcher, then adding/modifying/deleting a function in a file under `src/`, results in `README.md`'s corresponding auto-generated section reflecting that change within 2 seconds, with no changes to hand-written README content.
- Deleting a `.py` module file removes its entire auto-generated section from `README.md`.
- Re-running a sync with no source changes produces zero diff in `README.md`.
- A file with a Python syntax error does not crash the watcher and produces a logged warning.

## Risks and Mitigations
- **Risk**: Marker-based section replacement could corrupt README.md if markers are manually edited or duplicated. **Mitigation**: Validate marker pairs on each pass; if malformed/duplicated markers are detected for a module, skip that module's update and log a warning rather than guessing.
- **Risk**: Rapid successive file-save events (e.g. editor autosave) could trigger redundant sync passes. **Mitigation**: Debounce filesystem events (e.g. short delay/coalescing window) before running a sync pass.
- **Risk**: Large signatures/docstrings could produce unwieldy README content. **Mitigation**: Render signatures as single-line code spans and preserve docstrings verbatim without additional formatting logic.

## Appendix

### JIRA Story Reference
- **Story ID**: EPMCDMETST-62888
- **Summary**: Automated Documentation Sync for Code Changes
- **Link**: https://jiraeu.epam.com/browse/EPMCDMETST-62888

### Revision History
- 2026-09-03: Initial requirements gathered by Requirements Agent, incorporating stakeholder answers on trigger mechanism (file watcher), source scope (Python only), doc target (README.md via marker blocks), change detection (AST), update approach (rule-based templates), scope (standalone tool), and failure handling (skip + warn).
