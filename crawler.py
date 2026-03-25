import asyncio
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

os.environ.setdefault(
    "CRAWL4_AI_BASE_DIRECTORY",
    str(Path(__file__).resolve().parent / ".crawl4ai_runtime"),
)

try:
    from .models import PageData
except ImportError:  # pragma: no cover - allows running as a flat script
    from models import PageData

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    CRAWL4AI_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - runtime fallback
    AsyncWebCrawler = None
    BrowserConfig = None
    CacheMode = None
    CrawlerRunConfig = None
    CRAWL4AI_IMPORT_ERROR = str(exc)


LOGGER = logging.getLogger(__name__)

HIGH_SIGNAL_TERMS = [
    "about",
    "company",
    "team",
    "leadership",
    "executives",
    "contact",
    "careers",
    "press",
    "investor",
    "who-we-are",
]

SOCIAL_DOMAINS = {
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "facebook.com",
    "tiktok.com",
}

REQUEST_TIMEOUT = 12
MAX_PAGES_PER_DOMAIN = 5
USER_AGENT = (
    "BrandOnboardingPrototype/1.0 "
    "(ethical limited crawl for brand onboarding intelligence)"
)


def get_crawl4ai_status_message() -> str:
    if AsyncWebCrawler is not None:
        return "Crawl4AI available."
    if "unsupported operand type(s) for |" in CRAWL4AI_IMPORT_ERROR and sys.version_info < (3, 10):
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        return (
            "Crawl4AI could not load because this runtime is using Python "
            f"{version}. Use Python 3.10+ for the intended Crawl4AI path."
        )
    if CRAWL4AI_IMPORT_ERROR:
        return f"Crawl4AI could not load: {CRAWL4AI_IMPORT_ERROR}"
    return "Crawl4AI is not installed."


def normalize_domain(raw_domain: str) -> str:
    value = raw_domain.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    netloc = parsed.netloc.lower().strip()
    return netloc.replace("www.", "", 1)


def build_base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}"


def is_same_domain(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "", 1)
    return bool(host) and host.endswith(normalize_domain(domain))


def fetch_robots_txt(base_url: str) -> Dict:
    robots_url = urljoin(base_url, "/robots.txt")
    status = {
        "domain": normalize_domain(base_url),
        "url": robots_url,
        "status": "missing",
        "detail": "",
        "disallowed_paths": [],
    }
    try:
        response = requests.get(
            robots_url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            status["detail"] = f"robots.txt returned {response.status_code}"
            return status

        disallowed = []
        for line in response.text.splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            if cleaned.lower().startswith("disallow:"):
                _, _, path = cleaned.partition(":")
                path = path.strip()
                if path:
                    disallowed.append(path)
        status["status"] = "found"
        status["detail"] = "Parsed simple Disallow rules."
        status["disallowed_paths"] = disallowed[:50]
        return status
    except requests.RequestException as exc:
        status["status"] = "error"
        status["detail"] = str(exc)
        return status


def fetch_sitemap_urls(base_url: str) -> Tuple[Dict, List[str]]:
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    status = {
        "domain": normalize_domain(base_url),
        "url": sitemap_url,
        "status": "missing",
        "detail": "",
        "urls_found": 0,
    }
    try:
        response = requests.get(
            sitemap_url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            status["detail"] = f"sitemap.xml returned {response.status_code}"
            return status, []

        root = ElementTree.fromstring(response.content)
        urls = [node.text.strip() for node in root.iter() if node.tag.endswith("loc") and node.text]
        status["status"] = "found"
        status["detail"] = "Parsed sitemap.xml"
        status["urls_found"] = len(urls)
        return status, urls
    except ElementTree.ParseError as exc:
        status["status"] = "error"
        status["detail"] = f"Invalid XML: {exc}"
        return status, []
    except requests.RequestException as exc:
        status["status"] = "error"
        status["detail"] = str(exc)
        return status, []


def _path_score(url: str) -> int:
    lowered = url.lower()
    score = 0
    for index, term in enumerate(HIGH_SIGNAL_TERMS):
        if term in lowered:
            score += 100 - index
    return score


def select_candidate_urls(
    domain: str,
    homepage_url: str,
    sitemap_urls: List[str],
    homepage_links: List[str],
    disallowed_paths: List[str],
    max_pages: int = MAX_PAGES_PER_DOMAIN,
) -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = [(homepage_url, "internal_links")]

    def is_allowed(url: str) -> bool:
        path = urlparse(url).path or "/"
        return not any(path.startswith(rule) for rule in disallowed_paths if rule not in {"", "/"})

    filtered_sitemap = [
        url for url in sitemap_urls if is_same_domain(url, domain) and is_allowed(url)
    ]
    filtered_homepage_links = [
        url for url in homepage_links if is_same_domain(url, domain) and is_allowed(url)
    ]

    source = "sitemap" if filtered_sitemap else "internal_links"
    pool = filtered_sitemap or filtered_homepage_links
    ranked = sorted(set(pool), key=lambda item: (_path_score(item), len(item)), reverse=True)

    for url in ranked:
        if url == homepage_url:
            continue
        candidates.append((url, source))
        if len(candidates) >= max_pages:
            break

    return candidates[:max_pages]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_html_details(url: str, html: str, source: str, error: str = None) -> Dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _normalize_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    headings = [
        _normalize_text(tag.get_text(" ", strip=True))
        for tag in soup.find_all(["h1", "h2", "h3"])
        if _normalize_text(tag.get_text(" ", strip=True))
    ]
    meta_description_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    meta_description = _normalize_text(meta_description_tag.get("content", "") if meta_description_tag else "")

    links = []
    images = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor["href"].strip())
        if href.startswith("http"):
            links.append(href)
    for image in soup.find_all("img", src=True):
        src = urljoin(url, image["src"].strip())
        if src.startswith("http"):
            images.append(src)

    favicon = ""
    favicon_tag = soup.find("link", attrs={"rel": re.compile("icon", re.I)})
    if favicon_tag and favicon_tag.get("href"):
        favicon = urljoin(url, favicon_tag["href"].strip())

    og_image = ""
    og_image_tag = soup.find("meta", attrs={"property": "og:image"})
    if og_image_tag and og_image_tag.get("content"):
        og_image = urljoin(url, og_image_tag["content"].strip())

    canonical_url = ""
    canonical_tag = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    if canonical_tag and canonical_tag.get("href"):
        canonical_url = urljoin(url, canonical_tag["href"].strip())

    json_ld = []
    for script_tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        script_text = script_tag.string or script_tag.get_text(" ", strip=True)
        cleaned = script_text.strip() if script_text else ""
        if cleaned:
            json_ld.append(cleaned[:12000])

    text = _normalize_text(soup.get_text(" ", strip=True))
    return {
        "url": url,
        "title": title,
        "text": text[:12000],
        "html": html[:50000],
        "links": list(dict.fromkeys(links))[:200],
        "images": list(dict.fromkeys(images))[:100],
        "source": source,
        "error": error,
        "headings": headings[:20],
        "meta_description": meta_description,
        "favicon": favicon,
        "og_image": og_image,
        "canonical_url": canonical_url,
        "json_ld": json_ld[:10],
    }


async def _crawl_with_crawl4ai(url: str) -> Dict:
    if AsyncWebCrawler is None:
        raise RuntimeError(get_crawl4ai_status_message())

    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS if CacheMode else None,
        word_count_threshold=1,
        screenshot=False,
        verbose=False,
    )
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
        html = getattr(result, "cleaned_html", None) or getattr(result, "html", None) or ""
        return {
            "success": getattr(result, "success", bool(html)),
            "html": html,
            "error": getattr(result, "error_message", "") or "",
        }


