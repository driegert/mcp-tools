"""
MCP Server for querying the Evangeline email database.

Provides tools for searching emails by subject, sender, date range,
folder, and flags — plus semantic (vector similarity) search.
All queries run against the pre-indexed SQLite+vec database.

Replaces the old server_email_parser.py which parsed raw maildir files
on every request.
"""

import json
import re
import sqlite3
import time
from pathlib import Path

import requests
import sqlite_vec
from mcp.server.fastmcp import FastMCP

# -- Configuration -----------------------------------------------------------

DB_PATH = "/home/dave/git_repos/evangeline/evangeline.db"
OLLAMA_BASE_URL = "http://workhorse:11434"
OLLAMA_MODEL = "bge-m3:latest"
EMBEDDING_TIMEOUT = 5  # seconds — fallback to keyword search if exceeded

SNIPPET_LENGTH = 200  # characters of body text to include in results

MAILDIR_BASE = Path.home() / ".local/share/evolution/mail/local"


def _discover_folder_names() -> list[str]:
    """Auto-discover .Trent* folder names from the maildir."""
    if not MAILDIR_BASE.is_dir():
        return []
    return sorted(
        item.name.lstrip(".")
        for item in MAILDIR_BASE.iterdir()
        if item.is_dir() and item.name.startswith(".Trent") and (item / "cur").is_dir()
    )


FOLDER_NAMES = _discover_folder_names()

# -- Server setup ------------------------------------------------------------

mcp = FastMCP(name="Evangeline Email", host="127.0.0.1", port=8101)

# -- Database helpers --------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    """Open the Evangeline database with sqlite-vec loaded."""
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def _snippet(text: str, length: int = SNIPPET_LENGTH) -> str:
    """Truncate text to a readable snippet."""
    if not text:
        return ""
    text = " ".join(text.split())  # collapse whitespace
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "..."


def _format_email_row(row, columns, snippet_len=SNIPPET_LENGTH) -> dict:
    """Convert a DB row to a clean dict for the LLM."""
    data = dict(zip(columns, row))

    # Parse headers JSON for display fields
    headers = json.loads(data.get("headers", "{}"))

    result = {
        "id": data["id"],
        "folder": data["folder"],
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "date": headers.get("Date_ISO", data.get("date", "")),
        "has_attachments": bool(data.get("has_attachments", 0)),
    }
    if snippet_len > 0:
        result["snippet"] = _snippet(data.get("body_text", ""), snippet_len)
    if data.get("attachment_count", 0) > 0:
        result["attachment_count"] = data["attachment_count"]

    # Include similarity if present
    if "distance" in data:
        result["similarity"] = round(1.0 - data["distance"], 3) if data["distance"] is not None else None

    return result


_RESULT_COLUMNS = [
    "id", "folder", "headers", "body_text", "date",
    "has_attachments", "attachment_count",
]


def _build_select(extra_columns=None):
    """Build the SELECT column list."""
    cols = list(_RESULT_COLUMNS)
    if extra_columns:
        cols.extend(extra_columns)
    return ", ".join(f"e.{c}" if c != "distance" else c for c in cols)


# -- Embedding helper --------------------------------------------------------


def _embed_query(text: str):
    """
    Get an embedding vector from Ollama.

    Returns the raw bytes on success, or None if the request fails
    or takes longer than EMBEDDING_TIMEOUT.
    """
    import numpy as np

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/embeddings",
            json={"model": OLLAMA_MODEL, "prompt": text},
            timeout=EMBEDDING_TIMEOUT,
        )
        resp.raise_for_status()
        vec = np.array(resp.json()["embedding"], dtype=np.float32)
        return vec.tobytes()
    except Exception:
        return None


# -- MCP Tools ---------------------------------------------------------------


