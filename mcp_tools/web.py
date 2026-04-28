"""Web/GitHub/YouTube tools."""
import json
import re
import urllib.parse
import urllib.request


def _http_json(url: str, headers: dict = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={**(headers or {}),
                                                  "User-Agent": "Lab2-Chatbot/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_text(url: str, headers: dict = None, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={**(headers or {}),
                                                  "User-Agent": "Lab2-Chatbot/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return its text content (HTML stripped)."""
    try:
        html = _http_text(url, timeout=20)
        # Strip scripts, styles, tags, normalize whitespace.
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated, total ~{len(text)} chars]"
        return text
    except Exception as e:
        return f"Failed to fetch {url}: {e}"


def github_search_repos(query: str, max_results: int = 5) -> str:
    """Search GitHub repositories (no auth needed for public search)."""
    try:
        url = ("https://api.github.com/search/repositories?"
               + urllib.parse.urlencode({"q": query, "per_page": max_results}))
        data = _http_json(url)
        items = data.get("items", [])
        if not items:
            return f"No repos found for {query!r}"
        out = []
        for r in items[:max_results]:
            out.append(
                f"⭐ {r.get('stargazers_count', 0):,} · {r['full_name']}\n"
                f"   {r.get('description') or '(no description)'}\n"
                f"   {r['html_url']} · {r.get('language') or '?'}"
            )
        return "\n\n".join(out)
    except Exception as e:
        return f"GitHub search failed: {e}"


def github_read_file(repo: str, path: str, branch: str = "main") -> str:
    """Read a file from a public GitHub repo (no auth)."""
    try:
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        text = _http_text(url, timeout=20)
        if len(text) > 8000:
            text = text[:8000] + f"\n... [truncated, total {len(text)} chars]"
        return f"# {repo}/{path} (branch: {branch})\n```\n{text}\n```"
    except Exception as e:
        return f"Failed: {e}"


def youtube_transcript(video_url_or_id: str, lang: str = "en") -> str:
    """Fetch a YouTube video transcript without youtube-transcript-api package.
    Uses the timedtext endpoint (no auth, but only works for videos with captions)."""
    try:
        # Extract video ID
        vid = video_url_or_id
        m = re.search(r"(?:v=|youtu\.be/|/embed/|/watch\?v=)([\w-]{11})", video_url_or_id)
        if m:
            vid = m.group(1)

        # Try multiple approaches: scrape watch page for caption track URL.
        watch_html = _http_text(f"https://www.youtube.com/watch?v={vid}", timeout=20)
        m = re.search(r'"captionTracks":(\[[^\]]+\])', watch_html)
        if not m:
            return f"No captions available for video {vid}"
        tracks = json.loads(m.group(1))
        # Pick preferred lang or first.
        track = next((t for t in tracks if t.get("languageCode", "").startswith(lang)), tracks[0])
        track_url = track["baseUrl"].replace("\\u0026", "&")
        xml = _http_text(track_url, timeout=20)
        text_chunks = re.findall(r"<text[^>]*>(.*?)</text>", xml, re.DOTALL)
        # Decode HTML entities
        import html as html_mod
        text = " ".join(html_mod.unescape(re.sub(r"<[^>]+>", "", t)) for t in text_chunks)
        text = re.sub(r"\s+", " ", text).strip()
        title_m = re.search(r'"title":"([^"]+)"', watch_html)
        title = title_m.group(1) if title_m else f"YouTube {vid}"
        if len(text) > 6000:
            text = text[:6000] + f"\n... [truncated, total ~{len(text)} chars]"
        return f"# {title}\n\n{text}"
    except Exception as e:
        return f"Transcript failed: {e}"


TOOLS = {
    "fetch_url": {
        "description": "Fetch a URL and return its text content (HTML tags stripped). Use this to read any web page.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 4000}},
            "required": ["url"],
        },
        "handler": lambda a: fetch_url(a.get("url", ""), int(a.get("max_chars", 4000))),
    },
    "github_search_repos": {
        "description": "Search public GitHub repositories. Returns top matches with stars, description, language.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
            "required": ["query"],
        },
        "handler": lambda a: github_search_repos(a.get("query", ""), int(a.get("max_results", 5))),
    },
    "github_read_file": {
        "description": "Read a file from a public GitHub repo. e.g. repo='facebook/react', path='README.md'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name"},
                "path": {"type": "string"},
                "branch": {"type": "string", "default": "main"},
            },
            "required": ["repo", "path"],
        },
        "handler": lambda a: github_read_file(a.get("repo", ""), a.get("path", ""),
                                                 a.get("branch", "main")),
    },
    "youtube_transcript": {
        "description": "Fetch a YouTube video's transcript/captions. Pass URL or 11-char video ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "video_url_or_id": {"type": "string"},
                "lang": {"type": "string", "default": "en", "description": "Language prefix, e.g. 'en' or 'zh'"},
            },
            "required": ["video_url_or_id"],
        },
        "handler": lambda a: youtube_transcript(a.get("video_url_or_id", ""),
                                                  a.get("lang", "en")),
    },
}
