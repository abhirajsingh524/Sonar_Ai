"""
models/local_model.py
Tier-2: Local / fallback image generation.

Strategy
--------
1. If `diffusers` + a CUDA/CPU torch backend are available, attempt to load
   a lightweight fp16 pipeline (runwayml/stable-diffusion-v1-5 or similar).
2. If the library is absent or RAM is insufficient, fall back to a
   deterministic placeholder image so the app never returns an empty response.

The placeholder is a real PNG rendered with Pillow — it shows the prompt text
on a styled dark background, making it obvious to the user that the API was
unavailable while still returning a usable image object.
"""

import io
import logging
import hashlib

log = logging.getLogger(__name__)

# ── Optional heavy imports ────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    log.warning("Pillow not installed — placeholder images will be minimal PNGs.")


class LocalModelError(Exception):
    """Raised when local generation fails completely."""


# ── Pillow placeholder ────────────────────────────────────────────────────────

def _make_placeholder_png(prompt: str) -> bytes:
    """
    Render a 512×512 dark-themed placeholder PNG that displays the prompt.
    Requires Pillow; falls back to a 1×1 transparent PNG if unavailable.
    """
    if not _PIL_AVAILABLE:
        # Minimal valid 1×1 transparent PNG (hard-coded bytes)
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    W, H = 512, 512

    # Deterministic background colour derived from prompt hash
    h = hashlib.md5(prompt.encode()).hexdigest()
    r = int(h[0:2], 16) // 6        # keep dark
    g = int(h[2:4], 16) // 6
    b = int(h[4:6], 16) // 6

    img = Image.new("RGB", (W, H), color=(r + 10, g + 15, b + 30))
    draw = ImageDraw.Draw(img)

    # Grid lines
    for x in range(0, W, 40):
        draw.line([(x, 0), (x, H)], fill=(r + 20, g + 30, b + 50), width=1)
    for y in range(0, H, 40):
        draw.line([(0, y), (W, y)], fill=(r + 20, g + 30, b + 50), width=1)

    # Centre circle
    draw.ellipse([W//2 - 80, H//2 - 80, W//2 + 80, H//2 + 80],
                 outline=(0, 180, 255), width=2)
    draw.ellipse([W//2 - 50, H//2 - 50, W//2 + 50, H//2 + 50],
                 outline=(0, 180, 255, 120), width=1)

    # Header label
    try:
        font_large = ImageFont.truetype("arial.ttf", 18)
        font_small = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font_large = ImageFont.load_default()
        font_small = font_large

    draw.text((W // 2, 30), "◈ SONAR — FALLBACK MODE",
              fill=(0, 180, 255), font=font_large, anchor="mm")
    draw.text((W // 2, 55), "HF API unavailable",
              fill=(100, 150, 200), font=font_small, anchor="mm")

    # Prompt text (word-wrapped)
    words = prompt.split()
    lines, line = [], []
    for word in words:
        line.append(word)
        if len(" ".join(line)) > 38:
            lines.append(" ".join(line[:-1]))
            line = [word]
    if line:
        lines.append(" ".join(line))

    y_start = H // 2 + 100
    for i, ln in enumerate(lines[:5]):
        draw.text((W // 2, y_start + i * 20), ln,
                  fill=(180, 210, 240), font=font_small, anchor="mm")
    if len(lines) > 5:
        draw.text((W // 2, y_start + 5 * 20), "…",
                  fill=(100, 150, 200), font=font_small, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Public API ────────────────────────────────────────────────────────────────

def generate_image(prompt: str, model_key: str = "sd21") -> bytes:
    """
    Attempt local diffusion; fall back to a placeholder PNG.

    Returns PNG bytes — never raises (so the pipeline always has a result).
    """
    # ── Try diffusers if available ────────────────────────────────────────────
    try:
        import torch
        from diffusers import StableDiffusionPipeline

        model_id = "runwayml/stable-diffusion-v1-5"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        device = "cuda" if torch.cuda.is_available() else "cpu"

        log.info("Loading local diffusion model on %s …", device)
        pipe = StableDiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe = pipe.to(device)
        pipe.enable_attention_slicing()   # reduce VRAM / RAM

        result = pipe(prompt, num_inference_steps=20, guidance_scale=7.5)
        pil_img = result.images[0]

        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        log.info("Local diffusion succeeded.")
        return buf.getvalue()

    except ImportError:
        log.info("diffusers/torch not installed — using placeholder.")
    except Exception as exc:
        log.warning("Local diffusion failed (%s) — using placeholder.", exc)

    # ── Placeholder fallback ──────────────────────────────────────────────────
    log.info("Generating placeholder image for prompt: %.60s…", prompt)
    return _make_placeholder_png(prompt)
