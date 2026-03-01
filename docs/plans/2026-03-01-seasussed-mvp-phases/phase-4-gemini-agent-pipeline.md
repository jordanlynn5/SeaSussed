# Phase 4: Gemini Agent Pipeline

**Days:** 3–6 | **Depends on:** Phase 1 (backend scaffold), Phase 3 (database) | **Blocks:** Phase 5

---

## Steps

### 1. ScreenAnalyzerAgent

Uses Gemini 2.5 Flash vision to extract structured product info from a screenshot.

```python
# backend/agents/screen_analyzer.py
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from models import ProductInfo

SCREEN_ANALYZER_INSTRUCTION = """
You are a grocery product page analyst with expert vision capabilities.

You will be given a screenshot of an online grocery website.
Your task: determine if this is a seafood product page, and if so, extract all visible information.

Extract the following as JSON matching ProductInfo schema:
- is_seafood: true if a fish, shellfish, or seafood product is shown
- species: the common name of the seafood (e.g. "Atlantic salmon", "Gulf shrimp", "Bluefin tuna")
  - Be specific: "sockeye salmon" not just "salmon", "coho" not just "Pacific salmon"
  - If multiple species are on the page, focus on the primary product
- wild_or_farmed: "wild" if "wild-caught" or "wild" is shown/implied; "farmed" if "farmed", "farm-raised",
  "aquaculture" is shown; "unknown" if not determinable
- fishing_method: the specific gear type if visible (e.g. "Pole and line", "Bottom trawl", "Purse seine")
  - null if not shown
- origin_region: the catch or farm location if visible (e.g. "Alaska", "Norway", "Gulf of Mexico")
  - Be specific if possible: "Bristol Bay, Alaska" > "Alaska" > "Pacific Ocean"
  - null if not shown
- certifications: list of certification logos or text visible:
  - Look for: MSC blue fish logo, ASC teal logo, BAP star logos, Seafood Watch label,
    "sustainably sourced", "Responsibly Farmed", "Marine Stewardship Council", "Aquaculture Stewardship"

If the page does NOT show a seafood product, return: {"is_seafood": false, ...all other fields null/empty}

Important: Extract only what is VISUALLY PRESENT. Do not invent information.
"""

class ScreenAnalyzerAgent(LlmAgent):
  name = "screen_analyzer"
  model = "gemini-2.5-flash"
  instruction = SCREEN_ANALYZER_INSTRUCTION
  output_schema = ProductInfo

  async fn analyze(self, screenshot_b64: str, page_url: str) -> ProductInfo:
    response = await self.run(
      input={
        "image": screenshot_b64,
        "url": page_url,
      }
    )
    return response.output
```

### 2. Scoring Engine

Pure Python — no LLM needed for the math.

