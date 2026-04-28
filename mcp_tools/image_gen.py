"""Image generation via Pollinations.ai (free, no API key).

Uses FLUX.1 — currently the best-quality free open-source text-to-image
model (same family as Midjourney/SDXL successors). Pollinations also
exposes 'flux-realism' (photo-tuned) and 'turbo' (fast/lower quality).
"""
import os
import time
import urllib.parse
import urllib.request


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


_STYLE_HINTS = {
    "realistic": ", photorealistic, ultra detailed, sharp focus, 8k, professional photography",
    "anime": ", anime style, vibrant colors, detailed, studio quality",
    "cyberpunk": ", cyberpunk, neon lights, futuristic, cinematic",
    "oil-painting": ", oil painting, brush strokes, classical, museum quality",
    "watercolor": ", watercolor painting, soft colors, artistic",
    "3d-render": ", 3d render, octane render, cinematic lighting, ultra detailed",
    "sketch": ", pencil sketch, hand-drawn, fine lines",
    "digital-art": ", digital art, trending on artstation, masterpiece",
}

# Best-quality model is "flux" (FLUX.1). 'flux-realism' is photo-tuned;
# 'turbo' is fast but visibly worse.
_DEFAULT_MODEL = "flux"


def generate_image(prompt: str, width: int = 1024, height: int = 1024,
                   style: str = "realistic", seed: int = None,
                   negative_prompt: str = "",
                   model: str = _DEFAULT_MODEL,
                   enhance: bool = True) -> str:
    """Generate via Pollinations.ai (FLUX.1). Returns the [IMAGE] marker
    the frontend uses to render an inline preview, plus a tiny metadata
    footer for the LLM's context."""
    p = (prompt or "").strip()
    if not p:
        return "Error: prompt is empty"

    full_prompt = p + _STYLE_HINTS.get(style, "")
    if negative_prompt:
        full_prompt += f" --no {negative_prompt}"

    # Auto-pick the photo-tuned variant for realistic style.
    chosen_model = model
    if model == _DEFAULT_MODEL and style == "realistic":
        chosen_model = "flux-realism"

    params = {
        "width": width,
        "height": height,
        "model": chosen_model,
        "nologo": "true",
    }
    if enhance:
        # Pollinations runs the prompt through an LLM rewriter for
        # noticeably better composition / lighting.
        params["enhance"] = "true"
    if seed is not None:
        params["seed"] = seed
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(full_prompt[:500])
           + "?" + urllib.parse.urlencode(params))

    # FLUX takes longer than turbo (10–30s typical), so timeout up to 120s.
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
    except Exception as e:
        return f"Image generation failed: {e}"

    # Use the actual returned format so we keep PNG quality when offered.
    ext = "png" if "png" in ctype else "jpg"
    fname = f"gen_{int(time.time() * 1000)}.{ext}"
    path = os.path.join(UPLOAD_DIR, fname)
    public_url = f"/static/uploads/{fname}"
    with open(path, "wb") as f:
        f.write(data)

    return (f"[IMAGE]{public_url}[/IMAGE]\n"
            f"Generated image saved to {public_url}\n"
            f"Prompt: {p}\n"
            f"Model: {chosen_model}, Style: {style}, Size: {width}x{height}")


TOOLS = {
    "generate_image": {
        "description": (
            "Generate a high-quality AI image from a text prompt using FLUX.1 "
            "(via Pollinations.ai). Returns an image URL the user can see "
            "directly. Prefer English prompts for best results. Default size "
            "is 1024x1024 — only request smaller if the user explicitly asks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What to draw, in English for best results."},
                "width":  {"type": "integer", "default": 1024,
                           "description": "Width in px. Use 1024 for square, 1280 for landscape, 768 for portrait."},
                "height": {"type": "integer", "default": 1024,
                           "description": "Height in px."},
                "style": {
                    "type": "string",
                    "enum": list(_STYLE_HINTS.keys()),
                    "default": "realistic",
                },
                "model": {
                    "type": "string",
                    "enum": ["flux", "flux-realism", "flux-anime", "flux-3d", "turbo"],
                    "default": "flux",
                    "description": "FLUX is best quality. 'turbo' is faster but lower quality.",
                },
                "seed": {"type": "integer", "description": "Optional seed for reproducible generation"},
                "negative_prompt": {"type": "string", "description": "What NOT to include"},
            },
            "required": ["prompt"],
        },
        "handler": lambda a: generate_image(
            a.get("prompt", ""),
            int(a.get("width", 1024)),
            int(a.get("height", 1024)),
            a.get("style", "realistic"),
            a.get("seed"),
            a.get("negative_prompt", ""),
            a.get("model", _DEFAULT_MODEL),
        ),
    },
}
