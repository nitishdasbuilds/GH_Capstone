# Pull Request: Automated Documentation Sync for src/ Python Files

**Jira Ticket**: [EPMCDMETST-62888](https://your-jira-instance/browse/EPMCDMETST-62888)

## Summary
This PR introduces a local file-watcher (`src/doc_sync.py`) that monitors `src/` for `.py` file changes, extracts public function signatures/docstrings via AST parsing, and regenerates the "API Usage Examples" and "Configuration Options" sections of `README.md` between `<!-- AUTO-GENERATED:START/END -->` markers, per `artifacts/requirements.md` (FR-1, FR-2, FR-3) and the monolithic event-driven design in `artifacts/architecture.md`. A sample module (`src/calculator.py`) is included to give the watcher something to analyze and document. This implementation covers only FR-1/FR-2/FR-3 (and related NFRs); Git integration (FR-6), JIRA integration (FR-7), API doc generation (FR-4), and the conditional review workflow (FR-5) are out of scope for this change.

## Changes Made

### Added
- `src/doc_sync.py` — Watchdog-based file watcher, AST-based code analyzer, and template-based README section generator/writer, with debouncing (0.3s) and batching (2s window, 20-file cap per D003).
- `src/calculator.py` — Sample module (`add`, `subtract`, `multiply`, `divide`, `Calculator` class) used to exercise the watcher/analyzer; not a dependency of `doc_sync.py`.
- `tests/test_doc_sync.py` — 29 pytest cases covering file-change detection, README update logic, timestamp logging, calculator functions, and error handling.
- `artifacts/requirements.md`, `artifacts/architecture.md`, `artifacts/design-review.md`, `artifacts/impl-plan.md`, `artifacts/code-review.md`, `artifacts/verification-report.md` — upstream SDLC pipeline artifacts documenting requirements, design, review findings, and verification results for this change.

### Modified
- `README.md` — Contains the auto-generated `api_usage` and `configuration` marker sections that `doc_sync.py` updates in place.

## Test Evidence

**Command**: `python -m pytest tests/ -v --tb=short`

```
============================= test session starts =============================
platform win32 -- Python 3.14.5, pytest-9.1.1, pluggy-1.6.0
collected 29 items

tests/test_doc_sync.py::TestFileChangeDetection::test_py_file_modification_triggers_sync PASSED
tests/test_doc_sync.py::TestFileChangeDetection::test_non_py_file_ignored PASSED
tests/test_doc_sync.py::TestFileChangeDetection::test_directory_events_ignored PASSED
tests/test_doc_sync.py::TestFileChangeDetection::test_duplicate_events_debounced PASSED
tests/test_doc_sync.py::TestFileChangeDetection::test_flush_with_no_pending_events_does_nothing PASSED
tests/test_doc_sync.py::TestReadmeUpdate::test_marker_section_replaced PASSED
tests/test_doc_sync.py::TestReadmeUpdate::test_content_outside_markers_preserved PASSED
tests/test_doc_sync.py::TestReadmeUpdate::test_missing_markers_handled_gracefully PASSED
tests/test_doc_sync.py::TestReadmeUpdate::test_malformed_markers_start_after_end_treated_as_missing PASSED
tests/test_doc_sync.py::TestReadmeUpdate::test_template_content_substituted_into_readme PASSED
tests/test_doc_sync.py::TestReadmeUpdate::test_readme_preserves_prior_content_on_parse_failure FAILED
tests/test_doc_sync.py::TestSyncLogging::test_iso_now_returns_parseable_iso8601 PASSED
tests/test_doc_sync.py::TestSyncLogging::test_log_directory_created_if_missing PASSED
tests/test_doc_sync.py::TestSyncLogging::test_log_appends_not_overwrites PASSED
tests/test_doc_sync.py::TestSyncLogging::test_log_entry_has_iso8601_timestamp PASSED
tests/test_doc_sync.py::TestCalculator::test_add PASSED
tests/test_doc_sync.py::TestCalculator::test_subtract PASSED
tests/test_doc_sync.py::TestCalculator::test_multiply PASSED
tests/test_doc_sync.py::TestCalculator::test_divide PASSED
tests/test_doc_sync.py::TestCalculator::test_divide_by_zero_raises PASSED
tests/test_doc_sync.py::TestCalculator::test_calculator_running_total PASSED
tests/test_doc_sync.py::TestCalculator::test_calculator_reset PASSED
tests/test_doc_sync.py::TestCalculator::test_calculator_divide_by_zero_raises PASSED
tests/test_doc_sync.py::TestCalculator::test_square_actually_squares_the_total XFAIL
tests/test_doc_sync.py::TestErrorHandling::test_readme_write_failure_does_not_crash PASSED
tests/test_doc_sync.py::TestErrorHandling::test_log_write_failure_handled PASSED
tests/test_doc_sync.py::TestErrorHandling::test_corrupted_source_file_skipped PASSED
tests/test_doc_sync.py::TestErrorHandling::test_deleted_file_skipped_without_crashing PASSED
tests/test_doc_sync.py::TestErrorHandling::test_keyboard_interrupt_exits_cleanly PASSED

================================== FAILURES ===================================
____ TestReadmeUpdate.test_readme_preserves_prior_content_on_parse_failure ____
AssertionError: sync_readme() wiped previously-generated content after a parse
failure instead of preserving it (see code-review.md Blocking Issue #1)
=================== 1 failed, 27 passed, 1 xfailed in 0.25s ===================
```

- **Total Tests**: 29
- **Passed**: 27
- **Failed**: 1 (`test_readme_preserves_prior_content_on_parse_failure` — reproduces Code Review Blocking Issue #1, see Known Limitations)
- **XFailed**: 1 (`test_square_actually_squares_the_total` — reproduces a known, non-blocking `Calculator.square()` defect; marked `xfail(strict=True)`)
- **Coverage**: 93% overall (`doc_sync.py` 95%, `calculator.py` 84%) against a 70% target
- **Reference**: See `artifacts/verification-report.md` for full details

Test evidence above was captured fresh in this session and matches `artifacts/verification-report.md` exactly (27 passed, 1 failed, 1 xfailed, 93% coverage).

## Known Limitations
This PR is **not** in a mergeable state as-is — `artifacts/code-review.md` recorded a "CHANGES REQUIRED" verdict with 3 blocking issues, and `artifacts/verification-report.md` recorded "PASS WITH GAPS" because one of those issues reproduces as a genuine, currently-failing test:

1. **[Blocking — Correctness]** `sync_readme()` overwrites a previously-valid "API Usage Examples" section with an empty placeholder when a watched file has a transient syntax error, and only re-analyzes files in the current batch rather than the full `src/` tree — so unrelated files' documentation can be dropped on each sync. Violates the "never corrupt existing documentation" reliability requirement (NFR-3). Reproduced by the failing test above.
2. **[Blocking — Correctness]** Log timestamps in `logs/sync.log` are not ISO-8601 compliant (`logging.Formatter` default `asctime`, e.g. `2026-09-02 14:40:08,373`) despite the implementation spec requiring ISO-8601 log timestamps. Only the console `[SYNCED]` message is truly ISO-8601.
3. **[Blocking — Dependency Safety]** `watchdog` is imported by `doc_sync.py` but is not declared or pinned in any `requirements.txt`/`pyproject.toml` in the repository, so the project cannot be installed reproducibly in a clean environment.
4. **[Non-blocking]** `Calculator.square()` in `src/calculator.py` is mislabeled: its docstring claims it squares the running total, but it duplicates `multiply()`'s behavior. Covered by an `xfail(strict=True)` test.
5. **[Non-blocking / scope]** FR-4 (API documentation sync), FR-5 (conditional review workflow), FR-6 (Git integration), and FR-7 (JIRA integration) are not implemented in this PR — only FR-1/FR-2/FR-3 and the associated NFRs are addressed.
6. **[Non-blocking]** Test coverage gaps (documented in `artifacts/verification-report.md`): the `BATCH_MAX_FILES` overflow-requeue branch and `__main__`/startup print statements are not exercised by unit tests; considered low-risk and acceptable per the verification report.

## Reviewer Checklist
- [ ] Code changes align with `artifacts/requirements.md`
- [ ] Architecture and design decisions in `artifacts/architecture.md` / `artifacts/design-review.md` are correctly reflected in the implementation
- [ ] All blocking issues from `artifacts/code-review.md` have been resolved (currently **unresolved** — see Known Limitations)
- [ ] Test evidence above is sufficient and tests pass (currently 1 known failure, reproducing a blocking defect)
- [ ] No security concerns (secrets, unsafe file/path handling, unsafe eval/exec) — code review rated Security "Pass"
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
- 2026-09-02: Initial PR description generated by PR Agent
