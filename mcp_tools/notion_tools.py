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


_NOTION_LANGS = {
    "py", "python", "js", "javascript", "ts", "typescript", "html", "css",
    "json", "yaml", "yml", "bash", "shell", "sh", "sql", "java", "c", "c++",
    "cpp", "c#", "csharp", "go", "rust", "ruby", "php", "swift", "kotlin",
    "scala", "r", "matlab", "markdown", "md", "diff", "docker", "dockerfile",
    "graphql", "latex", "lua", "perl", "powershell", "scss", "sass",
    "plain text", "abap", "arduino", "assembly", "clojure", "coffeescript",
    "dart", "elixir", "elm", "erlang", "f#", "flow", "fortran", "gherkin",
    "groovy", "haskell", "haml", "ini", "julia", "livescript", "lisp",
    "makefile", "mathematica", "mermaid", "nix", "objective-c", "ocaml",
    "pascal", "prolog", "racket", "reason", "sas", "scheme", "smalltalk",
    "solidity", "stan", "stata", "tex", "toml", "vbnet", "verilog",
    "vhdl", "visual basic", "webassembly", "xml",
}


def _normalize_lang(lang: str) -> str:
    l = (lang or "").strip().lower()
    aliases = {
        "py": "python", "js": "javascript", "ts": "typescript",
        "shell": "bash", "sh": "bash", "yml": "yaml", "md": "markdown",
        "cpp": "c++", "csharp": "c#", "dockerfile": "docker",
    }
    l = aliases.get(l, l)
    return l if l in _NOTION_LANGS else "plain text"


# Inline rich-text patterns. Order matters — code is scanned first so that
# **inside `code`** isn't picked up as bold.
_INLINE_RE = re.compile(
    r"(`[^`\n]+`)"                  # `code`
    r"|(\*\*[^\*\n]+\*\*)"          # **bold**
    r"|(__[^_\n]+__)"               # __bold__
    r"|(\*[^\*\n]+\*)"              # *italic*
    r"|(_[^_\n]+_)"                 # _italic_
    r"|(~~[^~\n]+~~)"               # ~~strikethrough~~
    r"|(\[[^\]]+\]\([^\)\s]+\))"    # [text](url)
)


def _parse_rich_text(text: str) -> list[dict]:
    """Convert markdown-flavoured inline text into Notion rich_text spans."""
    if not text:
        return []
    out = []
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.extend(_plain_chunks(text[pos:m.start()]))
        token = m.group(0)
        if token.startswith("`") and token.endswith("`"):
            out.extend(_plain_chunks(token[1:-1], code=True))
        elif token.startswith("**") and token.endswith("**"):
            out.extend(_plain_chunks(token[2:-2], bold=True))
        elif token.startswith("__") and token.endswith("__"):
            out.extend(_plain_chunks(token[2:-2], bold=True))
        elif token.startswith("~~") and token.endswith("~~"):
            out.extend(_plain_chunks(token[2:-2], strikethrough=True))
        elif token.startswith("*") and token.endswith("*"):
            out.extend(_plain_chunks(token[1:-1], italic=True))
        elif token.startswith("_") and token.endswith("_"):
            out.extend(_plain_chunks(token[1:-1], italic=True))
        elif token.startswith("[") and "](" in token:
            label, _, rest = token[1:].partition("](")
            url = rest.rstrip(")")
            out.append({
                "type": "text",
                "text": {"content": label, "link": {"url": url}},
            })
        else:
            out.extend(_plain_chunks(token))
        pos = m.end()
    if pos < len(text):
        out.extend(_plain_chunks(text[pos:]))
    return out or [{"type": "text", "text": {"content": text}}]


def _plain_chunks(s: str, **annotations) -> list[dict]:
    """Notion limits a single text node to 2000 chars — chunk if needed."""
    if not s:
        return []
    out = []
    for i in range(0, len(s), 2000):
        chunk = {"type": "text", "text": {"content": s[i:i + 2000]}}
        if annotations:
            chunk["annotations"] = dict(annotations)
        out.append(chunk)
    return out


