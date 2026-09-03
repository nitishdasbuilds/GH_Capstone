# System Architecture Document

## 1. Executive Summary

The **Automated Documentation Sync System** is a local Python-based CLI application that monitors source code changes and automatically generates updated documentation using templates. The system runs as a single-process application on Windows, designed for solo developers working with Python codebases.

**Architecture Philosophy**: Simple, modular, event-driven monolith prioritizing maintainability and demonstration clarity over distributed complexity. The architecture emphasizes clear separation of concerns while keeping all components in a single deployable unit suitable for local execution.

**Key Technologies**: Python 3.9+, watchdog (file monitoring), GitPython (version control), Jinja2 (templating), pytest (testing)

## 2. Architecture Overview

### 2.1 Architecture Style
**Monolithic Event-Driven Architecture**

**Rationale**: 
- Single-user local execution eliminates need for distributed architecture
- Event-driven design allows asynchronous processing without blocking file watcher
- Monolithic approach simplifies deployment, debugging, and demonstration
- All components share same process space for efficient communication
- Matches constraints (local Windows, solo developer, demonstration focus)
- Easier to maintain and test for educational purposes

### 2.2 High-Level Component Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         User / Developer                          │
│                                                                    │
│  CLI Commands: start, stop, sync, status, config                 │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
                                 ↓
┌──────────────────────────────────────────────────────────────────┐
│                      CLI Interface Layer                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Command Parser (argparse)                                 │  │
│  │  - Validates commands and arguments                        │  │
│  │  - Routes to appropriate controller                        │  │
│  └──────────────────────────┬─────────────────────────────────┘  │
└─────────────────────────────┼────────────────────────────────────┘
                              │
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                     Application Core Layer                        │
│                                                                    │
│  ┌─────────────────────┐          ┌─────────────────────────┐   │
│  │  File Watcher       │          │  Sync Orchestrator      │   │
│  │  Service            │──events──▶│  (Main Controller)      │   │
│  │                     │          │                         │   │
│  │  - Monitors src/    │          │  - Coordinates workflow │   │
│  │  - Detects changes  │          │  - Manages state        │   │
│  │  - Debounces events │          │  - Routes operations    │   │
│  └─────────────────────┘          └────────┬────────────────┘   │
│                                             │                     │
│         ┌───────────────────────────────────┼───────────────┐   │
│         │                                   │               │   │
│         ↓                                   ↓               ↓   │
│  ┌─────────────────┐         ┌──────────────────┐  ┌─────────┐ │
│  │  Code Analyzer  │         │  Doc Generator   │  │ Review  │ │
│  │                 │─parsed──▶│                  │  │ Manager │ │
│  │  - AST parsing  │  code   │  - Jinja2 engine │  │         │ │
│  │  - Extract info │         │  - Template mgmt │  │ - Check │ │
│  │  - Docstrings   │         │  - Markdown gen  │  │ severity│ │
│  └─────────────────┘         └────────┬─────────┘  └────┬────┘ │
│                                        │                  │      │
│                                        └──────┬───────────┘      │
│                                               ↓                  │
│                              ┌────────────────────────────┐     │
│                              │  Documentation Writer      │     │
│                              │                            │     │
│                              │  - Section replacement     │     │
│                              │  - Markdown validation     │     │
│                              │  - Backup creation         │     │
│                              └────────────┬───────────────┘     │
└───────────────────────────────────────────┼──────────────────────┘
                                            │
                                            ↓
┌──────────────────────────────────────────────────────────────────┐
│                    Integration Layer                              │
│                                                                    │
│  ┌──────────────────┐    ┌──────────────────┐  ┌──────────────┐ │
│  │  Git Manager     │    │  JIRA Client     │  │  Secret      │ │
│  │                  │    │                  │  │  Detector    │ │
│  │  - GitPython API │    │  - REST API v2   │  │              │ │
│  │  - Commit/push   │    │  - Add comments  │  │  - Pattern   │ │
│  │  - Conflict mgmt │    │  - Link issues   │  │    matching  │ │
│  └────────┬─────────┘    └────────┬─────────┘  │  - Sanitize  │ │
│           │                       │             └──────────────┘ │
└───────────┼───────────────────────┼──────────────────────────────┘
            │                       │
            ↓                       ↓
┌──────────────────────────────────────────────────────────────────┐
│                    External Services                              │
│                                                                    │
│  ┌──────────────────────┐         ┌─────────────────────────┐   │
│  │  Git Remote          │         │  JIRA Server            │   │
│  │  (GitHub/GitLab/     │         │  (jiraeu.epam.com)      │   │
│  │   Bitbucket)         │         │                         │   │
│  └──────────────────────┘         └─────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                      Supporting Services                          │
│                                                                    │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  Config Manager │  │  Logger      │  │  Metrics Tracker  │  │
│  │                 │  │              │  │                   │  │
│  │  - Load config  │  │  - File log  │  │  - Success rate   │  │
│  │  - Env vars     │  │  - Console   │  │  - Duration       │  │
│  │  - Validation   │  │  - Rotation  │  │  - Operations     │  │
│  └─────────────────┘  └──────────────┘  └───────────────────┘  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                      Persistence Layer                            │
│                                                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  ┌──────────┐│
│  │  Config     │  │  Templates  │  │  Log Files │  │ Metrics  ││
│  │  File       │  │  Directory  │  │            │  │  JSON    ││
│  │  (YAML)     │  │  (Jinja2)   │  │  (.log)    │  │          ││
│  └─────────────┘  └─────────────┘  └────────────┘  └──────────┘│
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 Component Descriptions

#### Component: File Watcher Service
- **Purpose**: Monitor Python files in src/ directory and detect changes
- **Responsibilities**: 
  - Initialize watchdog file system observer
  - Watch for create, modify, delete events on .py files
  - Debounce rapid successive changes (300ms window)
  - Emit normalized change events to Sync Orchestrator
  - Handle watcher errors and continue monitoring
- **Technology**: Python `watchdog` library with Observer pattern
- **Interfaces**: 
  - Emits: `CodeChangeEvent(file_path, change_type, timestamp, content)`
  - Configuration: watch_directory, file_patterns
- **Scaling**: Single-threaded observer, efficient for local file systems

#### Component: Sync Orchestrator
- **Purpose**: Central controller coordinating the documentation sync workflow
- **Responsibilities**: 
  - Receive file change events from File Watcher
  - Queue and deduplicate changes (batch window: 2 seconds)
  - Create SyncOperation for each batch
  - Coordinate: CodeAnalyzer → DocGenerator → ReviewManager → DocWriter → GitManager
  - Manage operation state (pending → in_progress → completed/failed)
  - Track performance metrics
  - Handle errors and recovery
  - Notify on completion/failure
- **Technology**: Python asyncio for async coordination
- **Interfaces**: 
  - Input: CodeChangeEvent queue
  - Output: SyncOperation status updates
  - Uses: All service components
- **Scaling**: Event loop handles multiple operations efficiently

#### Component: Code Analyzer
- **Purpose**: Parse Python code and extract relevant information for documentation
- **Responsibilities**: 
  - Parse Python files using AST (Abstract Syntax Tree)
  - Extract functions, classes, methods with signatures
  - Parse docstrings (Google, NumPy, or Sphinx style)
  - Extract type hints and parameter information
  - Identify public API (not starting with _)
  - Calculate file hash for change detection
  - Handle syntax errors gracefully
- **Technology**: Python `ast` module (built-in)
- **Interfaces**: 
  - Input: File path, file content
  - Output: `ParsedCodeStructure` (classes, functions, docstrings)
- **Scaling**: Synchronous processing per file

#### Component: Doc Generator
- **Purpose**: Generate documentation content using templates
- **Responsibilities**: 
  - Load Jinja2 templates from templates/ directory
  - Map code structures to template variables
  - Generate README sections (API Examples, Configuration)
  - Generate API documentation pages
  - Validate generated Markdown
  - Support custom template filters
- **Technology**: Jinja2 template engine
- **Interfaces**: 
  - Input: ParsedCodeStructure, template name
  - Output: Generated Markdown content
