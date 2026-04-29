"""
check_hf_endpoint.py
Finds the correct HF Inference API endpoint and verifies the token.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)
key = os.getenv("HF_API_KEY", "")
print(f"Key: {key[:12]}...")

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}
payload = {
    "inputs": "a red circle",
    "options": {"wait_for_model": False},
}

endpoints = [
    ("Old (api-inference)",     "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1"),
    ("New router v3",           "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-2-1"),
    ("New router text-to-image","https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-2-1/text-to-image"),
]

print()
for name, url in endpoints:
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        ct = r.headers.get("Content-Type", "")
        print(f"[{name}]")
        print(f"  Status : {r.status_code}")
        print(f"  Content-Type: {ct[:60]}")
        if r.status_code == 200 and "image" in ct:
            print(f"  RESULT : SUCCESS - {len(r.content):,} bytes received")
        elif r.status_code == 503:
            print(f"  RESULT : Model loading - token is VALID")
        elif r.status_code == 429:
            print(f"  RESULT : Rate limited - token is VALID")
        elif r.status_code == 401:
            print(f"  RESULT : UNAUTHORIZED - token rejected")
            print(f"  Body   : {r.text[:200]}")
        elif r.status_code == 404:
            print(f"  RESULT : Endpoint not found (404)")
            print(f"  Body   : {r.text[:200]}")
        else:
            print(f"  RESULT : HTTP {r.status_code}")
            print(f"  Body   : {r.text[:200]}")
    except Exception as e:
        print(f"[{name}] ERROR: {e}")
    print()
