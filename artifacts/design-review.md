# Design Review Report

## Review Summary
- **Requirements Document**: `artifacts/requirements.md`
- **Architecture Document**: `artifacts/architecture.md`
- **Review Date**: 2026-09-03
- **Reviewed By**: Design Review Agent

### Overall Assessment
**APPROVED WITH CONDITIONS**

**Verdict Rationale**: The architecture is appropriately scoped, correctly rejects over-engineered options (no DB, no microservices, no async/multiprocessing), and covers most FR/NFR items with explicit component ownership. However, it has one critical functional gap around stale-doc removal on cold start, an internal diagram/text inconsistency affecting where path validation actually runs, and an unaddressed concurrency risk in the debounce mechanism. These must be resolved before implementation.

### Finding Statistics
| Severity | Count |
|----------|-------|
| Critical | 1 |
| High     | 2 |
| Medium   | 4 |
| Low      | 3 |
| **Total** | **10** |

---

## Critical Findings
> These must be resolved before implementation begins.

### C-1: No reconciliation of orphaned README blocks against currently-existing `src/` files at startup
- **Category**: Gap
- **Affected Requirement**: FR-4
- **Finding**: FR-4's acceptance criteria require "If a module `.py` file is deleted from `src/`, its entire marker block is removed from `README.md`" on "the next sync pass" — and the tool is explicitly expected to run locally, started/stopped repeatedly (not as a CI daemon), with `git checkout`/branch switches called out as a normal trigger scenario (NFR-5). If a module file is deleted or renamed while the watcher process is **not running** (e.g., `git checkout` to a branch missing that file, or manual deletion between sessions), the Sync Orchestrator's startup routine only "enumerate[s] all `.py` files under `src/` for an initial full sync" — it never reads the existing marker blocks in `README.md` and diffs them against the set of files actually present on disk. Deletions are only detected via live `watchdog` `on_deleted` events during an active session (per the Sync Orchestrator responsibilities: "Determine deletions ... and route them to the README Sync Writer"). There is no described mechanism for detecting a module whose file was already gone *before* the watcher started.
- **Evidence**: Section 2.3, Sync Orchestrator responsibilities: "On startup, enumerate all `.py` files under `src/` for an initial full sync" (no mention of comparing against existing README marker blocks). Section 2.3, README Sync Writer responsibilities only describe removal "For each deleted module" without defining how a deletion is discovered outside a live watchdog event.
- **Recommendation**: Add an explicit startup reconciliation step to the Sync Orchestrator: parse all existing `<!-- AUTO-DOC:START module=X -->` blocks in `README.md`, compute the set difference against the currently-enumerated `src/*.py` modules, and route any module present in README but absent on disk to the README Sync Writer for removal — as part of the initial full sync, before (or alongside) processing currently-existing files.
- **Effort Estimate**: Small

---

## High Findings

### H-1: Path Validator's position in the pipeline is inconsistent between the diagram and the component description
- **Category**: Security
- **Affected Requirement**: NFR-2
- **Finding**: The high-level component diagram (Section 2.2) places the Path Validator conceptually between the raw watchdog event and the Event Debouncer, wired only into the live-event path. But the Path Validator's own interface description says: `is_within_workspace(path, root) -> bool`, "called by the Sync Orchestrator before any file is opened" (Section 2.3) — i.e., invoked much later, downstream of debouncing, and (implicitly) for *every* file the Sync Orchestrator processes, including the startup full-sync enumeration that never passes through the debouncer or the watchdog event path at all. These two descriptions cannot both be literally true as drawn; as written, a reader cannot tell whether startup-enumerated files (from `os.walk`/`Path.rglob`) are ever run through `is_within_workspace` at all, since the diagram only shows it wired to watchdog events.
- **Evidence**: Section 2.2 diagram places "Path Validator" implicitly upstream of "Event Debouncer" for watchdog-sourced events (per the data flow arrows in Section 4.2: "watchdog event ──▶ Path Validator ──▶ Event Debouncer ──▶ Sync Orchestrator"), while Section 2.3's Path Validator interface states it is "called by the Sync Orchestrator" — a different, later stage that also covers the startup path.
- **Recommendation**: Resolve the contradiction explicitly: state that Path Validator is a shared utility invoked by the Sync Orchestrator immediately before any file open, for **both** watchdog-triggered paths and startup-enumerated paths, and correct the Section 4.2 diagram/flow text to show validation happening at that single point rather than implying it sits in the raw event pipeline.
- **Recommendation Detail**: Update Section 4.2's flow line to `watchdog event ──▶ Event Debouncer ──▶ Sync Orchestrator ──▶ (Path Validator, per file) ──▶ AST Extractor`, and add one sentence to Section 2.3 confirming startup-enumerated paths are validated identically.
- **Effort Estimate**: Small

