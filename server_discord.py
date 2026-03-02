import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="Discord Export Parser")


def _author_display_name(author: dict) -> str:
    return author.get("nickname") or author["name"]


def _author_role_names(author: dict) -> list[str]:
    return [r["name"] for r in author.get("roles", [])]


def _is_staff(author: dict, staff_roles: set[str]) -> bool:
    return bool(staff_roles & set(_author_role_names(author)))


@mcp.tool()
def parse_discord_export(file_path: str, staff_roles: str = "MATH - Teaching Assistant,Professor"):
    """
    Parses a DiscordChatExporter JSON file and identifies which student
    questions received a response from staff (TA or Professor).

    Returns structured JSON with every student question, its answer status,
    who responded, and a summary of unanswered questions.

    Use this tool to check whether students have received help on a Discord
    channel. The export must be in DiscordChatExporter JSON format.

    staff_roles is a comma-separated list of Discord role names that
    identify staff members (defaults to "MATH - Teaching Assistant,Professor").
    """
    export_path = Path(file_path).absolute()

    if not export_path.exists():
        return f"File does not exist at {export_path}."

    if not export_path.suffix.lower() == ".json":
        return f"File does not appear to be JSON. Extension: {export_path.suffix.lower()}"

    with open(export_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    if not messages:
        return "No messages found in export file."

    guild_id = data.get("guild", {}).get("id", "")
    channel_id = data.get("channel", {}).get("id", "")
    staff_role_set = {r.strip() for r in staff_roles.split(",")}

    # Build lookup: message id -> message
    msg_map = {m["id"]: m for m in messages}

    # Map which messages got threads: reference.channelId -> list of ThreadCreated messages
    thread_map: dict[str, list[dict]] = {}
    for m in messages:
        if m["type"] == "ThreadCreated":
            ref_channel = (m.get("reference") or {}).get("channelId")
            if ref_channel:
                thread_map.setdefault(ref_channel, []).append(m)

    # Map which messages got inline replies: reference.messageId -> list of Reply messages
    reply_map: dict[str, list[dict]] = {}
    for m in messages:
        if m["type"] == "Reply":
            ref_msg = (m.get("reference") or {}).get("messageId")
            if ref_msg:
                reply_map.setdefault(ref_msg, []).append(m)

    # Process each student Default message as a potential question
    questions = []
    for m in messages:
        if m["type"] != "Default":
            continue
        if _is_staff(m["author"], staff_role_set):
            continue
        # Skip empty messages with no content and no attachments
        if not m["content"].strip() and not m.get("attachments"):
            continue

        author_name = _author_display_name(m["author"])
        author_roles = _author_role_names(m["author"])

        responders = []

        # Check for threads started on this message
        for tc in thread_map.get(m["id"], []):
            tc_name = _author_display_name(tc["author"])
            tc_roles = _author_role_names(tc["author"])
            staff_match = staff_role_set & set(tc_roles)
            thread_channel_id = (tc.get("reference") or {}).get("channelId", "")
            responders.append({
                "name": tc_name,
                "role": next(iter(staff_match)) if staff_match else tc_roles[0] if tc_roles else "Unknown",
                "response_type": "thread",
                "is_staff": bool(staff_match),
                "thread_link": f"https://discord.com/channels/{guild_id}/{thread_channel_id}" if guild_id and thread_channel_id else None,
            })

        # Check for inline replies to this message
        for rp in reply_map.get(m["id"], []):
            rp_name = _author_display_name(rp["author"])
            rp_roles = _author_role_names(rp["author"])
            staff_match = staff_role_set & set(rp_roles)
            responders.append({
                "name": rp_name,
                "role": next(iter(staff_match)) if staff_match else rp_roles[0] if rp_roles else "Unknown",
                "response_type": "reply",
                "is_staff": bool(staff_match),
                "reply_content": rp["content"][:200],
            })

        has_staff_response = any(r["is_staff"] for r in responders)
        has_peer_response = any(not r["is_staff"] for r in responders)

        if has_staff_response:
            status = "staff_answered"
        elif has_peer_response:
            status = "peer_answered"
        else:
            status = "unanswered"

        # Build a direct link to this message in Discord
        msg_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{m['id']}" if guild_id and channel_id else None

        # Collect thread links from responders for convenience at the question level
        thread_links = [r["thread_link"] for r in responders if r.get("thread_link")]

        questions.append({
            "id": m["id"],
            "author": author_name,
            "author_roles": author_roles,
            "content": m["content"],
            "timestamp": m["timestamp"],
            "has_attachments": bool(m.get("attachments")),
            "message_link": msg_link,
            "thread_links": thread_links,
            "status": status,
            "responders": responders,
        })

    # Sort chronologically (oldest first)
    questions.sort(key=lambda q: q["timestamp"])

    # Build summary
    total = len(questions)
    staff_answered = sum(1 for q in questions if q["status"] == "staff_answered")
    peer_answered = sum(1 for q in questions if q["status"] == "peer_answered")
    unanswered = sum(1 for q in questions if q["status"] == "unanswered")
    unanswered_entries = [
        {
            "author": q["author"],
            "content": q["content"][:100],
            "timestamp": q["timestamp"],
            "message_link": q["message_link"],
        }
        for q in questions if q["status"] == "unanswered"
    ]

    result = {
        "guild": data.get("guild", {}).get("name", "Unknown"),
        "channel": data.get("channel", {}).get("name", "Unknown"),
        "category": data.get("channel", {}).get("category"),
        "export_date": data.get("exportedAt"),
        "staff_roles_used": sorted(staff_role_set),
        "questions": questions,
        "summary": {
            "total_questions": total,
            "staff_answered": staff_answered,
            "peer_answered": peer_answered,
            "unanswered": unanswered,
            "unanswered_entries": unanswered_entries,
        },
    }

    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