- **Scaling**: Template caching for performance

#### Component: Review Manager
- **Purpose**: Determine if documentation changes require manual review
- **Responsibilities**: 
  - Calculate change severity (minor, moderate, major)
  - Check structural changes (new/removed sections)
  - Count lines changed (threshold: 50 lines)
  - Identify changes to critical sections
  - Prompt user for review when needed
  - Record review decisions
- **Technology**: Python with diff algorithms
- **Interfaces**: 
  - Input: Old docs, new docs, DocumentationUpdate
  - Output: Review decision (approve/reject), severity
  - User interaction: Console prompts
- **Scaling**: Synchronous, interactive when review needed

#### Component: Documentation Writer
- **Purpose**: Update documentation files with generated content
- **Responsibilities**: 
  - Identify auto-generated sections (HTML markers)
  - Replace sections while preserving manual content
  - Create backups before changes
  - Validate Markdown syntax
  - Atomic file writes (write to temp, rename)
  - Rollback on validation failure
- **Technology**: Python file I/O with tempfile
- **Interfaces**: 
  - Input: Target file path, generated content, sections
  - Output: Updated file, backup path
- **Scaling**: File locking for safety

#### Component: Git Manager
- **Purpose**: Integrate with Git version control
- **Responsibilities**: 
  - Initialize GitPython repository connection
  - Stage modified documentation files
  - Create descriptive commit messages
  - Tag as automated update
  - Push to configured remote (optional)
  - Handle merge conflicts (code takes precedence)
  - Authenticate using credentials
- **Technology**: GitPython library
- **Interfaces**: 
  - Input: File paths, commit message
  - Output: Commit hash, success/failure
  - Configuration: git_enabled, git_remote
- **Scaling**: Synchronous git operations

#### Component: JIRA Client
- **Purpose**: Integrate with JIRA for traceability
- **Responsibilities**: 
  - Authenticate with JIRA REST API v2
  - Extract issue keys from branch names or commits
  - Add comments to JIRA stories
  - Link commits to issues
  - Handle API errors gracefully
  - Rate limiting and retry logic
- **Technology**: Python `requests` library
- **Interfaces**: 
  - Input: Issue key, comment text, commit hash
  - Output: Success/failure status
  - Configuration: jira_enabled, jira_url, credentials
- **Scaling**: Async requests, optional (low priority)

#### Component: Secret Detector
- **Purpose**: Prevent secrets from being committed in documentation
- **Responsibilities**: 
  - Scan generated docs for secret patterns
  - Patterns: API keys, passwords, tokens, private keys
  - Regular expression matching
  - Redact or alert on detection
  - Whitelist approved patterns
- **Technology**: Python regex library
- **Interfaces**: 
  - Input: Documentation content
  - Output: Detection results, sanitized content
- **Scaling**: Fast regex scanning

#### Component: Config Manager
- **Purpose**: Manage application configuration
- **Responsibilities**: 
  - Load from YAML config file
  - Override with environment variables
  - Provide sensible defaults
  - Validate configuration
  - Expose configuration to components
- **Technology**: Python `pyyaml` library
- **Interfaces**: 
  - Input: config.yaml, environment variables
  - Output: Configuration object
- **Scaling**: Load once at startup

#### Component: Logger
- **Purpose**: Centralized logging for all components
- **Responsibilities**: 
  - Configure Python logging module
  - File logging with rotation (10MB, 5 backups)
  - Console logging with colors
  - Structured logging format (timestamp, level, component, message)
  - Performance logging for metrics
  - Never log credentials
- **Technology**: Python `logging` module
- **Interfaces**: 
  - Used by: All components
  - Output: Log files, console
- **Scaling**: Thread-safe logging

#### Component: Metrics Tracker
- **Purpose**: Track and report performance metrics
- **Responsibilities**: 
  - Record sync operations (start, end, duration)
  - Calculate success rate
  - Calculate average sync duration
  - Persist metrics to JSON file
  - Report metrics via status command
- **Technology**: Python with JSON persistence
- **Interfaces**: 
  - Input: SyncOperation events
  - Output: metrics.json, status reports
- **Scaling**: In-memory with periodic persistence

## 3. Technology Stack

### 3.1 Frontend
**Not Applicable** - This is a CLI-only application with no graphical interface.

### 3.2 Backend

- **Language**: Python 3.9+
  - **Justification**: 
    - Required by project constraints
    - Excellent libraries for file watching, Git, templates
    - Cross-platform with good Windows support
    - Rapid development for demonstration purposes
    - Rich ecosystem for code parsing (AST)
    - Team expertise (solo developer knows Python)

- **CLI Framework**: `argparse` (built-in)
  - **Justification**: Standard library, no dependencies, sufficient for simple CLI

- **Async Framework**: `asyncio` (built-in)
  - **Justification**: Built-in, allows non-blocking operations, efficient event loop

### 3.3 Core Libraries

- **File Watching**: `watchdog` 3.0+
  - **Justification**: Industry standard, excellent Windows support, battle-tested, event-driven

- **Git Integration**: `GitPython` 3.1+
  - **Justification**: Pure Python, comprehensive Git API, well-documented, active maintenance

- **Template Engine**: `Jinja2` 3.1+
  - **Justification**: Powerful, flexible, widely used, extensive filter support, good error handling

- **Code Parsing**: `ast` (built-in)
  - **Justification**: Official Python parser, no dependencies, accurate, safe

- **Markdown Processing**: `markdown` 3.4+
  - **Justification**: Validation and parsing, extensible, pure Python

- **HTTP Client**: `requests` 2.31+
  - **Justification**: Simple API, robust, handles auth well (for JIRA)

- **Configuration**: `pyyaml` 6.0+
  - **Justification**: Human-readable config format, supports complex structures

### 3.4 Development & Quality Tools

- **Testing Framework**: `pytest` 7.4+
  - **Fixtures**: For test setup and teardown
  - **Mocking**: `pytest-mock` for mocking external services
  - **Coverage**: `pytest-cov` for code coverage reporting
  - **Target**: ≥ 70% coverage for core functionality

- **Code Formatting**: `black` 23.0+
  - **Justification**: Opinionated, consistent, PEP 8 compliant

- **Linting**: `pylint` 2.17+
  - **Justification**: Comprehensive, catches errors, enforces standards

- **Type Checking**: `mypy` 1.5+ (optional)
  - **Justification**: Catch type errors early, document interfaces

### 3.5 Infrastructure

- **Operating System**: Windows 10/11
  - **Requirement**: Project constraint

- **Python Distribution**: Standard CPython 3.9+
  - **Installation**: Via python.org or Microsoft Store

- **Version Control**: Git 2.40+
  - **Assumption**: Already installed on developer machine

- **Package Management**: `pip` with `requirements.txt`
  - **Virtual Environment**: `venv` (built-in)

### 3.6 Third-Party Services

- **Git Hosting**: GitHub / GitLab / Bitbucket
  - **Integration**: Via Git protocol (HTTPS or SSH)
  - **Authentication**: Personal access tokens or SSH keys

- **JIRA**: JIRA Cloud or Server (REST API v2)
  - **Integration**: REST API via requests library
  - **Authentication**: API tokens or username/password

## 4. Data Architecture

### 4.1 Data Models

#### Entity: CodeChange
```
In-Memory Structure (dataclass)
┌──────────────────┬──────────────┬────────────────────────────────┐
│ Field            │ Type         │ Purpose                        │
├──────────────────┼──────────────┼────────────────────────────────┤
│ file_path        │ str          │ Absolute path to changed file  │
│ change_type      │ str          │ "created", "modified",         │
│                  │              │ "deleted"                      │
│ timestamp        │ datetime     │ When change was detected       │
│ content          │ str          │ File content (if applicable)   │
│ previous_hash    │ str          │ SHA256 of previous version     │
│ current_hash     │ str          │ SHA256 of current version      │
└──────────────────┴──────────────┴────────────────────────────────┘
```

**Relationships**: Part of SyncOperation
**Storage**: In-memory only, not persisted