@mcp.tool()
def search_emails(
    folder: str | None = None,
    sender: str | None = None,
    subject: str | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
    seen: bool | None = None,
    flagged: bool | None = None,
    limit: int = 20,
) -> str:
    """
    Search emails in the Evangeline database with optional filters.

    All filters are optional and combined with AND logic.
    Results are sorted by date (newest first).

    Parameters:
        folder: Filter by folder name (TrentInbox, TrentSent, TrentDeleted, TrentArchived)
        sender: Case-insensitive substring match in the From header
        subject: Case-insensitive substring match in the Subject header
        date_after: ISO date string — only emails on or after this date (e.g., "2026-01-01")
        date_before: ISO date string — only emails on or before this date
        seen: Filter by read status (True=read, False=unread, None=either)
        flagged: Filter by flagged status (True=flagged, False=not flagged, None=either)
        limit: Maximum results to return (default: 20)

    Returns:
        JSON with total_matches and emails list
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor()

        conditions = []
        params = []

        if folder:
            conditions.append("e.folder = ?")
            params.append(folder)
        if sender:
            conditions.append("json_extract(e.headers, '$.From') LIKE ?")
            params.append(f"%{sender}%")
        if subject:
            conditions.append("json_extract(e.headers, '$.Subject') LIKE ?")
            params.append(f"%{subject}%")
        if date_after:
            conditions.append("e.date >= ?")
            params.append(date_after)
        if date_before:
            conditions.append("e.date <= ?")
            params.append(date_before)
        if seen is not None:
            conditions.append("json_extract(e.flags, '$.seen') = ?")
            params.append("true" if seen else "false")
        if flagged is not None:
            conditions.append("json_extract(e.flags, '$.flagged') = ?")
            params.append("true" if flagged else "false")

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        sql = f"""
            SELECT e.id, e.folder, e.headers, e.body_text, e.date,
                   e.has_attachments, e.attachment_count
            FROM emails e
            WHERE {where}
            ORDER BY e.date DESC
            LIMIT ?
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        columns = ["id", "folder", "headers", "body_text", "date",
                    "has_attachments", "attachment_count"]

        # Scale snippet length to keep response size manageable
        n = len(rows)
        if n > 50:
            snippet_len = 0  # metadata only for large result sets
        elif n > 20:
            snippet_len = 80
        else:
            snippet_len = SNIPPET_LENGTH

        emails = [_format_email_row(row, columns, snippet_len=snippet_len) for row in rows]

        result = {
            "total_results": len(emails),
            "emails": emails,
        }
        if snippet_len == 0:
            result["note"] = "Snippets omitted due to large result set. Use get_email(id) for details."

        return json.dumps(result, indent=2)

    finally:
        conn.close()


@mcp.tool()
def semantic_search(
    query: str,
    folder: str | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
    limit: int = 10,
) -> str:
    """
    Search emails by meaning using semantic similarity.

    Embeds the query using the Ollama bge-m3 model and finds the most
    semantically similar emails in the database. Falls back to keyword
    search on the subject if the embedding service is unavailable.

    Parameters:
        query: Natural language search query (e.g., "emails about project deadlines")
        folder: Optional folder filter
        date_after: Optional ISO date — only emails on or after this date
        date_before: Optional ISO date — only emails on or before this date
        limit: Maximum results (default: 10)

    Returns:
        JSON with emails ranked by similarity
    """
    # Try to get an embedding
    query_bytes = _embed_query(query)

    if query_bytes is None:
        # Fallback: keyword search on subject
        return search_emails(
            subject=query, folder=folder,
            date_after=date_after, date_before=date_before,
            limit=limit,
        )

    conn = _get_conn()
    try:
        cursor = conn.cursor()

        conditions = ["em.embedding IS NOT NULL"]
        params = [query_bytes]

        if folder:
            conditions.append("e.folder = ?")
            params.append(folder)
        if date_after:
            conditions.append("e.date >= ?")
            params.append(date_after)
        if date_before:
            conditions.append("e.date <= ?")
            params.append(date_before)

        where = " AND ".join(conditions)
        params.append(limit)

        sql = f"""
            SELECT e.id, e.folder, e.headers, e.body_text, e.date,
                   e.has_attachments, e.attachment_count,
                   vec_distance_cosine(em.embedding, ?) as distance
            FROM emails e
            JOIN email_embeddings em ON e.id = em.email_id
            WHERE {where}
            ORDER BY distance ASC
            LIMIT ?
        """

        cursor.execute(sql, params)
        rows = cursor.fetchall()

        columns = ["id", "folder", "headers", "body_text", "date",
                    "has_attachments", "attachment_count", "distance"]

        emails = [_format_email_row(row, columns) for row in rows]

        return json.dumps({
            "search_type": "semantic",
            "query": query,
            "total_results": len(emails),
            "emails": emails,
        }, indent=2)

    finally:
        conn.close()


