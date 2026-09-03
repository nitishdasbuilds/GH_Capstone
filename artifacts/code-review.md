# Code Review Report

## Review Summary
- **Files Reviewed**: `src/doc_sync.py`, `src/calculator.py`
- **Requirements Reference**: `artifacts/requirements.md`
- **Architecture Reference**: `artifacts/architecture.md`
- **Implementation Plan Reference**: `artifacts/impl-plan.md`
- **Review Date**: 2026-09-03
- **Reviewed By**: Code Review Agent

### Overall Assessment
**CHANGES REQUIRED**

**Verdict Rationale**: Correctness and Error Handling both carry blocking defects: exceptions raised inside `render_block()` (and a path-containment mismatch that can cause `_module_path_for()` to raise `ValueError`) are **not** caught by `SyncOrchestrator._build_block`/`startup_sync`/`process_batch`, contradicting the architecture's explicit "catch and route per-file exceptions ... without aborting the batch" design and violating FR-5/NFR-5's no-crash guarantee. A Fail on Correctness is automatically blocking per review rules. Dependency pinning and Python-version declaration also diverge from `impl-plan.md`'s T002 decisions.

### Criteria Scorecard

| Criterion | Verdict | Summary |
|-----------|---------|---------|
| Correctness | Fail | Uncaught exceptions in the render/path-derivation path can crash the watcher or drop a batch silently; validated boundary (workspace root) doesn't match the boundary assumed by module-path derivation (`src/`). |
| Security | Partial | Core NFR-2 controls (no exec/import, path containment) are correctly implemented; atomic-write helper silently narrows `README.md`'s file permissions on every sync. |
| Error Handling | Fail | `render_block()` call sits outside the `try/except ExtractionError` block in `_build_block`; no catch-all around the orchestrator's per-file loop for non-`DocSyncError` exceptions. |
| Test Coverage Readiness | Partial | Functions are largely pure/injectable and mockable, but the 700+-line single-file implementation ignores Architecture §12.1's explicit guidance to split into `src/doc_sync/` once past "a few hundred lines," and none of `impl-plan.md`'s T001-planned per-component files exist. |
| Code Clarity | Partial | Naming and structure mirror architecture components well; `ChangeEvent.kind` is populated but never consumed, which is misleading. |
| DRY Principle | Pass | `_apply()` avoids duplicating the `sync_readme` call/log pattern between startup and live sync; marker template vs. regex duplication is inherent/necessary. |
| Dependency Safety | Partial | `watchdog==6.0.0` is pinned but exceeds the range (`>=4.0,<5.0`) decided in `impl-plan.md` T002; no `pyproject.toml`/`setup.cfg` declares the minimum Python version as T002 required. |

---

## Detailed Findings

