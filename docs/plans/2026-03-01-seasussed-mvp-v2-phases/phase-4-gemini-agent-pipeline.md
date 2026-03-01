# Phase 4: Gemini Agent Pipeline

**Days:** 4–7 | **Depends on:** Phase 1 (backend scaffold), Phase 3 (database) | **Blocks:** Phase 5

---

## Deliverable

`POST /analyze` and `POST /score` endpoints fully implemented. A real Whole Foods salmon screenshot returns a `SustainabilityScore` with grade A or B in under 5 seconds.

## Architecture (this phase)

```
POST /analyze:
  1. ScreenAnalyzerAgent (ADK LlmAgent)   → ProductInfo
  2. identify_alternative_species()        → species names from related_products list
  3. score_product()                       → ScoreBreakdown + grade for main product
  4. score_alternatives()                  → scored Alternative list
  5. generate_content()                   → (explanation, score_factors) — one Gemini call
       explanation:   2–3 sentence summary (states visible vs unknown)
       score_factors: per-category WHY explanation + optional tip (C/D grades only)
  → returns SustainabilityScore

POST /score:
  1. score_product()                       → ScoreBreakdown + grade
  2. generate_content()                   → (explanation, score_factors)
  → returns SustainabilityScore
```

### Educational Layer

The side panel shows expandable breakdown rows. Each row's expanded state contains:
- **What**: factual data for this product and this category
- **Why**: plain-language explanation of why it matters
- **Tip**: (C/D grades only) one actionable sentence on what to look for next time

Content sources — layered to minimize hallucination risk:
- **Gear type notes**: from `fishing_methods.educational_note` in SQLite (static, reliable)
- **Cert definitions**: from `cert_education.py` lookup dict (static, reliable)
- **Species biology + ecological context**: Gemini-generated, anchored to FishBase factual data
- **Management + NOAA context**: Gemini-generated, anchored to cert names and NOAA status string

---

## Step 0: Updated models.py (add ScoreFactor)

Add to `backend/models.py`:

```python
class ScoreFactor(BaseModel):
    category: str        # "Biological & Population", "Fishing Practices", etc.
    score: float
    max_score: int
    explanation: str     # product-specific WHY: what was found + why it scored this way
    tip: str | None      # actionable shopping tip — only for C/D grade products
```

Update `SustainabilityScore` to add `score_factors`:

```python
class SustainabilityScore(BaseModel):
    score: int
    grade: Literal["A", "B", "C", "D"]
    breakdown: ScoreBreakdown
    alternatives: list[Alternative]
    alternatives_label: str
    explanation: str                  # 2–3 sentence summary
    score_factors: list[ScoreFactor]  # NEW — per-category educational content
    product_info: ProductInfo
```

---

## Step 0b: cert_education.py (static cert definitions)

Static lookup for all known certification types. These are factual constants — never
Gemini-generated. Passed to the side panel as part of the response.

