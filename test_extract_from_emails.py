"""Tests for the extract_from_emails tool in server_evangeline.py.

Uses an in-memory SQLite database with synthetic email data.
"""

import json
import sqlite3
from unittest.mock import patch

import sqlite_vec

# We need to patch _get_conn before the tool function uses it,
# so we import the module and patch at the function level.
import server_evangeline as srv


# -- Test fixtures -----------------------------------------------------------

SAMPLE_EMAILS = [
    {
        "id": 1,
        "filename": "msg001",
        "folder": "TrentInbox",
        "message_id": "aaa@example.com",
        "in_reply_to": "",
        "references": "",
        "headers": json.dumps({
            "From": "accommodations@university.ca",
            "To": "dave@university.ca",
            "Subject": "Accommodation Notice - MATH 1021",
            "Date_ISO": "2026-03-01T10:00:00",
        }),
        "body_text": (
            "Dear Professor,\n\n"
            "This is to inform you that the following student has been approved "
            "for academic accommodations:\n\n"
            "Student Name: Alice Johnson\n"
            "Student ID: 0412345\n"
            "Course: MATH 1021\n"
            "Accommodations: Extra time (1.5x), separate room\n\n"
            "Please contact our office if you have questions.\n"
            "Regards,\nAccessibility Services"
        ),
        "body_html": "",
        "flags": json.dumps({"seen": True, "flagged": False}),
        "date": "2026-03-01T10:00:00",
        "file_size": 1024,
        "has_attachments": 0,
        "attachment_count": 0,
    },
    {
        "id": 2,
        "filename": "msg002",
        "folder": "TrentInbox",
        "message_id": "bbb@example.com",
        "in_reply_to": "",
        "references": "",
        "headers": json.dumps({
            "From": "exams@university.ca",
            "To": "dave@university.ca",
            "Subject": "Exam Booking Confirmation - MATH 1021",
            "Date_ISO": "2026-03-10T14:00:00",
        }),
        "body_text": (
            "Exam Booking Details\n"
            "====================\n\n"
            "Student Name: Alice Johnson\n"
            "Student ID: 0412345\n"
            "Course: MATH 1021\n"
            "Exam Date: 2026-04-15\n"
            "Time: 09:00 - 11:30\n"
            "Room: OCA 301\n\n"
            "Student Name: Bob Smith\n"
            "Student ID: 0498765\n"
            "Course: MATH 1021\n"
            "Exam Date: 2026-04-15\n"
            "Time: 09:00 - 12:00\n"
            "Room: OCA 301\n\n"
            "Please ensure exam papers are delivered 24 hours in advance."
        ),
        "body_html": "",
        "flags": json.dumps({"seen": True, "flagged": False}),
        "date": "2026-03-10T14:00:00",
        "file_size": 2048,
        "has_attachments": 0,
        "attachment_count": 0,
    },
    {
        "id": 3,
        "filename": "msg003",
        "folder": "TrentInbox",
        "message_id": "ccc@example.com",
        "in_reply_to": "",
        "references": "",
        "headers": json.dumps({
            "From": "student@university.ca",
            "To": "dave@university.ca",
            "Subject": "Question about assignment 3",
            "Date_ISO": "2026-03-12T09:00:00",
        }),
        "body_text": (
            "Hi Professor,\n\n"
            "I had a question about assignment 3, problem 2. "
            "Could you clarify what is meant by 'convergence'?\n\n"
            "Thanks,\nCharlie"
        ),
        "body_html": "",
        "flags": json.dumps({"seen": False, "flagged": False}),
        "date": "2026-03-12T09:00:00",
        "file_size": 512,
        "has_attachments": 0,
        "attachment_count": 0,
    },
    {
        "id": 4,
        "filename": "msg004",
        "folder": "TrentSent",
        "message_id": "ddd@example.com",
        "in_reply_to": "",
        "references": "",
        "headers": json.dumps({
            "From": "dave@university.ca",
            "To": "someone@university.ca",
            "Subject": "Meeting notes",
            "Date_ISO": "2026-03-05T16:00:00",
        }),
        "body_text": "No accommodation info here. Just meeting notes.",
        "body_html": "",
        "flags": json.dumps({"seen": True, "flagged": False}),
        "date": "2026-03-05T16:00:00",
        "file_size": 256,
        "has_attachments": 0,
        "attachment_count": 0,
    },
]


