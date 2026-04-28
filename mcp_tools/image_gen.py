"""Image generation via Pollinations.ai (free, no API key)."""
import os
import time
import urllib.parse
import urllib.request


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


_STYLE_HINTS = {
    "realistic": ", photorealistic, ultra detailed, 8k",
    "anime": ", anime style, vibrant colors, detailed",
    "cyberpunk": ", cyberpunk, neon lights, futuristic",
    "oil-painting": ", oil painting, brush strokes, classical",
    "watercolor": ", watercolor painting, soft colors",
    "3d-render": ", 3d render, octane render, cinematic lighting",
    "sketch": ", pencil sketch, hand-drawn",
    "digital-art": ", digital art, trending on artstation",
}


def generate_image(prompt: str, width: int = 768, height: int = 512,
                   style: str = "realistic", seed: int = None,
                   negative_prompt: str = "") -> str:
    """Generate via Pollinations.ai. Returns markdown image string + path."""
    p = (prompt or "").strip()
    if not p:
        return "Error: prompt is empty"

    full_prompt = p + _STYLE_HINTS.get(style, "")
    if negative_prompt:
        full_prompt += f" --no {negative_prompt}"

    params = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(full_prompt[:500])
           + "?" + urllib.parse.urlencode(params))

    fname = f"gen_{int(time.time() * 1000)}.jpg"
    path = os.path.join(UPLOAD_DIR, fname)
    public_url = f"/static/uploads/{fname}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(path, "wb") as f:
            f.write(data)
    except Exception as e:
        return f"Image generation failed: {e}"

    # Return a special marker that the agentic loop / frontend can recognise.
    return (f"[IMAGE]{public_url}[/IMAGE]\n"
            f"Generated image saved to {public_url}\n"
            f"Prompt: {p}\n"
            f"Style: {style}, Size: {width}x{height}")


TOOLS = {
    "generate_image": {
        "description": "Generate an AI image from a text prompt using Pollinations.ai. Returns an image URL the user can see directly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What to draw, in English for best results."},
                "width": {"type": "integer", "default": 768},
                "height": {"type": "integer", "default": 512},
                "style": {
                    "type": "string",
                    "enum": list(_STYLE_HINTS.keys()),
                    "default": "realistic",
                },
                "seed": {"type": "integer", "description": "Optional seed for reproducible generation"},
                "negative_prompt": {"type": "string", "description": "What NOT to include"},
            },
            "required": ["prompt"],
        },
        "handler": lambda a: generate_image(
            a.get("prompt", ""),
            int(a.get("width", 768)),
            int(a.get("height", 512)),
            a.get("style", "realistic"),
            a.get("seed"),
            a.get("negative_prompt", ""),
        ),
    },
}
