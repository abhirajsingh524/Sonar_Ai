"""
tests/test_generate.py
Unit and integration tests for SONAR.

Run with:
    pytest tests/ -v

Mocking strategy after hf_model.py refactor
--------------------------------------------
hf_model.generate_image() now reads HF_API_KEY via os.getenv() at call time,
not as a module-level constant.  So we patch:
  - os.getenv          inside models.hf_model  (for key/timeout/retries)
  - models.hf_model.requests.post              (for HTTP calls)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_png() -> bytes:
    """Minimal valid 1×1 PNG."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
        b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
        b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _mock_getenv(key, default=""):
    """os.getenv stub: returns a fake API key, sensible defaults for others."""
    return {
        "HF_API_KEY":     "hf_fake_test_key",
        "HF_TIMEOUT":     "10",
        "HF_MAX_RETRIES": "1",   # 1 retry keeps tests fast
    }.get(key, default)


# ─────────────────────────────────────────────────────────────────────────────
# 1. HF Model
# ─────────────────────────────────────────────────────────────────────────────
class TestHFModel(unittest.TestCase):

    @patch("models.hf_model.os.getenv", side_effect=_mock_getenv)
    @patch("models.hf_model.requests.post")
    def test_valid_prompt_returns_bytes(self, mock_post, _getenv):
        """200 image response → returns PNG bytes."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.content = _minimal_png()
        mock_post.return_value = mock_resp

        from models.hf_model import generate_image
        result = generate_image("a red apple", "flux")
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    @patch("models.hf_model.os.getenv", side_effect=_mock_getenv)
    @patch("models.hf_model.requests.post")
    def test_api_failure_raises_hf_model_error(self, mock_post, _getenv):
        """500 on all retries → HFModelError raised."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.json.return_value = {"error": "Internal Server Error"}
        mock_post.return_value = mock_resp

        from models.hf_model import generate_image, HFModelError
        with self.assertRaises(HFModelError):
            generate_image("a red apple", "flux")

    @patch("models.hf_model.os.getenv", side_effect=lambda k, d="": "" if k == "HF_API_KEY" else _mock_getenv(k, d))
    def test_missing_api_key_raises(self, _getenv):
        """Empty HF_API_KEY → HFModelError immediately."""
        from models.hf_model import generate_image, HFModelError
        with self.assertRaises(HFModelError):
            generate_image("test prompt")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Local Model
# ─────────────────────────────────────────────────────────────────────────────
class TestLocalModel(unittest.TestCase):

    def test_placeholder_returns_png_bytes(self):
        """Local model always returns valid PNG bytes."""
        from models.local_model import generate_image
        result = generate_image("a blue sky", "flux")
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)
        self.assertEqual(result[:4], b"\x89PNG", "Expected PNG magic bytes")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Image Service — pipeline orchestration
# ─────────────────────────────────────────────────────────────────────────────
class TestImageService(unittest.TestCase):

    @patch("services.image_service._persist")
    @patch("services.image_service.hf_generate")
    def test_tier1_success(self, mock_hf, mock_persist):
        """HF API succeeds → model_used == 'hf_api'."""
        mock_hf.return_value = _minimal_png()
        from services.image_service import generate
        result = generate("futuristic city", "flux")
        self.assertEqual(result.model_used, "hf_api")
        self.assertTrue(result.image_url.startswith("/static/images/"))
        self.assertEqual(result.error, "")

    @patch("services.image_service._persist")
    @patch("services.image_service.local_generate")
    @patch("services.image_service.hf_generate")
    def test_tier2_fallback(self, mock_hf, mock_local, mock_persist):
        """HF fails → falls back to local; model_used == 'local'."""
        from models.hf_model import HFModelError
        mock_hf.side_effect = HFModelError("API down")
        mock_local.return_value = _minimal_png()
        from services.image_service import generate
        result = generate("ocean sunset", "flux")
        self.assertEqual(result.model_used, "local")
        self.assertIn("API down", result.error)

    @patch("services.image_service._persist")
    @patch("services.image_service.local_generate")
    @patch("services.image_service.hf_generate")
    def test_both_tiers_fail_raises(self, mock_hf, mock_local, mock_persist):
        """Both tiers fail → RuntimeError."""
        from models.hf_model import HFModelError
        mock_hf.side_effect = HFModelError("API down")
        mock_local.side_effect = Exception("Local broken")
        from services.image_service import generate
        with self.assertRaises(RuntimeError):
            generate("broken prompt", "flux")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Flask Routes — HTTP layer
