"""
find_working_model.py
Discovers which text-to-image models work with the current HF token
by probing the new router endpoint.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)
key = os.getenv("HF_API_KEY", "")
print(f"Testing with key: {key[:12]}...\n")

headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}
payload = {
    "inputs": "a red circle",
    "options": {"wait_for_model": False},
}

# Models to probe — mix of popular text-to-image models
candidates = [
    "black-forest-labs/FLUX.1-schnell",
    "black-forest-labs/FLUX.1-dev",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "stabilityai/stable-diffusion-2-1",
    "runwayml/stable-diffusion-v1-5",
    "CompVis/stable-diffusion-v1-4",
    "stabilityai/sdxl-turbo",
    "Lykon/dreamshaper-8",
    "SG161222/Realistic_Vision_V6.0_B1_noVAE",
]

# Try both endpoint patterns
url_patterns = [
    "https://router.huggingface.co/hf-inference/models/{model}",
    "https://api-inference.huggingface.co/models/{model}",
]

print(f"{'Model':<55} {'Router':<12} {'Old API':<12}")
print("-" * 80)

working = []

for model in candidates:
    results = []
    for pattern in url_patterns:
        url = pattern.format(model=model)
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "image" in ct:
                results.append("✅ IMAGE")
                if pattern == url_patterns[0] and model not in working:
                    working.append((model, pattern))
            elif r.status_code == 503:
                results.append("⏳ LOADING")
                if pattern == url_patterns[0] and model not in working:
                    working.append((model, pattern))
            elif r.status_code == 429:
                results.append("⚠️  RATE")
                if pattern == url_patterns[0] and model not in working:
                    working.append((model, pattern))
            elif r.status_code == 400:
                try:
                    err = r.json().get("error", "")[:30]
                except Exception:
                    err = ""
                results.append(f"❌ 400 {err}")
            elif r.status_code == 401:
                results.append("🔑 401 AUTH")
            elif r.status_code == 404:
                results.append("❌ 404")
            else:
                results.append(f"❌ {r.status_code}")
        except Exception as e:
            results.append(f"ERR {str(e)[:20]}")

    print(f"{model:<55} {results[0]:<20} {results[1]:<20}")

print()
if working:
    print("✅ Working models (use these in .env / config):")
    for model, pattern in working:
        print(f"   {model}")
        print(f"   Endpoint: {pattern.format(model=model)}")
else:
    print("❌ No models responded successfully.")
    print("   Possible causes:")
    print("   1. Token lacks 'Make calls to Inference Providers' permission")
    print("   2. Free tier credits exhausted")
    print("   3. Network issue")
