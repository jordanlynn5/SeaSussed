"""Screen analyzer using Gemini GenAI SDK.

Uses Gemini 2.5 Flash multimodal via the Google GenAI SDK to extract
structured PageAnalysis from a base64 PNG screenshot of a grocery page.

Detects page type (single product, product listing, or no seafood) and
extracts product info for all visible seafood products (up to 10).
"""

import asyncio
import base64
import json
import logging
from typing import Any

from google.genai import types as genai_types

from gemini_client import get_genai_client, strip_json_fences
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
- origin_region: catch or farm location if visible in any image or text.
  READ EVERY IMAGE CAREFULLY for origin text. Common locations on packaging:
  "Product of [country]", "Farm-raised in [country]", "Caught in [region]",
  "Origin: [country]", "Distributed by... [country]". Check the BACK of the
  bag/box — origin is often in small print near the barcode, nutrition facts,
  or ingredient list. If ANY image shows origin text, extract it. null ONLY
  if no origin text exists in any image or DOM text.
- certifications: list of certification marks visible in any image or
  mentioned in text (MSC, ASC, BAP, GlobalG.A.P., FOS, ASMI,
  Responsibly Farmed, Sustainably Sourced, etc.)
  IMPORTANT: Look for chain-of-custody codes like "MSC-C-12345" or
  "ASC-C-12345" — these confirm certification even without a logo.
  Also look for certification statements like "certified to the MSC's
  standard" or "www.msc.org" in fine print on back labels.
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
6. SPECIES IDENTIFICATION: The product title and text labels are the PRIMARY
   source for species. NEVER override what the text says based on how the fish
   looks in a photo. If the title says "yellowfin tuna" the species is yellowfin
   tuna, regardless of the color or appearance of the fish in the image. Text
   labels are authoritative; visual appearance of raw fish is not reliable.
7. ORIGIN — READ EVERY IMAGE, NEVER GUESS: origin_region must come from text
   visible in the images or DOM text. Scrutinize EVERY provided image — zoom in
   mentally on fine print, back labels, and text near barcodes. Common patterns:
   "Product of India", "Farm Raised in India", "Wild Caught in Alaska",
   "Produce of Thailand". If you see it in ANY image, extract it.
   If no origin is explicitly stated in any image or text, return null.
   Do NOT infer origin from species name, brand, store, or general knowledge.
8. WILD_OR_FARMED — NEVER GUESS: Must come from explicit text like "wild-caught",
   "farm-raised", "farmed", or "aquaculture" visible on the page. Do NOT infer
   from species name or general knowledge. No text about method → "unknown".

Return ONLY the JSON object with no explanation or markdown fencing."""

def _call_gemini_vision(parts: list[genai_types.Part]) -> str:
    """Synchronous Gemini vision call (run via asyncio.to_thread)."""
    client = get_genai_client()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=genai_types.Content(role="user", parts=parts),
        config=genai_types.GenerateContentConfig(
            system_instruction=SCREEN_ANALYZER_INSTRUCTION,
            response_mime_type="application/json",
        ),
    )
    return response.text or ""


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

    log.info(
        "Gemini vision input: %d parts, %d chars page_text, %d gallery images",
        len(parts),
        len(page_text) if page_text else 0,
        len(product_images) if product_images else 0,
    )
    raw = await asyncio.to_thread(_call_gemini_vision, parts)
    log.info("Gemini vision raw response: %s", raw[:1000])
    return _parse_page_analysis(raw)
