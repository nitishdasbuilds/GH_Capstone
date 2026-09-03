# Automated Documentation Sync for Code Changes

Automated Documentation Sync is a Python tool that watches the `src/` folder for code changes and automatically keeps the corresponding `README.md` documentation sections up to date. It was built as part of an agentic Software Development Life Cycle (SDLC) pipeline driven by GitHub Copilot, delivered under Jira ticket [EPMCDMETST-62888](https://jira.example.com/browse/EPMCDMETST-62888).

## Features

- Watches the `src/` directory for `.py` file changes in real time
- Automatically regenerates API usage documentation from function/module docstrings
- Batches rapid successive file changes to avoid redundant updates
- Updates only the designated auto-generated sections of `README.md`, leaving manual content untouched
- Logs sync activity to `logs/sync.log` for auditability

## Prerequisites

- Python 3.9 or later
- pip

## Installation

```powershell
pip install -r requirements.txt
```

## Usage

Run the sync tool from the project root to start watching `src/` for changes:

```powershell
python src/doc_sync.py
```

While running, any create/modify/delete of a `.py` file under `src/` triggers a refresh of the auto-generated sections below.

## Project Structure

```
GH_Capstone/
├── agents/            # SDLC pipeline sub-agent instructions
├── artifacts/          # Generated pipeline artifacts (requirements, architecture, etc.)
├── logs/               # Runtime logs (e.g. sync.log)
├── src/                # Application source code, including doc_sync.py
├── tests/              # Automated test suite
├── requirements.txt     # Python dependencies
└── status.json          # SDLC pipeline phase tracking
```

## How It Works

`doc_sync.py` uses `watchdog` to monitor `src/` for `.py` file changes, batches related changes within a short time window, extracts documentation-relevant information (such as function signatures and docstrings), and rewrites the content between the `AUTO-GENERATED:START`/`AUTO-GENERATED:END` markers in `README.md` — leaving everything above and outside those markers untouched.

<!-- AUTO-GENERATED:START:api_usage -->
### API Usage Examples

**`calculator`**

- `add(a, b)` — Return the sum of two numbers.
- `subtract(a, b)` — Return the difference between two numbers.
- `multiply(a, b)` — Return the product of two numbers.
- `divide(a, b)` — Return the quotient of two numbers.
<!-- AUTO-GENERATED:END:api_usage -->


<!-- AUTO-GENERATED:START:configuration -->
### Configuration Options

- Watch directory: `src`
- README target: `README.md`
- Batch window: 2.0s, max 20 files per batch
- Log file: `logs/sync.log`
<!-- AUTO-GENERATED:END:configuration -->
