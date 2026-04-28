"""Render docs/ARCHITECTURE.md to PDF.

Mermaid blocks are pre-rendered to PNG via kroki.io so the final HTML has
zero async work — Chrome can print it immediately and we don't fight a race
with mermaid's ESM bundle. Other code blocks render as plain monospace.

Run:  python docs/build_architecture_pdf.py
Output: docs/ARCHITECTURE.pdf
"""
import base64
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MD = ROOT / "ARCHITECTURE.md"
HTML = ROOT / "_arch_render.html"
PDF = ROOT / "ARCHITECTURE.pdf"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome():
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    chrome = shutil.which("chrome") or shutil.which("msedge")
    if chrome:
        return chrome
    raise RuntimeError("No Chrome/Edge found.")


def kroki_svg(diagram: str) -> str:
    """Render a mermaid diagram to SVG via a public renderer.

    Tries kroki.io first (POST), then falls back to mermaid.ink's GET API.
    Both return SVG markup as a string.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (architecture-pdf-builder)",
        "Accept": "image/svg+xml",
    }
    # 1. kroki.io POST
    try:
        req = urllib.request.Request(
            "https://kroki.io/mermaid/svg",
            data=diagram.encode("utf-8"),
            headers={**headers, "Content-Type": "text/plain"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            svg = resp.read().decode("utf-8")
    except Exception as e1:
        # 2. mermaid.ink fallback (GET, base64url-encoded source)
        b64 = base64.urlsafe_b64encode(diagram.encode("utf-8")).decode().rstrip("=")
        url = f"https://mermaid.ink/svg/{b64}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            svg = resp.read().decode("utf-8")

    svg = re.sub(r"<\?xml[^?]+\?>", "", svg).strip()
    return svg


def md_to_html(md_text: str) -> str:
    """Lightweight markdown → HTML (handles the subset ARCHITECTURE.md uses)."""
    out = []
    lines = md_text.split("\n")
    i = 0
    in_list = False

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        m = re.match(r"^```(\w+)?\s*$", line)
        if m:
            flush_list()
            lang = m.group(1) or ""
            i += 1
            buf = []
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            body = "\n".join(buf)
            if lang.lower() == "mermaid":
                print(f"  rendering mermaid block ({len(body)} chars)…")
                try:
                    svg = kroki_svg(body)
                    out.append(f'<div class="mermaid">{svg}</div>')
                except Exception as e:
                    print(f"  ! kroki failed: {e}")
                    out.append(f'<pre><code>[mermaid render failed]\n'
                               f'{escape(body)}</code></pre>')
            else:
                out.append(f"<pre><code>{escape(body)}</code></pre>")
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            flush_list()
            level = len(m.group(1))
            text = inline(m.group(2))
            out.append(f"<h{level}>{text}</h{level}>")
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^---+\s*$", line):
            flush_list()
            out.append("<hr>")
            i += 1
            continue

        # Blockquote
        if line.startswith("> "):
            flush_list()
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
            i += 1
            continue

        # Table (very simple — header row then |---|, then rows)
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|", lines[i+1] or ""):
            flush_list()
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2  # skip separator
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            tbl = ["<table><thead><tr>"]
            tbl += [f"<th>{inline(c)}</th>" for c in header_cells]
            tbl.append("</tr></thead><tbody>")
            for r in rows:
                tbl.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            tbl.append("</tbody></table>")
            out.append("".join(tbl))
            continue

        # Bullet list item
        m = re.match(r"^[-*]\s+(.+)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        # Blank line ends a paragraph/list
        if not line.strip():
            flush_list()
            i += 1
            continue

        # Plain paragraph: gather contiguous non-blank, non-special lines
        flush_list()
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and \
                not re.match(r"^(#{1,6}\s|```|---+\s*$|>\s|[-*]\s|\|)", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")

    flush_list()
    return "\n".join(out)


def escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def inline(s: str) -> str:
    """Inline markdown: code spans, bold, links."""
    s = escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Architecture</title>
<style>
  @page { size: A4; margin: 16mm 14mm; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Segoe UI", "Microsoft JhengHei", -apple-system, sans-serif;
    font-size: 10.5pt;
    line-height: 1.45;
    color: #1a1a1a;
  }
  h1 { font-size: 20pt; margin: 0 0 6pt; border-bottom: 2px solid #6366f1;
       padding-bottom: 4pt; page-break-after: avoid; }
  h2 { font-size: 14pt; margin: 16pt 0 6pt; color: #4338ca;
       page-break-after: avoid; }
  h3 { font-size: 12pt; margin: 12pt 0 4pt; page-break-after: avoid; }
  p, li { margin: 4pt 0; }
  ul { margin: 6pt 0 6pt 20pt; }
  blockquote { margin: 6pt 0; padding: 6pt 12pt; background: #f3f4ff;
               border-left: 3px solid #6366f1; color: #4b4b6b; }
  code { font-family: "Consolas", "Cascadia Mono", monospace;
         font-size: 9.5pt;
         background: #f3f3f7; padding: 1px 4px; border-radius: 3px; }
  pre {
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 8pt;
    line-height: 1.3;
    background: #f6f6fa;
    border: 1px solid #e2e2ea;
    border-radius: 6px;
    padding: 10pt;
    overflow-x: auto;
    page-break-inside: avoid;
    white-space: pre;
  }
  pre code { background: transparent; padding: 0; font-size: inherit; }
  .mermaid { text-align: center; margin: 12pt 0; page-break-inside: avoid; }
  .mermaid svg { max-width: 100%; height: auto; }
  hr { border: none; border-top: 1px solid #d4d4dc; margin: 16pt 0; }
  table { border-collapse: collapse; width: 100%; margin: 8pt 0;
          font-size: 10pt; page-break-inside: avoid; }
  th, td { border: 1px solid #d4d4dc; padding: 4pt 8pt; vertical-align: top; }
  th { background: #f3f4ff; }
  a { color: #4338ca; text-decoration: none; }
</style>
</head>
<body>
__BODY__
</body>
</html>
"""


def main():
    if not MD.exists():
        print(f"ERROR: {MD} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {MD.name}…")
    md = MD.read_text(encoding="utf-8")
    print("Converting markdown → HTML (with kroki for mermaid)…")
    body = md_to_html(md)

    html = HTML_TEMPLATE.replace("__BODY__", body)
    HTML.write_text(html, encoding="utf-8")
    print(f"Wrote {HTML.name} ({len(html):,} bytes)")

    chrome = find_chrome()
    print(f"Browser: {chrome}")

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        "--default-background-color=00000000",
        f"--print-to-pdf={PDF}",
        HTML.as_uri(),
    ]
    t = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    print(f"Took {time.time()-t:.1f}s. exit={res.returncode}")
    if res.stderr.strip():
        # Chrome writes the success message to stderr too.
        print("stderr:", res.stderr.strip()[:300])

    if PDF.exists() and PDF.stat().st_size > 1000:
        print(f"\nOK -> {PDF.name} ({PDF.stat().st_size:,} bytes)")
    else:
        print("ERROR: PDF not generated", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