```python
# backend/scoring.py
from models import ProductInfo, ScoreBreakdown
from database import get_species, get_msc_status, get_noaa_status, get_gear_score, get_country_score

fn score_biological(species_data: dict | None, noaa_data: dict | None) -> float:
  """Max 20 pts: vulnerability (10), resilience (7), IUCN (3)"""
  if species_data is None:
    return 10.0  # neutral default when unknown

  # Vulnerability: FishBase 0-100, invert (0 = not vulnerable = good)
  vuln = species_data.get("vulnerability") or 50.0
  vuln_score = (100.0 - vuln) / 100.0 * 10.0  # 0-10 pts

  # Resilience
  resilience_map = {"Very Low": 0, "Low": 2, "Medium": 5, "High": 7}
  resilience_score = float(resilience_map.get(species_data.get("resilience", ""), 3))

  # IUCN penalty
  iucn_penalties = {"LC": 0, "NT": -0.5, "VU": -1.5, "EN": -2.5, "CR": -3.0, "DD": 0}
  iucn_penalty = iucn_penalties.get(species_data.get("iucn_code") or "LC", 0)

  return max(0.0, vuln_score + resilience_score + iucn_penalty)  # max 17 + 3 free = 20

fn score_wild_practices(gear_data: dict | None) -> float:
  """Max 25 pts: gear impact score"""
  if gear_data is None:
    return 10.0  # penalty for unknown gear
  return float(gear_data["impact_score"]) / 100.0 * 25.0

fn score_aquaculture(product: ProductInfo, species_data: dict | None) -> float:
  """Max 25 pts: certifications + carnivory ratio"""
  base = 5.0  # minimum for any farmed product

  # Certification bonus
  certs = [c.upper() for c in product.certifications]
  if "ASC" in certs or "AQUACULTURE STEWARDSHIP" in " ".join(certs):
    base += 15.0
  elif "BAP" in " ".join(certs):
    base += 10.0
  elif "RESPONSIBLY FARMED" in " ".join(certs):
    base += 7.0

  # Carnivory modifier (less carnivorous = lower feed pressure)
  carnivory = (species_data or {}).get("carnivory_ratio", 0.5)
  carnivory_bonus = (1.0 - carnivory) * 5.0  # 0-5 pts

  return min(25.0, base + carnivory_bonus)

fn score_management(product: ProductInfo, species_data: dict | None, noaa_data: dict | None) -> float:
  """Max 30 pts: MSC (15) + NOAA status (10) + country (5)"""
  score = 0.0

  # MSC certification
  scientific = (species_data or {}).get("scientific_name")
  if scientific:
    if get_msc_status(scientific, product.fishing_method):
      score += 15.0
  elif "MSC" in [c.upper() for c in product.certifications]:
    score += 12.0  # visible MSC badge but couldn't verify in DB — partial credit

  # NOAA overfishing status (US species only)
  if noaa_data:
    fishing_rate = noaa_data.get("fishing_rate", "Unknown")
    if "not subject" in fishing_rate.lower():
      score += 10.0
    elif "unknown" in fishing_rate.lower():
      score += 4.0
    # "overfishing occurring" = 0

  # Country management score (max 5 pts)
  country_score = get_country_score(product.origin_region or "")
  score += float(country_score)

  return min(30.0, score)

fn score_ecological(species_data: dict | None) -> float:
  """Max 25 pts: trophic level (10) + IUCN/climate (10) + not-keystone-prey (5)"""
  if species_data is None:
    return 12.0  # neutral

  # Trophic level: higher trophic = top predator = more ecologically costly to overfish
  # We reward BOTH extremes being sustainable — low trophic (bivalves) = very sustainable
  # penalize mid-large predators that are overexploited
  trophic = species_data.get("trophic_level") or 3.0
  if trophic <= 2.5:  # filter feeders, herbivores
    trophic_score = 10.0
  elif trophic <= 3.5:  # small pelagics
    trophic_score = 7.0
  else:  # large predators
    trophic_score = 4.0

  # IUCN/conservation status (repeat from biological but ecological angle)
  iucn_map = {"LC": 10, "NT": 7, "VU": 4, "EN": 2, "CR": 0, "DD": 5}
  iucn_score = float(iucn_map.get(species_data.get("iucn_code") or "LC", 5))

  # Ecosystem balance bonus: 5 pts if not a keystone prey species under pressure
  # (simplified: give 3 pts default, +2 if resilience is High or Medium)
  resilience_bonus = 2.0 if species_data.get("resilience") in ("High", "Medium") else 1.0

  return min(25.0, trophic_score + iucn_score + resilience_bonus)

fn compute_total_score(product: ProductInfo) -> ScoreBreakdown:
  species_data = get_species(product.species or "")
  noaa_data = get_noaa_status(product.species or "") if product.species else None

  if product.wild_or_farmed == "farmed":
    practices = score_aquaculture(product, species_data)
  else:
    gear_data = get_gear_score(product.fishing_method or "Unknown")
    practices = score_wild_practices(gear_data)

  return ScoreBreakdown(
    biological=score_biological(species_data, noaa_data),
    practices=practices,
    management=score_management(product, species_data, noaa_data),
    ecological=score_ecological(species_data),
  )

fn breakdown_to_grade(breakdown: ScoreBreakdown) -> tuple[int, str]:
  total = int(breakdown.biological + breakdown.practices
              + breakdown.management + breakdown.ecological)
  grade = "A" if total >= 80 else "B" if total >= 60 else "C" if total >= 40 else "D"
  return total, grade
```

### 3. SustainabilityScorerAgent

