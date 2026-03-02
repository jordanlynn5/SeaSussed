"""Shared Gemini API client utilities."""

import os

from google import genai

_client: genai.Client | None = None


def get_genai_client() -> genai.Client:
    """Return a module-level cached genai.Client configured for Vertex AI."""
    global _client
    if _client is None:
        _client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION")
            or os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"),
        )
    return _client


def strip_json_fences(text: str) -> str:
    """Remove markdown code fences from a Gemini JSON response."""
    return text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
