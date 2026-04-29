"""
routes/generate.py
Blueprint for all image-generation and history endpoints.

Endpoints
---------
POST /generate   — generate an image from a text prompt
GET  /history    — retrieve last 20 generations from MongoDB
GET  /health     — lightweight liveness probe
"""

import logging
from datetime import timezone

from flask import Blueprint, jsonify, request

from services.image_service import generate
from db.mongo import get_collection
from utils.config import HF_API_KEY

log = logging.getLogger(__name__)

bp = Blueprint("generate", __name__)

# ── Input constraints ─────────────────────────────────────────────────────────
PROMPT_MAX_LEN = 500
VALID_MODELS   = {"sd21", "sdxl", "flux"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /generate
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/generate", methods=["POST"])
def generate_image():
    """
    Request body (JSON):
        { "prompt": "...", "model": "sd21" }

    Success response (200):
        { "image_url": "/static/images/sonar_xxx.png",
          "prompt": "...",
          "model_used": "hf_api" | "local",
          "model_key": "sd21",
          "fallback": false,
          "fallback_reason": "" }

    Error response (4xx / 5xx):
        { "error": "Human-readable message." }
    """
    # ── Parse & validate ──────────────────────────────────────────────────────
    body = request.get_json(force=True, silent=True) or {}

    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "Prompt cannot be empty."}), 400
    if len(prompt) > PROMPT_MAX_LEN:
        return jsonify({"error": f"Prompt exceeds {PROMPT_MAX_LEN} characters."}), 400

    model_key = (body.get("model") or "sd21").strip().lower()
    if model_key not in VALID_MODELS:
        return jsonify({
            "error": f"Invalid model '{model_key}'. Choose from: {', '.join(sorted(VALID_MODELS))}."
        }), 400

    if not HF_API_KEY:
        return jsonify({"error": "Server API key (HF_API_KEY) is not configured."}), 500

    # ── Run pipeline ──────────────────────────────────────────────────────────
    try:
        result = generate(prompt, model_key)
    except RuntimeError as exc:
        log.error("Generation pipeline failed: %s", exc)
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "image_url":      result.image_url,
        "prompt":         result.prompt,
        "model_used":     result.model_used,
        "model_key":      result.model_key,
        "fallback":       result.model_used == "local",
        "fallback_reason": result.error,
    }), 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /history
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/history", methods=["GET"])
def history():
    """Return the last 20 generations stored in MongoDB."""
    col = get_collection()
    if col is None:
        return jsonify({"items": [], "note": "History unavailable — MongoDB not configured."})

    try:
        docs = list(
            col.find({}, {"_id": 0})
               .sort("created_at", -1)
               .limit(20)
        )
        for doc in docs:
            ts = doc.get("created_at")
            if ts:
                # Ensure UTC-aware ISO string
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                doc["created_at"] = ts.isoformat()
        return jsonify({"items": docs}), 200
    except Exception as exc:
        log.error("History query failed: %s", exc)
        return jsonify({"error": "Could not retrieve history."}), 500


# ─────────────────────────────────────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────────────────────────────────────
@bp.route("/health", methods=["GET"])
def health():
    """Liveness probe used by Render / load balancers."""
    col = get_collection()
    return jsonify({
        "status":   "ok",
        "api_key":  bool(HF_API_KEY),
        "database": col is not None,
    }), 200
