# System Architecture Document

## 1. Executive Summary
This system is a local, standalone command-line tool (`src/doc_sync.py`) that watches the `src/` directory for changes to Python files and keeps auto-generated sections of `README.md` in sync with the code. It runs as a single long-lived process on a developer's machine, using an event-driven filesystem watcher (`watchdog`) to detect file changes, Python's `ast` module to statically extract module/function structure (no `exec`/`import` of scanned code), and a rule-based (non-LLM) template renderer to write clearly delimited auto-generated blocks into `README.md`. The design favors simplicity, safety (read-only parsing, restricted write target), idempotency, and resilience to per-file errors over scalability or distribution — this is an in-process, single-machine developer tool, not a service.

## 2. Architecture Overview

### 2.1 Architecture Style
**Event-driven, single-process, modular monolith (CLI tool).**

**Rationale**: The requirements describe a standalone local tool with one entry point (`python -m src.doc_sync --watch`), no network API, no multi-user concerns, and a single writable output file (`README.md`). A microservices or client-server style would add operational complexity with no corresponding benefit. An event-driven internal design (filesystem events → debounce → sync pipeline) directly matches FR-1/NFR-1's requirement to avoid polling and to react to `watchdog` events.

### 2.2 High-Level Component Diagram
```
                          Developer Machine (single process)
        ┌───────────────────────────────────────────────────────────────┐
        │                                                                │
        │   ┌───────────────┐      events       ┌───────────────────┐   │
        │   │  File Watcher │ ───────────────▶   │  Event Debouncer  │   │
        │   │  (watchdog)   │                    │  (coalesce bursts)│   │
        │   └───────────────┘                    └─────────┬─────────┘   │
        │          ▲                                        │             │
        │          │ watches                                ▼             │
        │   ┌───────────────┐                       ┌───────────────────┐│
        │   │   src/*.py    │◀──── read-only ───────│   Sync Orchestrator│
        │   │ (filesystem)  │       ast.parse        │  (pipeline runner) │
        │   └───────────────┘                        └─────────┬─────────┘
        │                                                        │           │
        │                                              ┌─────────▼─────────┐ │
        │                                              │  AST Extractor    │ │
        │                                              │ (ModuleInfo/      │ │
        │                                              │  FunctionInfo)    │ │
        │                                              └─────────┬─────────┘ │
        │                                                        │           │
        │                                              ┌─────────▼─────────┐ │
        │                                              │ Markdown Renderer │ │
        │                                              │ (rule-based       │ │
        │                                              │  templates)       │ │
        │                                              └─────────┬─────────┘ │
        │                                                        │           │
        │                                              ┌─────────▼─────────┐ │
        │                                              │ README Sync Writer│ │
        │                                              │ (marker-block     │ │
        │                                              │  read/patch/write)│ │
        │                                              └─────────┬─────────┘ │
        │                                                        │           │
        │                                                        ▼           │
        │                                                  README.md        │
        │                                                                    │
        │   ┌───────────────┐                                               │
        │   │  Logger        │◀── warnings/info from all components         │
        │   │  (stdlib logging)                                             │
        │   └───────────────┘                                               │
        └───────────────────────────────────────────────────────────────┘
```

### 2.3 Component Descriptions

#### Component: File Watcher
- **Purpose**: Detect create/modify/delete events on `.py` files under `src/`.
- **Responsibilities**:
  - Register a recursive `watchdog` `Observer` on `src/`.
  - Filter events to `.py` files only; ignore all other file types.
  - Emit normalized internal events (path, change type) to the Event Debouncer.
- **Technology**: `watchdog.observers.Observer` + a custom `FileSystemEventHandler`.
- **Interfaces**: Consumes OS filesystem events; produces `ChangeEvent(path, kind)` objects.
- **Scaling**: N/A (single watcher, single machine); relies on OS-level file event APIs (inotify/FSEvents/ReadDirectoryChangesW) for efficiency, satisfying NFR-1's no-polling requirement.