### H-2: Debounce buffer has no described concurrency/thread-safety mechanism
- **Category**: Reliability
- **Affected Requirement**: NFR-5, FR-1
- **Finding**: `watchdog`'s `Observer` dispatches filesystem events from a background thread, separate from the main thread. The Event Debouncer is described as using "Plain Python using `threading.Timer` (or a simple loop with timestamps)" to buffer and deduplicate paths in a shared collection (e.g., a `set[Path]`) that is written to by the watchdog event-handler thread and read/cleared by the timer callback (itself running on yet another thread). The architecture does not mention any lock, queue, or other synchronization primitive protecting this shared state. Without one, concurrent mutation of the buffer from two threads is a classic source of intermittent, hard-to-reproduce crashes or lost/duplicated events — directly undermining NFR-5's "must never crash" and "must keep running across repeated file-save events" requirements, which are exactly the burst-event scenarios (autosave, `git checkout`) most likely to trigger a race.
- **Evidence**: Section 2.3, Event Debouncer: "Buffer incoming `ChangeEvent`s within a short window... Technology: Plain Python using `threading.Timer`... no external dependency needed" — no mention of locking or a thread-safe queue.
- **Recommendation**: Specify that the Event Debouncer uses a `queue.Queue` (thread-safe by design) or an explicit `threading.Lock` guarding the shared buffer, and that the timer callback swaps/clears the buffer atomically under that lock before handing the batch to the Sync Orchestrator.
- **Effort Estimate**: Small

---

## Medium Findings

### M-1: No dependency version pinning specified
- **Category**: Compliance / Maintainability
- **Affected Requirement**: General (NFR-2 supply-chain adjacent)
- **Finding**: The architecture states `watchdog` is "declared in `requirements.txt`" as the only new dependency but never specifies a version or version range anywhere in the document, and Python itself is only ever referred to as "Python 3.x." This is the exact gap the architecture's own review dimension (version numbers, not "latest") would flag, and leaves the implementation/verification agents with no pinned baseline to reproduce builds or track CVEs against.
- **Evidence**: Section 3.5: "`watchdog` (PyPI package): Purpose — event-driven, cross-platform filesystem watching..." (no version). Section 3.2: "Language: Python 3.x."
- **Recommendation**: Specify a minimum supported Python version (e.g., "Python 3.10+") and pin `watchdog` to a specific version or compatible range (e.g., `watchdog>=4.0,<5.0`) in `requirements.txt`.
- **Effort Estimate**: Small

### M-2: "Tolerant" encoding error handling conflicts with FR-5's explicit warn-and-skip requirement
- **Category**: Gap
- **Affected Requirement**: FR-5, FR-2
- **Finding**: FR-2's acceptance criteria and FR-5 both require that unreadable/undecodable files be skipped **with a logged warning** containing the file path and reason. The AST Extractor's responsibility is described as reading "file content (with explicit UTF-8 decoding, tolerant error handling for encoding issues)" — "tolerant" is ambiguous and could reasonably be implemented as silently replacing/ignoring bad bytes (e.g., `errors="replace"`) rather than treating a decode failure as an error to be raised and logged. If implemented as silent tolerance, encoding problems would never surface as the FR-5-mandated warning, and could instead corrupt rendered docstring content in `README.md` silently.
- **Evidence**: Section 2.3, AST Extractor: "Read file content (with explicit UTF-8 decoding, tolerant error handling for encoding issues)."
- **Recommendation**: Replace "tolerant error handling" with an explicit contract: decode using strict UTF-8 (`errors="strict"`); on `UnicodeDecodeError`, raise the same typed `ExtractionError` used for `SyntaxError` so it is caught and logged as a `WARNING` by the Sync Orchestrator per FR-5, rather than silently substituting characters.
- **Effort Estimate**: Small

