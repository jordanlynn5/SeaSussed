"""ADK LlmAgent for extracting product info from grocery page screenshots.

Uses Google ADK's LlmAgent with Gemini 2.5 Flash multimodal to extract
structured PageAnalysis from a base64 PNG screenshot of a grocery page.

Detects page type (single product, product listing, or no seafood) and
extracts product info for all visible seafood products (up to 10).

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
from models import PageAnalysis, ProductInfo

log = logging.getLogger(__name__)

_MAX_PRODUCTS = 10
_MAX_GALLERY_IMAGES = 5

SCREEN_ANALYZER_INSTRUCTION = """
You are a grocery product page analyst with expert vision capabilities.

You will receive one or more images from an online grocery website, plus
extracted page text. Combine ALL sources to build the most complete extraction.

Images may include:
- A screenshot of the visible page
- Additional product gallery images (front of package, back label, nutrition
  facts, ingredient list, certification logos, etc.)

The page text may include product title, description, features, ingredients,
details, and specifications extracted from the full page DOM (including content
below the visible area).

STEP 1 — Determine page_type:
- "single_product": a dedicated product detail page showing one item
- "product_listing": a search results, category, or browse page showing
  multiple products (cards, tiles, or list items)
- "no_seafood": the page has no seafood products at all

STEP 2 — Extract products:
For each seafood product, extract from ANY of the provided images or text:
- is_seafood: true only if it is fish, shellfish, or other seafood
- species: common name, as specific as possible
  (e.g. "Alaska sockeye salmon" not "salmon") — null if not determinable.
  If a scientific name is visible (e.g. on a back label), use it to determine
  the most specific common name.
- wild_or_farmed: "wild" if label says wild-caught;
  "farmed" if label says farmed/farm-raised/aquaculture;
  "unknown" if not visible in any source
- fishing_method: specific gear type if visible — null if not shown
- origin_region: catch or farm location if visible in any image or text
  (check back labels, ingredient lists, product details) — null if not shown
- certifications: list of certification marks visible in any image or
  mentioned in text (MSC, ASC, BAP, GlobalG.A.P., FOS, ASMI,
  Responsibly Farmed, Sustainably Sourced, etc.)
- product_name: the full product title/name — null if not visible

For "single_product": extract one product with full detail.
For "product_listing": extract ALL visible seafood products (up to 10).
  Include non-seafood items too with is_seafood=false so they can be filtered.
For "no_seafood": return an empty products list.

Return a JSON object with this schema:
{
  "page_type": "single_product" | "product_listing" | "no_seafood",
  "products": [ { product fields... } ]
}

CRITICAL RULES:
1. Cross-reference ALL images and text. A certification logo on the back label
   counts even if the front image doesn't show it. An origin on the ingredient
   list counts even if the main photo doesn't show it.
2. If a field is not present in ANY source, return null (not a guess).
3. For species: if you can see "salmon" but not which type, return "salmon".
4. is_seafood must be false for non-seafood items (chicken, pasta, vegetables).
5. product_name should be the visible product title, exactly as shown.

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
            output_schema=PageAnalysis,
        )
        _session_service = InMemorySessionService()  # type: ignore[no-untyped-call]
        _runner = Runner(
            agent=agent,
            app_name="seasussed",
            session_service=_session_service,
        )
    assert _session_service is not None
    return _runner, _session_service


def _parse_page_analysis(text: str) -> PageAnalysis:
    """Parse JSON text into PageAnalysis, falling back to no_seafood on error."""
    try:
        data: dict[str, Any] = json.loads(strip_json_fences(text))
        pa = PageAnalysis(**data)
        # Truncate to max products
        if len(pa.products) > _MAX_PRODUCTS:
            pa = PageAnalysis(
                page_type=pa.page_type, products=pa.products[:_MAX_PRODUCTS]
            )
        return pa
    except Exception as e:
        log.warning("_parse_page_analysis failed: %s", e)
        return PageAnalysis(page_type="no_seafood", products=[])


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
    screenshot_b64: str,
    url: str,
    page_title: str,
    page_text: str = "",
    product_images: list[str] | None = None,
) -> PageAnalysis:
    """Run the screen analyzer on screenshot(s) + page text and return PageAnalysis."""
    runner, session_service = _get_runner()

    user_id = "analyze"
    session_id = str(uuid.uuid4())

    await session_service.create_session(
        app_name="seasussed",
        user_id=user_id,
        session_id=session_id,
    )

    parts: list[genai_types.Part] = []

    # Primary screenshot (optional — may be empty for DOM-only search results)
    if screenshot_b64:
        parts.append(
            genai_types.Part(
                inline_data=genai_types.Blob(
                    mime_type="image/png",
                    data=base64.b64decode(screenshot_b64),
                )
            )
        )

    # Additional product gallery images (back label, nutrition facts, etc.)
    for i, img_b64 in enumerate((product_images or [])[:_MAX_GALLERY_IMAGES]):
        try:
            img_bytes = base64.b64decode(img_b64)
            # Detect MIME type from first bytes
            mime = "image/jpeg"
            if img_bytes[:4] == b"\x89PNG":
                mime = "image/png"
            elif img_bytes[:4] == b"RIFF":
                mime = "image/webp"
            parts.append(
                genai_types.Part(
                    inline_data=genai_types.Blob(mime_type=mime, data=img_bytes)
                )
            )
            log.info("Attached gallery image %d (%d bytes)", i + 1, len(img_bytes))
        except Exception:
            log.warning("Skipping invalid gallery image %d", i + 1)

    # Text prompt with page context
    text_sections = [
        f"URL: {url}",
        f"Page title: {page_title or ''}",
    ]
    if page_text:
        text_sections.append(f"Extracted page text:\n{page_text[:5000]}")

    text_sections.append(
        "\nAnalyze this page: determine the page type and extract "
        "all seafood product information from ALL provided images and text."
    )

    parts.append(genai_types.Part(text="\n".join(text_sections)))

    message = genai_types.Content(role="user", parts=parts)

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

    return _parse_page_analysis(final_text)
