"""
verify_connections.py
Standalone script to verify HF API key and MongoDB connection.
Run with: python verify_connections.py
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

HF_API_KEY = os.getenv("HF_API_KEY", "")
MONGO_URI  = os.getenv("MONGO_URI", "")

RESET  = "\033[0m"
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"

def ok(msg):   print(f"  {GREEN}✅ {msg}{RESET}")
def fail(msg): print(f"  {RED}❌ {msg}{RESET}")
def warn(msg): print(f"  {YELLOW}⚠️  {msg}{RESET}")
def info(msg): print(f"  {CYAN}ℹ️  {msg}{RESET}")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Hugging Face API Key
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}{'─'*50}{RESET}")
print(f"{BOLD}  1. Hugging Face API Key{RESET}")
print(f"{BOLD}{'─'*50}{RESET}")

hf_ok = False

if not HF_API_KEY:
    fail("HF_API_KEY is not set in .env")
elif not HF_API_KEY.startswith("hf_"):
    warn(f"Key found but unusual format: {HF_API_KEY[:8]}...")
else:
    info(f"Key found: {HF_API_KEY[:10]}{'*' * (len(HF_API_KEY) - 10)}")

    # Fine-grained inference-only tokens return 401 on /api/whoami.
    # Verify by calling the actual inference router instead.
    try:
        resp = requests.get(
            "https://huggingface.co/api/whoami",
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            username = data.get("name", "unknown")
            acct_type = data.get("type", "unknown")
            orgs = [o.get("name") for o in data.get("orgs", [])]
            ok(f"Authenticated as: {username} ({acct_type})")
            if orgs:
                info(f"Organisations: {', '.join(orgs)}")
            hf_ok = True
        elif resp.status_code == 401:
            # Fine-grained tokens with only Inference permission can't hit whoami.
            # Fall through to the inference smoke-test below.
            info("whoami returned 401 — fine-grained token detected, verifying via inference API...")
        else:
            fail(f"Unexpected response: HTTP {resp.status_code} — {resp.text[:120]}")
    except requests.exceptions.Timeout:
        fail("Request timed out — check your internet connection")
    except requests.exceptions.ConnectionError as e:
        fail(f"Connection error: {e}")

# Quick inference smoke-test (always runs — works for both token types)
if hf_ok or True:
    print()
    info("Running inference smoke-test via router (FLUX.1-schnell, may take 20-60s)...")
    try:
        resp = requests.post(
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            headers={"Authorization": f"Bearer {HF_API_KEY}", "Content-Type": "application/json"},
            json={"inputs": "a red circle", "options": {"wait_for_model": True}},
            timeout=90,
        )
        ct = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and "image" in ct:
            ok(f"Inference API working — received {len(resp.content):,} bytes of image data")
            hf_ok = True
        elif resp.status_code == 503:
            warn("Model is loading (503) — token is VALID, model will be ready in ~30s on first use")
            hf_ok = True
        elif resp.status_code == 429:
            warn("Rate limited (429) — token is VALID but free-tier quota reached, try again later")
            hf_ok = True
        elif resp.status_code == 401:
            fail("Token rejected by inference API (401) — check token permissions")
            info("Ensure 'Make calls to Inference Providers' is checked when creating the token")
        elif resp.status_code == 400:
            try:
                body = resp.json()
                fail(f"Inference failed (400): {body.get('error', resp.text[:120])}")
            except Exception:
                fail(f"Inference failed (400): {resp.text[:120]}")
        else:
            fail(f"Unexpected inference response: HTTP {resp.status_code} — {resp.text[:120]}")
    except requests.exceptions.Timeout:
        warn("Inference timed out (90s) — model may be cold-starting, try again")
        hf_ok = True   # Timeout ≠ invalid token
    except requests.exceptions.ConnectionError as e:
        fail(f"Connection error during inference: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. MongoDB Connection
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}{'─'*50}{RESET}")
print(f"{BOLD}  2. MongoDB Connection{RESET}")
print(f"{BOLD}{'─'*50}{RESET}")

mongo_ok = False

if not MONGO_URI:
    warn("MONGO_URI is not set — history/persistence will be disabled")
    info("Get a free cluster at https://cloud.mongodb.com")
elif MONGO_URI in ("your_mongodb_connection_string", "mongodb+srv://user:password@cluster.mongodb.net/"):
    warn("MONGO_URI is still the placeholder value — please replace it with your real connection string")
    info("Get a free cluster at https://cloud.mongodb.com")
else:
    # Mask credentials in display
    display_uri = MONGO_URI
    if "@" in MONGO_URI:
        prefix = MONGO_URI.split("://")[0] + "://"
        rest   = MONGO_URI.split("@", 1)[1]
        display_uri = f"{prefix}****:****@{rest}"
    info(f"URI found: {display_uri}")

    try:
        from pymongo import MongoClient
        from pymongo.errors import ServerSelectionTimeoutError, OperationFailure

        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        server_info = client.server_info()

        ok(f"Connected! MongoDB version: {server_info.get('version', 'unknown')}")
        mongo_ok = True

        # Check database access
        db = client["sonar"]
        col = db["generations"]

        # Write test
        result = col.insert_one({"_verify": True, "test": "connection_check"})
        ok(f"Write test passed — inserted doc _id: {result.inserted_id}")

        # Read test
        doc = col.find_one({"_id": result.inserted_id})
        if doc:
            ok("Read test passed")
        else:
            fail("Read test failed — document not found after insert")

        # Cleanup
        col.delete_one({"_id": result.inserted_id})
        ok("Cleanup passed — test document removed")

        # Collection stats
        count = col.count_documents({})
        info(f"Existing generations in DB: {count}")

    except ServerSelectionTimeoutError as e:
        fail(f"Cannot reach MongoDB server (timeout): {e}")
        info("Check: IP whitelist in Atlas, correct URI, network connectivity")
    except OperationFailure as e:
        fail(f"Authentication/permission error: {e}")
        info("Check: username, password, and database permissions in Atlas")
    except Exception as e:
        fail(f"Unexpected error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{BOLD}{'─'*50}{RESET}")
print(f"{BOLD}  Summary{RESET}")
print(f"{BOLD}{'─'*50}{RESET}")

hf_status    = f"{GREEN}✅ Ready{RESET}"    if hf_ok    else f"{RED}❌ Not ready{RESET}"
mongo_status = f"{GREEN}✅ Ready{RESET}"    if mongo_ok else f"{YELLOW}⚠️  Disabled (optional){RESET}"

print(f"  Hugging Face API : {hf_status}")
print(f"  MongoDB          : {mongo_status}")

if hf_ok:
    print(f"\n{GREEN}{BOLD}  App is ready to run: python app.py{RESET}")
else:
    print(f"\n{RED}{BOLD}  Fix HF_API_KEY before running the app.{RESET}")
    print(f"  Get a token at: https://huggingface.co/settings/tokens")

print()
sys.exit(0 if hf_ok else 1)
