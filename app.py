from pathlib import Path
from typing import List
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from .crawler import crawl_domains, get_crawl4ai_status_message, normalize_domain
    from .extractor import extract_all
    from .llm_utils import build_profile
    from .models import PipelineResult
    from .vector_store import store_profile
except ImportError:  # pragma: no cover - allows running as a flat script
    from crawler import crawl_domains, get_crawl4ai_status_message, normalize_domain
    from extractor import extract_all
    from llm_utils import build_profile
    from models import PipelineResult
    from vector_store import store_profile


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)
app = FastAPI(title="Brand Onboarding Prototype")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def parse_domains(raw_domains: str) -> List[str]:
    domains: List[str] = []
    for token in raw_domains.replace("\n", ",").split(","):
        normalized = normalize_domain(token)
        if normalized and normalized not in domains:
            domains.append(normalized)
    return domains


def run_pipeline(company_name: str, domains: List[str]) -> PipelineResult:
    pages, robots, sitemaps = crawl_domains(domains)
    raw_extraction = extract_all(company_name=company_name, official_domains=domains, pages=pages)
    crawl4ai_status = get_crawl4ai_status_message()
    if crawl4ai_status != "Crawl4AI available.":
        raw_extraction.warnings.append(
            f"{crawl4ai_status} The prototype used the built-in requests fallback for page fetching."
        )
    crawl_errors = [f"{page.url}: {page.error}" for page in pages if page.error]
    profile = build_profile(
        company_name=company_name,
        official_domains=domains,
        pages_crawled=len(pages),
        crawl_errors=crawl_errors,
        raw_extraction=raw_extraction,
    )
    try:
        store_profile(profile)
    except Exception as exc:
        LOGGER.warning("Failed to store onboarding profile in vector DB: %s", exc)
    return PipelineResult(profile=profile, pages=pages, robots=robots, sitemaps=sitemaps)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "title": "Brand Onboarding Prototype",
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
def analyze(
    request: Request,
    company_name: str = Form(...),
    domains: str = Form(...),
) -> HTMLResponse:
    parsed_domains = parse_domains(domains)
    if not company_name.strip() or not parsed_domains:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "title": "Brand Onboarding Prototype",
                "error": "Please provide a company name and at least one valid domain.",
                "company_name": company_name,
                "domains": domains,
            },
            status_code=400,
        )

    result = run_pipeline(company_name=company_name.strip(), domains=parsed_domains)
    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "request": request,
            "title": "Onboarding Results",
            "result": result,
            "company_name": company_name.strip(),
            "domains": parsed_domains,
        },
    )