### M-3: Signature rendering doesn't explicitly address keyword-only and positional-only parameters
- **Category**: Gap
- **Affected Requirement**: FR-2
- **Finding**: FR-2 requires full signatures including "parameter names, defaults, `*args`/`**kwargs`, return annotation." The AST Extractor's described responsibility only enumerates "positional, defaults, `*args`, `**kwargs`, return annotation" — it does not mention `ast.arguments.posonlyargs` (PEP 570, the `/` marker) or `kwonlyargs`/`kw_defaults` (the `*` marker for keyword-only parameters). Any module-level function using either modern syntax feature (common in current Python code) would have an incompletely/incorrectly rendered signature.
- **Evidence**: Section 2.3, AST Extractor responsibilities: "Render each function's signature as a string from `ast.arguments` (positional, defaults, `*args`, `**kwargs`, return annotation)."
- **Recommendation**: Explicitly list all five `ast.arguments` component groups to be rendered: `posonlyargs` (with trailing `/`), `args` (with defaults), `vararg`, `kwonlyargs`/`kw_defaults` (with leading bare `*` when present and no `vararg`), and `kwarg`, plus the return annotation.
- **Effort Estimate**: Small

### M-4: No mitigation for the developer's editor holding unsaved `README.md` changes when a sync pass writes the file
- **Category**: Reliability
- **Affected Requirement**: NFR-5 (adjacent), General
- **Finding**: The atomic-write decision (Decision 5) protects against the tool's own process crashing mid-write, but does not address the realistic scenario where a developer has `README.md` open in an editor with unsaved manual edits outside the marker blocks at the moment a sync pass runs `os.replace()`. Depending on the editor, this can either be transparently picked up (fine) or cause the editor to silently continue displaying stale content that, if saved afterward, overwrites the tool's just-written auto-doc block — undermining the "hand-written content is preserved" goal (FR-3) in practice, even though the architecture is not technically at fault.
- **Recommendation**: Add a brief note to the Operability/Usability guidance (Section 9 or 12) recommending the tool log an `INFO` line whenever it writes `README.md`, and recommending developers avoid leaving `README.md` open with unsaved edits while the watcher runs — this is a documentation-level mitigation, not a code change.
- **Effort Estimate**: Small

---

## Low Findings

### L-1: No fast-forward/injection point described for testing the debounce window
- **Category**: Maintainability
- **Finding**: Section 12.2 mentions unit tests for the Extractor, Renderer, and README Sync Writer, and an integration test that invokes the Sync Orchestrator directly "without requiring real filesystem events" — but does not mention how the Event Debouncer itself (the component with the actual timing behavior) will be tested without real sleeps, risking flaky or slow tests.
- **Recommendation**: Note that the debounce window duration should be injectable (e.g., a constructor parameter) so tests can use a near-zero window or a fake clock instead of the real 300–500ms delay.

### L-2: No explicit mention of watch handle/observer cleanup on shutdown
- **Category**: Reliability
- **Finding**: NFR-5 requires no leaked file handles/watches, but Section 5.1 only states the CLI "stops the observer and exits with code 0" on `SIGINT` without describing that `Observer.stop()` must be paired with `Observer.join()` to fully release OS-level watch handles before process exit.
- **Recommendation**: Add one sentence to Section 5.1 or 8.3 specifying `observer.stop()` followed by `observer.join()` in the `SIGINT` handler.

### L-3: Python minimum version left as "3.x" throughout
- **Category**: Maintainability
- **Finding**: Every reference to the language version says "Python 3.x" rather than a concrete minimum (relevant since `ast.arguments.posonlyargs` requires 3.8+ and modern union-type annotation rendering behavior varies by version).
- **Recommendation**: State a concrete minimum Python version in Section 3.2 (this is the same underlying gap as M-1, called out separately here for the version-numbers-not-"latest" consistency dimension).

---

## Requirements Coverage Matrix

| Requirement | ID | Architectural Owner | Status | Notes |
|-------------|-----|---------------------|--------|-------|
| File watcher for source changes | FR-1 | File Watcher, Sync Orchestrator | Covered | Entry point, recursive watch, `.py` filtering all described |
| AST-based code structure extraction | FR-2 | AST Extractor | Partial | See M-3 (kwonly/posonly args) and M-2 (encoding handling) |
| Auto-generated Markdown section sync | FR-3 | Markdown Renderer, README Sync Writer | Covered | Marker format, idempotency, atomic write all described |
| Removal of stale documentation | FR-4 | Sync Orchestrator, README Sync Writer | Partial | C-1: no startup reconciliation for pre-existing deletions |
| Warning logging on failure | FR-5 | Logger, Sync Orchestrator | Partial | M-2: "tolerant" encoding handling may bypass the warning path |
| Performance (single file <2s, no polling) | NFR-1 | File Watcher, AST Extractor | Covered | Event-driven design, per-file budget addressed |
| Security (read-only src, README-only write, path validation) | NFR-2 | AST Extractor, Path Validator | Partial | H-1: Path Validator wiring inconsistent between diagram and text |
| Scalability (100 files / 10s) | NFR-3 | Sync Orchestrator | Covered | Sequential processing justified against target |
| Usability (zero-config, clear logs) | NFR-4 | Logger, CLI entry point | Covered | Log format and CLI invocation both specified |
| Reliability (no crash, no handle leaks) | NFR-5 | Event Debouncer, Sync Orchestrator | Partial | H-2 (debounce race), L-2 (observer cleanup) |

