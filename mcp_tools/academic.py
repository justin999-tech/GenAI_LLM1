"""arXiv and Wikipedia search tools."""
import re
import ssl
import urllib.parse
import urllib.request

# Tolerant SSL context for environments with missing root certs (common on Windows).
_SSL_CTX = ssl.create_default_context()
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE


def _http_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Lab2-Chatbot/2.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return r.read().decode("utf-8", errors="replace")


def arxiv_search(query: str, max_results: int = 5) -> str:
    """Search arXiv.org for papers."""
    try:
        url = ("http://export.arxiv.org/api/query?"
               + urllib.parse.urlencode({
                   "search_query": f"all:{query}",
                   "start": 0,
                   "max_results": max_results,
                   "sortBy": "relevance",
                   "sortOrder": "descending",
               }))
        xml = _http_text(url, timeout=20)
        # Parse minimal Atom XML
        entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
        if not entries:
            return f"No arXiv papers found for {query!r}"

        out = []
        for e in entries[:max_results]:
            title = re.search(r"<title>(.*?)</title>", e, re.DOTALL)
            summary = re.search(r"<summary>(.*?)</summary>", e, re.DOTALL)
            link = re.search(r'<id>(.*?)</id>', e)
            published = re.search(r"<published>(.*?)</published>", e)
            authors = re.findall(r"<name>(.*?)</name>", e)
            t = title.group(1).strip().replace("\n", " ") if title else "?"
            t = re.sub(r"\s+", " ", t)
            s = summary.group(1).strip().replace("\n", " ") if summary else ""
            s = re.sub(r"\s+", " ", s)[:400]
            l = link.group(1).strip() if link else ""
            p = published.group(1)[:10] if published else "?"
            a = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
            out.append(f"📄 {t}\n   {a} · {p}\n   {s}…\n   {l}")
        return "\n\n".join(out)
    except Exception as e:
        return f"arXiv search failed: {e}"


def wikipedia_search(query: str, lang: str = "en") -> str:
    """Search Wikipedia and return article extract."""
    try:
        # Step 1: search for page title
        search_url = (f"https://{lang}.wikipedia.org/w/api.php?"
                      + urllib.parse.urlencode({
                          "action": "query",
                          "list": "search",
                          "srsearch": query,
                          "format": "json",
                          "srlimit": 1,
                      }))
        import json
        search_data = json.loads(_http_text(search_url))
        results = search_data.get("query", {}).get("search", [])
        if not results:
            return f"No Wikipedia article for {query!r}"
        title = results[0]["title"]

        # Step 2: get extract
        extract_url = (f"https://{lang}.wikipedia.org/w/api.php?"
                       + urllib.parse.urlencode({
                           "action": "query",
                           "prop": "extracts",
                           "exintro": "1",
                           "explaintext": "1",
                           "titles": title,
                           "format": "json",
                       }))
        ex_data = json.loads(_http_text(extract_url))
        pages = ex_data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        extract = page.get("extract", "(no extract)")
        url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}"
        return f"# {title}\n\n{extract[:2000]}\n\n🔗 {url}"
    except Exception as e:
        return f"Wikipedia lookup failed: {e}"


TOOLS = {
    "arxiv_search": {
        "description": "Search arXiv.org for academic papers. Returns titles, authors, abstracts, links.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "default": 5}},
            "required": ["query"],
        },
        "handler": lambda a: arxiv_search(a.get("query", ""), int(a.get("max_results", 5))),
    },
    "wikipedia_search": {
        "description": "Search Wikipedia and return the article intro paragraph.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "lang": {"type": "string", "default": "en"}},
            "required": ["query"],
        },
        "handler": lambda a: wikipedia_search(a.get("query", ""), a.get("lang", "en")),
    },
}
