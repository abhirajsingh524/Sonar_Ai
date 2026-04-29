"""
services/image_service.py
Orchestrates the dual-model pipeline and persistence.

Pipeline
--------
User Prompt
    ↓
image_service.generate()
    ↓
Try Tier-1: HF API  (models/hf_model.py)
    ↓ (on failure)
Try Tier-2: Local / Placeholder  (models/local_model.py)
    ↓
Save PNG to static/images/
    ↓
Persist metadata to MongoDB  (db/mongo.py)
    ↓
Return GenerationResult
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


@dataclass
class GenerationResult:
    image_url:  str
    prompt:     str
    model_used: str                          # 'hf_api' | 'local'
    model_key:  str                          # 'sd21' | 'sdxl' | 'flux'
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error:      str = ""                     # non-empty only on partial failure


def _save_image(img_bytes: bytes, prompt: str) -> str:
    """
    Write PNG bytes to static/images/ and return the web-accessible URL path.
    Filename is derived from a short content hash to avoid collisions.
    """
    digest = hashlib.sha1(img_bytes[:512] + prompt.encode()).hexdigest()[:12]
    filename = f"sonar_{int(time.time())}_{digest}.png"
    filepath = os.path.join(STATIC_IMAGES_DIR, filename)

    with open(filepath, "wb") as fh:
        fh.write(img_bytes)

    log.info("Image saved → %s (%d bytes)", filepath, len(img_bytes))
    return f"/static/images/{filename}"


def _persist(result: GenerationResult) -> None:
    """Insert generation metadata into MongoDB (non-fatal if unavailable)."""
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


def generate(prompt: str, model_key: str = "sd21") -> GenerationResult:
    """
    Run the full dual-model pipeline.

    Parameters
    ----------
    prompt    : validated, non-empty user prompt
    model_key : 'sd21' | 'sdxl' | 'flux'

    Returns
    -------
    GenerationResult — always populated; check .error for fallback info.

    Raises
    ------
    RuntimeError — only if both tiers fail AND local fallback also errors.
    """
    img_bytes:  bytes = b""
    model_used: str   = "hf_api"
    error_note: str   = ""

    # ── Tier 1: Hugging Face API ──────────────────────────────────────────────
    try:
        img_bytes = hf_generate(prompt, model_key)
        log.info("Tier-1 (HF API) succeeded.")
    except HFModelError as exc:
        error_note = str(exc)
        log.warning("Tier-1 failed: %s — falling back to Tier-2.", error_note)

        # ── Tier 2: Local / Placeholder ───────────────────────────────────────
        try:
            img_bytes  = local_generate(prompt, model_key)
            model_used = "local"
            log.info("Tier-2 (local/placeholder) succeeded.")
        except Exception as local_exc:
            # Both tiers failed — propagate as RuntimeError
            raise RuntimeError(
                f"Both generation tiers failed. "
                f"API error: {error_note} | Local error: {local_exc}"
            ) from local_exc

    # ── Save & persist ────────────────────────────────────────────────────────
    image_url = _save_image(img_bytes, prompt)

    result = GenerationResult(
        image_url=image_url,
        prompt=prompt,
        model_used=model_used,
        model_key=model_key,
        error=error_note if model_used == "local" else "",
    )

    _persist(result)
    return result
