"""
utils/config.py
Centralised configuration — reads from .env via python-dotenv.
All other modules import from here; nothing reads os.getenv directly.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

# ── Hugging Face ──────────────────────────────────────────────────────────────
HF_API_KEY: str = os.getenv("HF_API_KEY", "")

# HF migrated to router.huggingface.co in 2025.
# Old api-inference.huggingface.co/models/* returns 404 for all models.
# Only models supported by the hf-inference provider work on the free tier.
# As of 2025, FLUX.1-schnell is the only free text-to-image model available.
_HF_BASE = "https://router.huggingface.co/hf-inference/models"

HF_MODEL_URLS: dict[str, str] = {
    "flux":  f"{_HF_BASE}/black-forest-labs/FLUX.1-schnell",
    # sd21 and sdxl are no longer supported on the free hf-inference provider
    # (returns 400 "Model not supported by provider hf-inference").
    # Kept as aliases pointing to flux so existing requests don't break.
    "sd21":  f"{_HF_BASE}/black-forest-labs/FLUX.1-schnell",
    "sdxl":  f"{_HF_BASE}/black-forest-labs/FLUX.1-schnell",
}

# ── Request tuning ────────────────────────────────────────────────────────────
HF_TIMEOUT: int   = int(os.getenv("HF_TIMEOUT", "90"))      # seconds per attempt
HF_MAX_RETRIES: int = int(os.getenv("HF_MAX_RETRIES", "3")) # total attempts

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI: str = os.getenv("MONGO_URI", "")
MONGO_DB:  str = os.getenv("MONGO_DB",  "sonar")
MONGO_COL: str = os.getenv("MONGO_COL", "generations")

# ── Flask ─────────────────────────────────────────────────────────────────────
SECRET_KEY: str = os.getenv("SECRET_KEY", os.urandom(32).hex())  # fallback is ephemeral
FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"
FLASK_PORT:  int  = int(os.getenv("PORT", "5000"))

# ── Image storage ─────────────────────────────────────────────────────────────
STATIC_IMAGES_DIR: str = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "static", "images"
)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
