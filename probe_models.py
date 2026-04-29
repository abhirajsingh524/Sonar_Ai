"""
probe_models.py  — finds every working text-to-image endpoint for your token.
Run: python probe_models.py
"""
import os, requests
from dotenv import load_dotenv
load_dotenv()

KEY = os.getenv("HF_API_KEY", "")
HDR = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
PAY = {"inputs": "a red circle", "parameters": {"num_inference_steps": 1}}

CANDIDATES = [
    # ── old api-inference base ────────────────────────────────────────────────
    ("old-api / sd-v1-5",   "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-v1-5"),
    ("old-api / sd-v1-4",   "https://api-inference.huggingface.co/models/CompVis/stable-diffusion-v1-4"),
    ("old-api / sd-2-1",    "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1"),
    ("old-api / flux-sch",  "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"),
    # ── new router base ───────────────────────────────────────────────────────
    ("router / flux-sch",   "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"),
    ("router / sd-v1-5",    "https://router.huggingface.co/hf-inference/models/runwayml/stable-diffusion-v1-5"),
    ("router / sd-2-1",     "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-2-1"),
    ("router / sdxl-turbo", "https://router.huggingface.co/hf-inference/models/stabilityai/sdxl-turbo"),
    ("router / sdxl-base",  "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-xl-base-1.0"),
]

print(f"\nToken: {KEY[:14]}...\n")
print(f"{'Label':<26} {'Status':<8} {'Result'}")
print("─" * 70)

winners = []
for label, url in CANDIDATES:
    try:
        r = requests.post(url, headers=HDR, json=PAY, timeout=20)
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "image" in ct:
            note = f"✅ IMAGE  {len(r.content):,} bytes"
            winners.append((label, url))
        elif r.status_code == 503:
            note = "⏳ 503 loading — token VALID"
            winners.append((label, url))
        elif r.status_code == 429:
            note = "⚠️  429 rate-limited — token VALID"
            winners.append((label, url))
        elif r.status_code == 404:
            note = "❌ 404 endpoint gone"
        elif r.status_code == 401:
            note = "🔑 401 unauthorized"
        elif r.status_code == 400:
            try:    note = f"❌ 400 {r.json().get('error','')[:50]}"
            except: note = "❌ 400"
        elif r.status_code == 410:
            note = "❌ 410 gone"
        else:
            note = f"❌ {r.status_code}"
    except Exception as e:
        note = f"ERR {str(e)[:40]}"
    print(f"{label:<26} {r.status_code if 'r' in dir() else '---':<8} {note}")

print()
if winners:
    print("✅ Working endpoints:")
    for lbl, url in winners:
        print(f"   {lbl}")
        print(f"   {url}")
else:
    print("❌ No working endpoints found.")