#### Entity: ParsedCodeStructure
```
In-Memory Structure (dataclass)
┌──────────────────┬──────────────┬────────────────────────────────┐
│ Field            │ Type         │ Purpose                        │
├──────────────────┼──────────────┼────────────────────────────────┤
│ file_path        │ str          │ Source file path               │
│ module_docstring │ str          │ Module-level documentation     │
│ imports          │ List[str]    │ Import statements              │
│ classes          │ List[Class]  │ Class definitions              │
│ functions        │ List[Func]   │ Function definitions           │
│ constants        │ Dict         │ Module-level constants         │
└──────────────────┴──────────────┴────────────────────────────────┘

Nested: ClassInfo
┌──────────────────┬──────────────┬────────────────────────────────┐
│ name             │ str          │ Class name                     │
│ docstring        │ str          │ Class documentation            │
│ bases            │ List[str]    │ Base classes                   │
│ methods          │ List[Method] │ Method definitions             │
│ attributes       │ List[Attr]   │ Class attributes               │
│ is_public        │ bool         │ Not starting with _            │
└──────────────────┴──────────────┴────────────────────────────────┘

Nested: FunctionInfo
┌──────────────────┬──────────────┬────────────────────────────────┐
│ name             │ str          │ Function name                  │
│ docstring        │ str          │ Function documentation         │
│ signature        │ str          │ Full signature with types      │
│ parameters       │ List[Param]  │ Parameter details              │
│ return_type      │ str          │ Return type annotation         │
│ is_async         │ bool         │ Is async function              │
│ is_public        │ bool         │ Not starting with _            │
└──────────────────┴──────────────┴────────────────────────────────┘
```

**Relationships**: Generated by CodeAnalyzer, consumed by DocGenerator
**Storage**: In-memory only

#### Entity: DocumentationUpdate
```
In-Memory Structure (dataclass)
┌──────────────────┬──────────────────┬─────────────────────────────┐
│ Field            │ Type             │ Purpose                     │
├──────────────────┼──────────────────┼─────────────────────────────┤
│ doc_type         │ str              │ "README" or "API"           │
│ target_file      │ str              │ Path to doc file            │
│ sections         │ List[str]        │ Sections to update          │
│ generated_content│ str              │ New documentation content   │
│ requires_review  │ bool             │ Manual review needed?       │
│ severity         │ str              │ "minor", "moderate",        │
│                  │                  │ "major"                     │
│ source_changes   │ List[CodeChange] │ Related code changes        │
│ backup_path      │ str              │ Backup file location        │
└──────────────────┴──────────────────┴─────────────────────────────┘
```

**Relationships**: Part of SyncOperation
**Storage**: In-memory, optionally logged

#### Entity: SyncOperation
```
In-Memory Structure + JSON Persistence (for metrics)
┌──────────────────┬───────────────────┬────────────────────────────┐
│ Field            │ Type              │ Purpose                    │
├──────────────────┼───────────────────┼────────────────────────────┤
│ id               │ str (UUID)        │ Unique operation ID        │
│ status           │ str               │ "pending", "in_progress",  │
│                  │                   │ "completed", "failed"      │
│ start_time       │ datetime          │ When operation started     │
│ end_time         │ datetime          │ When operation finished    │
│ duration_seconds │ float             │ Total duration             │
│ code_changes     │ List[CodeChange]  │ Code files changed         │
│ doc_updates      │ List[DocUpdate]   │ Documentation updates      │
│ errors           │ List[str]         │ Error messages             │
│ committed        │ bool              │ Committed to Git?          │
│ commit_hash      │ str               │ Git commit SHA             │
│ review_required  │ bool              │ Did it need review?        │
│ review_approved  │ bool              │ Was review approved?       │
└──────────────────┴───────────────────┴────────────────────────────┘
```

**Relationships**: Root entity containing all operation data
**Storage**: In-memory during execution, persisted summary to metrics.json

#### Entity: Configuration
```
File: config.yaml
┌──────────────────────────┬──────────┬────────────────────────────┐
│ Field                    │ Type     │ Default                    │
├──────────────────────────┼──────────┼────────────────────────────┤
│ watch_directory          │ str      │ "src/"                     │
│ readme_path              │ str      │ "README.md"                │
│ api_doc_path             │ str      │ "docs/API.md"              │
│ templates_directory      │ str      │ "templates/"               │
│ review_threshold_lines   │ int      │ 50                         │
│ git_enabled              │ bool     │ true                       │
│ git_remote               │ str      │ "origin"                   │
│ git_auto_push            │ bool     │ false                      │
│ jira_enabled             │ bool     │ false                      │
│ jira_url                 │ str      │ ""                         │
│ notification_channels    │ list     │ ["console"]                │
│ log_file                 │ str      │ "doc_sync.log"             │
│ log_level                │ str      │ "INFO"                     │
│ performance_metrics      │ bool     │ true                       │
│ metrics_file             │ str      │ "metrics.json"             │
│ debounce_seconds         │ float    │ 0.3                        │
│ batch_window_seconds     │ float    │ 2.0                        │
└──────────────────────────┴──────────┴────────────────────────────┘
```

**Storage**: config.yaml file, loaded at startup
**Override**: Environment variables (e.g., DOC_SYNC_GIT_ENABLED)

#### Entity: Metrics (Persisted)
```
File: metrics.json
{
  "total_operations": 0,
  "successful_operations": 0,
  "failed_operations": 0,
  "total_duration_seconds": 0.0,
  "operations_history": [
    {
      "id": "uuid",
      "timestamp": "ISO 8601",
      "duration_seconds": 0.0,
      "status": "completed|failed",
      "files_changed": 0,
      "docs_updated": 0,
      "review_required": false
    }
    // Last 100 operations
  ],
  "last_updated": "ISO 8601"
}
```

**Purpose**: Track performance metrics for success rate and duration reporting
**Updates**: After each sync operation
**Retention**: Last 100 operations

### 4.2 Data Flow Diagram

```
File Change in src/
       ↓
[File System Event]
       ↓
[File Watcher Service] ─────────────┐
       │                            │
       │ (debounce 300ms)           │ (watches)
       ↓                            │
[Event Queue]                       │
       │                            │
       │ (batch 2s)                 ↓
       ↓                    [File System src/]
[Sync Orchestrator]
       │
       │ Create SyncOperation
       │
       ├─→ [Code Analyzer]
       │          │
       │          │ Parse AST
       │          ↓
       │   [ParsedCodeStructure]
       │          │
       │          ↓
       ├─→ [Doc Generator]
       │          │
       │          │ Apply templates
       │          ↓
       │   [Generated Markdown]
       │          │
       │          ↓
       ├─→ [Review Manager]
       │          │
       │          ├─→ (if severe) [User Prompt] → (Approve/Reject)
       │          │
       │          ↓
       │   [Review Decision]
       │          │
       │          ↓ (if approved)
       ├─→ [Secret Detector]
       │          │
       │          │ Scan for secrets
       │          ↓
       │   [Sanitized Content]
       │          │
       │          ↓
       ├─→ [Documentation Writer]
       │          │
       │          ├─→ Create backup
       │          ├─→ Update sections
       │          ├─→ Validate
       │          ↓
       │   [Updated Doc Files]
       │          │
       │          ↓
       ├─→ [Git Manager] (if git_enabled)
       │          │
       │          ├─→ Stage files
       │          ├─→ Commit
       │          ├─→ Push (if auto_push)
       │          ↓
       │   [Git Commit Hash]
       │          │
       │          ↓
       ├─→ [JIRA Client] (if jira_enabled)
       │          │
       │          └─→ Add comment to issue
       │
       ├─→ [Metrics Tracker]
       │          │
       │          └─→ Record operation
       │
       └─→ [Logger]
              │
              └─→ Log success/failure
```

**Detailed Flow for Documentation Sync Operation:**

