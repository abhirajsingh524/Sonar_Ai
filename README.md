# ◈ SONAR — AI Image Generator

A production-ready, full-stack web application that converts text prompts into images using **Stable Diffusion** via the **Hugging Face Inference API**, with intelligent fallback to local generation.

**Stack:** Flask · Python · Vanilla JS · MongoDB Atlas · Render

---

## 🎯 Key Features

- **Dual-Model Pipeline**: Primary HF API with automatic fallback to local/placeholder generation
- **Robust Error Handling**: Retry logic, timeout management, graceful degradation
- **MongoDB Integration**: Persistent generation history with metadata
- **Clean Architecture**: Modular design with separation of concerns
- **Comprehensive Testing**: 17 unit & integration tests with 100% pass rate
- **Production-Ready**: Logging, security, input validation, error recovery

---

## 📁 Project Structure

```
sonar/
├── app.py                      # Flask application factory & entry point
├── routes/
│   ├── __init__.py
│   └── generate.py             # API endpoints (/generate, /history, /health)
├── services/
│   ├── __init__.py
│   └── image_service.py        # Dual-model pipeline orchestration
├── models/
│   ├── __init__.py
│   ├── hf_model.py             # Tier-1: Hugging Face API client
│   └── local_model.py          # Tier-2: Local/placeholder generation
├── db/
│   ├── __init__.py
│   └── mongo.py                # MongoDB connection singleton
├── utils/
│   ├── __init__.py
│   └── config.py               # Centralized configuration
├── static/
│   ├── css/style.css           # Dark sci-fi UI design
│   ├── js/main.js              # Frontend logic
│   └── images/                 # Generated images storage
├── templates/
│   └── index.html              # Single-page application
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # Pytest configuration
│   └── test_generate.py        # Comprehensive test suite
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

---

## 🚀 Quick Start (Local Development)

### 1. Prerequisites

- Python 3.9+ (tested on 3.13)
- pip or uv package manager
- Hugging Face account (free tier works)

### 2. Clone & Install

```bash
git clone <your-repo-url>
cd sonar
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```env
# Required: Get from https://huggingface.co/settings/tokens
HF_API_KEY=hf_your_token_here

# Optional: MongoDB Atlas connection string
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true&w=majority

# Optional: Tuning parameters
HF_TIMEOUT=90
HF_MAX_RETRIES=3
FLASK_DEBUG=false
PORT=5000
LOG_LEVEL=INFO
```

### 4. Run

```bash
python app.py
```

Visit **http://localhost:5000**

---

## 🧪 Testing

Run the full test suite:

```bash
pytest tests/ -v
```

Run specific test categories:

```bash
# HF API client tests
pytest tests/test_generate.py::TestHFModel -v

# Service layer tests
pytest tests/test_generate.py::TestImageService -v

# HTTP endpoint tests
pytest tests/test_generate.py::TestFlaskRoutes -v

# MongoDB persistence tests
pytest tests/test_generate.py::TestMongoPersistence -v
```

Test coverage:
- ✅ HF API success & failure scenarios
- ✅ Retry logic & timeout handling
- ✅ Fallback pipeline execution
- ✅ Input validation (empty, too long, invalid model)
- ✅ MongoDB persistence (success & failure)
- ✅ HTTP endpoints (200, 400, 500 responses)

---

## ☁️ Deploy to Render

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: SONAR AI Image Generator"
git remote add origin <your-github-repo-url>
git push -u origin main
```

### 2. Create Render Web Service

1. Go to [render.com](https://render.com) → **New Web Service**
2. Connect your GitHub repository
3. Configure:
   - **Name**: `sonar-ai-generator`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - **Instance Type**: Free (or Starter for better performance)

### 3. Add Environment Variables

In Render dashboard → Environment:

```
HF_API_KEY=hf_your_actual_token
MONGO_URI=mongodb+srv://...  (optional)
HF_TIMEOUT=90
HF_MAX_RETRIES=3
LOG_LEVEL=INFO
```

### 4. Deploy

Click **Create Web Service**. Render will:
- Clone your repo
- Install dependencies
- Start the Flask app with Gunicorn
- Provide a public URL (e.g., `https://sonar-ai-generator.onrender.com`)

**Note:** Free tier has cold-start delays (30-90s after inactivity).

---

## 🔌 API Reference

### `POST /generate`

Generate an image from a text prompt.

**Request:**
```json
{
  "prompt": "A futuristic city at sunset, neon reflections",
  "model": "sd21"
}
```

**Model Options:**
- `sd21` — Stable Diffusion 2.1 (default, fastest)
- `sdxl` — Stable Diffusion XL (higher quality, slower)
- `flux` — FLUX.1-schnell (experimental)

**Success Response (200):**
```json
{
  "image_url": "/static/images/sonar_1234567890_abc123.png",
  "prompt": "A futuristic city at sunset...",
  "model_used": "hf_api",
  "model_key": "sd21",
  "fallback": false,
  "fallback_reason": ""
}
```

**Fallback Response (200):**
```json
{
  "image_url": "/static/images/sonar_1234567890_def456.png",
  "prompt": "A futuristic city at sunset...",
  "model_used": "local",
  "model_key": "sd21",
  "fallback": true,
  "fallback_reason": "Image generation failed after 3 attempts. Last error: Request timed out"
}
```

**Error Response (400/500):**
```json
{
  "error": "Prompt cannot be empty."
}
```

---

### `GET /history`

Retrieve last 20 generations (requires MongoDB).

