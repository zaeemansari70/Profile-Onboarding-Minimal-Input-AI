from typing import List, Literal, Optional

from pydantic import BaseModel, Field


ConfidenceLevel = Literal["high", "medium", "low"]


class Signal(BaseModel):
    value: str
    source_url: str = ""
    evidence: str = ""
    confidence: ConfidenceLevel = "low"
    reasoning: str = ""
    observed: bool = True


class PersonSignal(BaseModel):
    name: str
    role: str = ""
    image_url: str = ""
    source_url: str = ""
    evidence: str = ""
    confidence: ConfidenceLevel = "low"
    reasoning: str = ""
    observed: bool = True


class CrawlStatus(BaseModel):
    status: str
    detail: str = ""
    disallowed_paths: List[str] = Field(default_factory=list)
    urls_found: int = 0


class PageData(BaseModel):
    url: str
    title: str = ""
    text: str = ""
    html: str = ""
    links: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    source: Literal["sitemap", "internal_links"] = "internal_links"
    error: Optional[str] = None
    headings: List[str] = Field(default_factory=list)
    meta_description: str = ""
    favicon: str = ""
    og_image: str = ""
    canonical_url: str = ""
    json_ld: List[str] = Field(default_factory=list)


class RawExtraction(BaseModel):
    discovered_domains: List[Signal] = Field(default_factory=list)
    brand_assets: List[Signal] = Field(default_factory=list)
    business_keywords: List[Signal] = Field(default_factory=list)
    key_people: List[PersonSignal] = Field(default_factory=list)
    social_profiles: List[Signal] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class OnboardingProfile(BaseModel):
    company_name: str
    official_domains: List[str] = Field(default_factory=list)
    company_summary: str = ""
    pages_crawled: int = 0
    crawl_errors: List[str] = Field(default_factory=list)
    discovered_domains: List[Signal] = Field(default_factory=list)
    brand_assets: List[Signal] = Field(default_factory=list)
    business_keywords: List[Signal] = Field(default_factory=list)
    key_people: List[PersonSignal] = Field(default_factory=list)
    social_profiles: List[Signal] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class PipelineResult(BaseModel):
    profile: OnboardingProfile
    pages: List[PageData] = Field(default_factory=list)
    robots: List[dict] = Field(default_factory=list)
    sitemaps: List[dict] = Field(default_factory=list)