def _markdown_to_blocks(md: str) -> list[dict]:
    """Convert markdown to Notion block objects.

    Supports: H1–H3, paragraphs with rich text (bold/italic/code/strike/link),
    bullet/numbered/to-do lists, quotes, code blocks (fenced ```lang),
    dividers (---), tables (| col | col |), images (![alt](url)),
    callouts (> [!note] / > [!warning] / > [!tip]).
    """
    blocks: list[dict] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.rstrip()
        stripped = s.strip()

        if not stripped:
            i += 1
            continue

        # Fenced code block: ```lang\n...\n```
        m = re.match(r"^```(\S*)\s*$", s)
        if m:
            lang = _normalize_lang(m.group(1))
            j = i + 1
            code_lines = []
            while j < len(lines) and not lines[j].rstrip().startswith("```"):
                code_lines.append(lines[j])
                j += 1
            blocks.append({
                "object": "block", "type": "code",
                "code": {
                    "rich_text": _plain_chunks("\n".join(code_lines)),
                    "language": lang,
                },
            })
            i = j + 1
            continue

        # Markdown table: header | sep | rows
        if "|" in s and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]):
            header = [c.strip() for c in s.strip("|").split("|")]
            j = i + 2
            rows = []
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append([c.strip() for c in lines[j].strip("|").split("|")])
                j += 1
            width = max(len(header), max((len(r) for r in rows), default=0))
            def pad(r): return r + [""] * (width - len(r))
            table_children = [
                {
                    "object": "block", "type": "table_row",
                    "table_row": {"cells": [_parse_rich_text(c) for c in pad(header)]},
                },
            ] + [
                {
                    "object": "block", "type": "table_row",
                    "table_row": {"cells": [_parse_rich_text(c) for c in pad(r)]},
                } for r in rows
            ]
            blocks.append({
                "object": "block", "type": "table",
                "table": {
                    "table_width": width,
                    "has_column_header": True,
                    "has_row_header": False,
                    "children": table_children,
                },
            })
            i = j
            continue

        # Image: ![alt](url)
        m = re.match(r"^!\[([^\]]*)\]\((https?://[^\s\)]+)\)\s*$", stripped)
        if m:
            alt, url = m.group(1), m.group(2)
            blocks.append({
                "object": "block", "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": url},
                    "caption": _parse_rich_text(alt) if alt else [],
                },
            })
            i += 1
            continue

        # Divider: --- / *** / ___
        if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", stripped):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # Headings (#, ##, ###; deeper levels collapse to H3)
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            level = min(len(m.group(1)), 3)
            ttype = f"heading_{level}"
            blocks.append({
                "object": "block", "type": ttype,
                ttype: {"rich_text": _parse_rich_text(m.group(2))},
            })
            i += 1
            continue

        # To-do: - [ ] foo / - [x] bar
        m = re.match(r"^[\-\*]\s+\[( |x|X)\]\s+(.*)$", s)
        if m:
            checked = m.group(1).lower() == "x"
            blocks.append({
                "object": "block", "type": "to_do",
                "to_do": {
                    "rich_text": _parse_rich_text(m.group(2)),
                    "checked": checked,
                },
            })
            i += 1
            continue

        # Bulleted list
        m = re.match(r"^[\-\*\+]\s+(.*)$", s)
        if m:
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": _parse_rich_text(m.group(1))},
            })
            i += 1
            continue

        # Numbered list
        m = re.match(r"^\d+\.\s+(.*)$", s)
        if m:
            blocks.append({
                "object": "block", "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": _parse_rich_text(m.group(1))},
            })
            i += 1
            continue

        # Callout: > [!note] / [!tip] / [!warning] / [!info]  text...
        m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", s)
        if m:
            kind = m.group(1).lower()
            text = m.group(2)
            icon_map = {
                "note": "📝", "info": "ℹ️", "tip": "💡", "warning": "⚠️",
                "danger": "🚨", "success": "✅", "question": "❓",
            }
            color_map = {
                "note": "default", "info": "blue_background",
                "tip": "yellow_background", "warning": "orange_background",
                "danger": "red_background", "success": "green_background",
                "question": "purple_background",
            }
            blocks.append({
                "object": "block", "type": "callout",
                "callout": {
                    "rich_text": _parse_rich_text(text),
                    "icon": {"type": "emoji", "emoji": icon_map.get(kind, "💬")},
                    "color": color_map.get(kind, "gray_background"),
                },
            })
            i += 1
            continue

        # Plain quote
        m = re.match(r"^>\s+(.*)$", s)
        if m:
            blocks.append({
                "object": "block", "type": "quote",
                "quote": {"rich_text": _parse_rich_text(m.group(1))},
            })
            i += 1
            continue

        # Paragraph (fall-through)
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _parse_rich_text(s)},
        })
        i += 1

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


