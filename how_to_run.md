# How To Run

1. Create and activate a virtual environment.

```bash
python3.10 -m venv .venv
source .venv/bin/activate
```

Use Python 3.10 or newer. Current Crawl4AI releases do not reliably import on Python 3.9.

2. Install dependencies.

```bash
cd brand_onboarding
pip install -r requirements.txt
```

3. Configure environment variables.

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` if you want normalization through OpenAI. The app still works without it.

4. Start the FastAPI app.

```bash
uvicorn app:app --reload
```

5. Open `http://127.0.0.1:8000`.

## Notes

- The crawler uses a limited, sequential process.
- `robots.txt` and `sitemap.xml` are checked before page selection.
- Crawl4AI is used for page crawling when available. A simple `requests` fallback is included to keep the prototype usable if Crawl4AI has local runtime issues.
- Each completed onboarding profile is stored in a local Qdrant vector database under `brand_onboarding/vector_db/`.
