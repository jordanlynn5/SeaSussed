# Phase 3: Sustainability Database

**Days:** 3–4 | **Depends on:** nothing | **Blocks:** Phase 4

---

## Deliverable

`backend/data/seafood.db` SQLite database with 500+ species records, queryable by common name, with FishBase biology data, NOAA overfishing status, gear impact scores, and seed alternatives.

**Changes from v1 plan:**
- `msc_fisheries` table removed entirely (no MSC CSV)
- `stock_exploitation` field added to `species` table (from FishBase stocks data)
- `country_management` table removed (country still used in explanation text via a lookup dict in scoring.py — not a scored DB table)

---

## SQLite Schema

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS species (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  common_name TEXT NOT NULL,
  scientific_name TEXT NOT NULL UNIQUE,
  vulnerability REAL,           -- FishBase 0–100 (higher = more vulnerable)
  resilience TEXT,              -- 'Very Low' | 'Low' | 'Medium' | 'High'
  iucn_code TEXT,               -- 'LC' | 'NT' | 'VU' | 'EN' | 'CR' | 'DD' | NULL
  max_age_years INTEGER,
  trophic_level REAL,
  fishbase_id INTEGER,
  is_farmed_common BOOLEAN DEFAULT FALSE,
  carnivory_ratio REAL,         -- 0–1: 1=obligate carnivore, 0=herbivore
  stock_exploitation TEXT       -- 'overexploited' | 'fully exploited' | 'not overexploited' | NULL
);