def notion_create_page(title: str, content: str = "", parent_id: str = "",
                       icon: str = "", cover_url: str = "") -> str:
    """Create a Notion page. parent_id can be a page ID (will create as subpage)
    or empty (will create at workspace root - requires Integration Token to have access).

    icon: optional emoji string to use as the page icon (e.g. "🌸").
    cover_url: optional public image URL for the page header cover."""
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
        if icon:
            body["icon"] = {"type": "emoji", "emoji": icon}
        if cover_url and cover_url.startswith(("http://", "https://")):
            body["cover"] = {"type": "external", "external": {"url": cover_url}}
        page = _request("POST", "/pages", body)
        return (f"✅ Page created: {title}\n"
                f"🔗 {page.get('url', '(no url)')}\n"
                f"id={page.get('id', '')}")
    except Exception as e:
        return f"Notion page creation failed: {e}"


# ---- Property schema builder for databases --------------------------------

def _build_db_property(spec) -> dict:
    """Convert a friendly property spec into Notion's property schema.

    Accepted shapes:
      "title"                       → title prop
      "text"                        → rich_text
      "number"                      → number
      "date"                        → date
      "url" / "email" / "phone"     → url / email / phone_number
      "files"                       → files
      "checkbox"                    → checkbox
      "people"                      → people
      ["select", "A", "B", "C"]     → select with options A/B/C
      ["multi", "tag1", "tag2"]     → multi_select with options
      ["status", "Todo", "Doing", "Done"] → status
      {"type":"select","options":[{"name":"A","color":"red"}]} → raw passthrough
    """
    if isinstance(spec, dict) and "type" in spec:
        t = spec["type"]
        return {t: spec.get(t, {})}
    if isinstance(spec, str):
        s = spec.lower()
        m = {"title":"title","text":"rich_text","rich_text":"rich_text",
             "number":"number","date":"date","url":"url","email":"email",
             "phone":"phone_number","phone_number":"phone_number",
             "files":"files","checkbox":"checkbox","people":"people",
             "created_time":"created_time","last_edited_time":"last_edited_time"}
        if s in m:
            payload = {} if m[s] != "number" else {"format": "number"}
            return {m[s]: payload}
        return {"rich_text": {}}
    if isinstance(spec, (list, tuple)) and len(spec) >= 1:
        kind = str(spec[0]).lower()
        opts = list(spec[1:])
        colors = ["default","gray","brown","orange","yellow","green","blue","purple","pink","red"]
        options = [{"name": str(o), "color": colors[i % len(colors)]} for i, o in enumerate(opts)]
        if kind in ("select", "sel"):
            return {"select": {"options": options}}
        if kind in ("multi", "multi_select", "tags"):
            return {"multi_select": {"options": options}}
        if kind in ("status",):
            return {"status": {}}
    return {"rich_text": {}}