def _crawl_with_requests(url: str) -> Dict:
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return {"success": True, "html": response.text, "error": ""}


def crawl_page(url: str, source: str) -> PageData:
    try:
        crawl_result = asyncio.run(_crawl_with_crawl4ai(url))
    except Exception as crawl_exc:
        LOGGER.warning("Crawl4AI failed for %s: %s", url, crawl_exc)
        try:
            crawl_result = _crawl_with_requests(url)
        except Exception as request_exc:
            return PageData(
                **_extract_html_details(url=url, html="", source=source, error=str(request_exc))
            )

    details = _extract_html_details(
        url=url,
        html=crawl_result.get("html", ""),
        source=source,
        error=None if crawl_result.get("success") else crawl_result.get("error") or "Unknown crawl error",
    )
    return PageData(**details)


def crawl_domain(domain: str, max_pages: int = MAX_PAGES_PER_DOMAIN) -> Tuple[List[PageData], Dict, Dict]:
    normalized = normalize_domain(domain)
    homepage_url = build_base_url(normalized)
    robots_status = fetch_robots_txt(homepage_url)
    sitemap_status, sitemap_urls = fetch_sitemap_urls(homepage_url)

    homepage_page = crawl_page(homepage_url, source="internal_links")
    homepage_links = homepage_page.links if not homepage_page.error else []
    candidates = select_candidate_urls(
        domain=normalized,
        homepage_url=homepage_url,
        sitemap_urls=sitemap_urls,
        homepage_links=homepage_links,
        disallowed_paths=robots_status.get("disallowed_paths", []),
        max_pages=max_pages,
    )

    pages: List[PageData] = []
    seen = set()
    for url, source in candidates:
        if url in seen:
            continue
        seen.add(url)
        if url == homepage_page.url:
            page = homepage_page
            page.source = source
        else:
            page = crawl_page(url, source=source)
        pages.append(page)

    return pages, robots_status, sitemap_status


def crawl_domains(domains: List[str], max_pages_per_domain: int = MAX_PAGES_PER_DOMAIN) -> Tuple[List[PageData], List[Dict], List[Dict]]:
    all_pages: List[PageData] = []
    robots_statuses: List[Dict] = []
    sitemap_statuses: List[Dict] = []
    for domain in domains:
        pages, robots_status, sitemap_status = crawl_domain(domain, max_pages=max_pages_per_domain)
        all_pages.extend(pages)
        robots_statuses.append(robots_status)
        sitemap_statuses.append(sitemap_status)
    return all_pages, robots_statuses, sitemap_statuses