CREATE INDEX IF NOT EXISTS idx_species_scientific ON species(scientific_name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS common_name_aliases (
  alias TEXT NOT NULL,
  scientific_name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_aliases ON common_name_aliases(alias COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS noaa_species (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  common_name TEXT NOT NULL,
  scientific_name TEXT,
  fishing_rate TEXT,       -- 'Not subject to overfishing' | 'Overfishing occurring' | 'Unknown'
  population_status TEXT,  -- 'Not overfished' | 'Overfished' | 'Unknown'
  habitat_impact TEXT,
  bycatch TEXT
);

CREATE TABLE IF NOT EXISTS fishing_methods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  method_name TEXT NOT NULL UNIQUE,
  impact_score INTEGER NOT NULL,  -- 0–100 (higher = more sustainable)
  bycatch_risk TEXT,
  habitat_impact TEXT,
  educational_note TEXT  -- plain-language explanation of this method for the side panel UI
);

CREATE TABLE IF NOT EXISTS alternatives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  for_species TEXT NOT NULL,
  alt_species TEXT NOT NULL,
  similarity_reason TEXT         -- "Similar mild white fish, pole & line caught"
);
"""
```

---

## Gear Impact Table (with educational notes)

Each entry: `(method_name, impact_score, bycatch_risk, habitat_impact, educational_note)`

```python
FISHING_METHODS = [
  ("Pole and line",   98, "Low",  "Low",
   "Each fish is caught individually on a single hook — the most selective fishing method "
   "in use. Near-zero bycatch and no seafloor impact. The gold standard for tuna fishing."),

  ("Hook and line",   95, "Low",  "Low",
   "Individual hooks catch fish one at a time. Highly selective, very low bycatch, "
   "and no habitat damage. Common for nearshore species."),

  ("Troll",           93, "Low",  "Low",
   "Lines with baited hooks are dragged slowly behind a boat. Selective and low-impact "
   "with minimal bycatch and no seafloor damage."),

  ("Reef net",        97, "Low",  "Low",
   "A stationary net suspended between anchored boats captures fish swimming between them. "
   "Extremely selective with near-zero bycatch — used primarily for wild salmon in the "
   "Pacific Northwest."),

  ("Pot / Trap",      88, "Low",  "Low",
   "Caged traps placed on the seafloor are retrieved after fish or shellfish enter. "
   "Relatively selective with low bycatch. Non-target species can often be released alive."),

  ("Purse seine (with FAD)", 55, "High", "Low",
   "A large net encircles a Fish Aggregating Device (FAD) — an artificial floating "
   "structure that attracts many species. High bycatch risk: juvenile tuna, sharks, rays, "
   "and sea turtles are commonly caught and discarded."),

  ("Purse seine (without FAD)", 78, "Low", "Low",
   "A large net surrounds a free-swimming school of fish. Without FADs, bycatch is "
   "significantly lower. Commonly used for mackerel, herring, and sardines."),

  ("Purse seine (dolphin-safe)", 72, "Low", "Low",
   "Encircles tuna found swimming near dolphin pods in the Eastern Pacific — without "
   "intentionally trapping dolphins. Reduces dolphin mortality but some non-target "
   "bycatch remains."),

  ("Gillnet",         45, "High", "Low",
   "A wall of near-invisible netting catches fish by their gills. High bycatch including "
   "dolphins, sea turtles, and seabirds. Some fisheries have implemented observer programs "
   "and modified gear to reduce bycatch."),

  ("Set net",         50, "Medium", "Low",
   "A stationary gillnet anchored to the seafloor or surface. Similar bycatch risks to "
   "drift gillnets. Impact varies significantly by location and target species."),

  ("Longline (surface)", 60, "Medium", "Low",
   "A main line with hundreds of baited hooks set near the surface. High bycatch of "
   "seabirds, sea turtles, and sharks. Can be substantially reduced with bird-scaring "
   "lines, circle hooks, and setting lines at night."),

  ("Longline (demersal)", 40, "High", "Low",
   "Baited hooks set on or near the seafloor. High bycatch of non-target bottom fish. "
   "Used for halibut, cod, and sablefish. Impact varies by gear modifications and location."),

  ("Midwater trawl",  35, "Medium", "Low",
   "A large net dragged through the water column without touching the seafloor. Lower "
   "habitat impact than bottom trawling, but moderate bycatch of non-target pelagic fish."),

  ("Otter trawl",     20, "High", "Medium",
   "A cone-shaped net dragged along or near the seafloor, held open by flat boards. "
   "Moderate-to-high seafloor disturbance and high bycatch of juvenile fish and "
   "non-target species."),

  ("Bottom trawl",     8, "High", "High",
   "A heavy net dragged along the seafloor, crushing everything in its path. Destroys "
   "coral reefs, sponge gardens, and seafloor structures that took centuries to form. "
   "Very high bycatch. Considered one of the most environmentally destructive fishing "
   "methods in use today."),

  ("Beam trawl",       5, "High", "High",
   "A trawl net held open by a rigid steel beam, dragged along the seafloor. Heavier "
   "and more damaging than otter trawls. Commonly used for flatfish and shrimp. "
   "High bycatch and severe seafloor habitat destruction."),
  ("Dredge",           3, "High", "High",
   "A metal cage dragged along the seafloor to collect shellfish. Extremely destructive "
   "to seagrass beds, coral reefs, and other benthic habitat. High non-target bycatch. "
   "One of the most habitat-damaging methods in use."),

  ("Unknown",         30, "Medium", "Medium",
   "The fishing method wasn't shown on this product's page. Fishing gear is one of the "
   "biggest factors in environmental impact — ranging from pole & line (near-zero bycatch) "
   "to bottom trawl (highly destructive). Look for gear type information on the packaging "
   "or retailer website."),
]

# Insert format in build_database.py — now 5 columns:
# conn.execute("""
#   INSERT OR IGNORE INTO fishing_methods
#     (method_name, impact_score, bycatch_risk, habitat_impact, educational_note)
#   VALUES (?, ?, ?, ?, ?)
# """, method_tuple)
```

---

## FishBase Ingestion

```python
fn ingest_fishbase(conn: sqlite3.Connection) -> None:
  """Download FishBase species + stocks data via DuckDB Parquet."""
  import duckdb

  # Main species data
  species_df = duckdb.sql("""
    SELECT
      s.SpecCode      AS fishbase_id,
      s.Genus || ' ' || s.Species AS scientific_name,
      s.Vulnerability AS vulnerability,
      CASE
        WHEN s.Resilience = 'Very low' THEN 'Very Low'
        WHEN s.Resilience = 'Low'      THEN 'Low'
        WHEN s.Resilience = 'Medium'   THEN 'Medium'
        WHEN s.Resilience = 'High'     THEN 'High'
        ELSE NULL
      END AS resilience,
      s.IUCNcode      AS iucn_code,
      s.LongevityWild AS max_age_years,
      s.DietTroph     AS trophic_level
    FROM read_parquet('https://fishbase.ropensci.org/fishbase/species.parquet') s
    WHERE s.Vulnerability IS NOT NULL
      AND s.Genus IS NOT NULL AND s.Species IS NOT NULL
  """).df()

  # Stock exploitation status — join stocks table
  # StatusLevel values seen in FishBase: 'overexploited', 'exploited', 'underexploited', NULL
  stocks_df = duckdb.sql("""
    SELECT
      sp.Genus || ' ' || sp.Species AS scientific_name,
      CASE
        WHEN MAX(CASE WHEN LOWER(st.StatusLevel) LIKE '%overexploit%' THEN 1 ELSE 0 END) = 1
          THEN 'overexploited'
        WHEN MAX(CASE WHEN LOWER(st.StatusLevel) LIKE '%fully%'
                           OR LOWER(st.StatusLevel) LIKE '%exploit%' THEN 1 ELSE 0 END) = 1
          THEN 'fully exploited'
        WHEN MAX(CASE WHEN LOWER(st.StatusLevel) LIKE '%under%' THEN 1 ELSE 0 END) = 1
          THEN 'not overexploited'
        ELSE NULL
      END AS stock_exploitation
    FROM read_parquet('https://fishbase.ropensci.org/fishbase/stocks.parquet') st
    JOIN read_parquet('https://fishbase.ropensci.org/fishbase/species.parquet') sp
      ON st.SpecCode = sp.SpecCode
    GROUP BY sp.Genus, sp.Species
  """).df()

  # Common English names
  comnames_df = duckdb.sql("""
    SELECT
      cn.ComName AS alias,
      sp.Genus || ' ' || sp.Species AS scientific_name
    FROM read_parquet('https://fishbase.ropensci.org/fishbase/comnames.parquet') cn
    JOIN read_parquet('https://fishbase.ropensci.org/fishbase/species.parquet') sp
      ON cn.SpecCode = sp.SpecCode
    WHERE cn.Language = 'English'
      AND cn.ComName IS NOT NULL
  """).df()

  # Merge exploitation into species_df
  species_df = species_df.merge(stocks_df, on='scientific_name', how='left')

  # Insert species
  for _, row in species_df.iterrows():
    conn.execute("""
      INSERT OR IGNORE INTO species
        (scientific_name, fishbase_id, vulnerability, resilience, iucn_code,
         max_age_years, trophic_level, stock_exploitation)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      row['scientific_name'], row.get('fishbase_id'),
      row.get('vulnerability'), row.get('resilience'), row.get('iucn_code'),
      row.get('max_age_years'), row.get('trophic_level'),
      row.get('stock_exploitation'),
    ))

  # Insert common name aliases
  for _, row in comnames_df.iterrows():
    conn.execute("""
      INSERT OR IGNORE INTO common_name_aliases (alias, scientific_name)
      VALUES (?, ?)
    """, (row['alias'], row['scientific_name']))

  # Best-fit common names: for each scientific name, pick the most frequent English name
  # and update species.common_name
  name_counts = comnames_df.groupby(['scientific_name', 'alias']).size().reset_index(name='count')
  best_names = name_counts.sort_values('count', ascending=False).drop_duplicates('scientific_name')
  for _, row in best_names.iterrows():
    conn.execute("""
      UPDATE species SET common_name = ? WHERE scientific_name = ?
    """, (row['alias'], row['scientific_name']))
```

---

## NOAA Ingestion (unchanged from v1)

```python
fn ingest_noaa(conn: sqlite3.Connection) -> None:
  """Fetch NOAA FishWatch species list."""
  import urllib.request, json

  urls_to_try = [
    "https://www.fishwatch.gov/api/species",
    "https://www.fisheries.noaa.gov/api/species",
  ]
  data = None
  for url in urls_to_try:
    try:
      with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
      break
    except Exception:
      continue

  if data is None:
    print("WARNING: NOAA FishWatch API unreachable; skipping NOAA data")
    return

  # data may be a list or dict — check before iterating
  if isinstance(data, dict):
    data = list(data.values())

  for sp in data:
    conn.execute("""
      INSERT OR IGNORE INTO noaa_species
        (common_name, scientific_name, fishing_rate, population_status, habitat_impact, bycatch)
      VALUES (?, ?, ?, ?, ?, ?)
    """, (
      sp.get('Species Name', ''),
      sp.get('Scientific Name', ''),
      sp.get('Fishing Rate', 'Unknown'),
      sp.get('Population', 'Unknown'),
      sp.get('Habitat Impacts', ''),
      sp.get('Bycatch', ''),
    ))
```

---

## Seed Alternatives (updated — for fallback when DOM scraping finds nothing)

```python
ALTERNATIVES = [
  # (for_species, alt_species, similarity_reason)
  ("Atlantic salmon (farmed)", "Alaska sockeye salmon",
   "Wild-caught Pacific salmon, similar rich flavor"),
  ("Atlantic salmon (farmed)", "US farmed rainbow trout",
   "Responsibly farmed, similar texture, high omega-3"),
  ("Bluefin tuna",             "Albacore tuna (pole & line)",
   "Pole & line caught, similar firm texture, lower mercury"),
  ("Bluefin tuna",             "Yellowfin tuna (pole & line)",
   "More abundant, comparable for sushi/sashimi"),
  ("Swordfish",                "Pacific halibut",
   "US-managed, similar firm white flesh"),
  ("Imported shrimp",          "US white shrimp",
   "Domestic, regulated, similar mild flavor"),
  ("Imported shrimp",          "Alaska spot prawns",
   "Wild-caught, sustainable, premium flavor"),
  ("Orange roughy",            "Alaskan pollock",
   "Abundant, MSC-certified, mild white fish"),
  ("Shark",                    "Pacific halibut",
   "Sustainable firm white fish alternative"),
  ("Chilean sea bass",         "Alaskan black cod (sablefish)",
   "Wild-caught, similarly rich and buttery"),
]
```

---

## Query Functions (database.py)

```python
# backend/database.py
import sqlite3
from pathlib import Path
from functools import lru_cache

DB_PATH = Path(__file__).parent / "data" / "seafood.db"

fn _connect() -> sqlite3.Connection:
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  return conn

@lru_cache(maxsize=512)
fn get_species(common_name: str) -> dict | None:
  """Look up species by common name (case-insensitive). Results are cached."""
  conn = _connect()
  row = conn.execute("""
    SELECT s.* FROM species s
    JOIN common_name_aliases a ON a.scientific_name = s.scientific_name
    WHERE a.alias = ? COLLATE NOCASE
    ORDER BY s.vulnerability DESC
    LIMIT 1
  """, (common_name,)).fetchone()
  conn.close()
  return dict(row) if row else None

fn get_noaa_status(common_name: str) -> dict | None:
  conn = _connect()
  row = conn.execute("""
    SELECT * FROM noaa_species
    WHERE common_name = ? COLLATE NOCASE
    LIMIT 1
  """, (common_name,)).fetchone()
  conn.close()
  return dict(row) if row else None

fn get_gear_score(method: str) -> dict | None:
  conn = _connect()
  row = conn.execute("""
    SELECT * FROM fishing_methods
    WHERE method_name = ? COLLATE NOCASE
    LIMIT 1
  """, (method,)).fetchone()
  if not row:
    # Fuzzy partial match
    row = conn.execute("""
      SELECT * FROM fishing_methods
      WHERE ? LIKE '%' || method_name || '%'
         OR method_name LIKE '%' || ? || '%'
      ORDER BY impact_score DESC
      LIMIT 1
    """, (method, method)).fetchone()
  conn.close()
  return dict(row) if row else None

fn get_seed_alternatives(species: str) -> list[dict]:
  conn = _connect()
  rows = conn.execute("""
    SELECT alt_species AS species, similarity_reason AS reason
    FROM alternatives
    WHERE for_species = ? COLLATE NOCASE
    LIMIT 3
  """, (species,)).fetchall()
  conn.close()
  return [dict(r) for r in rows]
```

---

## Tests

```python
# backend/tests/test_database.py
from database import get_species, get_noaa_status, get_gear_score, get_seed_alternatives

def test_salmon_lookup():
    result = get_species("Atlantic salmon")
    assert result is not None
    assert result["vulnerability"] is not None
    assert result["resilience"] in ("Very Low", "Low", "Medium", "High")

def test_species_has_exploitation_field():
    """stock_exploitation field exists (may be None for some species)."""
    result = get_species("Atlantic salmon")
    assert result is not None
    assert "stock_exploitation" in result

def test_pollock_noaa():
    result = get_noaa_status("Alaska pollock")
    assert result is not None
    rate = (result["fishing_rate"] or "").lower()
    assert "not" in rate or rate == "unknown"

def test_gear_bottom_trawl():
    result = get_gear_score("Bottom trawl")
    assert result is not None
    assert result["impact_score"] <= 10

def test_gear_pole_line():
    result = get_gear_score("Pole and line")
    assert result is not None
    assert result["impact_score"] >= 90

def test_seed_alternatives():
    alts = get_seed_alternatives("Bluefin tuna")
    assert len(alts) >= 1

def test_common_name_alias():
    """'sockeye salmon' and 'Atlantic salmon' should both resolve."""
    for name in ("sockeye salmon", "Atlantic salmon", "Atlantic mackerel"):
        result = get_species(name)
        assert result is not None, f"Species not found: {name}"
```

---

## Automated Success Criteria

```bash
cd /Users/jordan/sussed/backend

# Build the database (downloads FishBase Parquet via DuckDB, fetches NOAA)
# NOTE: No MSC CSV download required — MSC detection is visual (Gemini).
uv run python -m scripts.build_database

# Run database tests
uv run mypy . 2>&1; uv run ruff check . 2>&1; uv run pytest tests/test_database.py -v 2>&1
```

All tests pass. `backend/data/seafood.db` exists and is > 1 MB.

## Manual Success Criteria

```bash
# Spot-check species count
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/seafood.db')
print('species rows:', conn.execute('SELECT COUNT(*) FROM species').fetchone()[0])
print('aliases rows:', conn.execute('SELECT COUNT(*) FROM common_name_aliases').fetchone()[0])
print('noaa rows:', conn.execute('SELECT COUNT(*) FROM noaa_species').fetchone()[0])
print('methods rows:', conn.execute('SELECT COUNT(*) FROM fishing_methods').fetchone()[0])
"
# Expected: species > 500, aliases > 3000, noaa > 50, methods = 18
```