# ─────────────────────────────────────────────────────────────────────────────
class TestFlaskRoutes(unittest.TestCase):

    def setUp(self):
        os.environ.setdefault("HF_API_KEY", "hf_test_key")
        from app import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_index_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "ok")

    def test_generate_empty_prompt(self):
        resp = self.client.post("/generate", json={"prompt": "  ", "model": "flux"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_generate_prompt_too_long(self):
        resp = self.client.post("/generate", json={"prompt": "x" * 501, "model": "flux"})
        self.assertEqual(resp.status_code, 400)

    def test_generate_invalid_model(self):
        resp = self.client.post("/generate", json={"prompt": "a cat", "model": "bad_model"})
        self.assertEqual(resp.status_code, 400)

    def test_generate_valid_prompt(self):
        """Valid prompt → 200 with image_url."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.content = _minimal_png()

        with patch("models.hf_model.requests.post", return_value=mock_resp), \
             patch("models.hf_model.os.getenv", side_effect=_mock_getenv), \
             patch("services.image_service._persist"), \
             patch("routes.generate.HF_API_KEY", "hf_test_key"):
            resp = self.client.post("/generate", json={"prompt": "a cat", "model": "flux"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("image_url", data)
        self.assertEqual(data["model_used"], "hf_api")
        self.assertFalse(data["fallback"])

    def test_generate_fallback_response(self):
        """API failure → fallback → 200 with fallback=True."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Server Error"
        mock_resp.json.return_value = {"error": "Server Error"}

        with patch("models.hf_model.requests.post", return_value=mock_resp), \
             patch("models.hf_model.os.getenv", side_effect=_mock_getenv), \
             patch("services.image_service._persist"), \
             patch("routes.generate.HF_API_KEY", "hf_test_key"):
            resp = self.client.post("/generate", json={"prompt": "a dog", "model": "flux"})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["fallback"])
        self.assertIn("failed after", data["fallback_reason"])

    def test_history_no_db(self):
        """History returns empty list when MongoDB unavailable."""
        with patch("routes.generate.get_collection", return_value=None):
            resp = self.client.get("/history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["items"], [])


# ─────────────────────────────────────────────────────────────────────────────
# 5. MongoDB persistence
# ─────────────────────────────────────────────────────────────────────────────
class TestMongoPersistence(unittest.TestCase):

    @patch("services.image_service.get_collection")
    @patch("services.image_service.hf_generate")
    def test_db_insert_called_on_success(self, mock_hf, mock_col):
        """Successful generation triggers a MongoDB insert."""
        mock_hf.return_value = _minimal_png()
        mock_collection = MagicMock()
        mock_col.return_value = mock_collection
        from services.image_service import generate
        generate("a mountain", "flux")
        mock_collection.insert_one.assert_called_once()
        doc = mock_collection.insert_one.call_args[0][0]
        self.assertEqual(doc["prompt"], "a mountain")
        self.assertIn("image_url",  doc)
        self.assertIn("model_used", doc)
        self.assertIn("created_at", doc)

    @patch("services.image_service.get_collection")
    @patch("services.image_service.hf_generate")
    def test_db_failure_is_non_fatal(self, mock_hf, mock_col):
        """MongoDB insert failure does not crash the pipeline."""
        mock_hf.return_value = _minimal_png()
        mock_collection = MagicMock()
        mock_collection.insert_one.side_effect = Exception("DB write error")
        mock_col.return_value = mock_collection
        from services.image_service import generate
        result = generate("a river", "flux")
        self.assertIsNotNone(result.image_url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
