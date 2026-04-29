"""
app.py
SONAR — AI Image Generator
Flask application entry point.

Structure
---------
app.py                  ← this file (factory + entry point)
routes/generate.py      ← /generate, /history, /health blueprints
services/image_service.py ← dual-model pipeline orchestration
models/hf_model.py      ← Tier-1: Hugging Face Inference API
models/local_model.py   ← Tier-2: local diffusion / placeholder
db/mongo.py             ← MongoDB connection singleton
utils/config.py         ← all env-var configuration
"""

import logging
import os

from flask import Flask, render_template, request

from utils.config import FLASK_DEBUG, FLASK_PORT, STATIC_IMAGES_DIR, SECRET_KEY

log = logging.getLogger(__name__)


def create_app() -> Flask:
    """Application factory — creates and configures the Flask app."""
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # Ensure static/images directory exists
    os.makedirs(STATIC_IMAGES_DIR, exist_ok=True)

    # ── Register blueprints ───────────────────────────────────────────────────
    from routes.generate import bp as generate_bp
    app.register_blueprint(generate_bp)

    # ── Video background route ────────────────────────────────────────────────
    # Streams the video from the /vedio folder with proper range-request support
    # so browsers can seek/loop without downloading the whole file first.
    import mimetypes
    from flask import send_from_directory, Response, abort
    import re as _re

    VIDEO_DIR = os.path.join(os.path.dirname(__file__), "vedio")

    @app.route("/video/<path:filename>")
    def serve_video(filename):
        """
        Stream a video file from the /vedio directory.
        Supports HTTP Range requests so browsers can loop smoothly.
        """
        filepath = os.path.join(VIDEO_DIR, filename)
        if not os.path.isfile(filepath):
            abort(404)

        file_size = os.path.getsize(filepath)
        mime, _ = mimetypes.guess_type(filepath)
        mime = mime or "video/mp4"

        range_header = request.headers.get("Range", None)

        if not range_header:
            # Full file — let Flask handle it
            return send_from_directory(VIDEO_DIR, filename, mimetype=mime)

        # Parse "bytes=start-end"
        byte_range = range_header.replace("bytes=", "")
        parts = byte_range.split("-")
        start = int(parts[0]) if parts[0] else 0
        end   = int(parts[1]) if parts[1] else file_size - 1
        end   = min(end, file_size - 1)
        length = end - start + 1

        def generate_chunk():
            with open(filepath, "rb") as fh:
                fh.seek(start)
                remaining = length
                chunk_size = 64 * 1024  # 64 KB chunks
                while remaining > 0:
                    data = fh.read(min(chunk_size, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range":  f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges":  "bytes",
            "Content-Length": str(length),
            "Content-Type":   mime,
        }
        return Response(generate_chunk(), status=206, headers=headers)

    # ── Root route ────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Global error handlers ─────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify
        return jsonify({"error": "Endpoint not found."}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        from flask import jsonify
        return jsonify({"error": "Method not allowed."}), 405

    @app.errorhandler(500)
    def internal_error(e):
        from flask import jsonify
        log.exception("Unhandled server error")
        return jsonify({"error": "Internal server error."}), 500

    log.info("✅ SONAR app created (debug=%s)", FLASK_DEBUG)
    return app


# ── Entry point ───────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT, host="0.0.0.0")
