import json
import re
from collections import Counter
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from .models import PageData, PersonSignal, RawExtraction, Signal
except ImportError:  # pragma: no cover - allows running as a flat script
    from models import PageData, PersonSignal, RawExtraction, Signal


SOCIAL_PATTERNS = {
    "linkedin.com": "LinkedIn",
    "instagram.com": "Instagram",
    "twitter.com": "X/Twitter",
    "x.com": "X/Twitter",
    "youtube.com": "YouTube",
    "facebook.com": "Facebook",
    "tiktok.com": "TikTok",
}

ROLE_PATTERN = re.compile(
    r"\b(CEO|Founder|Co-Founder|President|Chief [A-Za-z ]+|Director|Managing Director|"
    r"Chief Executive Officer|Chief Technology Officer|Chief Marketing Officer|"
    r"Chief Product Officer|Chief Financial Officer|Vice President|General Manager|Head of [A-Za-z ]+)\b",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+){1,2})\b")
WORD_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z\-]{2,}\b")
STOPWORDS = {
    "about",
    "brand",
    "careers",
    "company",
    "contact",
    "cookies",
    "home",
    "leadership",
    "news",
    "page",
    "policy",
    "press",
    "privacy",
    "products",
    "services",
    "solutions",
    "team",
    "terms",
    "welcome",
}


CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
EXTERNAL_LOOKUP_TIMEOUT = 8
EXTERNAL_USER_AGENT = "BrandOnboardingPrototype/1.0"
LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "plc",
    "group",
    "holdings",
}
CONTEXT_TERMS = ("about", "company", "contact", "team", "leadership", "press", "investor", "privacy", "terms", "help")
PEOPLE_CONTEXT_TERMS = ("team", "leadership", "executive", "about", "company", "investor", "management")
EXCLUDED_RELATED_DOMAINS = {
    "amazonaws.com",
    "apple.com",
    "facebook.com",
    "github.com",
    "google.com",
    "greenhouse.io",
    "instagram.com",
    "linkedin.com",
    "lever.co",
    "microsoft.com",
    "salesforce.com",
    "shopify.com",
    "tiktok.com",
    "twitter.com",
    "workday.com",
    "x.com",
    "youtube.com",
}
WIKIPEDIA_FIELDS = ("founder", "founders", "key people", "ceo", "president", "owner")


def _dedupe_signals(signals: Iterable[Signal]) -> List[Signal]:
    unique: Dict[str, Signal] = {}
    for signal in signals:
        key = signal.value.lower().strip()
        current = unique.get(key)
        if current is None or CONFIDENCE_RANK[signal.confidence] > CONFIDENCE_RANK[current.confidence]:
            unique[key] = signal
    return list(unique.values())


def _dedupe_people(people: Iterable[PersonSignal]) -> List[PersonSignal]:
    unique: Dict[Tuple[str, str], PersonSignal] = {}
    for person in people:
        key = (person.name.lower().strip(), person.role.lower().strip())
        if key not in unique:
            unique[key] = person
    return list(unique.values())


def _confidence_from_count(count: int) -> str:
    if count >= 3:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _base_domain_label(domain: str) -> str:
    host = domain.lower().replace("www.", "", 1)
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        return parts[0]
    return host


def _brand_tokens(company_name: str, official_domains: List[str]) -> List[str]:
    name_tokens = [
        _normalize_token(part)
        for part in re.split(r"[^a-zA-Z0-9]+", company_name)
        if part and _normalize_token(part) not in LEGAL_SUFFIXES and len(_normalize_token(part)) >= 3
    ]
    domain_tokens = [_normalize_token(_base_domain_label(domain)) for domain in official_domains]
    tokens = [token for token in [*name_tokens, *domain_tokens] if token]
    return list(dict.fromkeys(tokens))


def _page_context_score(url: str) -> int:
    lowered = url.lower()
    return sum(1 for term in CONTEXT_TERMS if term in lowered)


def _is_excluded_related_domain(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in EXCLUDED_RELATED_DOMAINS)


def _confidence_sort_key(level: str) -> int:
    return CONFIDENCE_RANK.get(level, 0)


def _parse_json_ld_objects(page: PageData) -> List[dict]:
    objects: List[dict] = []
    for block in page.json_ld:
        try:
            parsed = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            objects.extend(item for item in parsed if isinstance(item, dict))
        elif isinstance(parsed, dict):
            if isinstance(parsed.get("@graph"), list):
                objects.extend(item for item in parsed["@graph"] if isinstance(item, dict))
            objects.append(parsed)
    return objects


