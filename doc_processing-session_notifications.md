# Session Notification for Long-Running MCP Tasks

## Problem

Long-running MCP tool calls (like PDF conversion) require the LLM to poll for
completion, wasting context tokens. Ideally, the MCP server would notify the
active OpenCode session when work is done, rather than the LLM polling.

## Desired Flow

1. User requests PDF conversion in OpenCode
2. Wrapper uploads PDF, starts conversion, returns immediately
3. When conversion completes, wrapper notifies the OpenCode session directly
4. Agent receives notification and downloads/presents results — no polling needed

## Blocked By

**OpenCode does not currently expose session IDs to MCP server processes.**

- Tracked in: https://github.com/anomalyco/opencode/issues/15117
- Status: Assigned to core dev (`thdxr`), labeled `core`
- Proposed env vars: `OPENCODE_SESSION_ID`, `OPENCODE_SESSION_TITLE`

## Why We Can't Work Around It

- OpenCode local server API (`localhost:4096`) can list sessions and post messages
- But with multiple OpenCode sessions running simultaneously, the wrapper
  cannot determine which session invoked the tool call
- Passing session ID as a tool argument is fragile and requires LLM cooperation

## Implementation Plan (Once #15117 Lands)

1. Read `OPENCODE_SESSION_ID` from environment in `server_documents_wrapper.py`
2. After `_process_job` completes, notify the session via one of:
   - **CLI**: `opencode run -s <session_id> "Conversion complete. Files at /path/..."`
   - **API**: `POST http://localhost:4096/session/<id>/message`
   - **Python SDK**: `opencode-sdk-python` (`client.session.prompt()`)
3. Remove `get_conversion_result` tool — no more polling needed
4. Single tool, single call, notification on completion

## References

- OpenCode SDK docs: https://opencode.ai/docs/sdk/
- OpenCode server API docs: https://opencode.ai/docs/server/
- Python SDK: https://github.com/anomalyco/opencode-sdk-python
- Session ID env var issue: https://github.com/anomalyco/opencode/issues/15117
