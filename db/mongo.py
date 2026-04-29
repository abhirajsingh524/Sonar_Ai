"""
db/mongo.py
MongoDB connection module.

Reads MONGO_URI fresh from environment on every call so the singleton
is not poisoned by a stale import-time value (e.g. during testing).
Returns the PyMongo Collection, or None when MongoDB is unavailable.
"""

import logging
import os

from dotenv import load_dotenv

log = logging.getLogger(__name__)

_collection = None   # cached after first successful connect
_failed     = False  # set True only on permanent auth/config errors


def get_collection():
    """
    Return the PyMongo Collection for sonar.generations.
    Returns None if MongoDB is not configured or unreachable.
    Non-fatal — callers must handle None gracefully.
    """
    global _collection, _failed

    # Already connected
    if _collection is not None:
        return _collection

    # Permanent failure (bad creds etc.) — don't keep retrying
    if _failed:
        return None

    # Read URI fresh — works even if .env was loaded after module import
    load_dotenv(override=False)
    mongo_uri = os.getenv("MONGO_URI", "").strip()
    mongo_db  = os.getenv("MONGO_DB",  "sonar")
    mongo_col = os.getenv("MONGO_COL", "generations")

    if not mongo_uri or mongo_uri == "your_mongodb_connection_string":
        log.warning("MONGO_URI not set — history/persistence disabled.")
        return None

    try:
        from pymongo import MongoClient
        from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.server_info()   # raises ServerSelectionTimeoutError if unreachable
        _collection = client[mongo_db][mongo_col]
        log.info("✅ MongoDB connected → %s.%s", mongo_db, mongo_col)
        return _collection

    except Exception as exc:
        log.warning("⚠️  MongoDB unavailable: %s", exc)
        # Don't set _failed — allow retry on next request (transient network issue)
        return None