@mcp.tool()
def get_email(email_id: int) -> str:
    """
    Get the full content of a single email by its database ID.

    Returns the complete email including full body text, all headers,
    and attachment information.

    Parameters:
        email_id: The database ID of the email (from search results)

    Returns:
        JSON with full email content
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, filename, folder, message_id, in_reply_to,
                      "references", headers, body_text, body_html,
                      flags, date, file_size, has_attachments, attachment_count
               FROM emails WHERE id = ?""",
            (email_id,),
        )
        row = cursor.fetchone()
        if not row:
            return json.dumps({"error": f"Email not found: {email_id}"}, indent=2)

        columns = ["id", "filename", "folder", "message_id", "in_reply_to",
                    "references", "headers", "body_text", "body_html",
                    "flags", "date", "file_size", "has_attachments", "attachment_count"]

        data = dict(zip(columns, row))
        headers = json.loads(data["headers"])
        flags = json.loads(data["flags"])

        return json.dumps({
            "id": data["id"],
            "folder": data["folder"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
            "date": headers.get("Date_ISO", data["date"]),
            "message_id": data["message_id"],
            "in_reply_to": data["in_reply_to"],
            "body_text": data["body_text"],
            "flags": flags,
            "has_attachments": bool(data["has_attachments"]),
            "attachment_count": data["attachment_count"],
            "file_size": data["file_size"],
        }, indent=2)

    finally:
        conn.close()


@mcp.tool()
def get_emails(email_ids: list[int]) -> str:
    """
    Get the full content of multiple emails by their database IDs.

    More efficient than calling get_email repeatedly — fetches all
    emails in a single database query.

    Parameters:
        email_ids: List of database IDs (from search results)

    Returns:
        JSON with list of full email contents
    """
    if not email_ids:
        return json.dumps({"error": "No email IDs provided"}, indent=2)

    conn = _get_conn()
    try:
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(email_ids))
        cursor.execute(
            f"""SELECT id, filename, folder, message_id, in_reply_to,
                       "references", headers, body_text, body_html,
                       flags, date, file_size, has_attachments, attachment_count
                FROM emails WHERE id IN ({placeholders})
                ORDER BY date ASC""",
            email_ids,
        )

        columns = ["id", "filename", "folder", "message_id", "in_reply_to",
                    "references", "headers", "body_text", "body_html",
                    "flags", "date", "file_size", "has_attachments", "attachment_count"]

        emails = []
        for row in cursor.fetchall():
            data = dict(zip(columns, row))
            headers = json.loads(data["headers"])
            flags = json.loads(data["flags"])
            emails.append({
                "id": data["id"],
                "folder": data["folder"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "cc": headers.get("Cc", ""),
                "date": headers.get("Date_ISO", data["date"]),
                "message_id": data["message_id"],
                "in_reply_to": data["in_reply_to"],
                "body_text": data["body_text"],
                "flags": flags,
                "has_attachments": bool(data["has_attachments"]),
                "attachment_count": data["attachment_count"],
                "file_size": data["file_size"],
            })

        not_found = set(email_ids) - {e["id"] for e in emails}

        result = {"total": len(emails), "emails": emails}
        if not_found:
            result["not_found"] = list(not_found)

        return json.dumps(result, indent=2)

    finally:
        conn.close()


@mcp.tool()
def get_conversation(conversation_id: str) -> str:
    """
    Get all emails in a conversation thread.

    Returns the conversation metadata and all emails in chronological order.

    Parameters:
        conversation_id: The conversation thread ID (from email search results or list_conversations)

    Returns:
        JSON with conversation details and all emails in the thread
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """SELECT id, conversation_id, subject, folder, email_ids,
                      participant_emails, first_date, last_date
               FROM conversations WHERE conversation_id = ?""",
            (conversation_id,),
        )
        conv_row = cursor.fetchone()
        if not conv_row:
            return json.dumps({"error": f"Conversation not found: {conversation_id}"}, indent=2)

        conv_columns = ["id", "conversation_id", "subject", "folder",
                        "email_ids", "participant_emails", "first_date", "last_date"]
        conv = dict(zip(conv_columns, conv_row))

        email_ids = json.loads(conv["email_ids"])
        participants = json.loads(conv["participant_emails"])

        # Fetch all emails in the thread
        emails = []
        if email_ids:
            placeholders = ",".join("?" * len(email_ids))
            cursor.execute(
                f"""SELECT id, folder, headers, body_text, date,
                           has_attachments, attachment_count
                    FROM emails WHERE id IN ({placeholders})
                    ORDER BY date ASC""",
                email_ids,
            )

            columns = ["id", "folder", "headers", "body_text", "date",
                        "has_attachments", "attachment_count"]
            emails = [_format_email_row(row, columns) for row in cursor.fetchall()]

        return json.dumps({
            "conversation_id": conv["conversation_id"],
            "subject": conv["subject"],
            "folder": conv["folder"],
            "participants": participants,
            "first_date": conv["first_date"],
            "last_date": conv["last_date"],
            "email_count": len(emails),
            "emails": emails,
        }, indent=2)

    finally:
        conn.close()


@mcp.tool()
def list_conversations(
    folder: str | None = None,
    participant: str | None = None,
    subject: str | None = None,
    limit: int = 20,
) -> str:
    """
    Browse conversation threads with optional filters.

    Parameters:
        folder: Filter by folder name
        participant: Filter by participant email address (substring match)
        subject: Filter by subject text (substring match)
        limit: Maximum results (default: 20)

    Returns:
        JSON with conversation summaries sorted by most recent activity
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor()

        conditions = []
        params = []

        if folder:
            conditions.append("folder = ?")
            params.append(folder)
        if participant:
            conditions.append("participant_emails LIKE ?")
            params.append(f"%{participant}%")
        if subject:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor.execute(
            f"""SELECT conversation_id, subject, folder, email_ids,
                       participant_emails, first_date, last_date
                FROM conversations
                WHERE {where}
                ORDER BY last_date DESC
                LIMIT ?""",
            params,
        )

        results = []
        for row in cursor.fetchall():
            email_ids = json.loads(row[3])
            participants = json.loads(row[4])
            results.append({
                "conversation_id": row[0],
                "subject": row[1],
                "folder": row[2],
                "email_count": len(email_ids),
                "participants": participants,
                "first_date": row[5],
                "last_date": row[6],
            })

        return json.dumps({
            "total_results": len(results),
            "conversations": results,
        }, indent=2)

    finally:
        conn.close()


@mcp.tool()
def email_stats() -> str:
    """
    Get a quick overview of the email database.

    Returns counts by folder, total emails, embedding coverage,
    and conversation statistics.

    Returns:
        JSON with database statistics
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor()

        # Folder counts
        cursor.execute(
            "SELECT folder, COUNT(*) FROM emails GROUP BY folder ORDER BY folder"
        )
        folders = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT COUNT(*) FROM emails")
        total_emails = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM email_embeddings")
        total_embeddings = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM conversations")
        total_conversations = cursor.fetchone()[0]

        multi_email_threads = 0
        longest_thread = 0
        if total_conversations > 0:
            cursor.execute(
                "SELECT COUNT(*) FROM conversations WHERE json_array_length(email_ids) > 1"
            )
            multi_email_threads = cursor.fetchone()[0]
            cursor.execute(
                "SELECT MAX(json_array_length(email_ids)) FROM conversations"
            )
            longest_thread = cursor.fetchone()[0] or 0

        return json.dumps({
            "emails_by_folder": folders,
            "total_emails": total_emails,
            "total_embeddings": total_embeddings,
            "embedding_coverage": f"{total_embeddings / total_emails * 100:.1f}%" if total_emails else "0%",
            "total_conversations": total_conversations,
            "multi_email_threads": multi_email_threads,
            "longest_thread": longest_thread,
        }, indent=2)

    finally:
        conn.close()


@mcp.tool()
def find_similar_responses(
    email_id: int | None = None,
    text: str | None = None,
    limit: int = 5,
) -> str:
    """
    Find past emails similar to a given one where you wrote a reply.

    Returns pairs of {received_email, your_reply} so you can see how you
    responded to similar situations in the past. Useful for drafting replies
    with consistent tone, style, and decision-making.

    Provide either email_id (for an email already in the database) or text
    (for raw email content you're looking at). If both are given, email_id
    takes precedence.

    Parameters:
        email_id: Database ID of the email you want to reply to
        text: Raw text of the email (subject + body) if not in the database
        limit: Maximum number of similar response pairs to return (default: 5)

    Returns:
        JSON with pairs of similar received emails and your replies
    """
    if email_id is None and text is None:
        return json.dumps({"error": "Provide either email_id or text"}, indent=2)

    conn = _get_conn()
    try:
        cursor = conn.cursor()

        # Step 1: Get or build the query embedding
        if email_id is not None:
            # Get embedding from the database
            cursor.execute(
                "SELECT embedding FROM email_embeddings WHERE email_id = ?",
                (email_id,),
            )
            row = cursor.fetchone()
            if row:
                query_bytes = row[0]
            else:
                # No embedding stored — get the email text and embed it
                cursor.execute(
                    "SELECT json_extract(headers, '$.Subject'), body_text FROM emails WHERE id = ?",
                    (email_id,),
                )
                erow = cursor.fetchone()
                if not erow:
                    return json.dumps({"error": f"Email not found: {email_id}"}, indent=2)
                subject, body = erow
                embed_text = f"{subject}\n\n{body}" if subject else (body or "")
                query_bytes = _embed_query(embed_text)
        else:
            query_bytes = _embed_query(text)

        if query_bytes is None:
            return json.dumps({
                "error": "Could not generate embedding — Ollama may be unavailable",
                "suggestion": "Try again, or use search_emails with keyword filters instead",
            }, indent=2)

        # Step 2: Find similar received emails that have a reply from you.
        #
        # Strategy A: Vector search against non-Sent emails, then join
        # to find your reply via in_reply_to or references.
        #
        # Strategy B: Also check conversations that span Inbox+Sent.
        #
        # We combine both and deduplicate.

        # Fetch more candidates than needed since many won't have replies
        candidate_limit = limit * 20

        # Strategy A: semantic search against received emails
        cursor.execute(
            """
            SELECT
                e.id, e.folder, e.headers, e.body_text, e.date,
                e.message_id, e.has_attachments, e.attachment_count,
                vec_distance_cosine(em.embedding, ?) as distance
            FROM emails e
            JOIN email_embeddings em ON e.id = em.email_id
            WHERE e.folder != 'TrentSent'
              AND em.embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT ?
            """,
            (query_bytes, candidate_limit),
        )

        candidates = []
        for row in cursor.fetchall():
            candidates.append({
                "id": row[0], "folder": row[1], "headers": row[2],
                "body_text": row[3], "date": row[4], "message_id": row[5],
                "has_attachments": row[6], "attachment_count": row[7],
                "distance": row[8],
            })

        # For each candidate, try to find a reply from TrentSent
        pairs = []
        seen_ids = set()

        for cand in candidates:
            if len(pairs) >= limit:
                break

            cand_msg_id = cand["message_id"] or ""
            cand_id = cand["id"]

            if cand_id in seen_ids:
                continue

            # Look for a sent email replying to this one via in_reply_to
            reply_row = None
            if cand_msg_id:
                cursor.execute(
                    """
                    SELECT id, headers, body_text, date
                    FROM emails
                    WHERE folder = 'TrentSent'
                      AND (in_reply_to = ? OR in_reply_to = ?)
                    ORDER BY date ASC
                    LIMIT 1
                    """,
                    (cand_msg_id, f"<{cand_msg_id}>"),
                )
                reply_row = cursor.fetchone()

            # Fallback: check references field
            if reply_row is None and cand_msg_id:
                cursor.execute(
                    """
                    SELECT id, headers, body_text, date
                    FROM emails
                    WHERE folder = 'TrentSent'
                      AND ("references" LIKE ? OR "references" LIKE ?)
                    ORDER BY date ASC
                    LIMIT 1
                    """,
                    (f"%{cand_msg_id}%", f"%<{cand_msg_id}>%"),
                )
                reply_row = cursor.fetchone()

            # Fallback: check conversation table for cross-folder thread
            if reply_row is None:
                cursor.execute(
                    """
                    SELECT c.email_ids FROM conversations c
                    WHERE EXISTS (
                        SELECT 1 FROM json_each(c.email_ids) je
                        WHERE je.value = ?
                    )
                    """,
                    (cand_id,),
                )
                conv_row = cursor.fetchone()
                if conv_row:
                    conv_email_ids = json.loads(conv_row[0])
                    # Find a sent email in this conversation that comes after the candidate
                    if conv_email_ids:
                        placeholders = ",".join("?" * len(conv_email_ids))
                        cursor.execute(
                            f"""
                            SELECT id, headers, body_text, date
                            FROM emails
                            WHERE id IN ({placeholders})
                              AND folder = 'TrentSent'
                              AND date >= ?
                            ORDER BY date ASC
                            LIMIT 1
                            """,
                            conv_email_ids + [cand["date"] or ""],
                        )
                        reply_row = cursor.fetchone()

            if reply_row is None:
                continue

            # Build the pair
            seen_ids.add(cand_id)

            cand_headers = json.loads(cand["headers"])
            reply_headers = json.loads(reply_row[1])

            similarity = round(1.0 - cand["distance"], 3) if cand["distance"] is not None else None

            pairs.append({
                "similarity": similarity,
                "received_email": {
                    "id": cand["id"],
                    "folder": cand["folder"],
                    "subject": cand_headers.get("Subject", ""),
                    "from": cand_headers.get("From", ""),
                    "date": cand_headers.get("Date_ISO", cand["date"]),
                    "snippet": _snippet(cand["body_text"]),
                },
                "your_reply": {
                    "id": reply_row[0],
                    "subject": reply_headers.get("Subject", ""),
                    "to": reply_headers.get("To", ""),
                    "date": reply_headers.get("Date_ISO", reply_row[3]),
                    "snippet": _snippet(reply_row[2]),
                },
            })

        # If we didn't find enough via threading, note it
        note = None
        if len(pairs) == 0:
            note = ("No reply pairs found. This may be because the received emails "
                    "similar to this one aren't in the local database yet, or because "
                    "threading headers didn't link them to your replies.")
        elif len(pairs) < limit:
            note = (f"Found {len(pairs)} pair(s). More may be available once additional "
                    "mail folders are synced to the local database.")

        result = {
            "query_email_id": email_id,
            "total_pairs": len(pairs),
            "pairs": pairs,
        }
        if note:
            result["note"] = note

        return json.dumps(result, indent=2)

    finally:
        conn.close()


@mcp.tool()
def extract_from_emails(
    pattern: str,
    folder: str | None = None,
    sender: str | None = None,
    subject: str | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
    limit: int = 200,
) -> str:
    """
    Extract text from email bodies using a regex pattern.

    Runs the pattern against the body_text of each matching email and returns
    only the captured matches — not the full body. Use named capture groups
    for structured extraction (e.g., "Student:\\s*(?P<name>.+?)\\n").

    If the pattern has capture groups, returns the group matches.
    If no capture groups, returns the full match text.
    All matches per email are returned (not just the first).

    Parameters:
        pattern: Python regex pattern to apply to each email's body_text
        folder: Filter by folder name (e.g., TrentInbox)
        sender: Case-insensitive substring match in the From header
        subject: Case-insensitive substring match in the Subject header
        date_after: ISO date string — only emails on or after this date
        date_before: ISO date string — only emails on or before this date
        limit: Maximum emails to scan (default: 200)

    Returns:
        JSON with emails that had matches, each including email metadata
        and a "matches" list of extracted data
    """
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as e:
        return json.dumps({"error": f"Invalid regex pattern: {e}"}, indent=2)

    has_groups = compiled.groups > 0
    has_named_groups = bool(compiled.groupindex)

    conn = _get_conn()
    try:
        cursor = conn.cursor()

        conditions = []
        params = []

        if folder:
            conditions.append("e.folder = ?")
            params.append(folder)
        if sender:
            conditions.append("json_extract(e.headers, '$.From') LIKE ?")
            params.append(f"%{sender}%")
        if subject:
            conditions.append("json_extract(e.headers, '$.Subject') LIKE ?")
            params.append(f"%{subject}%")
        if date_after:
            conditions.append("e.date >= ?")
            params.append(date_after)
        if date_before:
            conditions.append("e.date <= ?")
            params.append(date_before)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        cursor.execute(
            f"""SELECT e.id, e.folder, e.headers, e.body_text, e.date
                FROM emails e
                WHERE {where}
                ORDER BY e.date DESC
                LIMIT ?""",
            params,
        )

        results = []
        emails_scanned = 0

        for row in cursor.fetchall():
            emails_scanned += 1
            email_id, email_folder, headers_json, body_text, date = row
            if not body_text:
                continue

            matches_found = list(compiled.finditer(body_text))
            if not matches_found:
                continue

            headers = json.loads(headers_json)

            if has_named_groups:
                matches = [m.groupdict() for m in matches_found]
            elif has_groups:
                matches = [m.groups() for m in matches_found]
            else:
                matches = [m.group() for m in matches_found]

            results.append({
                "id": email_id,
                "folder": email_folder,
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date_ISO", date),
                "match_count": len(matches),
                "matches": matches,
            })

        return json.dumps({
            "pattern": pattern,
            "emails_scanned": emails_scanned,
            "emails_with_matches": len(results),
            "results": results,
        }, indent=2)

    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
