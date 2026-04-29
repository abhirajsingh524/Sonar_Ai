"""
models/hf_model.py
Tier-1: Hugging Face Inference API client.

Endpoint: router.huggingface.co/hf-inference  (migrated 2025)
Model:    black-forest-labs/FLUX.1-schnell     (only free-tier model)

Key design: config is read INSIDE generate_image(), not at import time.
This prevents stale module-level constants from surviving hot-reloads.
"""

import logging
import os
import time

import requests
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# ── Single source of truth for the working endpoint ──────────────────────────
# HF migrated away from api-inference.huggingface.co in 2025 (returns 404).
# Only FLUX.1-schnell is supported on the free hf-inference provider tier.
_FLUX_URL = (
    "https://router.huggingface.co/hf-inference/models"
    "/black-forest-labs/FLUX.1-schnell"
)

# All model keys resolve to FLUX — SD v1.5 / SD 2.1 / SDXL are gone from
# the free tier (400 "Model not supported by provider hf-inference").
MODEL_URL_MAP: dict[str, str] = {
    "flux": _FLUX_URL,
    "sd21": _FLUX_URL,   # alias → FLUX
    "sdxl": _FLUX_URL,   # alias → FLUX
}


class HFModelError(Exception):
    """Raised when the HF API cannot produce an image after all retries."""


def generate_image(prompt: str, model_key: str = "flux") -> bytes:
    """
    POST to the HF Inference router and return raw PNG bytes.

    Parameters
    ----------
    prompt    : text description of the desired image
    model_key : 'flux' | 'sd21' | 'sdxl'  (sd21/sdxl alias to flux)

    Returns
    -------
    bytes — raw PNG image data

    Raises
    ------
    HFModelError — on all unrecoverable failures
    """
    # Read config fresh every call — avoids stale import-time constants
    load_dotenv(override=False)
    api_key     = os.getenv("HF_API_KEY", "")
    timeout     = int(os.getenv("HF_TIMEOUT", "90"))
    max_retries = int(os.getenv("HF_MAX_RETRIES", "3"))

    if not api_key:
        raise HFModelError("HF_API_KEY is not configured on the server.")

    url = MODEL_URL_MAP.get(model_key, _FLUX_URL)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "Accept":        "image/png",
    }

    # FLUX.1-schnell works best with these parameters
    payload = {
        "inputs": prompt,
        "parameters": {
            "guidance_scale":       7.5,
            "num_inference_steps":  30,
        },
    }

    log.info("HF endpoint: %s", url)
    last_error = "Unknown error"

    for attempt in range(1, max_retries + 1):
        log.info("HF API attempt %d/%d — model_key=%s", attempt, max_retries, model_key)
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

            # ── Success ───────────────────────────────────────────────────────
            if resp.status_code == 200:
                ct = resp.headers.get("Content-Type", "")
                if "image" in ct or len(resp.content) > 500:
                    log.info("HF API success — %d bytes, Content-Type: %s",
                             len(resp.content), ct)
                    return resp.content
                # 200 but JSON body (shouldn't happen with Accept: image/png)
                try:
                    last_error = resp.json().get("error", "Non-image 200 response")
                except Exception:
                    last_error = "Non-image 200 response"
                log.warning("HF 200 but non-image: %s", last_error)

            # ── Model loading ─────────────────────────────────────────────────
            elif resp.status_code == 503:
                try:
                    wait = float(resp.json().get("estimated_time", 20))
                except Exception:
                    wait = 20
                wait = min(wait, 30) + attempt * 5
                last_error = f"Model loading (503) — waiting {wait:.0f}s"
                log.warning(last_error)
                if attempt < max_retries:
                    time.sleep(wait)
                    continue

            # ── Auth ──────────────────────────────────────────────────────────
            elif resp.status_code == 401:
                raise HFModelError(
                    "Invalid or expired HF_API_KEY. "
                    "Ensure 'Make calls to Inference Providers' is checked at "
                    "https://huggingface.co/settings/tokens"
                )

            # ── Rate limited ──────────────────────────────────────────────────
            elif resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                last_error = f"Rate limited — retry after {retry_after}s"
                log.warning(last_error)
                if attempt < max_retries:
                    time.sleep(min(retry_after, 60))
                    continue

            # ── Everything else ───────────────────────────────────────────────
            else:
                try:
                    last_error = resp.json().get("error", resp.text[:300])
                except Exception:
                    last_error = resp.text[:300] or f"HTTP {resp.status_code}"
                log.error("HF API HTTP %d: %s", resp.status_code, last_error)
                if attempt < max_retries:
                    time.sleep(5 * attempt)
                    continue

        except requests.exceptions.Timeout:
            last_error = f"Request timed out after {timeout}s"
            log.warning("HF timeout on attempt %d", attempt)
            if attempt < max_retries:
                time.sleep(5)
                continue

        except requests.exceptions.ConnectionError as exc:
            last_error = f"Connection error: {exc}"
            log.warning("HF connection error on attempt %d: %s", attempt, exc)
            if attempt < max_retries:
                time.sleep(5 * attempt)
                continue

        except requests.exceptions.RequestException as exc:
            raise HFModelError(f"Request error: {exc}") from exc

    raise HFModelError(
        f"Image generation failed after {max_retries} attempts. "
        f"Last error: {last_error}"
    )
