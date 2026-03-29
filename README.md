# mcp-tools

A collection of [MCP](https://modelcontextprotocol.io/) servers for use with AI assistants.

## Servers

### server_documents.py — PDF to Markdown

Converts PDFs to markdown using [marker-pdf](https://github.com/VikParuchuri/marker),
preserving equations (LaTeX), tables, and document structure.

Two processing modes:

- **fast** (default) — text, structure, equations, and tables. No LLM refinement or image extraction.
- **full** — everything marker-pdf offers, including LLM-based processors and image extraction.

Output is written to a directory alongside the source PDF containing the markdown file,
a JSON metadata file, and any extracted images.

**Running on ROCm:** Use `start_documents_rocm.sh` to launch with GPU acceleration.
See `CLAUDE.md` for hardware and setup details.

### server_documents_wrapper.py — Remote Document Processing

Async wrapper that uploads PDFs to a remote `server_documents.py` instance via SCP,
triggers conversion over MCP (streamable-http), and downloads results. Returns a job ID
immediately so the caller isn't blocked during long conversions.

### server_discord.py — Discord Export Parser

Parses Discord chat exports (JSON format from [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter))
and provides tools to search and summarize conversations.

### server_learning.py — Example Server

A simple example MCP server (character counting) used for learning and testing.

### server.py — Tool Server (WIP)

Document summarization via Ollama. Work in progress.

## Setup

Requires Python 3.12+. Uses [uv](https://docs.astral.sh/uv/) for package management.

```bash
uv sync
```