---

## Security Checklist

| Control | Status | Finding Ref |
|---------|--------|-------------|
| All API endpoints authenticated | Pass (N/A — no network API) | |
| Input validated at system boundary | Partial | H-1 |
| Secrets managed via vault/env injection | Pass (N/A — no secrets used) | |
| PII encrypted at rest | Pass (N/A — no PII in scope) | |
| PII encrypted in transit | Pass (N/A — no network transport) | |
| No sensitive data in logs | Pass | |
| Third-party dependencies pinned | Fail | M-1 |
| Admin endpoints segregated | Pass (N/A — no endpoints) | |

---

## Approved Items
> These aspects of the architecture are well-designed and should not be changed without a new review.

- The choice of a single-process, event-driven CLI architecture with no database, no microservices, and no async/multiprocessing is correctly matched to the stated scale (≤100 files, single developer machine) — no over-engineering.
- `ast.parse`-only extraction (never `exec`/`import`) is explicitly justified against NFR-2 and correctly rejects the `importlib`/`inspect` alternative for the right reason (arbitrary code execution risk).
- Marker-block strategy (HTML comment pairs, per-module) directly matches the requirement's specified format and correctly handles preservation of hand-written content by scoping replacement to only the block between markers.
- Atomic write via temp-file + `os.replace()` correctly protects `README.md` against partial/corrupted writes on crash or interruption (Decision 5).
- Debounce window design correctly targets the "rapid successive save events" risk called out in the requirements document, independent of the thread-safety gap noted in H-2.

---

## Conditions for Approval
> Track these before/during implementation:

1. Add startup reconciliation logic to the Sync Orchestrator to detect and remove orphaned README marker blocks for modules no longer present in `src/` (resolves C-1).
2. Correct the Section 4.2 data-flow diagram/text and Section 2.3 Path Validator description so both consistently state it runs per-file from the Sync Orchestrator for both startup-enumerated and watchdog-triggered files (resolves H-1).
3. Specify a thread-safe mechanism (lock or `queue.Queue`) for the Event Debouncer's shared buffer (resolves H-2).
4. Pin `watchdog`'s version in `requirements.txt` and state a minimum Python version (resolves M-1/L-3).
5. Replace "tolerant" encoding handling with strict UTF-8 decoding that raises `ExtractionError` on failure, caught and logged per FR-5 (resolves M-2).
6. Explicitly enumerate `posonlyargs`/`kwonlyargs` handling in the signature-rendering responsibility of the AST Extractor (resolves M-3).

---

## Unresolved Open Questions
> No "Open Questions" section exists in `artifacts/architecture.md`. The following questions were identified during this review and should be answered before or during implementation:

1. When a module is deleted while the watcher is not running, should the startup reconciliation (per C-1) treat this identically to a live `on_deleted` event, or log a distinct message (e.g., "removed stale section for module no longer present at startup")?
2. Should the Event Debouncer's window duration be a hardcoded constant or a CLI-configurable value (currently unspecified either way)?

---

## Appendix: Review Methodology
- Requirements coverage: checked each FR-X and NFR-X against architecture components in Section 2.3 and the data flow in Section 4.2.
- Security: reviewed against OWASP Top 10 (relevant categories: injection via untrusted file paths, insufficient input validation) and NFR-2's stated threat model.
- Performance: compared NFR-1/NFR-3 targets against the sequential, single-process processing model in Section 7.
- Data: validated `ModuleInfo`/`FunctionInfo` schema (Section 4.1) against FR-2's extraction requirements.
- Consistency: cross-checked component names and data-flow direction between Section 2.2 (diagram), Section 2.3 (component descriptions), and Section 4.2 (detailed flow).
