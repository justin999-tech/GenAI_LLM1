"""Notion integration tools.

User must provide a Notion Integration Token in .env (NOTION_TOKEN) or
via the providers.json config. Tools fail gracefully if no token is set.
"""
import json
import os
import re
import urllib.parse
import urllib.request


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _get_token() -> str | None:
    return os.getenv("NOTION_TOKEN")


def _request(method: str, path: str, body: dict = None) -> dict:
    token = _get_token()
    if not token:
        raise RuntimeError("NOTION_TOKEN not set. Add it in Settings → Notion.")
    url = f"{NOTION_API}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
            "User-Agent": "Lab2-Chatbot/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _markdown_to_blocks(md: str) -> list[dict]:
    """Convert simple markdown to Notion block objects."""
    blocks = []
    for line in md.splitlines():
        s = line.rstrip()
        if not s.strip():
            continue
        # Headings
        if s.startswith("# "):
            blocks.append({
                "object": "block", "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": s[2:]}}]},
            })
        elif s.startswith("## "):
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": s[3:]}}]},
            })
        elif s.startswith("### "):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": s[4:]}}]},
            })
        elif s.startswith("- ") or s.startswith("* "):
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": s[2:]}}]},
            })
        elif re.match(r"^\d+\.\s", s):
            content = re.sub(r"^\d+\.\s", "", s)
            blocks.append({
                "object": "block", "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })
        else:
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": s}}]},
            })
    return blocks


def notion_search(query: str = "", filter_type: str = "page") -> str:
    try:
        body = {"query": query, "page_size": 10}
        if filter_type in ("page", "database"):
            body["filter"] = {"property": "object", "value": filter_type}
        data = _request("POST", "/search", body)
        results = data.get("results", [])
        if not results:
            return "No matching pages found."
        out = []
        for r in results[:10]:
            obj = r.get("object")
            rid = r.get("id", "")[:8]
            props = r.get("properties", {})
            title = "(untitled)"
            if obj == "page":
                # Try common title properties
                for prop in props.values():
                    if prop.get("type") == "title":
                        chunks = prop.get("title", [])
                        title = "".join(c.get("plain_text", "") for c in chunks) or "(untitled)"
                        break
            elif obj == "database":
                t = r.get("title", [])
                title = "".join(c.get("plain_text", "") for c in t) or "(untitled DB)"
            url = r.get("url", "")
            out.append(f"📄 [{obj}] {title} · id={rid}\n   {url}")
        return "\n\n".join(out)
    except Exception as e:
        return f"Notion search failed: {e}"


def notion_create_page(title: str, content: str = "", parent_id: str = "") -> str:
    """Create a Notion page. parent_id can be a page ID (will create as subpage)
    or empty (will create at workspace root - requires Integration Token to have access)."""
    try:
        if not parent_id:
            # Find first accessible page to use as parent
            search_data = _request("POST", "/search", {
                "filter": {"property": "object", "value": "page"},
                "page_size": 1,
            })
            results = search_data.get("results", [])
            if not results:
                return "No accessible parent page. Share a page with the integration first."
            parent_id = results[0]["id"]

        body = {
            "parent": {"page_id": parent_id},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
            "children": _markdown_to_blocks(content),
        }
        page = _request("POST", "/pages", body)
        return (f"✅ Page created: {title}\n"
                f"🔗 {page.get('url', '(no url)')}\n"
                f"id={page.get('id', '')[:8]}")
    except Exception as e:
        return f"Notion page creation failed: {e}"


def notion_append_to_page(page_id: str, content: str) -> str:
    try:
        blocks = _markdown_to_blocks(content)
        if not blocks:
            return "No content to append."
        _request("PATCH", f"/blocks/{page_id}/children", {"children": blocks})
        return f"✅ Appended {len(blocks)} block(s) to page {page_id[:8]}"
    except Exception as e:
        return f"Notion append failed: {e}"


def notion_list_pages(limit: int = 10) -> str:
    return notion_search("", filter_type="page")


def notion_query_database(database_id: str, page_size: int = 10) -> str:
    try:
        data = _request("POST", f"/databases/{database_id}/query", {"page_size": page_size})
        results = data.get("results", [])
        if not results:
            return f"Database {database_id[:8]} is empty"
        out = [f"Database {database_id[:8]} — {len(results)} entries:"]
        for r in results[:page_size]:
            props = r.get("properties", {})
            line = []
            for name, val in props.items():
                t = val.get("type")
                if t == "title":
                    chunks = val.get("title", [])
                    s = "".join(c.get("plain_text", "") for c in chunks)
                    line.append(f"{name}: {s}")
                elif t == "rich_text":
                    chunks = val.get("rich_text", [])
                    s = "".join(c.get("plain_text", "") for c in chunks)
                    line.append(f"{name}: {s[:50]}")
                elif t == "select":
                    sel = val.get("select")
                    if sel:
                        line.append(f"{name}: {sel.get('name')}")
                elif t == "number":
                    line.append(f"{name}: {val.get('number')}")
            out.append(" · ".join(line) if line else "(empty row)")
        return "\n".join(out)
    except Exception as e:
        return f"Notion DB query failed: {e}"


TOOLS = {
    "notion_search": {
        "description": "Search Notion workspace for pages/databases by title/content. Requires NOTION_TOKEN.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "filter_type": {"type": "string", "enum": ["page", "database", "any"], "default": "page"},
            },
            "required": [],
        },
        "handler": lambda a: notion_search(a.get("query", ""), a.get("filter_type", "page")),
    },
    "notion_list_pages": {
        "description": "List all accessible Notion pages.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
            "required": [],
        },
        "handler": lambda a: notion_list_pages(int(a.get("limit", 10))),
    },
    "notion_create_page": {
        "description": "Create a new Notion page with markdown content. Requires sharing a parent page with the integration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string", "description": "Markdown content"},
                "parent_id": {"type": "string", "description": "Optional parent page ID"},
            },
            "required": ["title"],
        },
        "handler": lambda a: notion_create_page(a.get("title", ""), a.get("content", ""),
                                                    a.get("parent_id", "")),
    },
    "notion_append_to_page": {
        "description": "Append markdown content to an existing Notion page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["page_id", "content"],
        },
        "handler": lambda a: notion_append_to_page(a.get("page_id", ""), a.get("content", "")),
    },
    "notion_query_database": {
        "description": "Query a Notion database by ID and return its rows.",
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string"},
                "page_size": {"type": "integer", "default": 10},
            },
            "required": ["database_id"],
        },
        "handler": lambda a: notion_query_database(a.get("database_id", ""),
                                                       int(a.get("page_size", 10))),
    },
}
