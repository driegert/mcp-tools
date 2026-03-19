"""
MCP Server for parsing Evolution format emails (raw RFC 822 MIME files).

This server provides tools to list and parse emails stored in Evolution's
mail format, which stores each email as a separate file in directories
like /home/dave/.local/share/evolution/mail/local/.TrentInbox/cur
"""

import json
import os
from datetime import datetime, timezone
from email import policy
from email.parser import BytesFeedParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Email Parser", host="127.0.0.1", port=8101)


def _decode_mime_part(part):
    """
    Decode a MIME part's content, handling charset and encoding automatically.
    Returns the decoded text string.
    """
    try:
        # Use get_content() which automatically handles:
        # - Transfer-encoding decoding (quoted-printable, base64)
        # - Charset conversion to UTF-8
        # - Soft line break removal for quoted-printable
        # This is available in email library v3.11+ (Python 3.11+)
        if hasattr(part, "get_content"):
            content = part.get_content()
            if content is None:
                return ""
            # get_content() returns str for text parts, bytes for non-text
            if isinstance(content, bytes):
                charset = part.get_content_charset() or "utf-8"
                return content.decode(charset, errors="replace")
            return str(content)

        # Fallback for older Python versions: manually handle encoding
        # First try to get the transfer-encoding and handle it
        transfer_encoding = part.get_content_transfer_encoding()

        if transfer_encoding == "quoted-printable":
            # For quoted-printable, use get_payload(decode=True) to get raw bytes
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
            return str(payload) if payload else ""
        elif transfer_encoding == "base64":
            # For base64, decode the bytes
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
            return str(payload) if payload else ""
        else:
            # No encoding or unknown - get payload as string
            payload = part.get_payload()
            if payload is None:
                return ""
            if isinstance(payload, str):
                return payload
            # Handle bytes without transfer encoding
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    except Exception:
        return ""


def _extract_attachments(msg, path=""):
    """
    Recursively extract attachment information from a message.
    Returns a list of dicts with attachment details.
    """
    attachments = []

    if msg.is_multipart():
        for i, part in enumerate(msg.walk()):
            # Skip the root message itself
            if part == msg:
                continue

            # Check if this part is an attachment
            disposition = part.get_content_disposition()
            filename = part.get_filename()

            # Consider it an attachment if:
            # 1. It has a filename
            # 2. It has an attachment disposition
            # 3. It's not a text/plain or text/html part in a multipart/alternative
            if filename or disposition == "attachment":
                # Build a path-like identifier for nested attachments
                part_path = f"{path}/part_{i}" if path else f"part_{i}"

                attachments.append(
                    {
                        "filename": filename or "unnamed",
                        "content_type": part.get_content_type(),
                        "size": len(part.get_payload(decode=True) or b""),
                        "disposition": disposition or "inline",
                    }
                )
    else:
        # Single part message - check if it's an attachment
        filename = msg.get_filename()
        disposition = msg.get_content_disposition()
        if filename or disposition == "attachment":
            attachments.append(
                {
                    "filename": filename or "unnamed",
                    "content_type": msg.get_content_type(),
                    "size": len(msg.get_payload(decode=True) or b""),
                    "disposition": disposition or "inline",
                }
            )

    return attachments


def _get_evolution_flags(filename: str) -> dict:
    """
    Parse Evolution mailbox flags from filename.

    Evolution stores flags after a colon in the filename:
    - S = Seen
    - R = Recent
    - F = Flagged
    - T = Answered
    - D = Deleted
    - K = Draft
    """
    flags = {
        "seen": False,
        "recent": False,
        "flagged": False,
        "answered": False,
        "deleted": False,
        "draft": False,
    }

    if ":" in filename:
        flag_str = filename.split(":", 1)[1]
        if "S" in flag_str:
            flags["seen"] = True
        if "R" in flag_str:
            flags["recent"] = True
        if "F" in flag_str:
            flags["flagged"] = True
        if "T" in flag_str:
            flags["answered"] = True
        if "D" in flag_str:
            flags["deleted"] = True
        if "K" in flag_str:
            flags["draft"] = True

    return flags