```python
# backend/cert_education.py

CERT_DEFINITIONS: dict[str, dict[str, str]] = {
    "MSC": {
        "full_name": "Marine Stewardship Council",
        "color_hint": "blue fish logo",
        "explanation": (
            "The MSC blue fish logo means this fishery has been independently audited "
            "against rigorous science-based standards. To earn MSC certification, a fishery "
            "must demonstrate: (1) fish stocks are healthy and not overfished, "
            "(2) fishing operations minimize environmental impact and bycatch, and "
            "(3) effective management systems are in place. Annual surveillance audits "
            "maintain the certification."
        ),
    },
    "ASC": {
        "full_name": "Aquaculture Stewardship Council",
        "color_hint": "teal logo",
        "explanation": (
            "The ASC teal logo certifies that farmed seafood was raised responsibly. "
            "ASC-certified farms must meet standards covering: feed sourcing and efficiency, "
            "disease and chemical use, water quality, impacts on surrounding ecosystems, "
            "worker welfare, and traceability. Considered the gold standard for "
            "farmed seafood certification."
        ),
    },
    "BAP": {
        "full_name": "Best Aquaculture Practices",
        "color_hint": "star logo",
        "explanation": (
            "BAP (Best Aquaculture Practices) is a certification for farmed seafood covering "
            "four areas: hatcheries, farms, processing, and feed mills. The number of stars "
            "indicates how many components in the supply chain are certified. More stars "
            "indicate greater supply chain traceability and sustainability verification."
        ),
    },
    "GLOBALG.A.P.": {
        "full_name": "GlobalG.A.P.",
        "color_hint": "green logo",
        "explanation": (
            "GlobalG.A.P. (Good Agricultural Practices) certifies farms against standards "
            "covering food safety, environmental sustainability, and worker welfare. "
            "In seafood, it's primarily used for farmed fish and shellfish. "
            "Respected internationally but less seafood-specific than ASC."
        ),
    },
    "FRIEND OF THE SEA": {
        "full_name": "Friend of the Sea",
        "color_hint": "blue wave logo",
        "explanation": (
            "Friend of the Sea certifies both wild-caught and farmed seafood products "
            "against sustainability criteria including stock status, bycatch reduction, "
            "and no impact on endangered species or seabed. Widely recognized internationally."
        ),
    },
    "FOS": {
        "full_name": "Friend of the Sea",
        "color_hint": "blue wave logo",
        "explanation": (
            "Friend of the Sea (FOS) certifies both wild-caught and farmed seafood "
            "against sustainability criteria including stock status, bycatch reduction, "
            "and no impact on endangered species or seabed."
        ),
    },
    "ASMI": {
        "full_name": "Alaska Seafood Marketing Institute",
        "color_hint": "Alaska Seafood logo",
        "explanation": (
            "The Alaska Seafood logo indicates seafood from Alaska — one of the world's "
            "best-managed fisheries regions. All Alaska commercial fisheries are governed "
            "by the Magnuson-Stevens Act with science-based catch limits and independent "
            "stock assessments. Alaska pollock and sockeye salmon fisheries are among the "
            "largest MSC-certified fisheries on Earth."
        ),
    },
    "SUSTAINABLY SOURCED": {
        "full_name": "Sustainably Sourced (retailer claim)",
        "color_hint": "text label",
        "explanation": (
            "'Sustainably sourced' is an unverified marketing claim — it is not backed "
            "by an independent third-party audit. Unlike MSC or ASC, there is no standard "
            "defining what 'sustainably sourced' means. When you see this label without "
            "an MSC, ASC, or BAP logo, treat it with caution and look for more specific "
            "information about where and how the fish was caught."
        ),
    },
    "RESPONSIBLY FARMED": {
        "full_name": "Responsibly Farmed (retailer claim)",
        "color_hint": "text label",
        "explanation": (
            "'Responsibly Farmed' is a retailer-defined standard, not an independent "
            "third-party certification. Whole Foods Market's Responsibly Farmed program "
            "does have documented requirements, but it is audited by the retailer itself "
            "rather than an independent body. A step above no label, but not equivalent "
            "to ASC or BAP certification."
        ),
    },
    "SEAFOOD WATCH": {
        "full_name": "Monterey Bay Aquarium Seafood Watch",
        "color_hint": "green/yellow/red card",
        "explanation": (
            "Seafood Watch is a science-based consumer guide from the Monterey Bay Aquarium "
            "that rates seafood as Best Choice, Good Alternative, or Avoid. It is not a "
            "certification (no logo on packaging) but a widely respected rating system "
            "used by restaurants and retailers. The methodology closely mirrors the "
            "factors SeaSussed uses to calculate this score."
        ),
    },
}

fn get_cert_definition(cert_name: str) -> dict[str, str] | None:
    """Look up a cert definition by name (case-insensitive partial match)."""
    cert_upper = cert_name.upper()
    for key, definition in CERT_DEFINITIONS.items():
        if key in cert_upper or cert_upper in key:
            return definition
    return None
```

---

## Step 1: ScreenAnalyzerAgent (ADK)

