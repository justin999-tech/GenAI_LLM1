"""Filesystem tools — sandboxed to safe_workspace/."""
import os
import re

_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "safe_workspace")
os.makedirs(_ROOT, exist_ok=True)


def _safe_path(relpath: str) -> str:
    p = os.path.normpath(os.path.join(_ROOT, relpath.lstrip("/\\")))
    if not p.startswith(_ROOT):
        raise ValueError(f"Path traversal not allowed: {relpath}")
    return p


def read_file(path: str, max_bytes: int = 10240) -> str:
    try:
        full = _safe_path(path)
        if not os.path.exists(full):
            return f"File not found: {path}"
        size = os.path.getsize(full)
        with open(full, "rb") as f:
            data = f.read(max_bytes)
        text = data.decode("utf-8", errors="replace")
        suffix = "" if size <= max_bytes else f"\n... [truncated, total {size} bytes]"
        return f"```\n{text}{suffix}\n```"
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    try:
        full = _safe_path(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def list_directory(path: str = ".") -> str:
    try:
        full = _safe_path(path)
        if not os.path.isdir(full):
            return f"Not a directory: {path}"
        entries = []
        for name in sorted(os.listdir(full)):
            fp = os.path.join(full, name)
            kind = "📁" if os.path.isdir(fp) else "📄"
            size = os.path.getsize(fp) if os.path.isfile(fp) else "-"
            entries.append(f"{kind} {name} ({size} bytes)" if isinstance(size, int) else f"{kind} {name}/")
        if not entries:
            return f"(empty directory: {path})"
        return f"Contents of {path}:\n" + "\n".join(entries)
    except Exception as e:
        return f"Error: {e}"


def search_files(pattern: str, path: str = ".", max_results: int = 20) -> str:
    try:
        full = _safe_path(path)
        if not os.path.isdir(full):
            return f"Not a directory: {path}"
        rx = re.compile(pattern, re.IGNORECASE)
        hits = []
        for root, _dirs, files in os.walk(full):
            for f in files:
                if rx.search(f):
                    rel = os.path.relpath(os.path.join(root, f), _ROOT)
                    hits.append(rel)
                    if len(hits) >= max_results:
                        break
            if len(hits) >= max_results:
                break
        if not hits:
            return f"No files matching {pattern!r}"
        return f"Found {len(hits)} file(s):\n" + "\n".join(hits)
    except Exception as e:
        return f"Error: {e}"


TOOLS = {
    "read_file": {
        "description": "Read a text file from the sandbox workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 10240}},
            "required": ["path"],
        },
        "handler": lambda a: read_file(a.get("path", ""), int(a.get("max_bytes", 10240))),
    },
    "write_file": {
        "description": "Write a text file to the sandbox workspace. Creates parent dirs.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        "handler": lambda a: write_file(a.get("path", ""), a.get("content", "")),
    },
    "list_directory": {
        "description": "List files and folders in the sandbox workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "required": [],
        },
        "handler": lambda a: list_directory(a.get("path", ".")),
    },
    "search_files": {
        "description": "Search filenames by regex pattern in the sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["pattern"],
        },
        "handler": lambda a: search_files(a.get("pattern", ""),
                                            a.get("path", "."),
                                            int(a.get("max_results", 20))),
    },
}
