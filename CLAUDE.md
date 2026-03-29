# MCP Tools

Collection of MCP (Model Context Protocol) servers providing tool access for local LLMs.

## Project Structure

```
server_evangeline.py          # Email database search (Evangeline) — port 8101
server_documents.py           # Document processing
server_documents_wrapper.py   # Document server wrapper
server_discord.py             # Discord integration
server_learning.py            # Example/learning server
server.py                     # Generic tool server (in progress)
server_email_parser.py.disabled  # Old maildir parser — replaced by server_evangeline.py
```

## Package Manager

Uses uv. Dependencies in `pyproject.toml`. Run with `uv run` or the venv at `.venv/`.

## MCP Server Pattern

All servers use `mcp.server.fastmcp.FastMCP`:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP(name="Server Name", host="127.0.0.1", port=XXXX)

@mcp.tool()
def tool_name(param: str) -> str:
    """Tool description shown to LLMs."""
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

Tools return JSON strings. Parameters use Python type hints including `str | None = None` for optional params.

## Evangeline Email Server (`server_evangeline.py`)

Queries the Evangeline SQLite+vec email database. Replaces the old file-scanning email parser.

**ACCESS RESTRICTION**: This server should ONLY be configured for local/offline LLM clients. Do NOT add it to cloud-connected clients (Claude, ChatGPT, etc.) as it provides access to personal email content. It is configured as `evangeline-email` in `~/.claude/local-mcp-servers.json` (symlinked from `~/git_repos/config_files/claude/local-mcp-servers.json`), which is only loaded by `rippaclaude` sessions (local LLMs via llama-server).

- **Port**: 8101 (localhost only)
- **Database**: `/home/dave/git_repos/evangeline/evangeline.db`
- **Embeddings**: Ollama bge-m3 at `http://workhorse:11434` (5s timeout, falls back to keyword search)
- **Dependencies**: `sqlite-vec`, `requests` (plus the standard mcp stack)

### Tools

| Tool | Purpose |
|------|---------|
| `search_emails` | Filter by folder, sender, subject, date range, flags |
| `semantic_search` | Natural language query via vector similarity |
| `get_email` | Full email content by database ID |
| `get_conversation` | Complete conversation thread |
| `list_conversations` | Browse threads with filters |
| `email_stats` | Database overview and counts |
| `find_similar_responses` | Find past emails similar to one you're replying to, paired with how you responded — for reply drafting assistance |
| `extract_from_emails` | Run a regex against email body text and return only the matches — for bulk data extraction without reading full content |

### Systemd Service

```
~/.config/systemd/user/email-parser.service
```

```bash
systemctl --user status email-parser    # Check status
systemctl --user restart email-parser   # Restart after changes
journalctl --user -u email-parser -f    # Tail logs
```

## Key Notes

- sqlite-vec virtual tables (`vec0`) don't support `INSERT OR REPLACE`. Use `DELETE` + `INSERT`.
- Search results include 200-char body snippets to keep LLM context manageable. Use `get_email` for full content.
- The Evangeline database is managed by the evangeline project at `/home/dave/git_repos/evangeline/`. Use `evangeline sync` or `evangeline import` to update it.
- `find_similar_responses` works best when more mail folders are synced locally. Currently only ~93 direct Inbox->Sent reply pairs are linkable; syncing additional folders from the mail server would significantly improve coverage.