```python
# backend/agents/screen_analyzer.py
from google.adk.agents import LlmAgent
from models import ProductInfo

SCREEN_ANALYZER_INSTRUCTION = """
You are a grocery product page analyst with expert vision capabilities.

Given a screenshot of an online grocery website, extract structured information about the seafood product shown.

Return a JSON object matching this schema:
- is_seafood: true only if a fish, shellfish, or other seafood product is the primary product shown
- species: common name, as specific as possible (e.g. "Alaska sockeye salmon" not "salmon")
  - null if not determinable
- wild_or_farmed: "wild" if label says wild-caught; "farmed" if label says farmed/farm-raised/aquaculture;
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
"""

fn build_screen_analyzer() -> LlmAgent:
  return LlmAgent(
    name="screen_analyzer",
    model="gemini-2.5-flash",
    instruction=SCREEN_ANALYZER_INSTRUCTION,
    output_schema=ProductInfo,
  )
```

---

## Step 2: scoring.py — Pure Python Scoring

```python
# backend/scoring.py
from models import ProductInfo, ScoreBreakdown, Alternative
from database import get_species, get_noaa_status, get_gear_score

# Country management quality — used in explanation text only (not scored separately)
COUNTRY_MANAGEMENT_NOTES: dict[str, str] = {
  "norway": "strong fisheries management",
  "iceland": "strong fisheries management",
  "united states": "NOAA-regulated, strong management",
  "alaska": "NOAA-regulated, strong management",
  "canada": "DFO-regulated management",
  "australia": "strong fisheries management",
  "new zealand": "strong fisheries management",
  "china": "limited independent verification of fishing practices",
  "indonesia": "limited independent verification of fishing practices",
  "vietnam": "limited independent verification of fishing practices",
  "thailand": "limited independent verification of fishing practices",
  "india": "limited independent verification of fishing practices",
  "bangladesh": "limited independent verification of fishing practices",
}

# Certification scoring for Management category
CERT_SCORES: dict[str, int] = {
  "MSC": 15,
  "MARINE STEWARDSHIP COUNCIL": 15,
  "ASC": 15,
  "AQUACULTURE STEWARDSHIP COUNCIL": 15,
  "BAP": 10,
  "BEST AQUACULTURE PRACTICES": 10,
  "GLOBALG.A.P.": 8,
  "GLOBAL GAP": 8,
  "FRIEND OF THE SEA": 8,
  "FOS": 8,
  "ASMI": 7,
  "ALASKA SEAFOOD": 7,
  "SEAFOOD WATCH": 6,
  "RESPONSIBLY FARMED": 3,
  "SUSTAINABLY SOURCED": 3,
}

fn score_biological(species_data: dict | None) -> float:
  """Max 20 pts: vulnerability (10), resilience (7), IUCN (3)"""
  if species_data is None:
    return 10.0  # neutral default for unknown species

  vuln = float(species_data.get("vulnerability") or 50.0)
  vuln_score = (100.0 - vuln) / 100.0 * 10.0

  resilience_map = {"Very Low": 0.0, "Low": 2.0, "Medium": 5.0, "High": 7.0}
  resilience_score = resilience_map.get(species_data.get("resilience") or "", 3.0)

  iucn_scores = {"LC": 3.0, "NT": 2.0, "VU": 1.0, "EN": 0.5, "CR": 0.0, "DD": 1.5}
  iucn_score = iucn_scores.get(species_data.get("iucn_code") or "LC", 2.0)

  return min(20.0, vuln_score + resilience_score + iucn_score)

fn score_wild_practices(gear_data: dict | None) -> float:
  """Max 25 pts: gear impact score"""
  if gear_data is None:
    return 10.0  # penalty for unknown gear — reflects real uncertainty
  return float(gear_data["impact_score"]) / 100.0 * 25.0

fn score_aquaculture(certifications: list[str], species_data: dict | None) -> float:
  """Max 25 pts: certifications (20) + carnivory ratio (5)"""
  cert_upper = [c.upper() for c in certifications]

  cert_score = 5.0  # base: any farmed product
  for cert in cert_upper:
    for key, pts in CERT_SCORES.items():
      if key in cert or cert in key:
        cert_score = max(cert_score, float(pts))
        break

  # Cap cert_score contribution at 20 pts for practices category
  cert_score = min(20.0, cert_score)

  carnivory = float((species_data or {}).get("carnivory_ratio") or 0.5)
  carnivory_bonus = (1.0 - carnivory) * 5.0  # 0–5 pts

  return min(25.0, cert_score + carnivory_bonus)

fn score_management(
  certifications: list[str],
  noaa_data: dict | None,
  species_data: dict | None,
) -> float:
  """Max 30 pts: visual cert (15) + NOAA status (10) + FAO exploitation (5)"""

  # Visual cert detection: take highest cert found
  cert_upper = [c.upper() for c in certifications]
  cert_score = 0.0
  for cert in cert_upper:
    for key, pts in CERT_SCORES.items():
      if key in cert or cert in key:
        cert_score = max(cert_score, float(pts))
        break
  cert_score = min(15.0, cert_score)  # cap at 15 for management

  # NOAA overfishing status
  noaa_score = 4.0  # default for non-US species
  if noaa_data:
    rate = (noaa_data.get("fishing_rate") or "").lower()
    if "not subject" in rate or "not overfishing" in rate:
      noaa_score = 10.0
    elif "overfishing" in rate:
      noaa_score = 0.0

  # FAO stock exploitation from FishBase
  exploitation = (species_data or {}).get("stock_exploitation") or ""
  exploitation_score_map = {
    "not overexploited": 5.0,
    "fully exploited": 2.0,
    "overexploited": 0.0,
  }
  exploitation_score = exploitation_score_map.get(exploitation.lower(), 3.0)

  return min(30.0, cert_score + noaa_score + exploitation_score)

fn score_ecological(species_data: dict | None) -> float:
  """Max 25 pts: trophic (10) + IUCN conservation (10) + resilience bonus (5)"""
  if species_data is None:
    return 12.0  # neutral

  trophic = float(species_data.get("trophic_level") or 3.0)
  if trophic <= 2.5:    trophic_score = 10.0   # filter feeders, herbivores
  elif trophic <= 3.5:  trophic_score = 7.0    # small pelagics
  else:                 trophic_score = 4.0    # large predators

  iucn_map = {"LC": 10.0, "NT": 7.0, "VU": 4.0, "EN": 2.0, "CR": 0.0, "DD": 5.0}
  iucn_score = iucn_map.get(species_data.get("iucn_code") or "LC", 5.0)

  resilience_bonus = 2.0 if species_data.get("resilience") in ("High", "Medium") else 1.0

  return min(25.0, trophic_score + iucn_score + resilience_bonus)

fn compute_score(product: ProductInfo) -> tuple[ScoreBreakdown, int, str]:
  """Returns (breakdown, total_score, grade)."""
  species_data = get_species(product.species or "") if product.species else None
  noaa_data = get_noaa_status(product.species or "") if product.species else None

  biological = score_biological(species_data)
  ecological = score_ecological(species_data)
  management = score_management(product.certifications, noaa_data, species_data)

  # Farmed/wild split for practices
  effective_wild_or_farmed = product.wild_or_farmed
  if effective_wild_or_farmed == "unknown" and product.species:
    # Default well-known farmed species to 'farmed' for more accurate scoring
    MOSTLY_FARMED = {"atlantic salmon", "tilapia", "catfish", "rainbow trout",
                     "pangasius", "basa", "whiteleg shrimp"}
    if product.species.lower() in MOSTLY_FARMED:
      effective_wild_or_farmed = "farmed"

  if effective_wild_or_farmed == "farmed":
    practices = score_aquaculture(product.certifications, species_data)
  else:
    gear_data = get_gear_score(product.fishing_method or "Unknown")
    practices = score_wild_practices(gear_data)

  breakdown = ScoreBreakdown(
    biological=biological,
    practices=practices,
    management=management,
    ecological=ecological,
  )
  total = int(biological + practices + management + ecological)
  grade = "A" if total >= 80 else "B" if total >= 60 else "C" if total >= 40 else "D"
  return breakdown, total, grade
```

