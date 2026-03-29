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

# Running the document server

The document processing server (`server_documents.py`) uses marker-pdf, which runs on
PyTorch and is GPU-backend agnostic. The Python code works with both ROCm and CUDA —
only the launch script differs.

Each GPU backend has its own start script that sets up the required environment variables
before launching the server:

- **ROCm:** `./start_documents_rocm.sh` — sets ROCm/HIP env vars for lilbuddy's Radeon 8060S (gfx1151)
- **CUDA:** No script yet. Add a `start_documents_cuda.sh` when needed.

The server binds to `127.0.0.1:8200` (streamable-http) and is reverse-proxied by Caddy on `:8020`.

First run after reboot is slow (~4 min) as ROCm compiles GPU kernels for gfx1151.
New batch sizes also trigger kernel compilation on first encounter.

## Document processing modes

Two processing modes via the `mode` parameter:

- **fast** (default) — text extraction, structural analysis, equation LaTeX, and tables.
  Skips LLM-based processors and image extraction.
- **full** — everything marker-pdf offers, including LLM refinement and image extraction.

## Deployment

The document server runs as a systemd user service on lilbuddy:

```bash
systemctl --user status document-processing
systemctl --user restart document-processing
```

## Package management

Use `uv`, not pip. The venv is at `.venv/`.

## Key architectural notes

- marker-pdf's pipeline: layout detection -> OCR -> processors (in order) -> renderer
- Inline math ($...$) is captured during regular text OCR via surya's `math_mode` parameter
- Display math ($$...$$) requires `EquationProcessor` — it runs dedicated surya OCR on
  detected equation blocks that are skipped by the regular text OCR pass
- Table recognition uses three models: TableRecPredictor, DetectionPredictor, RecognitionPredictor
- ROCm kernel compilation is triggered per unique batch size; subsequent runs use cached kernels
- `FAST_PROCESSORS` list in `server_documents.py` is curated and tested; key fixes applied:
  - `pageheader` -> `page_header`, `blankpage` -> `blank_page` (module naming)
  - Added `EquationProcessor` (display-style equations were silently dropped without it)
  - Added `TableProcessor` (minimal overhead: 2-22% depending on table density)

## Known limitations

- No benchmarking of `"full"` mode on ROCm yet (only fast mode tested)
- LLM-based processors in full mode require an external LLM service — not configured
- The `force_ocr` parameter is ignored in fast mode (always False)
- No integration tests beyond manual PDF conversion
