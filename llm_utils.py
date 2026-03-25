import json
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

try:
    from .models import OnboardingProfile, PersonSignal, RawExtraction, Signal
except ImportError:  # pragma: no cover - allows running as a flat script
    from models import OnboardingProfile, PersonSignal, RawExtraction, Signal


load_dotenv()


def _signal_to_dict(signal: Signal) -> Dict[str, Any]:
    return signal.model_dump()


def _person_to_dict(person: PersonSignal) -> Dict[str, Any]:
    return person.model_dump()


def normalize_with_openai(
    raw_extraction: RawExtraction,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "discovered_domains": [_signal_to_dict(item) for item in raw_extraction.discovered_domains],
            "brand_assets": [_signal_to_dict(item) for item in raw_extraction.brand_assets],
            "business_keywords": [_signal_to_dict(item) for item in raw_extraction.business_keywords],
            "key_people": [_person_to_dict(item) for item in raw_extraction.key_people],
            "social_profiles": [_signal_to_dict(item) for item in raw_extraction.social_profiles],
            "warnings": raw_extraction.warnings + ["OpenAI normalization skipped because OPENAI_API_KEY is not set."],
        }

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    prompt = f"""
You are normalizing onboarding evidence for a brand protection system.

Rules:
- Use only the provided evidence.
- Do not invent people, domains, assets, or social profiles.
- Return strict JSON only.
- Keep short reasoning strings.
- Mark each item as observed true/false based on whether it was directly seen in the evidence.
- Preserve confidence unless the evidence clearly supports lowering or raising it.

Return this JSON object:
{{
  "discovered_domains": [{{"value":"","source_url":"","evidence":"","confidence":"high|medium|low","reasoning":"","observed":true}}],
  "brand_assets": [{{"value":"","source_url":"","evidence":"","confidence":"high|medium|low","reasoning":"","observed":true}}],
  "business_keywords": [{{"value":"","source_url":"","evidence":"","confidence":"high|medium|low","reasoning":"","observed":true}}],
  "key_people": [{{"name":"","role":"","image_url":"","source_url":"","evidence":"","confidence":"high|medium|low","reasoning":"","observed":true}}],
  "social_profiles": [{{"value":"","source_url":"","evidence":"","confidence":"high|medium|low","reasoning":"","observed":true}}],
  "warnings": ["..."]
}}
Evidence: {json.dumps(raw_extraction.model_dump(), ensure_ascii=True)}
""".strip()

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
        )
        payload = json.loads(response.output_text)
        payload["warnings"] = list(dict.fromkeys(payload.get("warnings", [])))
        return payload
    except Exception as exc:
        return {
            "discovered_domains": [_signal_to_dict(item) for item in raw_extraction.discovered_domains],
            "brand_assets": [_signal_to_dict(item) for item in raw_extraction.brand_assets],
            "business_keywords": [_signal_to_dict(item) for item in raw_extraction.business_keywords],
            "key_people": [_person_to_dict(item) for item in raw_extraction.key_people],
            "social_profiles": [_signal_to_dict(item) for item in raw_extraction.social_profiles],
            "warnings": raw_extraction.warnings + [f"OpenAI normalization failed: {exc}"],
        }


def build_profile(
    company_name: str,
    official_domains: List[str],
    pages_crawled: int,
    crawl_errors: List[str],
    raw_extraction: RawExtraction,
) -> OnboardingProfile:
    normalized = normalize_with_openai(raw_extraction)
    return OnboardingProfile(
        company_name=company_name,
        official_domains=official_domains,
        company_summary="",
        pages_crawled=pages_crawled,
        crawl_errors=crawl_errors,
        discovered_domains=[Signal(**item) for item in normalized.get("discovered_domains", [])],
        brand_assets=[Signal(**item) for item in normalized.get("brand_assets", [])],
        business_keywords=[Signal(**item) for item in normalized.get("business_keywords", [])],
        key_people=[PersonSignal(**item) for item in normalized.get("key_people", [])],
        social_profiles=[Signal(**item) for item in normalized.get("social_profiles", [])],
        warnings=list(dict.fromkeys(normalized.get("warnings", raw_extraction.warnings))),
    )