1. **File Watcher** detects change in src/example.py
2. **Debouncing**: Wait 300ms for additional changes
3. **Event Queue**: Add CodeChangeEvent to queue
4. **Batching**: Wait 2 seconds for related changes
5. **Sync Orchestrator**: Create SyncOperation with UUID
6. **Code Analyzer**: 
   - Read example.py content
   - Parse using AST
   - Extract functions, classes, docstrings
   - Return ParsedCodeStructure
7. **Doc Generator**:
   - Load appropriate Jinja2 templates
   - Map parsed code to template variables
   - Render README API section
   - Render API documentation
   - Return generated Markdown
8. **Review Manager**:
   - Compare old vs new documentation
   - Calculate lines changed, structural changes
   - Determine severity
   - If major/critical: Prompt user for review
   - User approves/rejects
9. **Secret Detector**:
   - Scan generated content with regex patterns
   - Check for API keys, tokens, passwords
   - Redact or alert if found
10. **Documentation Writer**:
    - Create backup of README.md
    - Find auto-generated section markers
    - Replace section content atomically
    - Validate Markdown syntax
    - Rollback if validation fails
11. **Git Manager** (if enabled):
    - Stage README.md and docs/API.md
    - Create commit message: "docs: auto-update from example.py changes"
    - Commit with [automated] tag
    - Push to remote (if auto_push)
    - Return commit hash
12. **JIRA Client** (if enabled):
    - Extract issue key from branch name
    - Post comment: "Documentation updated in commit {hash}"
13. **Metrics Tracker**:
    - Record end_time, duration, status
    - Update success/failure counts
    - Persist to metrics.json
14. **Logger**:
    - Log completion: "Sync operation {id} completed in 45.2s"
15. **User Notification**:
    - Console: "✓ Documentation synced successfully (45.2s)"

**Error Handling Path:**
- Any component failure → Log error → Mark SyncOperation as failed → Continue monitoring
- Validation failure → Rollback changes → Notify user → Log details
- Git conflict → Log conflict → Attempt resolution (code precedence) → Notify user

### 4.3 Caching Strategy

**Template Caching:**
- **Cache Layer**: In-memory Jinja2 environment with auto-reload
- **Cache Keys**: Template file path
- **TTL Strategy**: Reload if file modified (watch template directory)
- **Invalidation**: File system watch or manual reload command

**Code Analysis Caching:**
- **Cache Layer**: In-memory dictionary keyed by file hash
- **Cache Keys**: SHA256(file_content)
- **TTL Strategy**: Invalidate when file hash changes
- **Benefit**: Skip re-parsing if file hasn't changed (only timestamp update)

**Configuration Caching:**
- **Cache Layer**: Singleton ConfigManager
- **TTL Strategy**: Load once at startup, reload on SIGHUP or manual command
- **Invalidation**: `doc_sync.py config reload` command

**No Database Caching**: This is a local single-user application; database caching is not applicable.

## 5. API Design

### 5.1 CLI Commands (Command-Line API)

#### Command: start
```
python doc_sync.py start [--config CONFIG_FILE] [--daemon]

Purpose: Start the file watcher and documentation sync service

Options:
  --config PATH   Path to config.yaml (default: ./config.yaml)
  --daemon        Run in background (Windows service mode)

Behavior:
  1. Load configuration
  2. Initialize components (logger, metrics, file watcher)
  3. Start file watching on configured directory
  4. Display startup message with configuration summary
  5. Enter main event loop
  6. Process file changes until stopped

Output:
  Console: Status messages and sync notifications
  Log file: Detailed operation logs
  
Exit Codes:
  0 - Normal shutdown (Ctrl+C or stop command)
  1 - Configuration error
  2 - Permission error
  3 - Dependency missing
```

#### Command: stop
```
python doc_sync.py stop

Purpose: Gracefully stop the running service

Behavior:
  1. Send shutdown signal to running process
  2. Wait for current sync operation to complete
  3. Save metrics and state
  4. Clean up resources
  5. Exit

Output:
  "Service stopped gracefully"
  
Exit Codes:
  0 - Success
  1 - No running service found
```

#### Command: sync
```
python doc_sync.py sync [--file FILE_PATH] [--force]

Purpose: Manually trigger documentation sync

Options:
  --file PATH     Sync only this file (default: all files in src/)
  --force         Skip review prompts, apply all changes

Behavior:
  1. Load configuration
  2. Analyze specified file(s)
  3. Generate documentation
  4. Apply changes (with review if needed)
  5. Commit if git_enabled

Output:
  Detailed sync results for each file
  
Exit Codes:
  0 - All syncs successful
  1 - Some syncs failed
  2 - All syncs failed
```

#### Command: status
```
python doc_sync.py status [--json]

Purpose: Display current status and performance metrics

Options:
  --json          Output in JSON format

Output:
  Service Status: Running / Stopped
  Watching: src/ (15 .py files)
  
  Performance Metrics:
  ├─ Total Operations: 47
  ├─ Successful: 45 (95.7%)
  ├─ Failed: 2 (4.3%)
  ├─ Average Duration: 28.3s
  └─ Last Sync: 2026-09-01 14:32:15 (2 minutes ago)
  
  Recent Operations (last 5):
  1. [2026-09-01 14:32:15] src/example.py → ✓ (32.1s)
  2. [2026-09-01 13:15:42] src/config.py → ✓ (25.6s)
  3. [2026-09-01 12:08:19] src/main.py → ✗ (git error)
  4. [2026-09-01 11:45:33] src/utils.py → ✓ (19.8s)
  5. [2026-09-01 10:12:07] src/parser.py → ✓ (41.2s)
  
Exit Codes:
  0 - Always success
```

#### Command: config
```
python doc_sync.py config [--set KEY=VALUE] [--get KEY] [--list]

Purpose: View or update configuration

Options:
  --set KEY=VALUE Set configuration value
  --get KEY       Get specific configuration value
  --list          List all configuration (default)

Examples:
  python doc_sync.py config --list
  python doc_sync.py config --get git_enabled
  python doc_sync.py config --set git_auto_push=true

Output:
  Configuration values or confirmation of update
  
Exit Codes:
  0 - Success
  1 - Invalid key or value
```

### 5.2 Internal API (Python Module Interface)

Components expose clean interfaces for testing and extensibility:

```python
# File Watcher Service
class FileWatcherService:
    def start(self, directory: str, patterns: List[str]) -> None
    def stop(self) -> None
    def on_change(self, callback: Callable[[CodeChangeEvent], None]) -> None

# Code Analyzer
class CodeAnalyzer:
    def analyze_file(self, file_path: str) -> ParsedCodeStructure
    def extract_docstring(self, node: ast.AST) -> str

# Doc Generator
class DocGenerator:
    def generate_readme_section(self, structure: ParsedCodeStructure, 
                                 section: str) -> str
    def generate_api_docs(self, structures: List[ParsedCodeStructure]) -> str
    def load_template(self, name: str) -> jinja2.Template

# Review Manager
class ReviewManager:
    def assess_severity(self, old_doc: str, new_doc: str) -> str
    def requires_review(self, update: DocumentationUpdate) -> bool
    def prompt_user_review(self, update: DocumentationUpdate) -> bool

# Documentation Writer
class DocumentationWriter:
    def update_sections(self, file_path: str, sections: Dict[str, str]) -> None
    def create_backup(self, file_path: str) -> str
    def validate_markdown(self, content: str) -> bool

# Git Manager
class GitManager:
    def commit(self, files: List[str], message: str) -> str
    def push(self, remote: str = "origin") -> bool
    def handle_conflict(self, file_path: str) -> None
```

### 5.3 Error Handling

**Standard Error Response Format (Console):**
```
ERROR [component] message
Details: additional context
Suggestion: what user should do

Example:
ERROR [GitManager] Failed to push to remote 'origin'
Details: Remote rejected push (authentication failed)
Suggestion: Check Git credentials in environment or run 'git config credential.helper'
```

**Error Codes:**
- E001-E099: Configuration errors
- E100-E199: File system errors
- E200-E299: Parsing errors
- E300-E399: Template errors
- E400-E499: Git errors
- E500-E599: JIRA errors
- E600-E699: Validation errors
- E900-E999: Unknown errors

