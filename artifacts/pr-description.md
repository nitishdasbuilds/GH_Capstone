# Pull Request: Automated Documentation Sync Tool (`doc_sync`)

**Jira Ticket**: [EPMCDMETST-62888](https://jiraeu.epam.com/browse/EPMCDMETST-62888)

## Summary
This PR delivers `src/doc_sync.py`, a local, standalone CLI tool that watches `src/` for `.py` file changes via `watchdog`, extracts module/function structure using Python's `ast` module (no `exec`/`import` of scanned code), and keeps clearly-delimited auto-generated sections of `README.md` in sync using rule-based templates — without touching hand-written prose. The design follows the single-process, event-driven architecture (File Watcher → Event Debouncer → Sync Orchestrator → AST Extractor → Markdown Renderer → README Sync Writer) approved in `artifacts/architecture.md`, with all Critical/High design-review findings (startup orphan reconciliation, Path Validator wiring, thread-safe debouncer) resolved prior to code review sign-off.

## Changes Made

### Added
- `src/__init__.py` — marks `src/` as a package so `python -m src.doc_sync --watch` works as specified.
- `tests/__init__.py` — marks `tests/` as a package for test discovery.

### Modified
- `src/doc_sync.py` — implementation of the full doc-sync pipeline: `PyFileEventHandler`/`Observer`-based file watcher (FR-1), `EventDebouncer` with thread-safe buffering (resolves design-review H-2), `is_within_workspace` path validator (NFR-2), `extract_module`/`_render_signature` AST extractor covering posonly/kwonly/vararg/kwarg signatures and strict UTF-8 decoding (FR-2), `render_block` deterministic Markdown renderer (FR-3), marker-based `sync_readme`/atomic `_atomic_write` README writer (FR-3/FR-4), and `SyncOrchestrator` with startup orphan reconciliation (resolves design-review C-1) and per-file exception handling (FR-5/NFR-5, includes the two blocking-issue fixes from code review — see below).
- `src/calculator.py` — sample module (`add`, `subtract`, `multiply`, `divide`, `Calculator` class) used to exercise the doc-sync watcher against real, documented code.
- `tests/test_doc_sync.py` — 52-test suite covering file-change detection, README update logic, logging, calculator functions, and error handling (including regression tests for both code-review blocking issues).
- `README.md` — auto-generated legacy content (from an earlier `AUTO-GENERATED:START:api_usage`/`:configuration` marker format that predates the current `AUTO-DOC:START module=X` architecture) was removed, leaving the hand-authored title only; the new marker format will be (re)populated by running the watcher against this codebase.
- `status.json` — pipeline phase tracking updated as each SDLC phase completed.
- `artifacts/requirements.md`, `artifacts/architecture.md`, `artifacts/design-review.md`, `artifacts/impl-plan.md`, `artifacts/code-review.md`, `artifacts/verification-report.md` — SDLC pipeline artifacts produced/refined across the requirements, architecture, design review, implementation planning, code review, and verification phases for this ticket.

## Test Evidence

**Command**: `python -m pytest tests/test_doc_sync.py -v --cov=src --cov-report=term-missing`

```
============================= test session starts =============================
platform win32 -- Python 3.14.5, pytest-9.1.1, pluggy-1.6.0
collected 52 items

tests/test_doc_sync.py .................................................... [100%]

=============================== tests coverage ================================
Name                Stmts   Miss  Cover   Missing
-------------------------------------------------
src\__init__.py         0      0   100%
src\calculator.py      23      0   100%
src\doc_sync.py       391     43    89%   198, 209, 217, 225, 346, 361-362,
                                          418-419, 509, 546-547, 590-591,
                                          594-596, 630-632, 638-639, 688-714, 718
-------------------------------------------------
TOTAL                 414     43    90%
============================= 52 passed in 0.79s ==============================
```

- **Total Tests**: 52
- **Passed**: 52
- **Failed**: 0
- **Coverage**: 90% combined (`doc_sync.py` 89%, `calculator.py` 100%), exceeding the 70% target
- **Reference**: See `artifacts/verification-report.md` for the full breakdown by area, including the two dedicated regression tests for the code-review blocking issues (`test_build_block_catches_render_block_exception`, `test_module_path_boundary_uses_src_dir_consistently`)

## Known Limitations
- Uncovered lines in `src/doc_sync.py` (89% coverage) are concentrated in the `main()` live-watch blocking loop/`SIGINT` shutdown path and a few annotation-rendering sub-branches in `_render_signature`; these are documented in `artifacts/verification-report.md` as intentionally untested to avoid flaky/hanging tests, since the underlying components (`EventDebouncer.shutdown()`, `Observer` start/stop) are separately unit-tested.
- Non-blocking code-review recommendations not yet addressed: `_atomic_write` does not preserve `README.md`'s original file permissions (inherits `tempfile.mkstemp`'s restrictive mode); the unused `ChangeEvent.kind` field is misleading and should either be used or removed; `requirements.txt` pins `watchdog==6.0.0`, which exceeds the `<5.0` ceiling originally decided in `artifacts/impl-plan.md` T002 (no recorded rationale for the change); no `pyproject.toml`/`setup.cfg` declares the minimum supported Python version per T002.
- The implementation is a single ~700-line `src/doc_sync.py` module rather than the `src/doc_sync/` package structure originally scaffolded in `artifacts/impl-plan.md` T001; `artifacts/code-review.md` flags this as a documentation/planning divergence (Test Coverage Readiness: Partial) rather than a functional defect.
- `README.md`'s previous auto-generated content used an older marker format and has been stripped rather than migrated; running the watcher (`python -m src.doc_sync --watch`) against this repo will regenerate the current `AUTO-DOC:START module=X` sections.

## Reviewer Checklist
- [ ] Code changes align with `artifacts/requirements.md`
- [ ] Architecture and design decisions in `artifacts/architecture.md` / `artifacts/design-review.md` are correctly reflected in the implementation
- [ ] All blocking issues from `artifacts/code-review.md` have been resolved
- [ ] Test evidence above is sufficient and tests pass
- [ ] No security concerns (secrets, unsafe file/path handling, unsafe eval/exec)
- [ ] Documentation (README, docstrings) is up to date with the change
- [ ] Jira ticket EPMCDMETST-62888 accurately reflects the delivered scope

## References
- Requirements: `artifacts/requirements.md`
- Architecture: `artifacts/architecture.md`
- Design Review: `artifacts/design-review.md`
- Implementation Plan: `artifacts/impl-plan.md`
- Code Review: `artifacts/code-review.md`
- Verification Report: `artifacts/verification-report.md`
- Jira Ticket: EPMCDMETST-62888

## Revision History
- 2026-09-03: Initial PR description generated by PR Agent