def notion_create_database(title: str, parent_id: str,
                           properties: dict,
                           icon: str = "",
                           is_inline: bool = True) -> str:
    """Create a Notion database under the given parent page.

    properties: dict of column name → spec. The 'Name' (title) column is added
    automatically. Examples:
      {
        "Name": "title",
        "City": "text",
        "Days": "number",
        "Date": "date",
        "Tags": ["multi", "美食", "景點", "交通"],
        "Status": ["select", "想去", "已訂", "完成"],
        "URL": "url",
        "Photos": "files",
        "Done": "checkbox",
      }

    Returns the database id you can later pass to notion_add_database_row().
    Note: views (gallery / board / calendar) cannot be created via API; use the
    Notion UI's '+' button after the database appears."""
    if not parent_id:
        return "Error: parent_id is required to create a database."
    try:
        # Notion requires a title-typed property; add one if user didn't.
        props = {}
        has_title = False
        for name, spec in (properties or {}).items():
            built = _build_db_property(spec)
            if "title" in built and not has_title:
                has_title = True
            props[name] = built
        if not has_title:
            props = {"Name": {"title": {}}, **props}

        body = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": props,
            "is_inline": bool(is_inline),
        }
        if icon:
            body["icon"] = {"type": "emoji", "emoji": icon}
        db = _request("POST", "/databases", body)
        return (f"✅ Database created: {title}\n"
                f"🔗 {db.get('url','(no url)')}\n"
                f"database_id={db.get('id','')}\n"
                f"Tip: open the database in Notion and click '+ Add view' "
                f"to set up gallery / board / calendar views.")
    except Exception as e:
        return f"Notion database creation failed: {e}"


def _build_property_value(spec: dict, value):
    """Turn a Python value into the Notion property-value payload, given the
    column's schema (`spec` is one entry of database.properties)."""
    t = spec.get("type") if isinstance(spec, dict) else None
    if t == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)}}]}
    if t == "rich_text":
        return {"rich_text": _parse_rich_text(str(value))}
    if t == "number":
        try: return {"number": float(value)}
        except: return {"number": None}
    if t == "select":
        return {"select": {"name": str(value)}}
    if t == "status":
        return {"status": {"name": str(value)}}
    if t == "multi_select":
        if isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        return {"multi_select": [{"name": str(v)} for v in value or []]}
    if t == "date":
        if isinstance(value, dict):
            return {"date": value}
        return {"date": {"start": str(value)}}
    if t == "url":
        return {"url": str(value)}
    if t == "email":
        return {"email": str(value)}
    if t == "phone_number":
        return {"phone_number": str(value)}
    if t == "checkbox":
        return {"checkbox": bool(value)}
    if t == "files":
        items = value if isinstance(value, list) else [value]
        return {"files": [
            {"name": str(u).split("/")[-1] or "file",
             "external": {"url": str(u)}, "type": "external"}
            for u in items if u
        ]}
    # Fallback: rich text
    return {"rich_text": _parse_rich_text(str(value))}


def notion_add_database_row(database_id: str, properties: dict,
                            icon: str = "", cover_url: str = "",
                            children_markdown: str = "") -> str:
    """Add a row (page) to a database. Provide property values keyed by
    column name; types are auto-coerced based on the database schema.

    Example:
      notion_add_database_row("abc...", {
        "Name": "東京塔",
        "City": "Tokyo",
        "Tags": ["景點", "夜景"],
        "Status": "想去",
        "Date": "2026-05-10",
        "URL": "https://www.tokyotower.co.jp/",
      }, icon="🗼")"""
    try:
        db = _request("GET", f"/databases/{database_id}")
        schema = db.get("properties", {})
        notion_props = {}
        for name, val in (properties or {}).items():
            if name in schema:
                notion_props[name] = _build_property_value(schema[name], val)
            # Silently skip unknown columns rather than 400-erroring.
        body = {
            "parent": {"database_id": database_id},
            "properties": notion_props,
        }
        if icon:
            body["icon"] = {"type": "emoji", "emoji": icon}
        if cover_url and cover_url.startswith(("http://", "https://")):
            body["cover"] = {"type": "external", "external": {"url": cover_url}}
        if children_markdown:
            body["children"] = _markdown_to_blocks(children_markdown)
        page = _request("POST", "/pages", body)
        return f"✅ Row added to database {database_id[:8]} → {page.get('url','(no url)')}"
    except Exception as e:
        return f"Notion add row failed: {e}"