#### Component: Event Debouncer
- **Purpose**: Coalesce bursts of rapid events (e.g., autosave, `git checkout`) into a single sync trigger, per the Risks section of requirements.
- **Responsibilities**:
  - Buffer incoming `ChangeEvent`s within a short window (e.g., 300–500ms).
  - Deduplicate multiple events for the same path within the window.
  - Trigger the Sync Orchestrator once the window elapses with the set of changed paths.
- **Technology**: Plain Python using `threading.Timer` (or a simple loop with timestamps); no external dependency needed.
- **Interfaces**: Consumes `ChangeEvent`s; produces a batched `set[Path]` to the Sync Orchestrator.
- **Scaling**: In-memory, single-process; bounded by number of files under `src/` (NFR-3: ≤100 files comfortably).

#### Component: Sync Orchestrator
- **Purpose**: Coordinate a single sync pass: decide which modules need re-extraction, call the AST Extractor, call the Markdown Renderer, and call the README Sync Writer; also handles full-project sync at startup.
- **Responsibilities**:
  - On startup, enumerate all `.py` files under `src/` for an initial full sync.
  - On a debounced batch, run the pipeline only for changed/deleted modules (targeted sync).
  - Determine deletions (module file removed) and route them to the README Sync Writer for block removal.
  - Catch and route per-file exceptions to the Logger without aborting the batch (FR-5).
- **Technology**: Plain Python module/class (`SyncOrchestrator`) within `src/doc_sync.py` (or a package under `src/doc_sync/`).
- **Interfaces**: Internal function calls only; no external API.
- **Scaling**: Processes files sequentially (simplicity over throughput); acceptable per NFR-3 (100 files / 10s budget), can be parallelized later if needed (see Future Considerations).

#### Component: AST Extractor
- **Purpose**: Statically parse a `.py` file into a `ModuleInfo` data structure without executing it.
- **Responsibilities**:
  - Read file content (with explicit UTF-8 decoding, tolerant error handling for encoding issues).
  - Call `ast.parse(source, filename=path)`; on `SyntaxError`, raise a typed extraction error caught upstream.
  - Walk the module's top-level `ast.FunctionDef` nodes (excluding nested functions and class bodies) to build `FunctionInfo` entries.
  - Render each function's signature as a string from `ast.arguments` (positional, defaults, `*args`, `**kwargs`, return annotation).
- **Technology**: Python stdlib `ast`, `inspect`-free (pure AST walking, no `exec`/`import`) — satisfies NFR-2.
- **Interfaces**: `extract_module(path: Path) -> ModuleInfo` (raises `ExtractionError` on failure).
- **Scaling**: O(file size); bounded by NFR-1 (2s per file up to 2,000 lines).

#### Component: Markdown Renderer
- **Purpose**: Convert a `ModuleInfo` into the exact auto-generated Markdown block text for a module.
- **Responsibilities**:
  - Render module dotted path as a subheading (e.g., `### src.foo`).
  - Render module docstring (or omit if `None`).
  - Render each function as a subheading/bullet with its signature as a code span and its docstring text.
  - Guarantee deterministic, idempotent output (identical `ModuleInfo` → byte-identical block) — required for FR-3's no-diff-on-rerun criterion.
- **Technology**: Plain Python string templates (f-strings), no external templating engine (keeps output fully deterministic and dependency-free).
- **Interfaces**: `render_block(module_info: ModuleInfo) -> str`.
- **Scaling**: O(number of functions); negligible cost.

#### Component: README Sync Writer
- **Purpose**: Safely read, patch, and write `README.md`, replacing only the marker-delimited blocks that changed.
- **Responsibilities**:
  - Parse existing `README.md` to locate `<!-- AUTO-DOC:START module=X -->` / `<!-- AUTO-DOC:END module=X -->` pairs and build a map of `module -> (start_idx, end_idx)`.
  - Validate marker integrity (no unmatched/duplicated markers per module); on malformation, skip that module and log a warning (per Risks section) rather than guessing.
  - For each changed module: replace its block content in place, or append a new block (under `## API Reference` if present, else at end of file) if none exists yet.
  - For each deleted module: remove its entire block (including markers).
  - Write the file atomically (write to a temp file in the same directory, then `os.replace`) to avoid partial/corrupted writes if the process is interrupted mid-write.
