"""
tests/conftest.py
Pytest configuration and shared fixtures.
Forces test environment variables BEFORE any app imports,
so the real .env credentials are never used during tests.
"""
import os

# Override with test values — must happen before any app module is imported.
# This prevents the real HF_API_KEY from being used (which would make real
# API calls and cause the "prompt too long" validation test to hit the API
# instead of returning 400).
os.environ["HF_API_KEY"] = ""
os.environ["MONGO_URI"]  = ""