### 1. Correctness — Fail
- **Evidence**:
  - `SyncOrchestrator._build_block` ([src/doc_sync.py](../src/doc_sync.py#L577)):
    ```python
    def _build_block(self, file_path: Path, module_path: str) -> Optional[str]:
        try:
            module_info = extract_module(file_path, module_path)
        except ExtractionError as exc:
            logger.warning("Skipping %s: %s", file_path, exc)
            return None
        return render_block(module_info)
    ```
    `render_block(module_info)` is called **outside** the `try` block, so any exception it raises (e.g. an `AttributeError`/`TypeError` from unexpected AST-derived data) propagates uncaught out of `_build_block`, out of `startup_sync()`/`process_batch()`, crashing `main()` at startup or silently killing the debounce-timer thread mid-batch (see Error Handling for the threading implication).
  - `SyncOrchestrator._module_path_for` ([src/doc_sync.py](../src/doc_sync.py#L554)) assumes every validated path is relative to `self.src_dir`:
    ```python
    def _module_path_for(self, file_path: Path) -> str:
        rel = file_path.resolve().relative_to(self.src_dir.resolve())
    ```
    but the actual boundary check used before this call, `is_within_workspace(file_path, self.workspace_root)` (in both `startup_sync` and `process_batch`), validates against `workspace_root`, not `src_dir`. A `watchdog` `on_moved` event where a `.py` file is moved from `src/foo.py` to some other in-workspace-but-outside-`src/` location (e.g. project root) passes the workspace check but then makes `relative_to()` raise `ValueError`, which is unhandled.
  - `PyFileEventHandler.on_moved` ([src/doc_sync.py](../src/doc_sync.py#L497)) unconditionally enqueues a `"created"` event for `dest_path` whenever its suffix is `.py`, without checking whether `dest_path` is even inside `src/` — feeding exactly the scenario above into the pipeline.
- **Affected Requirement**: FR-5 ("Errors for one file do not stop the watcher process or block processing of other files"), NFR-5 ("A single malformed file must never crash the watcher").
- **Issues Found**: Uncaught exceptions can propagate from `_build_block`/`_module_path_for` through `startup_sync`/`process_batch`; the validated containment boundary (`workspace_root`) does not match the boundary assumed later (`src_dir`), creating a reachable crash path via file moves.
- **Recommendation**: Wrap the `render_block(module_info)` call in the same `try/except` as `extract_module`, catching a broad-but-intentional `Exception` there (logging via `logger.warning` with the file path) since `render_block` has no typed exception of its own. Additionally, either validate moved/changed paths against `self.src_dir` (not just `workspace_root`) before calling `_module_path_for`, or catch `ValueError` from `relative_to()` in `_module_path_for`'s caller and log-and-skip rather than let it propagate.

### 2. Security — Partial
- **Evidence**:
  - `is_within_workspace` ([src/doc_sync.py](../src/doc_sync.py#L163)) correctly resolves and checks containment; called once per file from the orchestrator only, consistent with the documented single call-site contract (H-1 resolution).
  - `extract_module` ([src/doc_sync.py](../src/doc_sync.py#L233)) only uses `ast.parse`, never `exec`/`import` — satisfies NFR-2.
  - `_atomic_write` ([src/doc_sync.py](../src/doc_sync.py#L349)):
    ```python
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=f".{path.name}.", suffix=".tmp")
    ...
    os.replace(tmp_name, path)
    ```
    `tempfile.mkstemp` creates the temp file with mode `0600` (owner read/write only) on POSIX. `os.replace` then makes `README.md` inherit that restrictive mode instead of preserving the file's prior permissions, so every sync pass silently narrows `README.md`'s permission bits (e.g. from `0644` to `0600`), which could break other tooling/collaborators expecting the file to remain group/world readable.
- **Affected Requirement**: NFR-2, Decision 5 (atomic writes) in `architecture.md`.
- **Issues Found**: No exec/import/traversal vulnerabilities found; the atomic-write helper has an unintended file-permission side effect.
- **Recommendation**: Before `os.replace`, copy the original file's mode via `os.chmod(tmp_name, os.stat(path).st_mode)` when `path` already exists, so permissions are preserved across syncs.

### 3. Error Handling — Fail
- **Evidence**: As detailed in Correctness above, `_build_block` only guards `extract_module` with `except ExtractionError`, leaving `render_block` unguarded. `EventDebouncer._flush` ([src/doc_sync.py](../src/doc_sync.py#L459)) invokes `self._callback(batch)` (i.e. `SyncOrchestrator.process_batch`) directly on the `threading.Timer` thread with no surrounding `try/except`; an unhandled exception there is only reported via Python's default `threading.excepthook` (raw traceback to stderr, bypassing the configured `logging` formatter entirely) rather than the `WARNING`-level, path-and-message log line architecture and FR-5 call for.
- **Affected Requirement**: FR-5, NFR-5.
- **Issues Found**: Non-`DocSyncError` exceptions during a sync pass are not caught anywhere in the orchestrator or debouncer, so FR-5's "errors for one file do not stop processing of other files" is not actually guaranteed for exceptions outside the two typed exception classes.
- **Recommendation**: Add a broad `except Exception as exc` around each per-file iteration inside `startup_sync` and `process_batch` (logging `logger.warning("Skipping %s due to unexpected error: %s", file_path, exc)`), and/or wrap `self._callback(batch)` in `EventDebouncer._flush` with a `try/except Exception` that logs via the module logger instead of relying on the default thread exception hook.

### 4. Test Coverage Readiness — Partial
- **Evidence**: `extract_module`, `render_block`, `sync_readme`, `is_within_workspace` are pure functions taking explicit parameters (no hidden globals besides the shared `logger`), and `SyncOrchestrator`/`EventDebouncer` take their dependencies (`workspace_root`, `src_dir`, `readme_path`, `callback`, `window_ms`) via constructor injection — all genuinely mockable/testable in isolation. However, `architecture.md` §12.1 states a single-file layout is "acceptable for this scope" but that splitting into `src/doc_sync/` (as `impl-plan.md` T001 fully scaffolds with `extractor.py`, `renderer.py`, `readme_writer.py`, `orchestrator.py`, `watcher.py`, `debouncer.py`, `errors.py`, `models.py`, `path_validator.py`, `constants.py`, `logger.py`) is "preferred once the implementation grows past a few hundred lines." The actual `src/doc_sync.py` is ~700 lines with all components in one module, and none of the T001-planned per-component files or their component-scoped test files (`tests/test_extractor.py`, `tests/test_renderer.py`, etc., per T022-T024) exist.
- **Issues Found**: No hard testability blockers (no module-level I/O side effects at import time — `logger = logging.getLogger(...)` is the only module-level statement and is side-effect-free), but the implementation structure diverges from both the architecture's stated preference and the impl-plan's task/file breakdown, which will make mapping tests to the planned per-component test files (T022-T028) awkward.
- **Recommendation**: Either update `impl-plan.md`/`architecture.md` to reflect the single-file decision explicitly (if intentional), or split `doc_sync.py` into the planned package structure before the verification phase writes `tests/test_doc_sync.py`, so test organization matches the plan.

### 5. Code Clarity — Partial
- **Evidence**: Naming (`SyncOrchestrator`, `EventDebouncer`, `PyFileEventHandler`, `AST Extractor`-equivalent functions) consistently mirrors `architecture.md` §2.3 component names. Control flow is shallow (no deep nesting). `ChangeEvent` ([src/doc_sync.py](../src/doc_sync.py#L440)):
  ```python
  @dataclass(frozen=True)
  class ChangeEvent:
      path: Path
      kind: str  # "created" | "modified" | "deleted"
  ```
  `kind` is populated by `PyFileEventHandler` for every event but is never read anywhere in `EventDebouncer` or `SyncOrchestrator.process_batch` (which instead re-derives state via `file_path.exists()`). A reader following `kind` through the pipeline will reasonably but incorrectly assume it drives branching logic.
- **Issues Found**: Dead/unused field (`ChangeEvent.kind`) creates a misleading impression of how deletions vs. modifications are actually distinguished.
- **Recommendation**: Either use `kind` in `process_batch` (and document why `exists()` is also needed as a race-condition safeguard), or remove the field and rely solely on `Path.exists()`, adding a one-line comment explaining that existence-checking is preferred over trusting the last-seen event kind.

### 6. DRY Principle — Pass
- **Evidence**: `SyncOrchestrator._apply` ([src/doc_sync.py](../src/doc_sync.py#L570)) centralizes the `sync_readme` call, `ReadmeSyncError` handling, and result-count logging shared between `startup_sync` and `process_batch`, avoiding duplicating that logic twice.
- **Issues Found**: None material. The marker template strings (`MARKER_START_TMPL`) and their corresponding parsing regexes (`MARKER_START_RE`) are separately defined, but this is a necessary render-vs-parse duplication rather than avoidable copy-paste.
- **Recommendation**: No action needed.

### 7. Dependency Safety — Partial
- **Evidence**: [requirements.txt](../requirements.txt) pins `watchdog==6.0.0`, `requests==2.34.2`, `python-dotenv==1.2.3`, `pytest==9.1.1`, `pytest-cov==7.1.0`. `impl-plan.md` T002 decided on `watchdog>=4.0,<5.0`, and no `pyproject.toml`/`setup.cfg` exists in the workspace to declare `Requires-Python >=3.10` as T002's acceptance criteria required. All imports in `src/doc_sync.py` (`argparse`, `ast`, `logging`, `os`, `re`, `signal`, `sys`, `tempfile`, `threading`, plus `watchdog`) are used; no unnecessary third-party surface area is introduced. The code uses `from __future__ import annotations` and only PEP 604 (`X | Y`) / builtin generic (`list[...]`, `dict[...]`) annotations, which remain compatible with Python 3.9+ given that import, so no syntax-level Python-version violation was found.
- **Affected Requirement**: Technical Requirements (Technology Stack), `impl-plan.md` T002.
- **Issues Found**: (1) `watchdog` pinned to `6.0.0`, a major-version jump beyond the `<5.0` ceiling the implementation plan decided on, with no recorded rationale for the change. (2) No file in the repo declares the minimum supported Python version, despite T002 explicitly requiring one.
- **Recommendation**: Either update `impl-plan.md` T002 to record the decision to move to `watchdog>=6.0,<7.0` (confirming the 5.x→6.x API is compatible with the `Observer`/`FileSystemEventHandler` usage here), or re-pin to the originally agreed range. Add a `pyproject.toml` (or `setup.cfg`) with `Requires-Python >=3.9` (or whatever minimum is actually tested against) to close T002's acceptance criteria.

---

## Requirements Traceability

| Requirement | ID | Implemented In | Status | Notes |
|-------------|-----|-----------------|--------|-------|
| File watcher for `.py` changes under `src/` | FR-1 | `src/doc_sync.py::PyFileEventHandler`, `main` | Covered | Recursive `Observer.schedule(..., recursive=True)`; SIGINT handled cleanly. |
| AST-based structure extraction | FR-2 | `src/doc_sync.py::extract_module`, `_render_signature` | Covered | Module-level-only, full `ast.arguments` handling (posonly/kwonly/vararg/kwarg). |
| Auto-generated marker sync in README | FR-3 | `src/doc_sync.py::render_block`, `sync_readme`, `_append_blocks` | Covered | Deterministic block rendering; insert/replace preserves surrounding content. |
| Removal of stale documentation | FR-4 | `src/doc_sync.py::SyncOrchestrator.startup_sync`, `process_batch` | Covered | Startup orphan reconciliation plus live-deletion handling both implemented. |
| Warning logging on failure, no crash | FR-5 | `src/doc_sync.py::SyncOrchestrator._build_block` | Partial | `ExtractionError` is caught and logged, but `render_block`/`_module_path_for` failures are not — see Correctness/Error Handling findings. |
| No `exec`/`import` of scanned files; path containment | NFR-2 | `src/doc_sync.py::extract_module`, `is_within_workspace` | Covered | Static `ast.parse` only; single call-site path validation in the orchestrator. |
| Clear pass-start/changed/added-updated-removed logging | NFR-4 | `src/doc_sync.py::configure_logging`, `SyncOrchestrator` logging calls | Covered | INFO lines for pass start/summary; WARNING for per-file skips. |
| Watcher never crashes on repeated events/malformed files | NFR-5 | `src/doc_sync.py::SyncOrchestrator`, `EventDebouncer._flush` | Partial | See Error Handling — unguarded exceptions can crash startup or silently drop a live batch. |

---

## Blocking Issues
1. **Correctness/Error Handling (FR-5, NFR-5)**: `render_block()` calls inside `SyncOrchestrator._build_block` are not wrapped in exception handling, and the workspace-root path-containment check does not guarantee the `src_dir`-relative assumption made in `_module_path_for`. Both can propagate an uncaught exception that crashes `main()` at startup or silently kills the debounce-timer thread during live watching. Must be fixed (add broad per-file exception handling in `_build_block`, `startup_sync`, `process_batch`, and/or `EventDebouncer._flush`) before this code proceeds.

## Non-Blocking Recommendations
1. Preserve `README.md`'s original file permissions in `_atomic_write` instead of inheriting `tempfile.mkstemp`'s restrictive default mode.
2. Remove or actually use the unused `ChangeEvent.kind` field to avoid misleading readers.
3. Reconcile `requirements.txt`'s `watchdog==6.0.0` pin with `impl-plan.md` T002's decided `<5.0` ceiling (update one or the other with a recorded rationale).
4. Add a `pyproject.toml`/`setup.cfg` declaring the minimum supported Python version per T002's acceptance criteria.
5. Consider splitting `src/doc_sync.py` into the `src/doc_sync/` package structure planned in `impl-plan.md` T001, per `architecture.md` §12.1's size guidance, before the verification phase's test files are written.

## Revision History
- 2026-09-03: Initial review by Code Review Agent