def _extract_same_as_links(page: PageData) -> List[str]:
    links: List[str] = []
    for obj in _parse_json_ld_objects(page):
        same_as = obj.get("sameAs")
        if isinstance(same_as, list):
            links.extend(item for item in same_as if isinstance(item, str))
        elif isinstance(same_as, str):
            links.append(same_as)
    return links


def extract_related_domains(company_name: str, official_domains: List[str], pages: List[PageData]) -> List[Signal]:
    official_hosts = {domain.lower() for domain in official_domains}
    brand_tokens = _brand_tokens(company_name, official_domains)
    candidates: Dict[str, Dict[str, object]] = {}

    for page in pages:
        page_score = _page_context_score(page.url)
        for url in page.links:
            host = urlparse(url).netloc.lower().replace("www.", "", 1)
            if not host or host in official_hosts:
                continue
            if any(host.endswith(f".{domain}") for domain in official_hosts):
                candidates[host] = {
                    "value": host,
                    "source_url": page.url,
                    "evidence": f"Observed subdomain linked from an official page: {host}",
                    "confidence": "high",
                    "reasoning": "Subdomain of an official domain observed directly in crawl data.",
                    "observed": True,
                    "score": 10,
                }
                continue
            if _is_excluded_related_domain(host):
                continue

            normalized_host = _normalize_token(host)
            brand_match = any(token in normalized_host for token in brand_tokens)
            if not brand_match and page_score == 0:
                continue

            entry = candidates.setdefault(
                host,
                {
                    "value": host,
                    "source_url": page.url,
                    "count": 0,
                    "context_score": 0,
                    "brand_match": brand_match,
                },
            )
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["context_score"] = max(int(entry.get("context_score", 0)), page_score)
            entry["brand_match"] = bool(entry.get("brand_match", False) or brand_match)

        host = urlparse(page.url).netloc.lower().replace("www.", "", 1)
        if host and host not in official_hosts and any(host.endswith(f".{domain}") for domain in official_hosts):
            candidates[host] = {
                "value": host,
                "source_url": page.url,
                "evidence": f"Crawled subdomain of an official domain: {host}",
                "confidence": "high",
                "reasoning": "Subdomain of an official domain observed directly in crawl data.",
                "observed": True,
                "score": 10,
            }

    signals: List[Signal] = []
    for host, data in candidates.items():
        if "confidence" in data:
            signals.append(Signal(**{key: value for key, value in data.items() if key in Signal.model_fields}))
            continue

        count = int(data.get("count", 0))
        context_score = int(data.get("context_score", 0))
        brand_match = bool(data.get("brand_match", False))
        if not brand_match and count < 2:
            continue

        confidence = "high" if brand_match and (count >= 2 or context_score >= 1) else "medium"
        reasoning = "Brand-aligned outbound domain repeatedly referenced from official pages."
        if context_score >= 1 and not brand_match:
            reasoning = "Domain was linked from high-signal official pages such as about, contact, or legal pages."
        signals.append(
            Signal(
                value=host,
                source_url=str(data.get("source_url", "")),
                evidence=f"Observed outbound domain {count} time(s) from official pages: {host}",
                confidence=confidence,
                reasoning=reasoning,
                observed=True,
            )
        )

    for page in pages:
        metadata_urls = [page.canonical_url, *_extract_same_as_links(page)]
        for url in metadata_urls:
            host = urlparse(url).netloc.lower().replace("www.", "", 1)
            if not host or host in official_hosts or _is_excluded_related_domain(host):
                continue
            if any(host.endswith(f".{domain}") for domain in official_hosts):
                signals.append(
                    Signal(
                        value=host,
                        source_url=page.url,
                        evidence=f"Structured metadata referenced official subdomain: {host}",
                        confidence="high",
                        reasoning="Observed in canonical or JSON-LD metadata on an official page.",
                        observed=True,
                    )
                )
                continue
            if any(token in _normalize_token(host) for token in brand_tokens):
                signals.append(
                    Signal(
                        value=host,
                        source_url=page.url,
                        evidence=f"Structured metadata referenced related domain: {host}",
                        confidence="medium",
                        reasoning="Observed in canonical or JSON-LD metadata and aligned with the brand.",
                        observed=True,
                    )
                )

    return sorted(_dedupe_signals(signals), key=lambda item: (-_confidence_sort_key(item.confidence), item.value))