- **Technology**: Plain Python file I/O + `re`/string parsing for marker detection; `os.replace` for atomic writes.
- **Interfaces**: `sync_readme(readme_path: Path, blocks: dict[str, str | None]) -> SyncResult` (`None` value signals block removal).
- **Scaling**: O(README size + number of blocks); README size is expected to be small (developer-authored doc file).

#### Component: Path Validator
- **Purpose**: Ensure all paths derived from watcher events resolve inside the workspace root before being opened (NFR-2).
- **Responsibilities**: Resolve each candidate path with `Path.resolve()` and confirm it is relative to the workspace root; reject/log-and-skip otherwise.
- **Technology**: Python stdlib `pathlib`.
- **Interfaces**: `is_within_workspace(path: Path, root: Path) -> bool`, called by the Sync Orchestrator before any file is opened.
- **Scaling**: O(1) per file.

#### Component: Logger
- **Purpose**: Provide structured, leveled console logging for sync pass start/end, per-file changes, and warnings (FR-5, NFR-4).
- **Responsibilities**: Emit `INFO` logs for sync pass start, files changed, sections added/updated/removed; emit `WARNING` logs for per-file failures with file path + exception message; never raise.
- **Technology**: Python stdlib `logging`, configured with a `StreamHandler` to stderr/stdout and a simple formatter.
- **Interfaces**: Standard `logging.getLogger(__name__)` used by all components.
- **Scaling**: N/A.

## 3. Technology Stack

### 3.1 Frontend
- Not applicable — this is a CLI-only developer tool with no UI.