```python
# backend/agents/sustainability_scorer.py
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from models import ProductInfo, SustainabilityScore, Alternative
from scoring import compute_total_score, breakdown_to_grade
from database import get_alternatives

SCORER_INSTRUCTION = """
You are a seafood sustainability expert. You have already received structured product information
extracted from a grocery store screenshot.

Your tasks:
1. Use the provided scoring tools to compute the sustainability score
2. Select 3 meaningful alternatives (from the alternatives database)
3. Write a 2-3 sentence explanation of the score in plain consumer language

Guidelines for the explanation:
- Be specific: mention the actual species, fishing method, or certification when known
- If grade is A: affirm the choice and mention why it's good
- If grade is B: say it's decent but mention the main concern
- If grade is C/D: clearly explain the main problem and encourage the alternatives
- Never be preachy. Be informative and helpful.
"""

# Tool definitions for ADK
@FunctionTool
fn tool_compute_score(product_info: dict) -> dict:
  """Compute sustainability score breakdown for the given product."""
  product = ProductInfo(**product_info)
  breakdown = compute_total_score(product)
  total, grade = breakdown_to_grade(breakdown)
  return {
    "score": total,
    "grade": grade,
    "breakdown": breakdown.model_dump(),
  }

@FunctionTool
fn tool_get_alternatives(species: str) -> list[dict]:
  """Get 3 sustainable alternatives for a given species."""
  return get_alternatives(species)

class SustainabilityScorerAgent(LlmAgent):
  name = "sustainability_scorer"
  model = "gemini-2.5-flash"
  instruction = SCORER_INSTRUCTION
  tools = [tool_compute_score, tool_get_alternatives]
  output_schema = SustainabilityScore
```

### 4. Updated Pipeline

```python
# backend/agents/pipeline.py
from google.adk.agents import SequentialAgent
from agents.screen_analyzer import ScreenAnalyzerAgent
from agents.sustainability_scorer import SustainabilityScorerAgent
from models import SustainabilityScore, ProductInfo

analyzer = ScreenAnalyzerAgent()
scorer = SustainabilityScorerAgent()

async fn run_pipeline(screenshot_b64: str, page_url: str) -> SustainabilityScore:
  # Step 1: Extract product info from screenshot
  product_info = await analyzer.analyze(screenshot_b64, page_url)

  # Short-circuit if not seafood
  if not product_info.is_seafood:
    return SustainabilityScore(
      score=0,
      grade="A",  # unused
      breakdown=...,
      alternatives=[],
      explanation="",
      product_info=product_info,
    )

  # Step 2: Score the product
  score_result = await scorer.run(input={"product_info": product_info.model_dump()})
  return score_result.output
```

### 5. Integration Tests

```python
# backend/tests/test_analyze.py
import base64
from pathlib import Path
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

fn load_fixture(name: str) -> str:
  """Load a test screenshot fixture as base64."""
  path = Path(__file__).parent / "fixtures" / name
  return base64.b64encode(path.read_bytes()).decode()

def test_seafood_product():
  """Test with a salmon product page fixture."""
  response = client.post("/analyze", json={
    "screenshot": load_fixture("whole_foods_salmon.png"),
    "url": "https://www.wholefoodsmarket.com/product/wild-caught-sockeye-salmon"
  })
  assert response.status_code == 200
  data = response.json()
  assert data["product_info"]["is_seafood"] is True
  assert data["score"] >= 0
  assert data["grade"] in ("A", "B", "C", "D")
  assert len(data["alternatives"]) == 3
  assert len(data["explanation"]) > 20

def test_non_seafood_page():
  """Test with a non-seafood product page."""
  response = client.post("/analyze", json={
    "screenshot": load_fixture("amazon_pasta.png"),
    "url": "https://www.amazon.com/pasta"
  })
  assert response.status_code == 200
  data = response.json()
  assert data["product_info"]["is_seafood"] is False

def test_response_time():
  """Verify response time < 5000ms."""
  import time
  start = time.time()
  client.post("/analyze", json={
    "screenshot": load_fixture("whole_foods_salmon.png"),
    "url": "https://www.wholefoodsmarket.com/product/salmon"
  })
  elapsed_ms = (time.time() - start) * 1000
  assert elapsed_ms < 5000, f"Response took {elapsed_ms:.0f}ms"
```

**Note:** Create test fixtures in `backend/tests/fixtures/`:
- `whole_foods_salmon.png` — screenshot of a Whole Foods wild salmon product page
- `amazon_pasta.png` — screenshot of a non-seafood product (to test is_seafood=false)
- `walmart_tilapia.png` — screenshot of a budget tilapia product

Take these screenshots manually and commit them as binary test fixtures.

## Verification

```bash
cd /Users/jordan/sussed/backend
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/test_analyze.py -v 2>&1
```