def extract_brand_assets(pages: List[PageData]) -> List[Signal]:
    signals: List[Signal] = []
    for page in pages:
        if page.favicon:
            signals.append(
                Signal(
                    value=page.favicon,
                    source_url=page.url,
                    evidence="Favicon link discovered in page head.",
                    confidence="high",
                    reasoning="Favicons are usually official brand assets.",
                )
            )
        if page.og_image:
            signals.append(
                Signal(
                    value=page.og_image,
                    source_url=page.url,
                    evidence="og:image metadata found on page.",
                    confidence="high",
                    reasoning="Open Graph images are often official shareable brand assets.",
                )
            )
        for image in page.images:
            lowered = image.lower()
            if any(term in lowered for term in ["logo", "brand", "mark"]):
                signals.append(
                    Signal(
                        value=image,
                        source_url=page.url,
                        evidence=f"Image URL contains a brand term: {image}",
                        confidence="medium",
                        reasoning="The image path strongly suggests branding usage.",
                    )
                )
    return _dedupe_signals(signals)


def extract_keywords(pages: List[PageData]) -> List[Signal]:
    counts: Counter = Counter()
    evidence_map: Dict[str, Signal] = {}

    for page in pages:
        candidate_text = " ".join(
            [page.title, page.meta_description, *page.headings, page.text[:2000]]
        )
        words = [word.lower() for word in WORD_PATTERN.findall(candidate_text)]
        for word in words:
            if word in STOPWORDS or len(word) < 4:
                continue
            counts[word] += 1
            if word not in evidence_map:
                evidence_map[word] = Signal(
                    value=word,
                    source_url=page.url,
                    evidence=f"Found in title/headings/body: {word}",
                    confidence="low",
                    reasoning="Repeated across crawled high-signal pages.",
                )

    results: List[Signal] = []
    for word, count in counts.most_common(15):
        signal = evidence_map[word].model_copy()
        signal.confidence = _confidence_from_count(count)
        results.append(signal)
    return results


def _extract_people_from_text(page: PageData) -> List[PersonSignal]:
    text = " ".join([page.title, page.meta_description, *page.headings, page.text])
    lines = [segment.strip() for segment in re.split(r"[.\n|]+", text) if segment.strip()]
    people: List[PersonSignal] = []

    for line in lines:
        role_match = ROLE_PATTERN.search(line)
        if not role_match:
            continue
        names = NAME_PATTERN.findall(line)
        for name in names[:2]:
            if name.lower() in {"chief executive officer", "managing director"}:
                continue
            people.append(
                PersonSignal(
                    name=name,
                    role=role_match.group(0),
                    source_url=page.url,
                    evidence=line[:240],
                    confidence="medium" if "team" in page.url or "leadership" in page.url else "low",
                    reasoning="Name found near an executive or leadership role.",
                )
            )
    return people


def _looks_like_name(text: str) -> bool:
    return bool(NAME_PATTERN.search(text)) and len(text.split()) <= 4


def _extract_people_from_html_blocks(page: PageData) -> List[PersonSignal]:
    if not page.html:
        return []

    soup = BeautifulSoup(page.html, "html.parser")
    candidates: List[PersonSignal] = []
    selectors = [
        "[class*='team']",
        "[class*='leader']",
        "[class*='executive']",
        "[class*='profile']",
        "[class*='bio']",
        "[id*='team']",
        "[id*='leadership']",
    ]

    seen_blocks = set()
    for selector in selectors:
        for block in soup.select(selector):
            text = " ".join(block.stripped_strings)
            normalized_text = re.sub(r"\s+", " ", text).strip()
            if not normalized_text or normalized_text in seen_blocks or len(normalized_text) > 500:
                continue
            seen_blocks.add(normalized_text)

            role_match = ROLE_PATTERN.search(normalized_text)
            if not role_match:
                continue

            name = ""
            for tag in block.find_all(["h1", "h2", "h3", "h4", "strong", "b", "span"], limit=8):
                candidate = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()
                if _looks_like_name(candidate):
                    name = NAME_PATTERN.search(candidate).group(1)
                    break
            if not name:
                match = NAME_PATTERN.search(normalized_text)
                if match:
                    name = match.group(1)
            if not name:
                continue

            image_url = ""
            image_tag = block.find("img", src=True)
            if image_tag:
                image_url = image_tag["src"].strip()
                if image_url.startswith("/"):
                    parsed = urlparse(page.url)
                    image_url = f"{parsed.scheme}://{parsed.netloc}{image_url}"

            confidence = "high" if any(term in page.url.lower() for term in PEOPLE_CONTEXT_TERMS) else "medium"
            candidates.append(
                PersonSignal(
                    name=name,
                    role=role_match.group(0),
                    image_url=image_url,
                    source_url=page.url,
                    evidence=normalized_text[:240],
                    confidence=confidence,
                    reasoning="Detected a likely leadership or profile block on an official page.",
                    observed=True,
                )
            )
    return candidates