**Recovery Strategies:**
- Transient errors (network): Retry with exponential backoff (3 attempts)
- Validation errors: Rollback changes, alert user
- Git conflicts: Apply resolution strategy, log outcome
- Missing files: Log warning, continue monitoring
- Fatal errors: Shutdown gracefully, preserve state

## 6. Security Architecture

### 6.1 Authentication & Authorization

**No User Authentication**: Single-user local application, relies on OS-level authentication.

**Git Authentication:**
- **Method**: OS Git credential manager or SSH keys
- **Storage**: Delegates to Git's credential.helper
- **Token Management**: Environment variable `GIT_TOKEN` or Git credential store

**JIRA Authentication:**
- **Method**: API token or username/password
- **Storage**: Environment variables (`JIRA_TOKEN`, `JIRA_USERNAME`, `JIRA_PASSWORD`)
- **Never stored in**: Config files, code, logs

**Credential Access:**
- Only GitManager and JIRAClient components can access credentials
- Credentials are read once at initialization
- Never passed through other components or logged

### 6.2 Data Security

**Encryption in Transit:**
- Git: HTTPS (TLS 1.2+) or SSH
- JIRA: HTTPS (TLS 1.2+)

**Encryption at Rest:**
- Not implemented (local filesystem, OS-level encryption if needed)
- Credentials: OS credential manager (Windows Credential Manager)

**Sensitive Data Handling:**
- **Secret Detection**: Regex patterns for API keys, tokens, passwords
- **Sanitization**: Redact before committing
- **Logging**: Never log credentials or tokens
- **Patterns Detected**:
  - API keys: `[A-Za-z0-9]{32,}`
  - AWS keys: `AKIA[0-9A-Z]{16}`
  - Private keys: `-----BEGIN.*PRIVATE KEY-----`
  - Passwords in config: `password\s*[:=]\s*['"](.*?)['"]`

### 6.3 Security Layers

**Application Security:**
- **Input Validation**: 
  - File paths: Prevent directory traversal
  - Config values: Type checking and bounds
  - CLI arguments: Sanitize before use
- **Code Injection Prevention**:
  - Templates: Jinja2 auto-escaping enabled
  - AST parsing: Safe, no eval() or exec()
  - Shell commands: Use GitPython API, not shell=True
- **File System Safety**:
  - Atomic writes: temp file + rename
  - Backups before modifications
  - Permission checks before writing

**Dependency Security:**
- Pin versions in requirements.txt
- Use `pip-audit` to check for vulnerabilities
- Regular updates for security patches

