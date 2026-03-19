# Email Parser MCP Server

An MCP server for parsing Evolution-format emails stored as raw RFC 822 MIME files.

## Location

```
/home/dave/git_repos/mcp-tools/server_email_parser.py
```

## Usage

Run the server:
```bash
cd /home/dave/git_repos/mcp-tools
uv run python server_email_parser.py
```

The server listens on `127.0.0.1:8101` (configurable via environment variables).

## Tools

### `list_emails(directory, limit=20)`
List emails in an Evolution mailbox directory.

**Returns:** JSON with email metadata (filename, size, modification date, flags)

**Example:**
```python
list_emails("/home/dave/.local/share/evolution/mail/local/.TrentInbox/cur", limit=10)
```

### `parse_email(file_path, extract_html=False)`
Parse a single email file and extract headers and body.

**Returns:** JSON with headers, body_text, optionally body_html, attachments list

**Example:**
```python
parse_email("/path/to/email:2,S", extract_html=True)
```

### `get_email_headers(file_path)`
Quick extraction of just the email headers.

**Returns:** JSON with all headers as key-value pairs

**Example:**
```python
get_email_headers("/path/to/email:2,S")
```

### `extract_email_body(file_path, prefer_html=False)`
Extract just the body content from an email.

**Returns:** JSON with content_type and content

**Example:**
```python
extract_email_body("/path/to/email:2,S", prefer_html=False)
```

### `search_emails(directory, sender=None, subject=None, since_date=None, limit=50)`
Search emails with optional filters.

**Parameters:**
- `sender`: Substring match in From header (case-insensitive)
- `subject`: Substring match in Subject header (case-insensitive)
- `since_date`: ISO format date (e.g., "2026-01-01")

**Returns:** JSON with matching emails

**Example:**
```python
search_emails("/path/to/mailbox", sender="ouac", since_date="2026-01-01")
```

### `search_emails_by_flag(directory, seen=None, flagged=None, answered=None, deleted=None, limit=50)`
Filter emails by Evolution mailbox flags.

**Parameters:** Any flag set to `None` means "don't filter on this"

**Returns:** JSON with filtered emails

**Example:**
```python
# Get unread emails
search_emails_by_flag("/path/to/mailbox", seen=False)

# Get flagged and unread emails
search_emails_by_flag("/path/to/mailbox", seen=False, flagged=True)
```

## Email Format Support

The server handles:
- **MIME parsing**: Multipart messages (multipart/alternative, multipart/mixed)
- **Encoding**: Quoted-printable, base64 decoding
- **Charset**: Automatic conversion to UTF-8 (Windows-1252, UTF-8, etc.)
- **Evolution flags**: Seen (S), Recent (R), Flagged (F), Answered (T), Deleted (D), Draft (K)

## Deployment

### systemd service

User-level service at `~/.config/systemd/user/email-parser.service`:

```ini
[Unit]
Description=Email Parser MCP Server
After=network.target

[Service]
WorkingDirectory=/home/dave/school_lab/git_repositories/mcp-tools
ExecStart=/home/dave/school_lab/git_repositories/mcp-tools/.venv/bin/python server_email_parser.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now email-parser.service
```

Note: If `systemctl --user` fails with "No medium found", set these first:
```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
loginctl enable-linger dave
```

### Caddy reverse proxy

Add to `/etc/caddy/Caddyfile`:

```
:8011 {
    reverse_proxy 127.0.0.1:8101 {
        header_up Host 127.0.0.1:8101
        flush_interval -1
        request_buffers 0
        response_buffers 0
    }
}
```

Then `sudo systemctl reload caddy`.

The `header_up Host` line is required because FastMCP/Uvicorn validates the Host header against its bind address.

### opencode client configuration

Add to `opencode.json` in the `"mcp"` section:

```json
"email-parser": {
  "type": "remote",
  "url": "http://<hostname>:8011/mcp",
  "enabled": true
}
```

Important: use `/mcp` (no trailing slash) — `/mcp/` returns a 307 redirect.

## Dependencies

Uses only Python's built-in `email` library - no additional dependencies required!