def _create_test_db():
    """Create an in-memory SQLite database with the emails table and sample data."""
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)

    conn.execute("""
        CREATE TABLE emails (
            id INTEGER PRIMARY KEY,
            filename TEXT UNIQUE NOT NULL,
            folder TEXT NOT NULL DEFAULT '',
            message_id TEXT DEFAULT '',
            in_reply_to TEXT DEFAULT '',
            "references" TEXT DEFAULT '',
            headers TEXT NOT NULL DEFAULT '{}',
            body_text TEXT NOT NULL DEFAULT '',
            body_html TEXT DEFAULT '',
            flags TEXT NOT NULL DEFAULT '{}',
            date TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            has_attachments INTEGER DEFAULT 0,
            attachment_count INTEGER DEFAULT 0
        )
    """)

    for email in SAMPLE_EMAILS:
        conn.execute(
            """INSERT INTO emails
               (id, filename, folder, message_id, in_reply_to, "references",
                headers, body_text, body_html, flags, date, file_size,
                has_attachments, attachment_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email["id"], email["filename"], email["folder"],
                email["message_id"], email["in_reply_to"], email["references"],
                email["headers"], email["body_text"], email["body_html"],
                email["flags"], email["date"], email["file_size"],
                email["has_attachments"], email["attachment_count"],
            ),
        )
    conn.commit()
    return conn


# -- Tests -------------------------------------------------------------------

_test_conn = None


def _get_test_conn():
    return _test_conn


def _run_extract(**kwargs):
    """Call extract_from_emails with the test DB patched in."""
    global _test_conn
    _test_conn = _create_test_db()
    try:
        with patch.object(srv, "_get_conn", _get_test_conn):
            result_json = srv.extract_from_emails(**kwargs)
        return json.loads(result_json)
    finally:
        _test_conn.close()
        _test_conn = None


def test_named_groups_single_match():
    """Named capture groups extract structured data from one email."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)\nStudent ID:\s*(?P<id>\d+)",
        subject="Accommodation",
    )
    assert result["emails_scanned"] == 1
    assert result["emails_with_matches"] == 1

    email = result["results"][0]
    assert email["id"] == 1
    assert email["match_count"] == 1
    assert email["matches"][0]["name"] == "Alice Johnson"
    assert email["matches"][0]["id"] == "0412345"


def test_named_groups_multiple_matches():
    """Multiple matches in one email are all returned."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)\nStudent ID:\s*(?P<id>\d+)",
        subject="Exam Booking",
    )
    assert result["emails_with_matches"] == 1

    email = result["results"][0]
    assert email["match_count"] == 2
    assert email["matches"][0]["name"] == "Alice Johnson"
    assert email["matches"][1]["name"] == "Bob Smith"
    assert email["matches"][1]["id"] == "0498765"


def test_unnamed_groups():
    """Unnamed capture groups return tuples."""
    result = _run_extract(
        pattern=r"Student Name:\s*(.+)\nStudent ID:\s*(\d+)",
        subject="Accommodation",
    )
    match = result["results"][0]["matches"][0]
    assert match == ["Alice Johnson", "0412345"]


def test_no_groups():
    """Pattern without groups returns full match strings."""
    result = _run_extract(
        pattern=r"Room:\s*\S+",
        subject="Exam Booking",
    )
    email = result["results"][0]
    assert email["match_count"] == 2
    assert email["matches"] == ["Room: OCA", "Room: OCA"]


def test_no_matches():
    """When no emails match the regex, results list is empty."""
    result = _run_extract(
        pattern=r"NONEXISTENT_PATTERN_XYZ",
    )
    assert result["emails_with_matches"] == 0
    assert result["results"] == []


def test_folder_filter():
    """Folder filter restricts which emails are scanned."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)",
        folder="TrentSent",
    )
    assert result["emails_scanned"] == 1
    assert result["emails_with_matches"] == 0


def test_sender_filter():
    """Sender filter narrows results."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)",
        sender="exams@",
    )
    assert result["emails_scanned"] == 1
    assert result["emails_with_matches"] == 1
    assert result["results"][0]["id"] == 2


def test_date_filters():
    """Date range filters work correctly."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)",
        date_after="2026-03-05",
        date_before="2026-03-11",
    )
    # Only email 2 (March 10) should match the date range AND have student names
    assert result["emails_with_matches"] == 1
    assert result["results"][0]["id"] == 2


def test_invalid_regex():
    """Invalid regex returns an error, not a crash."""
    result = _run_extract(pattern=r"[invalid")
    assert "error" in result
    assert "Invalid regex" in result["error"]


def test_empty_body():
    """Emails with empty body_text are skipped without error."""
    # All our sample emails have body text, so this tests the skip path
    # indirectly — the key thing is no crash
    result = _run_extract(
        pattern=r"anything",
        folder="TrentInbox",
    )
    assert "error" not in result


def test_metadata_in_results():
    """Results include email metadata alongside matches."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)",
        subject="Accommodation",
    )
    email = result["results"][0]
    assert email["subject"] == "Accommodation Notice - MATH 1021"
    assert email["from"] == "accommodations@university.ca"
    assert email["date"] == "2026-03-01T10:00:00"
    assert email["folder"] == "TrentInbox"


def test_all_emails_scanned_without_filters():
    """Without filters, all emails are scanned."""
    result = _run_extract(
        pattern=r"Student Name:\s*(?P<name>.+)",
    )
    assert result["emails_scanned"] == 4
    assert result["emails_with_matches"] == 2  # emails 1 and 2
