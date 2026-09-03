---
name: jira-fetch-ticket
description: 'Fetch a Jira ticket (summary, description, status, priority) from https://jiraeu.epam.com via REST API with basic auth, and save it to artifacts/jira_story.json. Use before starting/resuming the SDLC pipeline for a ticket, when artifacts/jira_story.json is missing or stale, or whenever the user asks to fetch/refresh/re-sync Jira ticket data.'
argument-hint: 'JIRA ticket ID (e.g. EPMCDMETST-62888)'
---

# Jira Ticket Fetcher

## When to Use
- As **step 0** of the SDLC Orchestrator pipeline — before running Phase 1 (`requirements`), so `artifacts/jira_story.json` reflects the ticket in scope.
- The user asks to fetch, refresh, or re-sync a Jira ticket's details.
- `artifacts/jira_story.json` is missing, or its ticket key doesn't match the active ticket (e.g. `status.json.ticket`).

## Prerequisites
- `requests` and `python-dotenv` (already in `requirements.txt`) installed in the active virtualenv.
- A `.env` file at the repo root containing:
  ```
  JIRA_EMAIL=<your-jira-email>
  JIRA_API_TOKEN=<your-jira-api-token>
  ```
  Never print, log, echo, or commit these values. Confirm `.env` is covered by `.gitignore` before running.
  If `.env` is missing or incomplete, [jira_fetch.py](../../../jira_fetch.py) will interactively prompt for the missing value — let the human type it into the terminal directly; do not ask for it via chat and do not fabricate credentials.

## Procedure
1. Resolve the ticket ID: use the ID given in the request/argument; if none given, fall back to `status.json.ticket`; if neither exists, ask the human for it.
2. Run the fetch script from the repo root:
   ```powershell
   python jira_fetch.py <TICKET_ID>
   ```
   Optionally override the output path with `--output <path>` (default: `artifacts/jira_story.json`).
   This calls `GET {JIRA_BASE_URL}/rest/api/2/issue/<TICKET_ID>?fields=summary,description,status,priority` with HTTP Basic Auth using `JIRA_EMAIL` / `JIRA_API_TOKEN` from `.env`. See [jira_fetch.py](../../../jira_fetch.py) for the implementation.
3. Check the result:
   - Exit code `0` with `🎉 Process completed successfully!` → **success**.
   - Exit code `1` → **error** (`401` auth failure, `404` not found, connection/timeout issue, or file-write failure).
4. If this is being run as the orchestrator's step 0, only continue to Phase 1 after this step reports success.

## Output Format
- **Success**: report the ticket ID, summary, status, and priority, and confirm `artifacts/jira_story.json` was written/updated.
- **Error**: report the specific failure reason from the script's output, and state that no pipeline phase should proceed until it's resolved.