---

## Step 3: Alternative Scoring

```python
# backend/alternatives.py
from google import genai
from models import ProductInfo, Alternative
from scoring import compute_score
from database import get_seed_alternatives
import os, json

fn identify_species_from_names(product_names: list[str]) -> dict[str, str | None]:
  """
  Given a list of grocery product title strings, return a mapping of
  product_name -> species common name (or None if not a seafood product).
  Uses one Gemini call for all names at once.
  """
  if not product_names:
    return {}

  client = genai.Client(vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"))

  names_json = json.dumps(product_names)
  prompt = f"""
You are a seafood species identifier. Given a list of grocery product titles,
identify the seafood species for each item that is a seafood product.

Product titles:
{names_json}

Return a JSON object mapping each product title to the species common name,
or null if it is not a seafood product.
Only return the JSON object, no explanation.
Example: {{"Wild Alaskan Sockeye Salmon Fillet": "sockeye salmon", "Organic Pasta": null}}
"""

  response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
  )

  try:
    raw = response.text.strip().lstrip("```json").rstrip("```").strip()
    return json.loads(raw)
  except Exception:
    return {}

fn score_alternatives(
  related_products: list[str],
  main_product: ProductInfo,
  main_score: int,
  main_grade: str,
) -> tuple[list[Alternative], str]:
  """
  Score related products and return alternatives with appropriate label.
  Returns (alternatives, label) where label is 'Similar great choices'
  or 'Better alternatives'.
  """
  if not related_products:
    return _seed_alternatives(main_product, main_score, main_grade)

  # Identify which products are seafood and what species
  species_map = identify_species_from_names(related_products)

  scored: list[tuple[int, Alternative]] = []
  for product_name, species in species_map.items():
    if species is None:
      continue
    # Score this species with minimal info (no method/origin/cert visible)
    candidate = ProductInfo(
      is_seafood=True,
      species=species,
      wild_or_farmed="unknown",
      fishing_method=None,
      origin_region=None,
      certifications=[],
    )
    _, alt_score, alt_grade = compute_score(candidate)
    scored.append((alt_score, Alternative(
      species=species,
      score=alt_score,
      grade=alt_grade,
      reason=product_name,  # show the actual product title from the site
      from_page=True,
    )))

  if not scored:
    return _seed_alternatives(main_product, main_score, main_grade)

  scored.sort(key=lambda x: x[0], reverse=True)

  if main_grade == "A":
    # Show top alternatives as "similar great choices" (A or B grade)
    top = [alt for _, alt in scored if alt.grade in ("A", "B")][:3]
    label = "Similar great choices"
  else:
    # Show alternatives better than current product
    top = [alt for score, alt in scored if score > main_score][:3]
    label = "Better alternatives"

  if not top:
    return _seed_alternatives(main_product, main_score, main_grade)

  return top, label

fn _seed_alternatives(
  product: ProductInfo,
  main_score: int,
  main_grade: str,
) -> tuple[list[Alternative], str]:
  """Fallback: seed DB alternatives, labeled honestly."""
  seeds = get_seed_alternatives(product.species or "")
  alts = []
  for s in seeds:
    candidate = ProductInfo(
      is_seafood=True, species=s["species"], wild_or_farmed="unknown",
      fishing_method=None, origin_region=None, certifications=[])
    _, alt_score, alt_grade = compute_score(candidate)
    alts.append(Alternative(
      species=s["species"],
      score=alt_score,
      grade=alt_grade,
      reason=s["reason"],
      from_page=False,
    ))

  label = "Similar great choices" if main_grade == "A" else "Better alternatives — check if available here"
  return alts[:3], label
```