def notion_add_embed(page_id: str, url: str, caption: str = "") -> str:
    """Embed any URL into a Notion page (countdown widgets via indify.co,
    Google Maps, YouTube videos, Figma boards, weather widgets, etc.).
    Notion auto-detects providers it knows; everything else falls back to
    a generic iframe embed."""
    if not url or not url.startswith(("http://", "https://")):
        return "Error: url must be a public http(s) URL"
    try:
        block = {
            "object": "block", "type": "embed",
            "embed": {"url": url, "caption": _parse_rich_text(caption) if caption else []},
        }
        _request("PATCH", f"/blocks/{page_id}/children", {"children": [block]})
        return f"✅ Embed added to page {page_id[:8]}"
    except Exception as e:
        return f"Notion embed failed: {e}"


def notion_update_page_meta(page_id: str, icon: str = "",
                            cover_url: str = "", title: str = "") -> str:
    """Set/update a page's emoji icon, cover image, or title."""
    try:
        body = {}
        if icon:
            body["icon"] = {"type": "emoji", "emoji": icon}
        if cover_url and cover_url.startswith(("http://", "https://")):
            body["cover"] = {"type": "external", "external": {"url": cover_url}}
        if title:
            body["properties"] = {"title": {"title": [
                {"type": "text", "text": {"content": title}},
            ]}}
        if not body:
            return "Error: nothing to update"
        _request("PATCH", f"/pages/{page_id}", body)
        bits = []
        if icon: bits.append(f"icon={icon}")
        if cover_url: bits.append("cover updated")
        if title: bits.append(f"title='{title}'")
        return f"✅ Updated page {page_id[:8]}: {', '.join(bits)}"
    except Exception as e:
        return f"Notion update failed: {e}"


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


def notion_list_pages_structured(limit: int = 100) -> list[dict]:
    """Return shared pages as plain dicts for the UI picker.
    Shape: [{id, title, url, parent_id, parent_type, icon}]"""
    body = {
        "filter": {"property": "object", "value": "page"},
        "page_size": min(max(int(limit or 100), 1), 100),
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    }
    data = _request("POST", "/search", body)
    out = []
    for r in data.get("results", []):
        title = "(untitled)"
        for prop in (r.get("properties") or {}).values():
            if prop.get("type") == "title":
                chunks = prop.get("title", [])
                title = "".join(c.get("plain_text", "") for c in chunks) or "(untitled)"
                break
        parent = r.get("parent") or {}
        icon_obj = r.get("icon") or {}
        icon = (icon_obj.get("emoji")
                or (icon_obj.get("external") or {}).get("url")
                or (icon_obj.get("file") or {}).get("url")
                or "")
        out.append({
            "id": r.get("id"),
            "title": title.strip(),
            "url": r.get("url", ""),
            "parent_id": parent.get("page_id") or parent.get("database_id") or "",
            "parent_type": parent.get("type", ""),
            "icon": icon if isinstance(icon, str) and icon.startswith(("http", "data:")) is False else "",
            "last_edited": r.get("last_edited_time", ""),
        })
    return out


def notion_add_callout(page_id: str, text: str, emoji: str = "💡",
                       color: str = "blue_background") -> str:
    """Append a single callout block (emoji + colored background)."""
    try:
        block = {
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": _parse_rich_text(text),
                "icon": {"type": "emoji", "emoji": emoji or "💡"},
                "color": color or "blue_background",
            },
        }
        _request("PATCH", f"/blocks/{page_id}/children", {"children": [block]})
        return f"✅ Callout added to page {page_id[:8]}"
    except Exception as e:
        return f"Notion callout failed: {e}"