def _extract_people_from_json_ld(page: PageData) -> List[PersonSignal]:
    people: List[PersonSignal] = []
    for obj in _parse_json_ld_objects(page):
        obj_type = obj.get("@type")
        if isinstance(obj_type, list):
            obj_type = " ".join(str(item) for item in obj_type)
        obj_type = str(obj_type or "")

        if "Person" in obj_type:
            name = str(obj.get("name", "")).strip()
            role = str(obj.get("jobTitle", "")).strip()
            image_url = str(obj.get("image", "")).strip()
            if name and role:
                people.append(
                    PersonSignal(
                        name=name,
                        role=role,
                        image_url=image_url,
                        source_url=page.url,
                        evidence="JSON-LD Person object on official page.",
                        confidence="high" if any(term in page.url.lower() for term in PEOPLE_CONTEXT_TERMS) else "medium",
                        reasoning="Structured data exposed a named person and role.",
                        observed=True,
                    )
                )

        for field in ("founder", "employee", "member"):
            value = obj.get(field)
            if isinstance(value, dict):
                value = [value]
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                role = str(item.get("jobTitle", "")).strip() or field.title()
                image_url = str(item.get("image", "")).strip()
                if name:
                    people.append(
                        PersonSignal(
                            name=name,
                            role=role,
                            image_url=image_url,
                            source_url=page.url,
                            evidence=f"JSON-LD Organization field '{field}' on official page.",
                            confidence="medium",
                            reasoning="Structured data associated this person with the organization.",
                            observed=True,
                        )
                    )
    return people


def _wikipedia_slug_candidates(company_name: str, official_domains: List[str]) -> List[str]:
    candidates = [company_name.strip().replace(" ", "_")]
    candidates.extend(_base_domain_label(domain).replace("-", "_").title() for domain in official_domains)
    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


def _extract_people_from_wikipedia(company_name: str, official_domains: List[str]) -> List[PersonSignal]:
    brand_tokens = _brand_tokens(company_name, official_domains)
    for slug in _wikipedia_slug_candidates(company_name, official_domains):
        url = f"https://en.wikipedia.org/wiki/{slug}"
        try:
            response = requests.get(url, timeout=EXTERNAL_LOOKUP_TIMEOUT, headers={"User-Agent": EXTERNAL_USER_AGENT})
        except requests.RequestException:
            continue
        if response.status_code >= 400 or "Wikipedia does not have an article" in response.text:
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        page_title = soup.find("title").get_text(" ", strip=True) if soup.find("title") else ""
        if not _matches_brand(page_title, brand_tokens) and not _matches_brand(response.text[:12000], brand_tokens):
            continue

        infobox = soup.find("table", class_=re.compile("infobox"))
        if not infobox:
            continue

        people: List[PersonSignal] = []
        for row in infobox.find_all("tr"):
            header = row.find("th")
            cell = row.find("td")
            if not header or not cell:
                continue
            label = header.get_text(" ", strip=True).lower()
            if label not in WIKIPEDIA_FIELDS:
                continue
            text = re.sub(r"\[[^\]]+\]", "", cell.get_text(" ", strip=True))
            names = NAME_PATTERN.findall(text)
            for name in names[:3]:
                people.append(
                    PersonSignal(
                        name=name,
                        role=header.get_text(" ", strip=True),
                        source_url=response.url,
                        evidence=f"Wikipedia infobox field '{header.get_text(' ', strip=True)}'.",
                        confidence="low",
                        reasoning="Trusted external fallback used because official pages did not expose clear key people.",
                        observed=False,
                    )
                )
        if people:
            return people
    return []