---

## Step 4: Content Generation (explanation + per-factor education, one Gemini call)

```python
# backend/explanation.py
from google import genai
from models import ProductInfo, ScoreBreakdown, ScoreFactor
from database import get_gear_score
import os, json

fn generate_content(
  product: ProductInfo,
  breakdown: ScoreBreakdown,
  score: int,
  grade: str,
) -> tuple[str, list[ScoreFactor]]:
  """
  Single Gemini call that returns both:
  - explanation: 2–3 sentence summary (states visible vs. unknown fields)
  - score_factors: per-category WHY explanations + tips (C/D only)

  Gear educational note is sourced from the DB (reliable static data) and
  passed to Gemini as factual context. Gemini's role is language — not fact invention.
  Never fabricates data.
  """
  client = genai.Client(vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"))

  # Build visibility context
  visible = []
  unknown = []
  if product.species:                      visible.append(f"species: {product.species}")
  else:                                    unknown.append("species (unknown)")
  if product.wild_or_farmed != "unknown":  visible.append(f"wild/farmed: {product.wild_or_farmed}")
  else:                                    unknown.append("wild vs farmed (unknown)")
  if product.fishing_method:               visible.append(f"fishing method: {product.fishing_method}")
  else:                                    unknown.append("fishing method (unknown)")
  if product.origin_region:               visible.append(f"origin: {product.origin_region}")
  else:                                    unknown.append("origin (unknown)")
  if product.certifications:              visible.append(f"certifications seen: {', '.join(product.certifications)}")
  else:                                    unknown.append("certifications (none visible)")

  practices_label = "Aquaculture Practices" if product.wild_or_farmed == "farmed" else "Fishing Practices"

  # Pull gear educational note from DB (static, reliable — not Gemini-generated)
  gear_note = ""
  if product.fishing_method:
    gear_data = get_gear_score(product.fishing_method)
    gear_note = (gear_data or {}).get("educational_note", "")

  prompt = f"""
You are a seafood sustainability educator writing for a consumer shopping app.
Your goal is to help shoppers understand not just their score, but WHY — so they
make more informed choices over time. Be factual, specific, and educational.
Never preachy. Never fabricate information.

PRODUCT INFORMATION:
  Species: {product.species or 'unknown'}
  Wild or farmed: {product.wild_or_farmed}
  Fishing method: {product.fishing_method or 'unknown'}
  Origin: {product.origin_region or 'unknown'}
  Certifications visible: {', '.join(product.certifications) if product.certifications else 'none'}

SCORE:
  Grade: {grade}  ({score}/100)
  Biological & Population:  {breakdown.biological:.1f}/20
  {practices_label}:        {breakdown.practices:.1f}/25
  Management & Regulation:  {breakdown.management:.1f}/30
  Environmental & Ecological: {breakdown.ecological:.1f}/25

WHAT WAS VISIBLE ON PAGE: {', '.join(visible)}
WHAT WAS NOT SHOWN (defaults applied): {', '.join(unknown)}

FISHING METHOD EDUCATION (from database — use this text verbatim in the Fishing Practices factor if relevant):
{gear_note if gear_note else 'No gear method data available.'}

RULES:
1. Only state facts that come from the product information above. Do NOT invent facts about
   this specific product (e.g. do not claim a stock is overfished unless NOAA data confirms it).
2. If a field was unknown/not shown, say so in the relevant factor explanation.
3. For grade A/B factors: explain what was good and why it matters.
4. For grade C/D factors: explain what the problem is and why it matters.
5. Tips: only include for grade C or D products. One sentence per factor at most.
   Make tips actionable: "Look for the MSC blue fish logo" not "try to find better options."
6. Biological & Ecological explanations may reference species biology known from science
   (e.g. trophic level, maturity age, known population trends) — but label it as
   "scientifically, [species] is known for..." rather than product-specific claims.

Return ONLY valid JSON in this exact structure:
{{
  "summary": "2–3 sentence overall explanation. State grade, key strengths/weaknesses,
              and note any fields not visible on the page.",
  "factors": {{
    "biological": {{
      "explanation": "2–3 sentences: what was found, why this score, why it matters.",
      "tip": "one sentence tip OR null"
    }},
    "practices": {{
      "explanation": "2–3 sentences. If gear is known, use the gear education text above.",
      "tip": "one sentence tip OR null"
    }},
    "management": {{
      "explanation": "2–3 sentences: cert name/absence, NOAA status, why certs matter.",
      "tip": "one sentence tip OR null"
    }},
    "ecological": {{
      "explanation": "2–3 sentences: trophic role, ecosystem impact, species context.",
      "tip": "one sentence tip OR null"
    }}
  }}
}}
"""

  try:
    response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=prompt,
    )
    raw = response.text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    data = json.loads(raw)

    summary = data.get("summary", "")
    factors_raw = data.get("factors", {})
    include_tips = grade in ("C", "D")

    score_factors = [
      ScoreFactor(
        category="Biological & Population",
        score=breakdown.biological,
        max_score=20,
        explanation=factors_raw.get("biological", {}).get("explanation", ""),
        tip=factors_raw.get("biological", {}).get("tip") if include_tips else None,
      ),
      ScoreFactor(
        category=practices_label,
        score=breakdown.practices,
        max_score=25,
        explanation=factors_raw.get("practices", {}).get("explanation", ""),
        tip=factors_raw.get("practices", {}).get("tip") if include_tips else None,
      ),
      ScoreFactor(
        category="Management & Regulation",
        score=breakdown.management,
        max_score=30,
        explanation=factors_raw.get("management", {}).get("explanation", ""),
        tip=factors_raw.get("management", {}).get("tip") if include_tips else None,
      ),
      ScoreFactor(
        category="Environmental & Ecological",
        score=breakdown.ecological,
        max_score=25,
        explanation=factors_raw.get("ecological", {}).get("explanation", ""),
        tip=factors_raw.get("ecological", {}).get("tip") if include_tips else None,
      ),
    ]

    return summary, score_factors

  except Exception:
    # Fallback: minimal template content if parsing fails
    summary = _fallback_summary(product, score, grade)
    score_factors = _fallback_factors(breakdown, grade, practices_label)
    return summary, score_factors

fn _fallback_summary(product: ProductInfo, score: int, grade: str) -> str:
  grade_text = {
    "A": "an excellent choice with strong sustainability credentials",
    "B": "a decent choice with some areas for improvement",
    "C": "a product to approach with caution",
    "D": "a product best avoided based on available sustainability data",
  }.get(grade, "a seafood product")
  species = product.species or "this seafood product"
  return (
    f"{species.capitalize()} received a grade {grade} ({score}/100), "
    f"indicating it is {grade_text}. "
    "Detailed explanations are unavailable — please try analyzing again."
  )

fn _fallback_factors(
  breakdown: ScoreBreakdown,
  grade: str,
  practices_label: str,
) -> list[ScoreFactor]:
  return [
    ScoreFactor(category="Biological & Population", score=breakdown.biological,
                max_score=20, explanation="Score based on species vulnerability and resilience data.", tip=None),
    ScoreFactor(category=practices_label, score=breakdown.practices,
                max_score=25, explanation="Score based on fishing gear type or aquaculture certifications.", tip=None),
    ScoreFactor(category="Management & Regulation", score=breakdown.management,
                max_score=30, explanation="Score based on visible certifications and fishery management data.", tip=None),
    ScoreFactor(category="Environmental & Ecological", score=breakdown.ecological,
                max_score=25, explanation="Score based on species trophic level and ecosystem role.", tip=None),
  ]
```