def notion_add_image(page_id: str, image_url: str, caption: str = "") -> str:
    """Embed an external image (must be a publicly reachable URL).
    Notion does NOT accept localhost / private URLs — use a public host."""
    if not image_url or not image_url.startswith(("http://", "https://")):
        return "Error: image_url must be a public http(s) URL"
    try:
        block = {
            "object": "block", "type": "image",
            "image": {
                "type": "external",
                "external": {"url": image_url},
                "caption": _parse_rich_text(caption) if caption else [],
            },
        }
        _request("PATCH", f"/blocks/{page_id}/children", {"children": [block]})
        return f"✅ Image embedded in page {page_id[:8]}"
    except Exception as e:
        return f"Notion image embed failed: {e}"


def notion_add_code(page_id: str, code: str, language: str = "python",
                    caption: str = "") -> str:
    """Append a code block with syntax highlighting."""
    try:
        block = {
            "object": "block", "type": "code",
            "code": {
                "rich_text": _plain_chunks(code),
                "language": _normalize_lang(language),
                "caption": _parse_rich_text(caption) if caption else [],
            },
        }
        _request("PATCH", f"/blocks/{page_id}/children", {"children": [block]})
        return f"✅ Code block ({language}) added to page {page_id[:8]}"
    except Exception as e:
        return f"Notion code block failed: {e}"


def notion_add_todos(page_id: str, items: list, checked: bool = False) -> str:
    """Append a list of to-do items. items can be strings or
    {text, checked} dicts."""
    try:
        children = []
        for it in items or []:
            if isinstance(it, dict):
                txt = str(it.get("text", "")).strip()
                chk = bool(it.get("checked", checked))
            else:
                txt = str(it).strip()
                chk = checked
            if not txt:
                continue
            children.append({
                "object": "block", "type": "to_do",
                "to_do": {"rich_text": _parse_rich_text(txt), "checked": chk},
            })
        if not children:
            return "Error: no items to add"
        _request("PATCH", f"/blocks/{page_id}/children", {"children": children})
        return f"✅ {len(children)} to-do items added to page {page_id[:8]}"
    except Exception as e:
        return f"Notion to-do failed: {e}"