def _get_basename(filename: str) -> str:
    """Get the actual filename without Evolution flags."""
    return filename.split(":", 1)[0]


@mcp.tool()
def list_emails(directory: str, limit: int = 20):
    """
    List emails in an Evolution mail directory.

    Evolution stores emails as raw RFC 822 MIME files in directories
    like /home/dave/.local/share/evolution/mail/local/.TrentInbox/cur

    Returns JSON with filename, size, modified_date, and flags (Seen, Recent, etc.)
    for each email. Results are sorted by modification date (newest first).

    Parameters:
        directory: Path to the Evolution mail directory (e.g., cur folder)
        limit: Maximum number of emails to return (default: 20)

    Returns:
        JSON string with email metadata
    """
    dir_path = Path(directory).expanduser().absolute()

    if not dir_path.exists():
        return json.dumps(
            {
                "error": f"Directory does not exist: {dir_path}",
                "emails": [],
            },
            indent=2,
        )

    if not dir_path.is_dir():
        return json.dumps(
            {
                "error": f"Path is not a directory: {dir_path}",
                "emails": [],
            },
            indent=2,
        )

    emails = []
    for filename in dir_path.iterdir():
        if filename.is_file():
            try:
                stat = filename.stat()
                mod_time = datetime.fromtimestamp(stat.st_mtime)

                email_info = {
                    "filename": _get_basename(filename.name),
                    "full_path": str(filename),
                    "size_bytes": stat.st_size,
                    "modified_date": mod_time.isoformat(),
                    "flags": _get_evolution_flags(filename.name),
                }
                emails.append(email_info)
            except OSError as e:
                emails.append(
                    {
                        "filename": filename.name,
                        "error": f"Could not read file metadata: {str(e)}",
                    }
                )

    # Sort by modification date (newest first)
    emails.sort(key=lambda x: x.get("modified_date", "") or "", reverse=True)

    # Apply limit
    if limit and limit > 0:
        emails = emails[:limit]

    return json.dumps(
        {
            "directory": str(dir_path),
            "total_count": len(emails),
            "limit_applied": limit if limit else None,
            "emails": emails,
        },
        indent=2,
    )


@mcp.tool()
def parse_email(file_path: str, extract_html: bool = False):
    """
    Parse a single email file in Evolution format (raw RFC 822 MIME).

    Extracts headers, body content, and attachment information.
    Handles multipart messages, quoted-printable and base64 decoding,
    and charset conversion to UTF-8 automatically.

    Parameters:
        file_path: Path to the email file
        extract_html: If True, also extract text/html content (default: False)

    Returns:
        JSON string with headers, body_text, body_html (if requested),
        is_multipart flag, and attachments list
    """
    email_path = Path(file_path).expanduser().absolute()

    if not email_path.exists():
        return json.dumps(
            {
                "error": f"File does not exist: {email_path}",
            },
            indent=2,
        )

    if not email_path.is_file():
        return json.dumps(
            {
                "error": f"Path is not a file: {email_path}",
            },
            indent=2,
        )

    try:
        with open(email_path, "rb") as f:
            raw_content = f.read()

        # Parse the email using the email library with strict policy
        parser = BytesFeedParser(policy=policy.default)
        parser.feed(raw_content)
        msg = parser.close()

        # Extract standard headers
        headers = {
            "From": msg.get("From", ""),
            "To": msg.get("To", ""),
            "Subject": msg.get("Subject", ""),
            "Date": msg.get("Date", ""),
            "Message-ID": msg.get("Message-ID", ""),
        }

        # Try to parse date to ISO format
        if headers["Date"]:
            try:
                parsed_date = parsedate_to_datetime(headers["Date"])
                headers["Date_ISO"] = parsed_date.isoformat()
            except (ValueError, TypeError):
                headers["Date_ISO"] = ""

        # Extract bodies
        body_text = ""
        body_html = ""

        if msg.is_multipart():
            is_multipart = True

            # Walk through parts to find text/plain and text/html
            for part in msg.walk():
                content_type = part.get_content_type().lower()

                # Skip parts that are attachments
                disposition = part.get_content_disposition()
                if disposition == "attachment":
                    continue

                if content_type == "text/plain":
                    if not body_text:  # Get first text/plain part
                        body_text = _decode_mime_part(part)
                elif content_type == "text/html" and extract_html:
                    if not body_html:  # Get first text/html part
                        body_html = _decode_mime_part(part)
        else:
            is_multipart = False
            content_type = msg.get_content_type().lower()

            if content_type == "text/plain":
                body_text = _decode_mime_part(msg)
            elif content_type == "text/html":
                if extract_html:
                    body_html = _decode_mime_part(msg)
                else:
                    # Treat HTML as text if extract_html is False
                    body_text = _decode_mime_part(msg)

        # Extract attachments
        attachments = _extract_attachments(msg)

        result = {
            "headers": headers,
            "body_text": body_text,
            "is_multipart": is_multipart,
            "attachments": attachments,
        }

        if extract_html and body_html:
            result["body_html"] = body_html

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to parse email: {str(e)}",
            },
            indent=2,
        )