**Response:**
```json
{
  "items": [
    {
      "prompt": "A futuristic city...",
      "image_url": "/static/images/sonar_xxx.png",
      "model_used": "hf_api",
      "model_key": "sd21",
      "created_at": "2026-04-28T14:30:00.000Z"
    }
  ]
}
```

---

### `GET /health`

Liveness probe for monitoring.

**Response:**
```json
{
  "status": "ok",
  "api_key": true,
  "database": true
}
```

---

## 🧠 Architecture Deep Dive

### Dual-Model Pipeline

```
User Prompt
    ↓
Flask Route (/generate)
    ↓
Image Service (services/image_service.py)
    ↓
┌─────────────────────────────────────┐
│ Tier 1: Hugging Face API            │
│ - Retry up to 3 times               │
│ - Exponential backoff               │
│ - Timeout: 90s per attempt          │
│ - Handles 503 (model loading)       │
│ - Handles 429 (rate limit)          │
└─────────────────────────────────────┘
    ↓ (on failure)
┌─────────────────────────────────────┐
│ Tier 2: Local/Placeholder           │
│ - Generates styled placeholder PNG  │
│ - Shows prompt text on dark grid    │
│ - Never fails (always returns bytes)│
└─────────────────────────────────────┘
    ↓
Save PNG to static/images/
    ↓
Persist metadata to MongoDB (optional)
    ↓
Return image_url + metadata
```

### Error Handling Strategy

1. **HF API Errors**:
   - `401` → Immediate failure (invalid API key)
   - `429` → Wait for `Retry-After` header, then retry
   - `503` → Wait for `estimated_time`, then retry
   - `500/other` → Exponential backoff, then retry
   - `Timeout` → Retry with same timeout

2. **Fallback Trigger**:
   - After 3 failed HF API attempts
   - Generates placeholder PNG with Pillow
   - Returns `fallback=true` in response

3. **MongoDB Failures**:
   - Non-fatal (logged but doesn't crash pipeline)
   - History unavailable if DB is down

---

## 🔐 Security

- ✅ API keys stored in `.env` (never committed)
- ✅ Input validation (prompt length, model whitelist)
- ✅ No code execution from user input
- ✅ CORS headers (can be configured if needed)
- ✅ Rate limiting (via HF API tier limits)

---

## ⚙️ Configuration

All settings in `utils/config.py` read from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_API_KEY` | *(required)* | Hugging Face API token |
| `MONGO_URI` | `""` | MongoDB connection string (optional) |
| `MONGO_DB` | `sonar` | Database name |
| `MONGO_COL` | `generations` | Collection name |
| `HF_TIMEOUT` | `90` | Seconds per API request |
| `HF_MAX_RETRIES` | `3` | Total retry attempts |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |
| `PORT` | `5000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## 🐛 Troubleshooting

### Issue: "HF_API_KEY is not configured"

**Solution:** Add your Hugging Face token to `.env`:
```bash
HF_API_KEY=hf_your_token_here
```
Get a token at https://huggingface.co/settings/tokens (READ access is sufficient).

---

### Issue: Images not generating (always fallback mode)

**Possible Causes:**
1. Invalid/expired API key → Check token at HF settings
2. Rate limit exceeded → Wait 1 hour or upgrade HF tier
3. Model loading (503) → Wait 30-60s, then retry
4. Network issues → Check internet connection

**Debug:**
```bash
# Run with verbose logging
LOG_LEVEL=DEBUG python app.py
```

---

### Issue: MongoDB connection failed

**Solution:** MongoDB is optional. If you see:
```
⚠️  MongoDB unavailable: ...
```
This is non-fatal. History will be disabled but image generation works.

To fix:
1. Create free cluster at https://cloud.mongodb.com
2. Get connection string
3. Add to `.env`: `MONGO_URI=mongodb+srv://...`

---

### Issue: Tests failing

**Solution:**
```bash
# Ensure pytest is installed
pip install pytest

# Run with verbose output
pytest tests/ -v -s

# Check pytest.ini exists (disables log capture)
cat pytest.ini
```

---

## 📊 Performance

### Benchmarks (Free Tier)

| Metric | Value |
|--------|-------|
| HF API latency | 15-45s (cold start), 5-15s (warm) |
| Fallback generation | <1s |
| Memory usage | ~150MB (Flask + deps) |
| Concurrent requests | 1-2 (free tier) |

### Optimization Tips

1. **Upgrade HF Tier**: Paid tiers have faster inference & higher rate limits
2. **Use Render Starter**: Faster cold starts, more RAM
3. **Enable Caching**: Add Redis for prompt → image_url cache
4. **Async Workers**: Use `gunicorn --worker-class gevent` for concurrency

---

## 🔮 Future Enhancements

- [ ] Add Redis caching for duplicate prompts
- [ ] Implement user authentication (JWT)
- [ ] Add image upscaling (Real-ESRGAN)
- [ ] Support batch generation
- [ ] Add negative prompts & advanced parameters
- [ ] Implement rate limiting per user
- [ ] Add image-to-image generation
- [ ] Support custom LoRA models

---

## 📄 License

!!Permission to get the license first and then  use it in your project.

---

## 🙏 Acknowledgments

- **Hugging Face** for the Inference API
- **Stability AI** for Stable Diffusion models
- **Flask** for the web framework
- **MongoDB** for persistence

---

## 📞 Support

For issues or questions:
1. Check the Troubleshooting section above
2. Review test cases in `tests/test_generate.py`
3. Check logs: `LOG_LEVEL=DEBUG python app.py`
4. Open an issue on GitHub

---

**Built with ❤️ for the AI community**
