"""Gemini embedding client with configured-key rotation and FTS-friendly fallback."""
import os
import math

import httpx
from dotenv import load_dotenv

import logutil
import providers

load_dotenv()

EMBEDDING_MODEL = os.getenv("PDF_EMBEDDING_MODEL", "models/text-embedding-004").strip()
EMBEDDING_URL = "https://generativelanguage.googleapis.com/v1beta/models:batchEmbedContents"


async def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Return normalized-compatible vectors, or None when embedding service is unavailable."""
    keys = providers.PROVIDERS.get("gemini", {}).get("keys", [])
    if not keys or not texts:
        return None

    all_vectors = []
    model = EMBEDDING_MODEL if EMBEDDING_MODEL.startswith("models/") else f"models/{EMBEDDING_MODEL}"
    for offset in range(0, len(texts), 100):
        batch = texts[offset:offset + 100]
        vectors_for_batch = None
        for key_index, key in enumerate(keys):
            try:
                requests = [
                    {"model": model, "content": {"parts": [{"text": text}]}}
                    for text in batch
                ]
                response = await providers.get_client().post(
                    EMBEDDING_URL,
                    params={"key": key},
                    json={"requests": requests},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
                vectors = [
                    item.get("values") if isinstance(item, dict) else None
                    for item in embeddings
                ] if isinstance(embeddings, list) else []
                if len(vectors) != len(batch) or any(
                    not isinstance(vector, list)
                    or not vector
                    or any(
                        not isinstance(value, (int, float)) or not math.isfinite(value)
                        for value in vector
                    )
                    for vector in vectors
                ):
                    raise ValueError("Embedding provider returned an invalid vector response.")
                vectors_for_batch = [[float(value) for value in vector] for vector in vectors]
                break
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                logutil.log(
                    "embedding_provider_failure",
                    provider="gemini",
                    key_index=key_index + 1,
                    reason=type(error).__name__,
                )
        if vectors_for_batch is None:
            return None
        all_vectors.extend(vectors_for_batch)
    return all_vectors