@mcp.tool()
def get_email_headers(file_path: str):
    """
    Quick extraction of just headers from an email file.

    Returns all headers as key-value pairs in JSON format.

    Parameters:
        file_path: Path to the email file

    Returns:
        JSON string with all headers as key-value pairs
    """
    email_path = Path(file_path).expanduser().absolute()

    if not email_path.exists():
        return json.dumps(
            {
                "error": f"File does not exist: {email_path}",
            },
            indent=2,
        )

    if not email_path.is_file():
        return json.dumps(
            {
                "error": f"Path is not a file: {email_path}",
            },
            indent=2,
        )

    try:
        with open(email_path, "rb") as f:
            raw_content = f.read()

        # Parse the email
        parser = BytesFeedParser(policy=policy.default)
        parser.feed(raw_content)
        msg = parser.close()

        # Extract all headers as key-value pairs
        headers = {}
        for key, value in msg.items():
            headers[key] = value

        # Also include parsed date if available
        if msg["Date"]:
            try:
                parsed_date = parsedate_to_datetime(msg["Date"])
                headers["Date_ISO"] = parsed_date.isoformat()
            except (ValueError, TypeError):
                pass

        return json.dumps(
            {
                "headers": headers,
                "total_headers": len(headers),
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to parse email headers: {str(e)}",
            },
            indent=2,
        )


@mcp.tool()
def extract_email_body(file_path: str, prefer_html: bool = False):
    """
    Extract just the body content from an email.

    For multipart/alternative messages, chooses between plain text and HTML
    based on the prefer_html flag.

    Parameters:
        file_path: Path to the email file
        prefer_html: If True, prefer HTML content over plain text (default: False)

    Returns:
        JSON string with content_type and content (the body text)
    """
    email_path = Path(file_path).expanduser().absolute()

    if not email_path.exists():
        return json.dumps(
            {
                "error": f"File does not exist: {email_path}",
            },
            indent=2,
        )

    if not email_path.is_file():
        return json.dumps(
            {
                "error": f"Path is not a file: {email_path}",
            },
            indent=2,
        )

    try:
        with open(email_path, "rb") as f:
            raw_content = f.read()

        # Parse the email
        parser = BytesFeedParser(policy=policy.default)
        parser.feed(raw_content)
        msg = parser.close()

        content_type = ""
        content = ""

        if msg.is_multipart():
            # For multipart/alternative, choose based on prefer_html
            is_alternative = msg.get_content_subtype() == "alternative"

            if is_alternative:
                # Find both text/plain and text/html parts
                plain_text = ""
                html_content = ""

                for part in msg.walk():
                    if part == msg:
                        continue

                    disposition = part.get_content_disposition()
                    if disposition == "attachment":
                        continue

                    ct = part.get_content_type().lower()
                    if ct == "text/plain" and not plain_text:
                        plain_text = _decode_mime_part(part)
                    elif ct == "text/html" and not html_content:
                        html_content = _decode_mime_part(part)

                # Choose based on preference
                if prefer_html and html_content:
                    content = html_content
                    content_type = "text/html"
                elif plain_text:
                    content = plain_text
                    content_type = "text/plain"
                elif html_content:
                    content = html_content
                    content_type = "text/html"
            else:
                # For other multipart types, get the first text part
                for part in msg.walk():
                    if part == msg:
                        continue

                    disposition = part.get_content_disposition()
                    if disposition == "attachment":
                        continue

                    ct = part.get_content_type().lower()
                    if ct.startswith("text/"):
                        content = _decode_mime_part(part)
                        content_type = ct
                        break
        else:
            # Single part message
            content_type = msg.get_content_type()
            content = _decode_mime_part(msg)

        return json.dumps(
            {
                "content_type": content_type,
                "content": content,
            },
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to extract email body: {str(e)}",
            },
            indent=2,
        )


