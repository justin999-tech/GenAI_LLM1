"""Code interpreter — sandboxed Python execution.

Uses a subprocess with cleared environment, restricted module list, and
auto-captures matplotlib plots as PNG images.
"""
import os
import subprocess
import sys
import tempfile
import time
import re
import shutil

WORKSPACE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "code_workspace")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "static", "uploads")
os.makedirs(WORKSPACE, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


_BANNED_PATTERNS = [
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\bsocket\b",
    r"\b__import__\s*\(\s*['\"]os['\"]",
    r"\bopen\s*\(\s*['\"](?:\.\.|/|c:|d:)",  # absolute / parent paths
    r"\bshutil\.rmtree",
    r"\bos\.remove\b",
    r"\bos\.rmdir\b",
    r"\bos\.environ\b",
]


def _sanity_check(code: str) -> str | None:
    """Return error message if code looks dangerous, else None."""
    for pat in _BANNED_PATTERNS:
        if re.search(pat, code):
            return f"⚠️ Refused: code matches banned pattern: {pat}"
    return None


def execute_python(code: str, timeout: int = 12) -> str:
    """Run Python code in subprocess with timeout and matplotlib capture."""
    bad = _sanity_check(code)
    if bad:
        return bad

    # Wrap user code: redirect matplotlib figures to PNG files in workspace.
    figs_dir = os.path.join(WORKSPACE, f"run_{int(time.time() * 1000)}")
    os.makedirs(figs_dir, exist_ok=True)

    # Write the user code to a separate file, then a wrapper that loads it.
    user_code_path = os.path.join(figs_dir, "_user_code.py")
    with open(user_code_path, "w", encoding="utf-8") as f:
        f.write(code)

    wrapper = (
        "import sys, os\n"
        f"os.chdir({figs_dir!r})\n"
        "try:\n"
        "    import matplotlib\n"
        "    matplotlib.use('Agg')\n"
        "    import matplotlib.pyplot as plt\n"
        "except ImportError:\n"
        "    plt = None\n"
        "\n"
        f"with open({user_code_path!r}, 'r', encoding='utf-8') as _f:\n"
        "    _src = _f.read()\n"
        "exec(compile(_src, '<user>', 'exec'), {'__name__': '__main__'})\n"
        "\n"
        "if plt is not None:\n"
        "    for i, n in enumerate(plt.get_fignums()):\n"
        "        try:\n"
        "            plt.figure(n).savefig(f'fig_{i}.png', dpi=120, bbox_inches='tight')\n"
        "        except Exception as e:\n"
        "            print(f'[warn] save fig {i}: {e}', file=sys.stderr)\n"
    )
    script_path = os.path.join(figs_dir, "_run.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(wrapper)

    # Cleared environment: keep system essentials, drop GROQ/NOTION secrets.
    SECRET_KEYS = {"GROQ_API_KEY", "NOTION_TOKEN", "OPENAI_API_KEY",
                   "ANTHROPIC_API_KEY"}
    env = {k: v for k, v in os.environ.items() if k not in SECRET_KEYS}
    env["PYTHONIOENCODING"] = "utf-8"

    start = time.time()
    # Log details to help diagnose subprocess issues.
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "code_exec.log")
    with open(log_path, "a", encoding="utf-8") as lg:
        lg.write(f"[{time.strftime('%H:%M:%S')}] cmd={sys.executable!r} script={script_path}\n")
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", script_path],
            cwd=figs_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return f"⏱️ Timeout after {timeout}s. Code execution stopped."
    except Exception as e:
        return f"Execution error: {e}"
    duration = (time.time() - start) * 1000

    # Move generated figures to public uploads dir
    images = []
    for fname in sorted(os.listdir(figs_dir)):
        if fname.startswith("fig_") and fname.endswith(".png"):
            src = os.path.join(figs_dir, fname)
            new_name = f"code_{int(time.time() * 1000)}_{fname}"
            dst = os.path.join(UPLOAD_DIR, new_name)
            try:
                shutil.move(src, dst)
                images.append(f"/static/uploads/{new_name}")
            except Exception:
                pass

    # Clean up workspace dir
    try:
        shutil.rmtree(figs_dir, ignore_errors=True)
    except Exception:
        pass

    # Format result
    parts = [f"⚙️ Executed in {duration:.0f}ms (rc={rc})"]
    if stdout.strip():
        out_short = stdout if len(stdout) < 4000 else stdout[:4000] + "\n... [truncated]"
        parts.append(f"📤 stdout:\n```\n{out_short}\n```")
    if stderr.strip():
        err_short = stderr if len(stderr) < 1500 else stderr[:1500] + "\n... [truncated]"
        parts.append(f"⚠️ stderr:\n```\n{err_short}\n```")
    for img_url in images:
        parts.append(f"[IMAGE]{img_url}[/IMAGE]")
    if not stdout.strip() and not stderr.strip() and not images:
        parts.append("(no output)")
    return "\n\n".join(parts)


TOOLS = {
    "execute_python": {
        "description": "Execute Python code in a sandbox. Supports matplotlib (auto-captures plots), pandas, numpy, requests, etc. Use for data analysis, calculations, charts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "timeout": {"type": "integer", "default": 12},
            },
            "required": ["code"],
        },
        "handler": lambda a: execute_python(a.get("code", ""), int(a.get("timeout", 12))),
    },
}
