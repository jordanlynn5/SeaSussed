"""ADK LlmAgent for extracting product info from grocery page screenshots.

Uses Google ADK's LlmAgent with Gemini 2.5 Flash multimodal to extract
structured ProductInfo from a base64 PNG screenshot of a grocery product page.

The Runner and session service are initialized lazily on first call to
avoid import-time Vertex AI credential requirements.
"""

import base64
import json
import logging
import uuid
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from gemini_client import strip_json_fences
from models import ProductInfo

log = logging.getLogger(__name__)

SCREEN_ANALYZER_INSTRUCTION = """
You are a grocery product page analyst with expert vision capabilities.

Given a screenshot of an online grocery website, extract structured
information about the seafood product shown.

Return a JSON object matching this schema:
- is_seafood: true only if a fish, shellfish, or other seafood product
  is the primary product shown
- species: common name, as specific as possible
  (e.g. "Alaska sockeye salmon" not "salmon") — null if not determinable
- wild_or_farmed: "wild" if label says wild-caught;
  "farmed" if label says farmed/farm-raised/aquaculture;
  "unknown" if not visible
- fishing_method: specific gear type if visible (e.g. "Pole and line", "Bottom trawl")
  - null if not shown
- origin_region: catch or farm location if visible (e.g. "Bristol Bay, Alaska", "Norway")
  - Be as specific as the label allows. null if not shown.
- certifications: list of certification marks or text visible on the product. Check for:
  - "MSC" or the MSC blue fish logo
  - "ASC" or the ASC teal logo
  - "BAP" or star logos (Best Aquaculture Practices)
  - "GlobalG.A.P." or "Global GAP"
  - "Friend of the Sea" or "FOS"
  - "ASMI" or "Alaska Seafood" certification marks
  - "Responsibly Farmed", "Sustainably Sourced" (unverified labels — still include)
  - "Seafood Watch" or Monterey Bay Aquarium label
  - Return an empty list if no certification marks are visible

CRITICAL RULES:
1. Extract ONLY what is visually present on the page. Do not infer, assume, or hallucinate.
2. If a field is not clearly visible, return null (not a guess).
3. For species: if you can see "salmon" but not which type, return "salmon" (not "Atlantic salmon").
4. is_seafood must be false if this is a non-seafood product page (e.g. chicken, pasta, vegetables).

Return ONLY the JSON object with no explanation or markdown fencing."""

_runner: Runner | None = None
_session_service: InMemorySessionService | None = None


def _get_runner() -> tuple[Runner, InMemorySessionService]:
    global _runner, _session_service
    if _runner is None:
        agent = LlmAgent(
            name="screen_analyzer",
            model="gemini-2.5-flash",
            instruction=SCREEN_ANALYZER_INSTRUCTION,
            output_schema=ProductInfo,
        )
        _session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
        _runner = Runner(
            agent=agent,
            app_name="seasussed",
            session_service=_session_service,
        )
    assert _session_service is not None
    return _runner, _session_service


def _parse_product_info(text: str) -> ProductInfo:
    """Parse JSON text into ProductInfo, falling back to non-seafood on error."""
    try:
        data: dict[str, Any] = json.loads(strip_json_fences(text))
        return ProductInfo(**data)
    except Exception as e:
        log.warning("_parse_product_info failed: %s", e)
        return ProductInfo(
            is_seafood=False,
            species=None,
            wild_or_farmed="unknown",
            fishing_method=None,
            origin_region=None,
            certifications=[],
        )


async def analyze_screenshot(
    screenshot_b64: str, url: str, page_title: str
) -> ProductInfo:
    """Run the screen analyzer on a screenshot and return ProductInfo."""
    runner, session_service = _get_runner()

    user_id = "analyze"
    session_id = str(uuid.uuid4())

    await session_service.create_session(
        app_name="seasussed",
        user_id=user_id,
        session_id=session_id,
    )

    image_bytes = base64.b64decode(screenshot_b64)

    message = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(
                inline_data=genai_types.Blob(
                    mime_type="image/png",
                    data=image_bytes,
                )
            ),
            genai_types.Part(
                text=(
                    f"URL: {url}\n"
                    f"Page title: {page_title or ''}\n\n"
                    "Extract the seafood product information from this screenshot."
                )
            ),
        ],
    )

    final_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text = str(part.text)
                        break
            break

    return _parse_product_info(final_text)