def _parse_email_headers_only(file_path: Path) -> dict | None:
    """
    Parse only the headers from an email file efficiently.

    Returns a dict with 'From', 'Subject', 'Date' keys, or None if parsing fails.
    """
    try:
        with open(file_path, "rb") as f:
            raw_content = f.read()

        parser = BytesFeedParser(policy=policy.default)
        parser.feed(raw_content)
        msg = parser.close()

        return {
            "From": msg.get("From", ""),
            "Subject": msg.get("Subject", ""),
            "Date": msg.get("Date", ""),
        }
    except Exception:
        return None


@mcp.tool()
def search_emails(
    directory: str,
    sender: str | None = None,
    subject: str | None = None,
    since_date: str | None = None,
    limit: int = 50,
):
    """
    Search emails in an Evolution mail directory with optional filters.

    Filters:
        - sender: Case-insensitive substring match in the From header
        - subject: Case-insensitive substring match in the Subject header
        - since_date: ISO format date string (e.g., "2026-01-01"), only returns
          emails on or after this date (based on the email's Date header)

    Returns JSON with total_matches, limit_applied, and emails list sorted by
    modification date (newest first).

    Parameters:
        directory: Path to the Evolution mail directory
        sender: Optional substring to match in From header (case-insensitive)
        subject: Optional substring to match in Subject header (case-insensitive)
        since_date: Optional ISO format date string (e.g., "2026-01-01")
        limit: Maximum number of emails to return (default: 50)

    Returns:
        JSON string with total_matches, limit_applied, and emails
    """
    dir_path = Path(directory).expanduser().absolute()

    if not dir_path.exists():
        return json.dumps(
            {
                "error": f"Directory does not exist: {dir_path}",
                "total_matches": 0,
                "limit_applied": limit,
                "emails": [],
            },
            indent=2,
        )

    if not dir_path.is_dir():
        return json.dumps(
            {
                "error": f"Path is not a directory: {dir_path}",
                "total_matches": 0,
                "limit_applied": limit,
                "emails": [],
            },
            indent=2,
        )

    # Parse since_date if provided (make timezone-aware for comparison)
    since_datetime = None
    if since_date:
        try:
            parsed = datetime.fromisoformat(since_date)
            # Make timezone-aware if naive, so it can compare with email dates
            if parsed.tzinfo is None:
                since_datetime = parsed.replace(tzinfo=timezone.utc)
            else:
                since_datetime = parsed
        except ValueError:
            pass  # Invalid date format, ignore the filter

    emails = []
    for filename in dir_path.iterdir():
        if not filename.is_file():
            continue

        try:
            stat = filename.stat()
            mod_time = datetime.fromtimestamp(stat.st_mtime)

            # Parse headers only (don't extract body)
            headers = _parse_email_headers_only(filename)
            if headers is None:
                continue  # Skip files that can't be parsed

            # Apply sender filter (case-insensitive substring match)
            if sender is not None:
                if sender.lower() not in headers["From"].lower():
                    continue

            # Apply subject filter (case-insensitive substring match)
            if subject is not None:
                if subject.lower() not in headers["Subject"].lower():
                    continue

            # Apply since_date filter
            if since_datetime is not None:
                email_date_str = headers.get("Date", "")
                if email_date_str:
                    try:
                        email_datetime = parsedate_to_datetime(email_date_str)
                        if email_datetime < since_datetime:
                            continue
                    except (ValueError, TypeError):
                        # If we can't parse the date, skip this email
                        continue
                else:
                    # No date header, skip
                    continue

            email_info = {
                "filename": _get_basename(filename.name),
                "full_path": str(filename),
                "size_bytes": stat.st_size,
                "modified_date": mod_time.isoformat(),
                "flags": _get_evolution_flags(filename.name),
                "from": headers["From"],
                "subject": headers["Subject"],
            }
            emails.append(email_info)

        except OSError:
            continue  # Skip files that can't be accessed

    # Sort by modification date (newest first)
    emails.sort(key=lambda x: x.get("modified_date", "") or "", reverse=True)

    # Track total matches before limit
    total_matches = len(emails)

    # Apply limit
    if limit and limit > 0:
        emails = emails[:limit]

    return json.dumps(
        {
            "directory": str(dir_path),
            "total_matches": total_matches,
            "limit_applied": limit if limit else None,
            "emails": emails,
        },
        indent=2,
    )


