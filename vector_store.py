import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

try:
    from .models import OnboardingProfile
except ImportError:  # pragma: no cover - allows running as a flat script
    from models import OnboardingProfile


COLLECTION_NAME = "brand_profiles"
VECTOR_SIZE = 256
VECTOR_DB_PATH = Path(__file__).resolve().parent / "vector_db"


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]{2,}", (text or "").lower())


def _hash_token(token: str) -> int:
    value = 2166136261
    for char in token:
        value ^= ord(char)
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def _embed_text(text: str, vector_size: int = VECTOR_SIZE) -> List[float]:
    vector = [0.0] * vector_size
    for token in _tokenize(text):
        index = _hash_token(token) % vector_size
        vector[index] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _profile_to_document(profile: OnboardingProfile) -> str:
    keywords = ", ".join(item.value for item in profile.business_keywords[:10])
    people = ", ".join(
        f"{person.name} ({person.role})" if person.role else person.name
        for person in profile.key_people[:5]
    )
    domains = ", ".join(profile.official_domains + [item.value for item in profile.discovered_domains[:10]])
    social = ", ".join(item.value for item in profile.social_profiles[:10])
    assets = ", ".join(item.value for item in profile.brand_assets[:10])
    return "\n".join(
        [
            f"Company: {profile.company_name}",
            f"Official domains: {domains}",
            f"Keywords: {keywords}",
            f"Key people: {people}",
            f"Social profiles: {social}",
            f"Brand assets: {assets}",
        ]
    )


def _build_client() -> QdrantClient:
    VECTOR_DB_PATH.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(VECTOR_DB_PATH))


def _ensure_collection(client: QdrantClient) -> None:
    collections = client.get_collections().collections
    if any(collection.name == COLLECTION_NAME for collection in collections):
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )


def store_profile(profile: OnboardingProfile) -> str:
    client = _build_client()
    _ensure_collection(client)

    profile_id = str(uuid.uuid4())
    document = _profile_to_document(profile)
    vector = _embed_text(document)
    payload = {
        "profile_id": profile_id,
        "company_name": profile.company_name,
        "official_domains": profile.official_domains,
        "pages_crawled": profile.pages_crawled,
        "document": document,
        "profile": profile.model_dump(),
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=profile_id,
                vector=vector,
                payload=payload,
            )
        ],
    )
    return profile_id