**Logging Security:**
- Never log: passwords, tokens, API keys, SSH keys
- Sanitize: file paths (don't expose username)
- Audit: All authentication attempts

### 6.4 Compliance

**Not Applicable**: Solo developer demonstration project, no regulatory requirements.

**Best Practices Followed:**
- Least privilege: Only access needed resources
- Secure defaults: Git push disabled by default
- Audit logging: All operations logged
- Secret management: Use environment variables

## 7. Scalability & Performance

### 7.1 Scalability Strategy

**Not Applicable - Single User System**

This system is designed for a single developer running locally. Scalability across users or machines is out of scope.

**Local Performance Scalability:**
- **File Count**: Efficiently handles projects with 100-500 Python files
- **File Size**: Parses files up to 10,000 lines efficiently
- **Concurrency**: Single-threaded file watcher, async sync operations

**Limitations:**
- Very large monorepos (>1000 files): May have slower startup
- Mitigation: Configurable watch directory to monitor subset

### 7.2 Performance Optimization

**Caching:**
- Template caching: Jinja2 environment caches compiled templates
- Code analysis caching: Skip re-parsing unchanged files (hash-based)
- Configuration caching: Load once at startup

**Efficient File Watching:**
- Debouncing: Avoid processing rapid successive saves (300ms window)
- Batching: Group related changes (2-second window)
- Selective watching: Only .py files in src/ directory

**Asynchronous Processing:**
- Non-blocking file I/O using asyncio
- Background sync while watching continues
- Queue management prevents backlog

**Database Optimization:**
- **Not Applicable**: No database used
- Metrics persisted to JSON (lightweight)

**Template Optimization:**
- Pre-compile templates at startup
- Minimize template complexity
- Use template inheritance to avoid duplication

### 7.3 Performance Targets

**From NFR-1 Requirements:**

- **File Change Detection Latency**: < 5 seconds from file save
  - Target: < 2 seconds (watchdog is very fast)
  
- **Documentation Generation Time**: < 2 minutes for typical changes
  - Target: < 30 seconds for single file
  
- **Complete Sync Cycle**: < 5 minutes (detection → commit)
  - Target: < 3 minutes average
  
- **Sync Success Rate**: ≥ 95%
  - Target: ≥ 98% (fail only on unexpected errors)
  
- **CPU Usage (Idle)**: < 5%
  - Target: < 2% (file watcher is efficient)
  
- **Memory Usage**: < 100 MB
  - Target: < 50 MB for typical projects

**Measurement:**
- Performance metrics tracked in SyncOperation
- Reported via `status` command
- Logged for analysis

## 8. Reliability & Availability

### 8.1 High Availability

**Not Applicable**: Single-user local application, no HA requirements.

**Restart Capability:**
- Service can be restarted without data loss
- Metrics persist across restarts
- No lost file change events (manual sync available)

### 8.2 Disaster Recovery

**RTO (Recovery Time Objective)**: Immediate (restart service)

**RPO (Recovery Point Objective)**: Last committed change

**Backup Strategy:**
- Documentation backups: Created before each update
- Metrics: Persisted after each operation
- Logs: Rotated and preserved
- Code: Under version control (Git)

**Recovery Procedures:**
1. If service crashes: Restart with `python doc_sync.py start`
2. If documentation corrupted: Restore from backup or Git history
3. If Git issues: Manual Git operations to resolve
4. If metrics lost: Rebuild from Git history

### 8.3 Fault Tolerance

**Circuit Breakers:**
- JIRA API: After 3 consecutive failures, disable JIRA integration for 5 minutes
- Git push: After failure, log and continue (don't block sync)

**Retry Logic:**
- Git operations: 3 attempts with exponential backoff (1s, 2s, 4s)
- JIRA API: 3 attempts with exponential backoff
- File I/O: 2 attempts with 1-second delay

**Graceful Degradation:**
- JIRA unavailable: Log warning, continue sync without JIRA
- Git push fails: Commit locally, alert user to push manually
- Template missing: Use fallback basic template
- Review prompt fails: Default to requiring review (safe choice)

**Error Isolation:**
- Each SyncOperation is independent
- One failure doesn't stop file watching
- Errors logged but service continues

**Health Checks:**
- File watcher status: Check observer is alive
- Disk space: Warn if < 100MB free
- Git repository: Check repo is valid
- Configuration: Validate on load

**Self-Healing:**
- File watcher crash: Automatically restart observer
- Temp file cleanup: Remove orphaned temp files on startup
- Lock file cleanup: Remove stale lock files

## 9. Monitoring & Observability

### 9.1 Metrics

**System Metrics:**
- CPU usage: Monitored by Python `psutil` library (optional)
- Memory usage: Tracked for performance
- Disk space: Checked periodically

**Application Metrics:**
- Sync operations: Total, successful, failed
- Sync duration: Min, max, average, p95, p99
- Review rate: Percentage requiring manual review
- File watch events: Total events detected
- Component failures: Errors per component

**Business Metrics:**
- Documentation freshness: Time since last sync
- Files monitored: Count of .py files in src/
- Commits generated: Auto-commits per day

**Metrics Collection:**
- Tracked by MetricsTracker component
- Persisted to metrics.json
- Retained: Last 100 operations

### 9.2 Logging

**Log Levels:**
- **ERROR**: Failures, exceptions, critical issues
- **WARN**: Potential issues, degraded operation
- **INFO**: Normal operations, sync completions
- **DEBUG**: Detailed traces, internal state (disabled by default)

**Log Format:**
```
[YYYY-MM-DD HH:MM:SS.mmm] [LEVEL] [Component] Message
Context: {key: value}

Example:
[2026-09-01 14:32:15.234] [INFO] [SyncOrchestrator] Sync operation completed
Context: {operation_id: "abc-123", duration: 32.1, files: 1, status: "success"}
```

**Log Aggregation:**
- Single log file: doc_sync.log
- Rotation: 10 MB per file, keep 5 backups
- Location: Configurable, default project root

**Log Retention:**
- 5 rotated files = ~50MB total
- Equivalent to ~1-2 weeks of operation

**What is Logged:**
- All sync operations (start, end, duration, status)
- File changes detected
- Documentation updates applied
- Git commits created
- JIRA comments added
- Errors and stack traces
- Configuration changes
- User interactions (review prompts)

**What is NOT Logged:**
- Credentials or tokens
- File content (only paths and hashes)
- Personal information

### 9.3 Alerting

**Alert Channels:**
- Console: Immediate notifications during operation
- Log file: All events for later review
- (Optional) Email: Not implemented in v1

**Alert Conditions:**
- **Critical**:
  - Service crash or unexpected shutdown
  - Git commit failed repeatedly
  - Documentation corruption detected
- **Warning**:
  - Sync failure (single operation)
  - JIRA API unavailable
  - Disk space < 100MB
  - Review required (user prompt)
- **Info**:
  - Sync completed successfully
  - Configuration reloaded

**Alert Format (Console):**
```
⚠ WARNING: Git push failed (authentication error)
✓ SUCCESS: Documentation synced for src/example.py
✗ ERROR: Failed to parse src/broken.py (syntax error)
⟳ REVIEW: Major documentation change requires approval
```

**On-Call Rotation:**
- Not applicable (solo developer)

### 9.4 Distributed Tracing

**Not Applicable**: Monolithic single-process application, no distributed components.

**Operation Tracing:**
- Each SyncOperation has unique ID (UUID)
- All logs for an operation include operation_id
- Can trace flow through components via ID

## 10. Key Design Decisions

### Decision 1: Monolithic vs. Microservices Architecture

**Context**: Need to decide overall architecture pattern for the system.

**Options Considered:**
1. **Monolithic Python Application**
   - **Pros**: Simple deployment, easy debugging, no network overhead, suitable for solo developer
   - **Cons**: Less scalable, components tightly coupled
   
2. **Microservices (File Watcher, Doc Generator, Git Service)**
   - **Pros**: Scalable, independent deployment, polyglot
   - **Cons**: Complex for single user, network overhead, harder to debug, over-engineered
   
3. **Serverless Functions (Lambda/Azure Functions)**
   - **Pros**: Auto-scaling, pay-per-use
   - **Cons**: Requires cloud, cold starts, complex state management, violates local-only constraint

**Decision**: Monolithic Python Application

**Rationale**:
- Single-user local execution (no scale requirements)
- Demonstration focus requires simplicity and clarity
- Easier to understand, test, and debug
- No network latency between components
- Matches Python ecosystem conventions
- Deployment is trivial (single script)

**Consequences**:
- Cannot scale horizontally (not needed)
- All components share same process (tight coupling acceptable for this use case)
- Simpler testing and demonstration
- Faster development cycle

**Related Requirements**: All constraints (local Windows, solo developer, demonstration)

### Decision 2: Event-Driven vs. Polling for File Watching

**Context**: How to detect file changes in the src/ directory.

**Options Considered:**
1. **Event-Driven (watchdog library)**
   - **Pros**: Immediate detection, low CPU, efficient, industry standard
   - **Cons**: Requires library, platform differences
   
2. **Polling (check periodically)**
   - **Pros**: Simple, no dependencies
   - **Cons**: High CPU, delayed detection, inefficient
   
3. **Git Hooks (pre-commit)**
   - **Pros**: Integrated with Git workflow
   - **Cons**: Requires manual setup, only triggers on commit, misses intermediate changes

**Decision**: Event-Driven with watchdog library

**Rationale**:
- Meets performance requirement (< 5 seconds detection)
- Minimal CPU overhead (< 5% idle)
- Watchdog is mature, well-tested on Windows
- Real-time detection better than polling delay
- Industry standard approach

**Consequences**:
- Dependency on watchdog library
- Must handle platform differences (watchdog abstracts this)
- Excellent performance characteristics

**Related Requirements**: FR-1, NFR-1 (Performance)

### Decision 3: Template-Based vs. AI-Generated Documentation

**Context**: How to generate documentation content from code.

**Options Considered:**
1. **Template-Based (Jinja2)**
   - **Pros**: Predictable, fast, no API costs, works offline, customizable
   - **Cons**: Less intelligent, requires template maintenance
   
2. **AI/LLM (OpenAI, Claude)**
   - **Pros**: Intelligent, context-aware, natural language
   - **Cons**: API costs, latency, requires internet, less predictable
   
3. **Hybrid (Templates + AI enhancement)**
   - **Pros**: Best of both worlds
   - **Cons**: Complex, costly, over-engineered for demo

**Decision**: Template-Based with Jinja2

**Rationale**:
- Requirement explicitly specifies template-based (stakeholder preference)
- Works offline (local development)
- No API costs or rate limits
- Fast and predictable
- Easier to demonstrate and understand
- Sufficient for Python code with docstrings
- Templates can be customized by user

**Consequences**:
- Documentation quality depends on template design
- Requires well-structured code with docstrings
- No advanced natural language generation
- Templates need initial setup

**Related Requirements**: FR-2 (Template-Based Documentation Generation)

### Decision 4: Synchronous vs. Asynchronous Processing

**Context**: How to process sync operations while continuing to watch files.

**Options Considered:**
1. **Fully Synchronous (Single-threaded)**
   - **Pros**: Simple, no concurrency issues
   - **Cons**: Blocks file watching during sync, poor UX
   
2. **Threading (concurrent.futures)**
   - **Pros**: True parallelism, familiar pattern
   - **Cons**: GIL limitations, complex error handling, shared state issues
   
3. **Async/Await (asyncio)**
   - **Pros**: Efficient I/O, cooperative multitasking, Pythonic
   - **Cons**: Requires async-aware libraries

**Decision**: Hybrid - Async I/O with asyncio

**Rationale**:
- File watching continues while sync operations run
- Async is ideal for I/O-bound operations (file, network)
- Python 3.9+ has mature asyncio support
- Better resource utilization than threads
- Cooperative multitasking avoids race conditions
- Can batch multiple changes efficiently

**Consequences**:
- Must use async-compatible libraries or run_in_executor for sync code
- Slightly more complex code structure
- Excellent performance and responsiveness

**Related Requirements**: NFR-1 (Performance - non-blocking), NFR-4 (Usability)

### Decision 5: Conditional Review vs. Always Manual vs. Fully Automated

**Context**: When should documentation changes require human approval?

**Options Considered:**
1. **Always Manual Review**
   - **Pros**: Maximum safety, human oversight
   - **Cons**: Tedious, slows workflow, defeats automation purpose
   
2. **Fully Automated (No Review)**
   - **Pros**: Fastest, true automation
   - **Cons**: Risk of errors, bad documentation committed
   
3. **Conditional (Severity-Based)**
   - **Pros**: Balances automation and safety
   - **Cons**: Requires severity assessment logic

**Decision**: Conditional Review Based on Severity

**Rationale**:
- Requirement specifies conditional review (FR-5)
- Minor changes (typo fixes, small additions) don't need review
- Major changes (structural, critical sections) need review
- Balances automation efficiency with quality control
- User maintains oversight on important changes
- Configurable threshold (50 lines default)

**Consequences**:
- Requires severity assessment logic (line count, structure analysis)
- Some operations require user interaction
- Must handle review prompts gracefully
- Good balance for demonstration

**Related Requirements**: FR-5 (Conditional Review Workflow)

### Decision 6: Git Commit Strategy - Auto vs. Manual vs. Staged

**Context**: How to handle committing documentation changes to Git.

**Options Considered:**
1. **Auto-Commit and Push**
   - **Pros**: Fully automated, immediate sync
   - **Cons**: May pollute Git history, risky if push fails
   
2. **Auto-Commit, Manual Push**
   - **Pros**: Safe, preserves local changes, user control
   - **Cons**: Requires manual step
   
3. **Stage Only, Manual Commit**
   - **Pros**: Maximum user control
   - **Cons**: Defeats automation purpose

**Decision**: Auto-Commit Locally, Optional Auto-Push (Default: Disabled)

**Rationale**:
- Commits provide audit trail and versioning
- Local commits are safe (can amend or revert)
- Auto-push disabled by default for safety
- User can enable auto-push if desired
- Separate commits for each sync operation (clear history)
- Commits tagged as [automated] for clarity

**Consequences**:
- Git history includes automated commits
- User can review commits before pushing
- Must handle commit failures gracefully
- Push failures don't break sync workflow

**Related Requirements**: FR-6 (Version Control Integration)

### Decision 7: In-Memory State vs. Database for Metrics

**Context**: How to persist sync operation metrics and history.

**Options Considered:**
1. **SQLite Database**
   - **Pros**: Structured queries, relational data, mature
   - **Cons**: Overkill for simple metrics, adds dependency
   
2. **JSON File**
   - **Pros**: Simple, human-readable, no dependencies
   - **Cons**: Limited query capability, load entire file
   
3. **No Persistence (In-Memory Only)**
   - **Pros**: Simplest
   - **Cons**: Lose metrics on restart

**Decision**: JSON File with In-Memory Cache

**Rationale**:
- Simple metrics (counts, averages) don't need SQL
- JSON is human-readable and debuggable
- Python json module is built-in
- Persist after each operation (durability)
- Load into memory at startup (fast queries)
- Retain last 100 operations (bounded size)
- Suitable for single-user demonstration

**Consequences**:
- Limited to simple queries (recent operations, averages)
- File I/O on each update (acceptable for infrequent operations)
- Manual file editing possible if needed
- ~10KB file size (very lightweight)

**Related Requirements**: NFR-1 (Performance metrics), Success Criteria

### Decision 8: Secrets Management Strategy

**Context**: How to securely handle Git and JIRA credentials.

**Options Considered:**
1. **Config File (YAML)**
   - **Pros**: Simple, centralized
   - **Cons**: Insecure, credentials in plaintext
   
2. **Environment Variables**
   - **Pros**: Standard practice, no file storage, OS-level protection
   - **Cons**: Must set before running, less convenient
   
3. **Windows Credential Manager**
   - **Pros**: Secure OS storage, encrypted
   - **Cons**: Platform-specific, requires additional library
   
4. **Hybrid (Env Vars + Credential Manager)**
   - **Pros**: Flexibility
   - **Cons**: More complex

**Decision**: Environment Variables (Primary) with Git Credential Helper (Fallback)

**Rationale**:
- Environment variables are standard for credentials
- No plaintext in config files or code
- Git already has credential.helper system
- JIRA credentials via JIRA_TOKEN env var
- Simple and secure
- Documented in README setup instructions
- Meets security requirements (NFR-2)

**Consequences**:
- User must set environment variables
- Clear documentation needed in README
- No credential storage in code or config
- Credentials never logged

**Related Requirements**: NFR-2 (Security)

## 11. Deployment Architecture

### 11.1 Environments

**Single Environment: Local Development**

- **Purpose**: Solo developer's local Windows machine
- **Configuration**: config.yaml in project root
- **Deployment**: Manual (git clone + pip install)

**No Staging or Production**: This is a local demonstration project, not a deployed service.

### 11.2 Deployment Strategy

**Installation:**
```bash
# 1. Clone repository
git clone <repository-url>
cd doc-sync-project

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure
copy config.example.yaml config.yaml
# Edit config.yaml with project-specific paths

# 5. Set credentials (environment variables)
setx GIT_TOKEN "your-git-token"
setx JIRA_TOKEN "your-jira-token"

# 6. Run
python doc_sync.py start
```

**Update Strategy:**
```bash
git pull origin main
pip install --upgrade -r requirements.txt
python doc_sync.py stop
python doc_sync.py start
```

**Rollback Strategy:**
```bash
git checkout <previous-commit>
pip install -r requirements.txt
python doc_sync.py start
```

**Database Migrations:**
- Not applicable (no database)
- Configuration schema changes: Manual config.yaml update

### 11.3 Infrastructure as Code

**Not Applicable**: Local execution, no cloud infrastructure.

**Configuration as Code:**
- config.yaml: Application configuration
- requirements.txt: Python dependencies
- templates/: Documentation templates
- All version-controlled in Git

## 12. Development Guidelines

### 12.1 Code Organization

**Project Structure:**
```
doc-sync-project/
├── doc_sync.py              # Main CLI entry point
├── config.yaml              # Configuration file
├── config.example.yaml      # Template configuration
├── requirements.txt         # Python dependencies
├── README.md                # User documentation
├── LICENSE                  # License file
│
├── src/                     # User's code (watched)
│   ├── __init__.py
│   └── ...                  # User's Python modules
│
├── doc_sync/                # Application package
│   ├── __init__.py
│   ├── core/                # Core components
│   │   ├── __init__.py
│   │   ├── orchestrator.py  # SyncOrchestrator
│   │   └── models.py        # Data models (dataclasses)
│   │
│   ├── watchers/            # File watching
│   │   ├── __init__.py
│   │   └── file_watcher.py  # FileWatcherService
│   │
│   ├── analyzers/           # Code analysis
│   │   ├── __init__.py
│   │   └── code_analyzer.py # CodeAnalyzer
│   │
│   ├── generators/          # Documentation generation
│   │   ├── __init__.py
│   │   ├── doc_generator.py # DocGenerator
│   │   └── templates/       # Jinja2 templates
│   │       ├── readme_api.j2
│   │       ├── readme_config.j2
│   │       └── api_doc.j2
│   │
│   ├── writers/             # Documentation writing
│   │   ├── __init__.py
│   │   └── doc_writer.py    # DocumentationWriter
│   │
│   ├── reviewers/           # Review management
│   │   ├── __init__.py
│   │   └── review_manager.py# ReviewManager
│   │
│   ├── integrations/        # External integrations
│   │   ├── __init__.py
│   │   ├── git_manager.py   # GitManager
│   │   ├── jira_client.py   # JIRAClient
│   │   └── secret_detector.py# SecretDetector
│   │
│   ├── utils/               # Utilities
│   │   ├── __init__.py
│   │   ├── config.py        # ConfigManager
│   │   ├── logger.py        # Logger setup
│   │   └── metrics.py       # MetricsTracker
│   │
│   └── cli/                 # CLI interface
│       ├── __init__.py
│       └── commands.py      # Command handlers
│
├── tests/                   # Test suite
│   ├── __init__.py
│   ├── unit/                # Unit tests
│   │   ├── test_analyzer.py
│   │   ├── test_generator.py
│   │   └── ...
│   ├── integration/         # Integration tests
│   │   ├── test_sync_flow.py
│   │   └── ...
│   └── fixtures/            # Test fixtures
│       ├── sample_code.py
│       └── expected_docs.md
│
├── templates/               # User-editable templates
│   ├── readme_api.j2
│   ├── readme_config.j2
│   └── api_doc.j2
│
├── docs/                    # Project documentation
│   ├── API.md               # Generated API docs (example)
│   └── ARCHITECTURE.md      # This document
│
├── logs/                    # Log files (gitignored)
│   └── doc_sync.log
│
└── metrics.json             # Performance metrics (gitignored)
```

**Module Boundaries:**
- Each subdirectory is a logical module with `__init__.py`
- Single Responsibility: Each module has one primary purpose
- Dependency Direction: Core → Utils, Generators → Analyzers, Orchestrator → All
- No circular dependencies

**Dependency Management:**
- requirements.txt for production dependencies
- requirements-dev.txt for development tools (pytest, black, pylint)
- Use `pip freeze` to lock versions

### 12.2 Development Workflow

**Branching Strategy**: Simple GitHub Flow (for demonstration)

- `main`: Stable, working code
- `feature/feature-name`: New features
- `fix/bug-description`: Bug fixes
- `docs/update-description`: Documentation updates

**Workflow:**
1. Create feature branch from `main`
2. Develop and test locally
3. Run tests: `pytest`
4. Run linter: `pylint doc_sync/`
5. Format code: `black doc_sync/`
6. Commit with descriptive messages
7. Push branch
8. Create pull request (if team collaboration)
9. Merge to `main` after review

**Code Review:**
- Self-review for solo developer
- Checklist:
  - [ ] Tests pass
  - [ ] Code formatted (black)
  - [ ] Linter passes (pylint)
  - [ ] Docstrings added
  - [ ] No secrets committed
  - [ ] README updated if needed

**Testing Requirements:**
- Unit tests: ≥ 70% coverage for core functionality
- Integration tests: Key workflows (file change → doc update → commit)
- Manual testing: Run full sync cycle before release

### 12.3 Documentation Requirements

**Code Documentation:**
- All modules: Module-level docstring explaining purpose
- All classes: Class docstring with attributes and purpose
- All public functions: Docstring with parameters, return value, raises
- Complex logic: Inline comments explaining "why", not "what"

**Docstring Format**: Google Style
```python
def generate_readme_section(self, structure: ParsedCodeStructure, section: str) -> str:
    """Generate a README section from parsed code structure.
    
    Args:
        structure: Parsed code structure from CodeAnalyzer
        section: Section name ('api' or 'config')
        
    Returns:
        Generated Markdown content for the section
        
    Raises:
        TemplateNotFoundError: If template file doesn't exist
        GenerationError: If template rendering fails
    """
```

**API Documentation:**
- Maintained in docs/API.md (auto-generated by the system itself!)
- Documents all public classes and functions
- Includes usage examples

**Architecture Decision Records:**
- Section 10 of this document serves as ADR
- Update when major decisions change

**README.md:**
- Installation instructions
- Configuration guide
- Usage examples
- Troubleshooting

## 13. Migration Strategy

**Not Applicable**: This is a new system, not replacing an existing one.

**Onboarding Strategy (for user adopting the system):**
1. Install dependencies
2. Configure config.yaml for their project
3. Run initial manual sync to bootstrap documentation
4. Start automated watching

## 14. Risks & Mitigations

### Risk 1: Template Complexity (From Requirements)
- **Probability**: Medium
- **Impact**: High (core functionality)
- **Mitigation**: 
  - Start with simple templates
  - Use Python AST for reliable parsing (not regex)
  - Include template testing in test suite
  - Provide template examples
- **Contingency**: Fallback to basic format if template fails
- **Status**: Addressed in design with CodeAnalyzer and template structure

### Risk 2: File Watcher Performance on Windows (From Requirements)
- **Probability**: Low
- **Impact**: Medium
- **Mitigation**: 
  - Use watchdog library (proven on Windows)
  - Implement debouncing (300ms)
  - Batch changes (2-second window)
  - Monitor CPU/memory usage
- **Contingency**: Fallback to polling if watchdog fails
- **Status**: Addressed with watchdog + debouncing strategy

### Risk 3: Secret Exposure (From Requirements)
- **Probability**: Medium
- **Impact**: High (security)
- **Mitigation**: 
  - SecretDetector component with regex patterns
  - Scan before commit
  - Manual review for major changes
  - Never log credentials
- **Contingency**: Git history rewriting if secret committed
- **Status**: Addressed with SecretDetector and security architecture

### Risk 4: Git Conflicts in Documentation
- **Probability**: Low (solo developer)
- **Impact**: Low
- **Mitigation**: 
  - Code takes precedence strategy
  - Automated conflict resolution
  - Backups before changes
  - Can manually revert via Git
- **Contingency**: Manual resolution instructions in documentation
- **Status**: Addressed in GitManager design

### Risk 5: Dependencies Breaking
- **Probability**: Low
- **Impact**: Medium
- **Mitigation**: 
  - Pin versions in requirements.txt
  - Test before updating dependencies
  - Document compatible versions
- **Contingency**: Rollback to previous working versions
- **Status**: requirements.txt with pinned versions

### Risk 6: User Adoption Difficulty
- **Probability**: Low
- **Impact**: Medium (demonstration goal)
- **Mitigation**: 
  - Comprehensive README with step-by-step setup
  - Sensible defaults in config
  - Clear error messages with suggestions
  - Example templates included
- **Contingency**: Create video walkthrough if needed
- **Status**: Addressed with usability focus in design

## 15. Open Questions

1. **Template Format Details**: What specific information should API documentation include? (Function signatures, parameters, examples, etc.)
   - **Resolution Path**: Define during implementation based on user needs

2. **Review Interface**: Should review prompts be console-based or open a text editor?
   - **Proposed**: Console-based for simplicity (y/n prompt with diff preview)

3. **Metrics Visualization**: Should there be a graphical view of metrics?
   - **Proposed**: Not in v1, status command is sufficient for demonstration

4. **Multiple Projects**: Should one service instance handle multiple projects?
   - **Proposed**: No, one instance per project (keep it simple)

5. **Error Notification**: Should errors send desktop notifications?
   - **Proposed**: Not in v1, console + log is sufficient

## 16. Future Considerations

**Phase 2 Enhancements (Out of scope for v1):**

1. **AI-Enhanced Generation**: Integrate LLM for more intelligent documentation
2. **Web Dashboard**: Browser-based UI for status, metrics, and configuration
3. **Multi-Language Support**: Extend beyond Python (JavaScript, Java, etc.)
4. **ReadTheDocs Integration**: Auto-publish documentation to hosting platforms
5. **Advanced Templates**: Visual template editor, template marketplace
6. **Team Features**: Multi-user support, collaborative review workflow
7. **CI/CD Integration**: GitHub Actions plugin for automated docs in PR checks
8. **Documentation Quality Scoring**: Analyze documentation completeness and quality
9. **Custom Hooks**: Plugin system for user-defined processing steps
10. **Real-Time Preview**: Live documentation preview as you code

**Architectural Considerations for Future:**
- Plugin architecture for extensibility
- Web API for remote control
- Database for multi-user state
- Microservices for scaling to teams

## 17. Appendix

### 17.1 Glossary

- **AST**: Abstract Syntax Tree - parsed representation of Python code
- **Debouncing**: Delaying action until a pause in events (avoid processing rapid changes)
- **Batching**: Grouping multiple related events for efficient processing
- **Docstring**: Documentation string in Python code ("""...""")
- **Jinja2**: Python template engine for generating text/markup
- **GitPython**: Python library for Git operations
- **Watchdog**: Python library for file system event monitoring
- **Sync Operation**: End-to-end process from file change to documentation commit
- **Review Severity**: Classification of documentation change impact (minor, moderate, major)
- **Secret Detector**: Component that scans for credentials in documentation
- **CLI**: Command-Line Interface
- **NFR**: Non-Functional Requirement
- **FR**: Functional Requirement
- **RTO**: Recovery Time Objective
- **RPO**: Recovery Point Objective

### 17.2 References

- **Requirements Document**: `artifacts/requirements.md` (EPMCDMETST-62888)
- **Python AST Documentation**: https://docs.python.org/3/library/ast.html
- **Watchdog Documentation**: https://python-watchdog.readthedocs.io/
- **Jinja2 Documentation**: https://jinja.palletsprojects.com/
- **GitPython Documentation**: https://gitpython.readthedocs.io/
- **PEP 8 Style Guide**: https://peps.python.org/pep-0008/
- **PEP 257 Docstring Conventions**: https://peps.python.org/pep-0257/

### 17.3 Revision History

- **2026-09-01**: Initial architecture design by Architecture Agent
  - Designed for local Windows Python CLI application
  - Monolithic event-driven architecture
  - Template-based documentation generation
  - Comprehensive component design
  - Security, performance, and reliability considerations
  - Ready for implementation phase
