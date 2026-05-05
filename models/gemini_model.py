"""
models/gemini_model.py
Tier-1.5: Google Gemini API image generation client.

Position in pipeline
--------------------
Tier-1  → HF FLUX.1-schnell  (primary, free)
Tier-1.5→ Gemini             (this file — called only when HF fails)
Tier-2  → Local placeholder  (last resort, always works)

Design decisions
----------------
- Config read inside generate_image() at call time (same pattern as hf_model.py)
  so stale import-time constants never cause silent failures.
- Uses google-generativeai SDK (not raw HTTP) for cleaner error handling.
- Exponential backoff with jitter on 429 / 503 responses.
- Returns raw PNG bytes — same contract as hf_model.generate_image().
- Zero local model weights loaded → RAM cost is ~8 MB (SDK import only).
- Supports text-to-image only (image-to-image requires Gemini Pro Vision,
  which is a separate endpoint not needed for this pipeline).

Supported models (as of 2025)
------------------------------
  gemini-2.0-flash-exp-image-generation  — fast, free quota
  imagen-3.0-generate-002                — higher quality, paid

The model is selected via GEMINI_MODEL env var; defaults to the free model.
"""

import base64
import io
import logging
import os
import time

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# ── Model registry ────────────────────────────────────────────────────────────
# Maps user-facing keys to actual Gemini model IDs.
# "fast"    → free-tier flash model (default)
# "quality" → higher-quality paid model
GEMINI_MODELS: dict[str, str] = {
    "fast":    "gemini-2.0-flash-exp-image-generation",
    "quality": "gemini-2.0-flash-exp-image-generation",  # upgrade when available
    # Aliases so existing model_key values from the HF pipeline still work
    "flux":    "gemini-2.0-flash-exp-image-generation",
    "sd21":    "gemini-2.0-flash-exp-image-generation",
    "sdxl":    "gemini-2.0-flash-exp-image-generation",
}

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-exp-image-generation"


class GeminiModelError(Exception):
    """
    Raised when Gemini cannot produce an image after all retries.
    Carries the last HTTP status code for upstream decision-making.
    """
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


# ── Internal helpers ──────────────────────────────────────────────────────────

def _backoff(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    """
    Exponential backoff with full jitter.
    attempt=1 → ~1s, attempt=2 → ~2s, attempt=3 → ~4s (capped at cap).
    """
    import random
    delay = min(base ** attempt, cap)
    return delay * (0.5 + random.random() * 0.5)   # 50–100% of computed delay


def _extract_png_from_response(response) -> bytes:
    """
    Walk the Gemini response candidates and extract the first inline image.

    Gemini returns images as base64-encoded inline_data parts.
    Raises GeminiModelError if no image part is found.
    """
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                mime = part.inline_data.mime_type or "image/png"
                raw  = base64.b64decode(part.inline_data.data)

                # Normalise to PNG regardless of what Gemini returns
                if "png" in mime.lower():
                    return raw

                # Convert JPEG / WebP → PNG via Pillow if available
                try:
                    from PIL import Image
                    buf = io.BytesIO()
                    Image.open(io.BytesIO(raw)).save(buf, format="PNG")
                    return buf.getvalue()
                except ImportError:
                    # Pillow not installed — return raw bytes as-is
                    return raw

    raise GeminiModelError(
        "Gemini response contained no image data. "
        "The model may have refused the prompt or returned text only.",
        status_code=0,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def generate_image(prompt: str, model_key: str = "flux") -> bytes:
    """
    Call the Gemini API and return PNG bytes.

    Parameters
    ----------
    prompt    : text description of the desired image (max ~500 chars)
    model_key : 'flux' | 'sd21' | 'sdxl' | 'fast' | 'quality'
                All keys map to the same free-tier Gemini model.

    Returns
    -------
    bytes — raw PNG image data

    Raises
    ------
    GeminiModelError — on all unrecoverable failures (auth, quota, no image)
    ImportError      — if google-generativeai is not installed
    """
    # ── Read config fresh every call ──────────────────────────────────────────
    load_dotenv(override=False)
    api_key     = os.getenv("GEMINI_API_KEY", "").strip()
    max_retries = int(os.getenv("HF_MAX_RETRIES", "3"))   # reuse same retry budget
    model_id    = GEMINI_MODELS.get(model_key, DEFAULT_GEMINI_MODEL)

    if not api_key:
        raise GeminiModelError(
            "GEMINI_API_KEY is not set. "
            "Get a key at https://aistudio.google.com/app/apikey"
        )

    # ── Import SDK (lazy — only when this function is actually called) ────────
    try:
        import google.generativeai as genai
        from google.api_core.exceptions import (
            ResourceExhausted,   # 429 quota
            ServiceUnavailable,  # 503
            InvalidArgument,     # 400 bad prompt
            PermissionDenied,    # 403 / 401
            GoogleAPIError,
        )
    except ImportError as exc:
        raise ImportError(
            "google-generativeai is not installed. "
            "Run: pip install google-generativeai==0.8.5"
        ) from exc

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_id)

    log.info("Gemini model: %s", model_id)
    last_error = "Unknown error"

    for attempt in range(1, max_retries + 1):
        log.info("Gemini attempt %d/%d", attempt, max_retries)
        try:
            response = model.generate_content(
                contents=prompt,
                generation_config=genai.GenerationConfig(
                    temperature=1.0,
                    candidate_count=1,
                    # response_modalities tells Gemini we want an image back
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            img_bytes = _extract_png_from_response(response)
            log.info("Gemini success — %d bytes", len(img_bytes))
            return img_bytes

        # ── Rate limit / quota ────────────────────────────────────────────────
        except ResourceExhausted as exc:
            last_error = f"Gemini quota exceeded (429): {exc}"
            log.warning(last_error)
            if attempt < max_retries:
                wait = _backoff(attempt, base=10.0, cap=120.0)
                log.info("Waiting %.1fs before retry…", wait)
                time.sleep(wait)
                continue

        # ── Service unavailable ───────────────────────────────────────────────
        except ServiceUnavailable as exc:
            last_error = f"Gemini service unavailable (503): {exc}"
            log.warning(last_error)
            if attempt < max_retries:
                wait = _backoff(attempt)
                time.sleep(wait)
                continue

        # ── Auth / permission ─────────────────────────────────────────────────
        except PermissionDenied as exc:
            raise GeminiModelError(
                f"Gemini API key invalid or lacks image generation permission. "
                f"Enable 'Generative Language API' in Google Cloud Console. "
                f"Detail: {exc}",
                status_code=403,
            ) from exc

        # ── Bad prompt / invalid request ──────────────────────────────────────
        except InvalidArgument as exc:
            raise GeminiModelError(
                f"Gemini rejected the request (400): {exc}",
                status_code=400,
            ) from exc

        # ── No image in response (safety filter / text-only response) ─────────
        except GeminiModelError as exc:
            last_error = str(exc)
            log.warning("Gemini returned no image on attempt %d: %s", attempt, last_error)
            if attempt < max_retries:
                time.sleep(_backoff(attempt))
                continue

        # ── Catch-all Google API errors ───────────────────────────────────────
        except Exception as exc:
            last_error = f"Unexpected Gemini error: {exc}"
            log.error(last_error)
            if attempt < max_retries:
                time.sleep(_backoff(attempt))
                continue

    raise GeminiModelError(
        f"Gemini image generation failed after {max_retries} attempts. "
        f"Last error: {last_error}"
    )
