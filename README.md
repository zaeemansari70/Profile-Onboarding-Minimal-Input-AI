# Brand Onboarding Prototype

This prototype automates brand onboarding from minimal customer input:

- company name
- one or more official domains

From that input, it performs a small, ethical crawl and produces an onboarding profile with:

- likely official or related domains
- brand assets such as favicons, logos, and `og:image`
- business keywords
- key people
- social profile links
- a short company summary

## Stack

- Python
- FastAPI
- Jinja2 templates
- Bootstrap via CDN
- Crawl4AI
- OpenAI API for normalization only
- Pydantic
- Qdrant local vector database

## Runtime Note

Use Python 3.10 or newer for the intended Crawl4AI path. The prototype includes a `requests` fallback for demo resilience, but the assignment-aligned setup is Python 3.10+ with Crawl4AI available.

## Flow

1. Parse customer input.
2. Check `robots.txt`.
3. Parse `sitemap.xml`.
4. Select a few high-signal URLs.
5. Crawl pages sequentially.
6. Extract deterministic signals with Python.
7. Normalize and consolidate with OpenAI.
8. Store the onboarding profile in a local vector database.
9. Render the onboarding profile in a simple UI.

## Project Structure

```text
brand_onboarding/
├── app.py
├── crawler.py
├── extractor.py
├── llm_utils.py
├── models.py
├── templates/
│   ├── index.html
│   └── results.html
├── static/
│   └── styles.css
├── requirements.txt
├── .env.example
├── how_to_run.md
├── README.md
└── analysis.md
```

## Important Constraints

- No database
- No authentication
- No React
- No agents
- No concurrent crawling
- No detection engine

## Running

See [how_to_run.md](./how_to_run.md).