### 3.2 Backend
- **Language**: Python 3.x (matching the requirement's technical stack and the existing repo).
- **Framework**: None (plain stdlib + `watchdog`); a framework would be over-engineering for a single-purpose CLI tool.
- **API Style**: None — no network API in this iteration (per requirements' API Specifications).
- **Entry Point**: `python -m src.doc_sync --watch`, implemented via `argparse` for CLI argument parsing and a `if __name__ == "__main__":` guard.
- **Authentication**: Not applicable (local process, no network exposure).

### 3.3 Database
- Not applicable. The system has no database; its only persistent state is the workspace filesystem (`src/*.py` read-only, `README.md` read/write). No caching layer, search index, or message queue is required given the tool's scope and NFR-3's modest scale (≤100 files, ≤10s full sync).

### 3.4 Infrastructure
- **Cloud Provider**: None — runs entirely on the developer's local machine.
- **Container Orchestration**: None.
- **CI/CD**: Out of scope per requirements (explicitly excludes CI/CD pipeline integration); repo may still run unit tests locally via `pytest` but no pipeline is designed here.
- **Monitoring**: Console logging only (see Logger component); no external monitoring stack, consistent with a local dev tool.
- **Logging**: Python stdlib `logging` to stdout/stderr; no log aggregation needed at this scale.

### 3.5 Third-Party Services
- **`watchdog`** (PyPI package): Purpose — event-driven, cross-platform filesystem watching, avoiding a manual polling loop (NFR-1). No other third-party services or network calls are used, per the explicit "no LLM or external network calls" constraint.

## 4. Data Architecture

### 4.1 Data Models
These are in-memory dataclasses only — there is no database; they exist for the duration of a sync pass.

**ModuleInfo**
| Field | Type | Constraints | Purpose |
|---|---|---|---|
| `module_path` | `str` | dotted path relative to `src/` (e.g. `src.foo.bar`) | Stable key used for marker matching and README block identity |
| `docstring` | `str \| None` | raw module docstring text, or `None` if absent | Rendered under the module subheading |
| `functions` | `list[FunctionInfo]` | ordered as they appear in source | Rendered as the module's function list |

**FunctionInfo**
| Field | Type | Constraints | Purpose |
|---|---|---|---|
| `name` | `str` | function identifier | Rendered as function subheading/bullet label |
| `signature` | `str` | rendered from `ast.arguments` + return annotation | Rendered as a single-line code span |
| `docstring` | `str \| None` | first line and full text both available | Rendered as descriptive text under the signature |

**No relational schema or indexes are needed** — these are transient in-memory structures produced per sync pass and discarded after rendering.

### 4.2 Data Flow Diagram
```
 watchdog event ──▶ Path Validator ──▶ Event Debouncer ──▶ Sync Orchestrator
                                                                │
                                     ┌──────────────────────────┼───────────────────────────┐
                                     │ (for each changed module) │ (for each deleted module) │
                                     ▼                           ▼
                             AST Extractor              (no extraction — mark for removal)
                                     │
                                     ▼
                             Markdown Renderer
                                     │
                                     ▼
                          README Sync Writer ──▶ README.md (atomic write)
                                     │
                                     ▼
                                  Logger (INFO: sections added/updated/removed)
```

**Detailed Flow for "Function added to an existing module":**
1. `watchdog` emits a `modified` event for `src/foo.py` → Path Validator confirms it resolves within the workspace root.
2. Event Debouncer buffers the event for the coalescing window, then forwards `{src/foo.py}` to the Sync Orchestrator.
3. Sync Orchestrator calls AST Extractor on `src/foo.py`, producing a `ModuleInfo` with the updated `functions` list.
4. Markdown Renderer converts `ModuleInfo` into the full `<!-- AUTO-DOC:START module=src.foo -->...<!-- AUTO-DOC:END module=src.foo -->` block text.
5. README Sync Writer locates the existing marker pair for `src.foo` in `README.md`, replaces only the content between the markers, and writes the file atomically.
6. Logger emits an `INFO` line: sync pass started, `src/foo.py` changed, section `src.foo` updated.
7. **Error handling path**: if step 3 raises `ExtractionError` (e.g. `SyntaxError`), the Sync Orchestrator catches it, logs a `WARNING` with the file path and exception message, leaves the module's existing README block untouched, and continues processing any other changed files in the batch (FR-5).

### 4.3 Caching Strategy
- No caching layer is used. Given NFR-1/NFR-3 targets (single file <2s, 100 files <10s) and the fact that `ast.parse` on files up to a few thousand lines is fast, re-parsing on every triggered sync is simpler and avoids cache-invalidation complexity that would otherwise need to track file mtimes/hashes. This can be revisited (see Future Considerations) if file counts grow substantially.

## 5. API Design

### 5.1 API Endpoints
Not applicable — no network/HTTP API exists in this iteration (per the requirements' API Specifications, the only interface is the CLI entry point below).

**CLI Interface**
- **Command**: `python -m src.doc_sync --watch`
- **Behavior**: Runs an initial full sync of all `.py` files under `src/`, then starts the `watchdog` observer and blocks until `SIGINT` (`Ctrl+C`), at which point it stops the observer and exits with code `0`.
- **Errors**: Per-file errors never raise to the CLI level (FR-5); only fatal startup errors (e.g. `src/` directory missing) produce a non-zero exit code with a clear stderr message.

### 5.2 API Versioning Strategy
Not applicable — no external API surface to version. The internal Python module functions (`extract_module`, `render_block`, `sync_readme`) are considered internal implementation details, not a versioned public API.

### 5.3 Error Handling
- Internal errors are represented by a small typed exception hierarchy (e.g. `DocSyncError` base, `ExtractionError`, `ReadmeSyncError`) so the Sync Orchestrator can catch narrowly and log meaningfully rather than using bare `except Exception`.
- All caught per-file errors result in a `logging.warning(...)` call including the file path and `str(exception)`, and do not propagate — satisfying FR-5 and NFR-5 (no crash on malformed input).

## 6. Security Architecture

### 6.1 Authentication & Authorization
- Not applicable — single-user local process with no network exposure, no login, and no multi-tenant concerns.

### 6.2 Data Security
- **Encryption in Transit**: Not applicable (no network transport).
- **Encryption at Rest**: Not applicable (relies on the developer's local filesystem/OS-level protections; the tool introduces no additional persistent secrets or credentials).
- **Sensitive Data**: The tool only reads Python source and docstrings and writes derived text into `README.md`; it introduces no PII handling. Developers are responsible for not putting secrets in docstrings, same as with any documentation tool.

### 6.3 Security Layers
- **Network Security**: Not applicable (no listening ports, no outbound calls).
- **Application Security**:
  - Source files are only ever parsed via `ast.parse`, never `exec`/`import`ed, eliminating arbitrary code execution risk from scanning untrusted-looking `.py` content (NFR-2).
  - The Path Validator enforces that any path derived from a filesystem event resolves within the workspace root, preventing path traversal (e.g. via symlinks pointing outside the project) before any file is opened for reading (NFR-2).
  - Writes are strictly scoped to `README.md`; no other file is ever opened for writing.
- **API Security**: Not applicable — no API surface.

### 6.4 Compliance
- Not applicable — the tool processes only source code and documentation text local to the repository; no regulated data categories (PII/PHI/PCI) are in scope.

## 7. Scalability & Performance

### 7.1 Scalability Strategy
- **Horizontal Scaling**: Not applicable — single-process, single-machine developer tool by design.
- **Vertical Scaling**: Naturally benefits from a faster local machine (more CPU for `ast.parse`, faster disk I/O), but no explicit vertical-scaling design is required at this scope.
- **Auto-scaling**: Not applicable.

### 7.2 Performance Optimization
- **Targeted sync**: Only changed/deleted modules (as reported by the debounced event batch) are re-extracted and re-rendered; unaffected modules' README blocks are left untouched, minimizing per-event work.
- **Debouncing**: Coalesces rapid successive save events into a single sync pass, avoiding redundant AST parses and README writes (addresses the "rapid successive file-save events" risk).
- **Atomic, single-pass README write**: The README Sync Writer performs one read and one atomic write per sync pass (not per module), keeping I/O overhead low even when multiple modules changed in the same batch.

### 7.3 Performance Targets
- **Single-file sync pass**: < 2 seconds for files up to 2,000 lines (NFR-1).
- **Full-project sync pass**: < 10 seconds for up to 100 Python files under `src/` (NFR-3).
- **Event responsiveness**: No busy-loop polling; reaction to changes is bounded by the debounce window (target: a few hundred milliseconds) plus processing time.

## 8. Reliability & Availability

### 8.1 High Availability
- Not applicable in the traditional sense (no uptime SLA, single local process). "Availability" here means the watcher process keeps running across repeated save events without crashing (NFR-5).
- **Redundancy / Load Balancing**: Not applicable — single process, single machine.

### 8.2 Disaster Recovery
- **RTO/RPO**: Not applicable — no persisted service state beyond `README.md`, which is itself version-controlled by the developer's normal Git workflow (providing implicit recovery via `git checkout`/`git diff` if an update is ever unwanted).
- **Backup Strategy**: Atomic writes (temp file + `os.replace`) ensure `README.md` is never left partially written even if the process is killed mid-write.
- **Failover Procedures**: Not applicable.

### 8.3 Fault Tolerance
- **Circuit Breakers / Retry Logic**: Not required — there are no flaky remote dependencies; local file I/O failures are logged and the affected file is skipped for that pass rather than retried in a loop (avoids masking a persistent problem).
- **Graceful Degradation**: A single malformed/unreadable file degrades only that module's documentation (left stale with a warning) while all other modules continue to sync normally (FR-5, NFR-5).
- **Health Checks**: Not applicable to a local CLI process; process liveness is simply whether the terminal session is still running.

## 9. Monitoring & Observability

### 9.1 Metrics
- No metrics backend is used given the tool's local, single-user scope. Effective "metrics" are surfaced directly via log lines: number of files changed per pass, number of sections added/updated/removed, and per-pass duration (optionally logged at `INFO` or `DEBUG` level to help verify NFR-1/NFR-3 targets during development).

### 9.2 Logging
- **Log Levels**: `INFO` for pass start/end and section-level changes; `WARNING` for per-file skips/failures; `ERROR` reserved for fatal startup conditions (e.g. `src/` missing).
- **Log Format**: Plain text, single-line, human-readable (e.g. `2026-09-03 10:00:00 INFO Sync pass: 2 files changed, 1 section updated`), matching NFR-4's requirement for clear console output — structured JSON logging is unnecessary overhead for a local console tool.
- **Log Aggregation**: Not applicable — output goes to the developer's terminal (stdout/stderr) only.
- **Retention**: Not applicable — no persisted logs beyond terminal scrollback.

### 9.3 Alerting
- Not applicable — no on-call rotation or alert channel; the developer directly observes console warnings in real time.

### 9.4 Distributed Tracing
- Not applicable — single in-process pipeline with no distributed calls.

## 10. Key Design Decisions

### Decision 1: Marker-block replacement strategy for README.md
- **Context**: FR-3/FR-4 require preserving hand-written README content while keeping auto-generated sections in sync, and must support safe removal on module/function deletion.
- **Options Considered**:
  1. Regenerate the entire `README.md` from a template each pass — simple, but destroys any hand-written content (violates FR-3).
  2. HTML-comment marker pairs (`<!-- AUTO-DOC:START module=X -->...END-->`) scoped per module — precise, preserves surrounding content, human-readable in raw Markdown.
  3. A separate `docs/*.md` file per module — avoids touching `README.md` at all, but explicitly out of scope per requirements.
- **Decision**: Option 2 — per-module HTML comment marker pairs.
- **Rationale**: Directly matches the requirement's specified marker format, keeps the diff surface minimal (only the changed module's block changes), and supports precise removal (FR-4) by deleting the whole marker pair.
- **Consequences**: The README Sync Writer must defensively validate marker pairing/uniqueness (risk noted in requirements) and skip-with-warning on malformed markers rather than guessing.
- **Related Requirements**: FR-3, FR-4.

### Decision 2: Debounced, event-driven watcher instead of polling
- **Context**: NFR-1 explicitly forbids busy-loop/polling; FR-1 requires reacting to create/modify/delete events.
- **Options Considered**:
  1. Polling loop that periodically re-scans `src/` for mtime changes — simple but violates NFR-1 and wastes CPU.
  2. `watchdog` OS-level event API with an in-process debounce buffer.
  3. `watchdog` with no debounce — reacts to every raw event, risking redundant syncs on autosave bursts.
- **Decision**: Option 2 — `watchdog` events plus a short in-process debounce window.
- **Rationale**: Satisfies NFR-1 (event-driven, no polling) while mitigating the "rapid successive save events" risk called out in the requirements.
- **Consequences**: Introduces a small fixed latency (the debounce window) before a sync pass runs; acceptable given the 2-second NFR-1 budget still leaves ample headroom.
- **Related Requirements**: FR-1, NFR-1, Risks section.

### Decision 3: `ast`-only parsing, never `exec`/`import`
- **Context**: NFR-2 mandates the tool must not execute or import scanned source files.
- **Options Considered**:
  1. `importlib` + `inspect` to introspect live modules — richer runtime info but executes arbitrary code, a security risk (violates NFR-2).
  2. `ast.parse` static analysis — no execution, slightly more manual work to render signatures/docstrings.
- **Decision**: Option 2 — pure `ast` static parsing.
- **Rationale**: Directly required by NFR-2; also inherently safer for a tool that reacts automatically to filesystem changes without human review before parsing.
- **Consequences**: Cannot resolve runtime-computed defaults or dynamically generated functions — acceptable given FR-2's explicit scope (module-level `def`s only, no dynamic introspection required).
- **Related Requirements**: FR-2, NFR-2.

### Decision 4: Sequential, single-process pipeline (no async/multiprocessing)
- **Context**: The tool must meet modest performance targets (NFR-1: 2s/file, NFR-3: 10s/100 files) without introducing operational complexity.
- **Options Considered**:
  1. Sequential processing in the main thread/process — simplest to reason about and debug.
  2. `multiprocessing` pool to parse files in parallel — faster for large file counts, but adds complexity (IPC, pickling `ModuleInfo`) disproportionate to the stated scale.
  3. `asyncio` with async file I/O — file I/O and `ast.parse` are CPU/sync-bound, so async offers little benefit here.
- **Decision**: Option 1 — sequential processing.
- **Rationale**: At ≤100 files with a 10-second budget, sequential `ast.parse` calls comfortably meet the target on typical developer hardware; added concurrency would increase complexity without clear necessity.
- **Consequences**: If the project scale grows far beyond 100 files, a future revision could introduce a process pool (see Future Considerations).
- **Related Requirements**: NFR-1, NFR-3.

### Decision 5: Atomic file writes for README.md
- **Context**: NFR-5 requires the tool never crash or corrupt state across repeated events; a crash mid-write to `README.md` would corrupt the file.
- **Options Considered**:
  1. Direct in-place write (`open(path, "w")` then write) — simplest, but a crash mid-write leaves a truncated/corrupted file.
  2. Write to a temp file in the same directory, then `os.replace()` onto `README.md` — atomic on POSIX and Windows (same-volume rename).
- **Decision**: Option 2 — temp file + atomic replace.
- **Rationale**: Guarantees `README.md` is always either fully the old version or fully the new version, never partially written, protecting the developer's hand-written content.
- **Consequences**: Slightly more I/O code (temp file creation/cleanup) but negligible performance cost.
- **Related Requirements**: NFR-5, FR-3.

## 11. Deployment Architecture

### 11.1 Environments
- **Development**: The only environment — this tool runs directly on a developer's local machine against their working copy of the repository. No staging/production environments apply, per the requirement's explicit "runs locally on a developer machine (not inside CI)" assumption.

### 11.2 Deployment Strategy
- **Deployment Method**: None required — the tool is invoked directly via `python -m src.doc_sync --watch` from the repo checkout; there is no packaging/release pipeline in this iteration.
- **Rollback Strategy**: Standard Git workflow — if an auto-generated README change is unwanted, the developer can `git diff`/`git checkout -- README.md` like any other local change.
- **Database Migrations**: Not applicable (no database).

### 11.3 Infrastructure as Code
- Not applicable — no cloud infrastructure is provisioned.

## 12. Development Guidelines

### 12.1 Code Organization
- **Project Structure**:
  ```
  src/
    doc_sync.py        # CLI entry point (argparse, wiring) OR package: src/doc_sync/
                        #   __main__.py     - CLI entry point
                        #   watcher.py      - File Watcher + Event Debouncer
                        #   orchestrator.py - Sync Orchestrator
                        #   extractor.py    - AST Extractor (ModuleInfo/FunctionInfo)
                        #   renderer.py     - Markdown Renderer
                        #   readme_writer.py- README Sync Writer (marker parsing/patching)
                        #   errors.py       - DocSyncError hierarchy
  tests/
    test_doc_sync.py   # unit/integration tests per verification phase
  README.md
  ```
  A single-file `src/doc_sync.py` is acceptable for this scope; splitting into a small `src/doc_sync/` package (as sketched above) is preferred once the implementation grows past a few hundred lines, to keep each component's responsibility (per Section 2.3) independently testable.
- **Module Boundaries**: Each component in Section 2.3 maps to one internal module with a narrow, pure-function-style public interface (e.g. `extract_module`, `render_block`, `sync_readme`), keeping the AST Extractor and Markdown Renderer free of filesystem side effects so they can be unit tested with in-memory strings.
- **Dependency Management**: Declared in `requirements.txt` (already present in the repo); only new dependency is `watchdog`.

### 12.2 Development Workflow
- **Branching Strategy**: Standard trunk-based or feature-branch workflow per existing repo conventions (not redefined here).
- **Code Review**: Handled by the pipeline's `code_review` phase (per the orchestrator's phase sequence) — architecture does not need to redefine this.
- **Testing Requirements**: Unit tests for the AST Extractor (signature/docstring extraction edge cases), the Markdown Renderer (idempotent output), and the README Sync Writer (marker insert/replace/remove, malformed-marker handling); an integration test simulating a full watch-trigger-sync cycle without requiring real filesystem events (e.g. by invoking the Sync Orchestrator directly with a synthetic change set).

### 12.3 Documentation Requirements
- **API Documentation**: Not applicable (no network API); the CLI's `--help` output (via `argparse`) documents usage.
- **Code Documentation**: Each extracted-facing function should have a docstring consistent with what the tool itself expects to parse (dogfooding), but this is not a hard architectural requirement.
- **Architecture Decision Records**: Captured inline in Section 10 of this document; no separate ADR directory is introduced given the project's small scope.

## 13. Migration Strategy (If Applicable)
Not applicable — this is a new tool being added to the repository, not a replacement for an existing system. The only "migration" concern is the first full sync pass on startup, which will insert new marker blocks into the existing `README.md` without disturbing current hand-written content (handled by the README Sync Writer's append-if-missing behavior).

## 14. Risks & Mitigations

### Risk 1: Marker corruption from manual edits or duplication
- **Probability**: Medium
- **Impact**: Medium
- **Mitigation**: README Sync Writer validates marker pairing/uniqueness per module before patching; malformed markers cause that module's update to be skipped with a logged warning rather than an unpredictable rewrite.
- **Contingency**: Since `README.md` is version-controlled, a developer can manually fix or remove the malformed markers and let the next sync pass re-insert a clean block.

### Risk 2: Redundant sync passes from rapid successive save events
- **Probability**: High (common with editor autosave)
- **Impact**: Low (wasted CPU/log noise, not correctness)
- **Mitigation**: Event Debouncer coalesces events within a short window before triggering a sync pass.
- **Contingency**: If debounce window proves too short/long in practice, it is a single configurable constant to tune.

### Risk 3: Large/unwieldy docstrings or signatures degrading README readability
- **Probability**: Medium
- **Impact**: Low
- **Mitigation**: Signatures are rendered as single-line code spans; docstrings are preserved verbatim without extra formatting logic, per requirements' explicit mitigation.
- **Contingency**: None needed beyond developer discipline in writing reasonably-sized docstrings; out of scope to auto-truncate.

### Risk 4: Path traversal via crafted/symlinked paths in watcher events
- **Probability**: Low
- **Impact**: High (could read/write outside the project)
- **Mitigation**: Path Validator resolves and checks every candidate path against the workspace root before any open() call (NFR-2).
- **Contingency**: Any rejected path is logged as a warning and simply skipped; no file operation occurs.

### Risk 5: Process interrupted mid-write corrupting README.md
- **Probability**: Low
- **Impact**: High (would corrupt the developer's documentation file)
- **Mitigation**: Atomic writes via temp file + `os.replace()` (Decision 5).
- **Contingency**: Git version history provides a recovery path even in the unlikely event of an unexpected write failure.

## 15. Open Questions
- Should the debounce window and full-vs-targeted sync thresholds be hardcoded constants or exposed as optional CLI flags? (Architecture allows either; recommend starting with hardcoded sensible defaults and revisiting during implementation if needed.)
- Exact placement rule when no `## API Reference` heading exists and the file has other trailing sections (e.g., a `## License` at the very end) — recommend appending new blocks immediately before the first existing `<!-- AUTO-DOC:START -->` block if any exist, otherwise at end of file; to be finalized during implementation planning.

## 16. Future Considerations
- Parallelizing AST extraction (e.g. `multiprocessing.Pool`) if the project's file count grows well beyond the 100-file NFR-3 target.
- Optional support for class/method documentation extraction, explicitly out of scope for this iteration.
- Optional CI integration (e.g. a "check mode" that fails if README.md would differ from a fresh sync), explicitly out of scope for this iteration but architecturally compatible since the Sync Orchestrator/Renderer/Writer are pure enough to run in a "dry-run diff" mode without code changes to their core logic.

## 17. Appendix

### 17.1 Glossary
- **Marker block**: A pair of HTML comments (`<!-- AUTO-DOC:START module=X -->` / `<!-- AUTO-DOC:END module=X -->`) delimiting auto-generated content for one module in `README.md`.
- **Debounce**: Coalescing multiple rapid events into a single triggered action after a quiet period.
- **Idempotent sync**: Running the sync pass again with no source changes produces no diff in `README.md`.

### 17.2 References
- Requirements Document: `artifacts/requirements.md`

### 17.3 Revision History
- 2026-09-03: Initial architecture design by Architecture Agent.