def notion_get_page_content(page_id: str, max_blocks: int = 50) -> str:
    """Fetch a page's content blocks as plain text/markdown so the AI can
    read what's already on the page before deciding what to append."""
    try:
        data = _request("GET", f"/blocks/{page_id}/children?page_size={min(max(int(max_blocks),1),100)}")
        results = data.get("results", [])
        if not results:
            return "(empty page)"
        out = []
        for b in results:
            t = b.get("type")
            payload = b.get(t, {}) or {}
            chunks = payload.get("rich_text", [])
            text = "".join(c.get("plain_text", "") for c in chunks)
            if t == "heading_1":   out.append(f"# {text}")
            elif t == "heading_2": out.append(f"## {text}")
            elif t == "heading_3": out.append(f"### {text}")
            elif t == "bulleted_list_item": out.append(f"- {text}")
            elif t == "numbered_list_item": out.append(f"1. {text}")
            elif t == "to_do":
                box = "[x]" if payload.get("checked") else "[ ]"
                out.append(f"- {box} {text}")
            elif t == "quote":   out.append(f"> {text}")
            elif t == "callout":
                emo = payload.get("icon", {}).get("emoji", "💬")
                out.append(f"> [{emo}] {text}")
            elif t == "code":
                lang = payload.get("language", "")
                out.append(f"```{lang}\n{text}\n```")
            elif t == "divider": out.append("---")
            elif t == "image":
                url = (payload.get("external") or payload.get("file") or {}).get("url", "")
                out.append(f"![image]({url})")
            elif t == "table": out.append("(table — open in Notion to view)")
            else:
                if text: out.append(text)
        return "\n".join(out)
    except Exception as e:
        return f"Notion read failed: {e}"


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
        "description": (
            "Create a new Notion page. The 'content' field accepts rich markdown which is "
            "converted to native Notion blocks: # / ## / ### headings, **bold**, *italic*, "
            "`inline code`, ~~strikethrough~~, [links](url), - bullets, 1. numbered, "
            "- [ ] / - [x] to-dos, > quotes, > [!tip] / [!warning] / [!note] callouts, "
            "```lang\\ncode\\n``` code blocks, --- dividers, ![alt](url) images, "
            "and | markdown | tables |. Optionally set an emoji 'icon' and a 'cover_url' "
            "(public image URL) for a polished header — use these for travel plans, project "
            "pages, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title":     {"type": "string"},
                "content":   {"type": "string", "description": "Rich markdown — see description for supported syntax."},
                "parent_id": {"type": "string", "description": "Optional parent page ID"},
                "icon":      {"type": "string", "description": "Single emoji used as the page icon, e.g. '🌸'"},
                "cover_url": {"type": "string", "description": "Public http(s) image URL to use as the page cover."},
            },
            "required": ["title"],
        },
        "handler": lambda a: notion_create_page(a.get("title", ""), a.get("content", ""),
                                                    a.get("parent_id", ""),
                                                    a.get("icon", ""),
                                                    a.get("cover_url", "")),
    },
    "notion_create_database": {
        "description": (
            "Create a structured Notion database (table) under a parent page. Define columns "
            "via the 'properties' map; values can be simple strings ('title', 'text', 'number', "
            "'date', 'url', 'email', 'phone', 'files', 'checkbox', 'people') or arrays for "
            "select/multi-select/status: ['select', 'option1', 'option2'], "
            "['multi', 'tag1', 'tag2'], ['status', 'Todo', 'Doing', 'Done']. "
            "After it's created, populate rows with notion_add_database_row. "
            "NOTE: gallery / board / calendar VIEWS cannot be created via API — the user "
            "needs to click '+ Add view' in the Notion UI once."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title":      {"type": "string"},
                "parent_id":  {"type": "string", "description": "Page ID this database lives under"},
                "properties": {"type": "object",
                               "description": "{ColumnName: typeSpec, ...} — see description"},
                "icon":       {"type": "string", "description": "Optional emoji icon"},
                "is_inline":  {"type": "boolean", "default": True,
                               "description": "True = inline DB inside the page; False = full-page DB"},
            },
            "required": ["title", "parent_id", "properties"],
        },
        "handler": lambda a: notion_create_database(
            a.get("title", ""), a.get("parent_id", ""),
            a.get("properties", {}) or {},
            a.get("icon", ""),
            a.get("is_inline", True),
        ),
    },
    "notion_add_database_row": {
        "description": (
            "Add a row (page) to a Notion database. 'properties' maps column name → value. "
            "Types are auto-coerced from the database schema (number → number, multi_select → "
            "list of tag names, date → ISO string or {start, end} dict, etc.). Optional 'icon', "
            "'cover_url', and 'children_markdown' (for page body content)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id":       {"type": "string"},
                "properties":        {"type": "object"},
                "icon":              {"type": "string"},
                "cover_url":         {"type": "string"},
                "children_markdown": {"type": "string", "description": "Optional markdown body for the row's page"},
            },
            "required": ["database_id", "properties"],
        },
        "handler": lambda a: notion_add_database_row(
            a.get("database_id", ""), a.get("properties", {}) or {},
            a.get("icon", ""), a.get("cover_url", ""),
            a.get("children_markdown", ""),
        ),
    },
    "notion_add_embed": {
        "description": (
            "Embed any URL into a Notion page — works for indify.co widgets (countdown, "
            "weather, clock, progress bar), Google Maps, YouTube, Figma, Twitter/X posts, "
            "GitHub gists, etc. Use this to add the live widgets that make travel/project pages "
            "feel alive."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "url":     {"type": "string"},
                "caption": {"type": "string", "default": ""},
            },
            "required": ["page_id", "url"],
        },
        "handler": lambda a: notion_add_embed(a.get("page_id",""), a.get("url",""), a.get("caption","")),
    },
    "notion_update_page_meta": {
        "description": "Set/update an existing page's emoji icon, cover image URL, or title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id":   {"type": "string"},
                "icon":      {"type": "string", "description": "Emoji icon"},
                "cover_url": {"type": "string", "description": "Public http(s) image URL"},
                "title":     {"type": "string"},
            },
            "required": ["page_id"],
        },
        "handler": lambda a: notion_update_page_meta(
            a.get("page_id", ""), a.get("icon", ""),
            a.get("cover_url", ""), a.get("title", ""),
        ),
    },
    "notion_append_to_page": {
        "description": (
            "Append rich markdown content to an existing Notion page. Same markdown features "
            "as notion_create_page (headings, lists, to-dos, quotes, callouts, code blocks, "
            "dividers, images, tables). Use it when the user wants to add content to a page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "content": {"type": "string", "description": "Rich markdown content."},
            },
            "required": ["page_id", "content"],
        },
        "handler": lambda a: notion_append_to_page(a.get("page_id", ""), a.get("content", "")),
    },
    "notion_add_callout": {
        "description": "Append a callout block (emoji + colored background) to a page. Good for highlights, tips, warnings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "text":    {"type": "string"},
                "emoji":   {"type": "string", "default": "💡"},
                "color":   {"type": "string",
                            "enum": ["default","gray_background","brown_background",
                                     "orange_background","yellow_background","green_background",
                                     "blue_background","purple_background","pink_background",
                                     "red_background"],
                            "default": "blue_background"},
            },
            "required": ["page_id", "text"],
        },
        "handler": lambda a: notion_add_callout(a.get("page_id",""), a.get("text",""),
                                                a.get("emoji","💡"), a.get("color","blue_background")),
    },
    "notion_add_image": {
        "description": (
            "Embed an external image (must be a publicly reachable http(s) URL) into a Notion page. "
            "Use this AFTER generate_image to put the generated image into Notion — pass the image URL "
            "(NOT a local /static/uploads path; that's only reachable on this machine)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id":   {"type": "string"},
                "image_url": {"type": "string", "description": "Public http(s) URL of the image."},
                "caption":   {"type": "string", "default": ""},
            },
            "required": ["page_id", "image_url"],
        },
        "handler": lambda a: notion_add_image(a.get("page_id",""), a.get("image_url",""),
                                              a.get("caption","")),
    },
    "notion_add_code": {
        "description": "Append a syntax-highlighted code block to a page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id":  {"type": "string"},
                "code":     {"type": "string"},
                "language": {"type": "string", "default": "python",
                             "description": "python, javascript, typescript, bash, sql, json, yaml, html, css, etc."},
                "caption":  {"type": "string", "default": ""},
            },
            "required": ["page_id", "code"],
        },
        "handler": lambda a: notion_add_code(a.get("page_id",""), a.get("code",""),
                                             a.get("language","python"), a.get("caption","")),
    },
    "notion_add_todos": {
        "description": "Append a list of to-do (checkbox) items to a page.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "items":   {"type": "array", "items": {"type": "string"},
                            "description": "List of to-do text items."},
                "checked": {"type": "boolean", "default": False},
            },
            "required": ["page_id", "items"],
        },
        "handler": lambda a: notion_add_todos(a.get("page_id",""), a.get("items",[]),
                                              bool(a.get("checked", False))),
    },
    "notion_get_page_content": {
        "description": (
            "Fetch the existing content of a Notion page as markdown so you can read what's "
            "already there before deciding what to append/modify."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id":    {"type": "string"},
                "max_blocks": {"type": "integer", "default": 50},
            },
            "required": ["page_id"],
        },
        "handler": lambda a: notion_get_page_content(a.get("page_id",""),
                                                     int(a.get("max_blocks", 50))),
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
