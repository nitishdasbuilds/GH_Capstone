#!/usr/bin/env python3
"""PostToolUse hook: run doc_sync.py once when a src/*.py file was edited.

Reads the tool-call payload from stdin, checks whether any referenced file
path is a .py file under src/, and if so runs `python src/doc_sync.py --once`
to regenerate the auto-generated sections of README.md.

Exits 0 (no-op or success) or a non-zero, non-2 code on failure so this stays
a non-blocking warning rather than halting the agent (per hook exit code
contract: 0 = success, 2 = blocking error, other = non-blocking warning).
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_PY_PATTERN = re.compile(r"(^|[\\/])src[\\/].*\.py$", re.IGNORECASE)


def _collect_strings(value, out):
    """Recursively collect every string value found in a JSON-like structure."""
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _collect_strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _collect_strings(v, out)


def touched_src_py_file(payload) -> bool:
    strings = []
    _collect_strings(payload, strings)
    return any(SRC_PY_PATTERN.search(s) for s in strings)


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    if not touched_src_py_file(payload):
        return 0

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "src" / "doc_sync.py"), "--once"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"doc_sync --once failed: {result.stderr.strip()}", file=sys.stderr)
        return 1

    print(json.dumps({"systemMessage": "README.md auto-synced from src/ changes."}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