---

## Step 5: Pipeline — Updated main.py

```python
# backend/main.py (full implementation replacing Phase 1 stubs)
from fastapi import FastAPI, HTTPException
from models import AnalyzeRequest, ScoreRequest, SustainabilityScore, ProductInfo
from agents.screen_analyzer import build_screen_analyzer
from scoring import compute_score
from alternatives import score_alternatives
from explanation import generate_content
from cert_education import CERT_DEFINITIONS, get_cert_definition
import os

app = FastAPI(title="SeaSussed Backend", version="0.1.0")
_analyzer = build_screen_analyzer()

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "seasussed-backend", "version": "0.1.0"}

@app.post("/analyze", response_model=SustainabilityScore)
async def analyze(request: AnalyzeRequest) -> SustainabilityScore:
    if not request.screenshot:
        raise HTTPException(400, "screenshot is required")

    # 1. Vision extraction
    product_info: ProductInfo = await _analyzer.run(input={
        "image": request.screenshot,
        "url": request.url,
        "page_title": request.page_title,
    })

    if not product_info.is_seafood:
        return _not_seafood_response(product_info)

    # 2. Score + generate educational content
    breakdown, score, grade = compute_score(product_info)
    alternatives, alts_label = score_alternatives(
        request.related_products, product_info, score, grade)
    explanation, score_factors = generate_content(product_info, breakdown, score, grade)

    return SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=product_info,
    )

@app.post("/score", response_model=SustainabilityScore)
async def score_endpoint(request: ScoreRequest) -> SustainabilityScore:
    """Re-score without vision. Used by 'Not right?' correction flow."""
    product_info = request.product_info
    breakdown, score, grade = compute_score(product_info)
    alternatives, alts_label = score_alternatives([], product_info, score, grade)
    explanation, score_factors = generate_content(product_info, breakdown, score, grade)

    return SustainabilityScore(
        score=score,
        grade=grade,
        breakdown=breakdown,
        alternatives=alternatives,
        alternatives_label=alts_label,
        explanation=explanation,
        score_factors=score_factors,
        product_info=product_info,
    )

fn _not_seafood_response(product_info: ProductInfo) -> SustainabilityScore:
    from models import ScoreBreakdown
    return SustainabilityScore(
        score=0,
        grade="D",  # unused — UI checks product_info.is_seafood
        breakdown=ScoreBreakdown(biological=0, practices=0, management=0, ecological=0),
        alternatives=[],
        alternatives_label="",
        explanation="",
        score_factors=[],
        product_info=product_info,
    )
```