@mcp.tool()
def search_emails_by_flag(
    directory: str,
    seen: bool | None = None,
    flagged: bool | None = None,
    answered: bool | None = None,
    deleted: bool | None = None,
    limit: int = 50,
):
    """
    Filter emails in an Evolution mail directory by mailbox flags.

    Evolution flags are stored in the filename after a colon:
        - S = Seen (email has been read)
        - F = Flagged (email is marked for follow-up)
        - T = Answered (a reply has been sent)
        - D = Deleted (marked for deletion)

    Any flag parameter set to None means "don't filter on this flag".

    Returns JSON with emails matching all specified flag criteria, sorted by
    modification date (newest first).

    Parameters:
        directory: Path to the Evolution mail directory
        seen: Filter by seen flag (True=read, False=unread, None=don't filter)
        flagged: Filter by flagged flag (True=flagged, False=not flagged, None=don't filter)
        answered: Filter by answered flag (True=answered, False=unanswered, None=don't filter)
        deleted: Filter by deleted flag (True=deleted, False=not deleted, None=don't filter)
        limit: Maximum number of emails to return (default: 50)

    Returns:
        JSON string with total_count, limit_applied, and emails
    """
    dir_path = Path(directory).expanduser().absolute()

    if not dir_path.exists():
        return json.dumps(
            {
                "error": f"Directory does not exist: {dir_path}",
                "total_count": 0,
                "limit_applied": limit,
                "emails": [],
            },
            indent=2,
        )

    if not dir_path.is_dir():
        return json.dumps(
            {
                "error": f"Path is not a directory: {dir_path}",
                "total_count": 0,
                "limit_applied": limit,
                "emails": [],
            },
            indent=2,
        )

    emails = []
    for filename in dir_path.iterdir():
        if not filename.is_file():
            continue

        try:
            stat = filename.stat()
            mod_time = datetime.fromtimestamp(stat.st_mtime)

            flags = _get_evolution_flags(filename.name)

            # Apply flag filters (only filter if parameter is not None)
            if seen is not None and flags["seen"] != seen:
                continue
            if flagged is not None and flags["flagged"] != flagged:
                continue
            if answered is not None and flags["answered"] != answered:
                continue
            if deleted is not None and flags["deleted"] != deleted:
                continue

            email_info = {
                "filename": _get_basename(filename.name),
                "full_path": str(filename),
                "size_bytes": stat.st_size,
                "modified_date": mod_time.isoformat(),
                "flags": flags,
            }
            emails.append(email_info)

        except OSError:
            continue  # Skip files that can't be accessed

    # Sort by modification date (newest first)
    emails.sort(key=lambda x: x.get("modified_date", "") or "", reverse=True)

    # Track total count before limit
    total_count = len(emails)

    # Apply limit
    if limit and limit > 0:
        emails = emails[:limit]

    return json.dumps(
        {
            "directory": str(dir_path),
            "total_count": total_count,
            "limit_applied": limit if limit else None,
            "emails": emails,
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
