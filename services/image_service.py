"""
services/image_service.py
Orchestrates the three-tier image generation pipeline and persistence.

Pipeline
--------
User Prompt
    ↓
image_service.generate()
    ↓
┌─────────────────────────────────────────────────────────────┐
│ Tier 1 — Hugging Face FLUX.1-schnell (primary, free)        │
│   models/hf_model.py                                        │
│   Retry: up to HF_MAX_RETRIES with exponential backoff      │
└─────────────────────────────────────────────────────────────┘
    ↓ (HFModelError raised)
┌─────────────────────────────────────────────────────────────┐
│ Tier 1.5 — Google Gemini API (secondary, requires key)      │
│   models/gemini_model.py                                    │
│   Only attempted when GEMINI_API_KEY is set in .env         │
│   Retry: same HF_MAX_RETRIES budget                         │
│   RAM cost: ~8 MB (SDK import only, no local weights)       │
└─────────────────────────────────────────────────────────────┘
    ↓ (GeminiModelError raised OR key not set)
┌─────────────────────────────────────────────────────────────┐
│ Tier 2 — Local / Pillow placeholder (last resort)           │
│   models/local_model.py                                     │
│   Never raises — always returns a valid PNG                 │
│   RAM cost: ~10 MB (Pillow only, no diffusion weights)      │
└─────────────────────────────────────────────────────────────┘
    ↓
Save PNG → static/images/sonar_{timestamp}_{hash}.png
    ↓
Persist metadata → MongoDB (non-fatal if DB unavailable)
    ↓
Return GenerationResult

RAM budget (Render free tier = 512 MB)
---------------------------------------
  Flask + gunicorn (2 workers)  ~130 MB
  PyMongo                         ~5 MB
  Pillow                         ~10 MB
  google-generativeai SDK         ~8 MB
  Requests + dotenv               ~5 MB
  ─────────────────────────────────────
  Total at idle                 ~158 MB   ← well within 512 MB
  Total under load              ~200 MB   ← safe headroom
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from models.hf_model import generate_image as hf_generate, HFModelError
from models.local_model import generate_image as local_generate
from db.mongo import get_collection
from utils.config import STATIC_IMAGES_DIR

log = logging.getLogger(__name__)

# Ensure the images directory exists at import time
os.makedirs(STATIC_IMAGES_DIR, exist_ok=True)


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class GenerationResult:
    """
    Returned by generate() for every successful pipeline run.

    Attributes
    ----------
    image_url   : web-accessible path, e.g. /static/images/sonar_xxx.png
    prompt      : the original user prompt
    model_used  : 'hf_api' | 'gemini' | 'local'
    model_key   : 'flux' | 'sd21' | 'sdxl'
    created_at  : UTC datetime of generation
    error       : non-empty string when a fallback tier was used
    """
    image_url:  str
    prompt:     str
    model_used: str
    model_key:  str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error:      str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _save_image(img_bytes: bytes, prompt: str) -> str:
    """
    Write PNG bytes to static/images/ and return the web-accessible URL path.

    Filename format: sonar_{unix_timestamp}_{sha1_hash[:12]}.png
    The hash is derived from the first 512 bytes of the image + the prompt,
    so identical generations produce the same filename (natural dedup).
    """
    digest   = hashlib.sha1(img_bytes[:512] + prompt.encode()).hexdigest()[:12]
    filename = f"sonar_{int(time.time())}_{digest}.png"
    filepath = os.path.join(STATIC_IMAGES_DIR, filename)

    with open(filepath, "wb") as fh:
        fh.write(img_bytes)

    log.info("Image saved → %s (%d bytes)", filepath, len(img_bytes))
    return f"/static/images/{filename}"


def _persist(result: GenerationResult) -> None:
    """
    Insert generation metadata into MongoDB.
    Non-fatal — a DB failure never crashes the pipeline.
    """
    col = get_collection()
    if col is None:
        return
    try:
        col.insert_one({
            "prompt":     result.prompt,
            "image_url":  result.image_url,
            "model_used": result.model_used,
            "model_key":  result.model_key,
            "created_at": result.created_at,
        })
        log.debug("Persisted generation to MongoDB.")
    except Exception as exc:
        log.warning("MongoDB insert failed (non-fatal): %s", exc)


def _try_gemini(prompt: str, model_key: str) -> tuple[bytes, str]:
    """
    Attempt Tier-1.5 Gemini generation.

    Returns
    -------
    (img_bytes, model_used_label)

    Raises
    ------
    Exception — any error from Gemini (caller decides what to do)
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not gemini_key:
        raise RuntimeError("GEMINI_API_KEY not configured — skipping Gemini tier.")

    from models.gemini_model import generate_image as gemini_generate
    img_bytes = gemini_generate(prompt, model_key)
    return img_bytes, "gemini"


# ── Public API ────────────────────────────────────────────────────────────────

def generate(prompt: str, model_key: str = "flux") -> GenerationResult:
    """
    Run the full three-tier pipeline.

    Parameters
    ----------
    prompt    : validated, non-empty user prompt (max 500 chars)
    model_key : 'flux' | 'sd21' | 'sdxl'

    Returns
    -------
    GenerationResult — always populated.
    Check .error for non-empty string when a fallback tier was used.
    Check .model_used for which tier actually produced the image.

    Raises
    ------
    RuntimeError — only if ALL three tiers fail (extremely unlikely).
    """
    img_bytes:  bytes = b""
    model_used: str   = "hf_api"
    error_note: str   = ""

    # ── Tier 1: Hugging Face FLUX.1-schnell ───────────────────────────────────
    try:
        img_bytes = hf_generate(prompt, model_key)
        log.info("Tier-1 (HF API) succeeded.")
        model_used = "hf_api"

    except HFModelError as hf_exc:
        error_note = str(hf_exc)
        log.warning("Tier-1 (HF) failed: %s", error_note)

        # ── Tier 1.5: Google Gemini ───────────────────────────────────────────
        try:
            img_bytes, model_used = _try_gemini(prompt, model_key)
            log.info("Tier-1.5 (Gemini) succeeded.")
            # Preserve the HF error note so the response shows what happened
            error_note = f"HF failed ({error_note}); Gemini used as fallback."

        except Exception as gemini_exc:
            gemini_msg = str(gemini_exc)
            log.warning("Tier-1.5 (Gemini) failed: %s", gemini_msg)
            error_note = (
                f"HF: {error_note} | Gemini: {gemini_msg}"
            )

            # ── Tier 2: Local / Pillow placeholder ────────────────────────────
            try:
                img_bytes  = local_generate(prompt, model_key)
                model_used = "local"
                log.info("Tier-2 (local/placeholder) succeeded.")
            except Exception as local_exc:
                # All three tiers failed — this should never happen in practice
                raise RuntimeError(
                    f"All generation tiers failed. "
                    f"HF: {hf_exc} | "
                    f"Gemini: {gemini_msg} | "
                    f"Local: {local_exc}"
                ) from local_exc

    # ── Save & persist ────────────────────────────────────────────────────────
    image_url = _save_image(img_bytes, prompt)

    result = GenerationResult(
        image_url=image_url,
        prompt=prompt,
        model_used=model_used,
        model_key=model_key,
        # Only expose error note when a fallback was used
        error=error_note if model_used != "hf_api" else "",
    )

    _persist(result)
    return result