def extract_key_people(pages: List[PageData]) -> List[PersonSignal]:
    people: List[PersonSignal] = []
    leadership_urls = ("team", "leadership", "about", "executive", "company")
    for page in pages:
        people.extend(_extract_people_from_json_ld(page))
        people.extend(_extract_people_from_html_blocks(page))
        page_people = _extract_people_from_text(page)
        for person in page_people:
            if any(token in page.url.lower() for token in leadership_urls):
                person.confidence = "high" if person.confidence == "medium" else "medium"
        people.extend(page_people)
    return _dedupe_people(people)


def _build_linkedin_slug_candidates(company_name: str, official_domains: List[str]) -> List[str]:
    name_parts = [
        part.lower()
        for part in re.split(r"[^a-zA-Z0-9]+", company_name)
        if part and _normalize_token(part) not in LEGAL_SUFFIXES
    ]
    candidates = []
    if name_parts:
        candidates.append("-".join(name_parts[:4]))
        candidates.append("".join(name_parts[:4]))
    candidates.extend(_base_domain_label(domain) for domain in official_domains)
    return [candidate for candidate in dict.fromkeys(candidates) if len(candidate) >= 3][:4]


def _matches_brand(text: str, brand_tokens: List[str]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in brand_tokens if len(token) >= 3)


def discover_external_social_profiles(company_name: str, official_domains: List[str]) -> List[Signal]:
    brand_tokens = _brand_tokens(company_name, official_domains)
    for slug in _build_linkedin_slug_candidates(company_name, official_domains):
        url = f"https://www.linkedin.com/company/{slug}/"
        try:
            response = requests.get(
                url,
                timeout=EXTERNAL_LOOKUP_TIMEOUT,
                headers={"User-Agent": EXTERNAL_USER_AGENT},
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code >= 400 or "/company/" not in response.url:
            continue
        if not _matches_brand(response.url, brand_tokens) and not _matches_brand(response.text[:12000], brand_tokens):
            continue

        return [
            Signal(
                value=response.url,
                source_url="https://www.linkedin.com/",
                evidence=f"External LinkedIn company page matched the brand using slug '{slug}'.",
                confidence="medium",
                reasoning="Used a trusted external LinkedIn fallback because no social profiles were found on the official site.",
                observed=False,
            )
        ]
    return []


def extract_social_profiles(company_name: str, official_domains: List[str], pages: List[PageData]) -> List[Signal]:
    signals: List[Signal] = []
    for page in pages:
        candidate_urls = [*page.links, *_extract_same_as_links(page)]
        for url in candidate_urls:
            host = urlparse(url).netloc.lower().replace("www.", "", 1)
            if host not in SOCIAL_PATTERNS:
                continue
            page_path = urlparse(page.url).path.strip("/")
            confidence = "high" if not page_path or page_path in {"about", "contact"} else "medium"
            evidence = f"Social link found on page: {url}"
            if url in _extract_same_as_links(page):
                evidence = f"Social profile referenced in JSON-LD sameAs metadata: {url}"
            signals.append(
                Signal(
                    value=url,
                    source_url=page.url,
                    evidence=evidence,
                    confidence=confidence,
                    reasoning=f"Observed link to {SOCIAL_PATTERNS[host]} profile.",
                )
            )
    signals = _dedupe_signals(signals)
    if signals:
        return signals
    return discover_external_social_profiles(company_name, official_domains)


def collect_warnings(pages: List[PageData]) -> List[str]:
    warnings = []
    failed_pages = [page for page in pages if page.error]
    if failed_pages:
        warnings.append(f"{len(failed_pages)} page(s) failed during crawling and were skipped or partially parsed.")
    sparse_pages = [page for page in pages if not page.text]
    if sparse_pages:
        warnings.append("Some pages returned very little visible text, which may reduce extraction quality.")
    return warnings


def extract_all(company_name: str, official_domains: List[str], pages: List[PageData]) -> RawExtraction:
    discovered_domains = extract_related_domains(company_name, official_domains, pages)
    brand_assets = extract_brand_assets(pages)
    business_keywords = extract_keywords(pages)
    key_people = extract_key_people(pages)
    if not key_people:
        key_people = _extract_people_from_wikipedia(company_name, official_domains)
    social_profiles = extract_social_profiles(company_name, official_domains, pages)
    warnings = collect_warnings(pages)
    return RawExtraction(
        discovered_domains=discovered_domains,
        brand_assets=brand_assets,
        business_keywords=business_keywords,
        key_people=key_people,
        social_profiles=social_profiles,
        warnings=warnings,
    )