---

## Integration Tests

Create screenshot fixtures in `backend/tests/fixtures/`:
- `whole_foods_sockeye.png` — Whole Foods wild Alaska sockeye salmon product page
- `whole_foods_farmed_salmon.png` — Whole Foods farmed Atlantic salmon
- `amazon_pasta.png` — non-seafood product (for is_seafood=false test)

These must be taken manually. See manual success criteria.

```python
# backend/tests/test_analyze.py
import base64
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
import time

client = TestClient(app)

fn load_fixture(name: str) -> str:
    path = Path(__file__).parent / "fixtures" / name
    return base64.b64encode(path.read_bytes()).decode()

def test_seafood_product_returns_valid_score():
    response = client.post("/analyze", json={
        "screenshot": load_fixture("whole_foods_sockeye.png"),
        "url": "https://www.wholefoodsmarket.com/product/sockeye-salmon",
        "related_products": [],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["product_info"]["is_seafood"] is True
    assert data["grade"] in ("A", "B", "C", "D")
    assert 0 <= data["score"] <= 100
    assert len(data["explanation"]) > 20
    assert data["breakdown"]["biological"] >= 0
    assert data["breakdown"]["management"] >= 0

def test_non_seafood_returns_is_seafood_false():
    response = client.post("/analyze", json={
        "screenshot": load_fixture("amazon_pasta.png"),
        "url": "https://www.amazon.com/pasta",
        "related_products": [],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["product_info"]["is_seafood"] is False

def test_score_endpoint_correction_flow():
    """Verify /score re-scores a corrected ProductInfo without vision."""
    response = client.post("/score", json={
        "product_info": {
            "is_seafood": True,
            "species": "Alaska sockeye salmon",
            "wild_or_farmed": "wild",
            "fishing_method": "Purse seine",
            "origin_region": "Bristol Bay, Alaska",
            "certifications": ["MSC"],
        }
    })
    assert response.status_code == 200
    data = response.json()
    assert data["grade"] in ("A", "B")
    assert data["score"] >= 60
    assert len(data["explanation"]) > 20

def test_response_time():
    start = time.time()
    client.post("/analyze", json={
        "screenshot": load_fixture("whole_foods_sockeye.png"),
        "url": "https://www.wholefoodsmarket.com/product/sockeye-salmon",
    })
    elapsed_ms = (time.time() - start) * 1000
    assert elapsed_ms < 8000, f"Response took {elapsed_ms:.0f}ms — too slow"
```

---

## Automated Success Criteria

```bash
cd /Users/jordan/sussed/backend
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/test_analyze.py -v 2>&1
```

## Manual Success Criteria

- Take `whole_foods_sockeye.png`: navigate to wholefoodsmarket.com, find a wild Alaska sockeye salmon product page, take a full-page screenshot
- Take `amazon_pasta.png`: any non-seafood product on Amazon
- `POST /analyze` with sockeye fixture → `grade` is A or B, `score` > 60
- `POST /score` with corrected bluefin tuna → `grade` is D, `score` < 30
- Explanation for sockeye mentions "Alaska" or "wild" — not fabricated details
- Explanation for a product with no fishing method explicitly states method was unknown
