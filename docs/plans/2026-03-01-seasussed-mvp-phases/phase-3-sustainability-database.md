# Phase 3: Sustainability Database [batch-eligible]

**Days:** 2–3 | **Depends on:** nothing | **Blocks:** Phase 4

---

## Steps

### 1. SQLite Schema

```python
# backend/scripts/build_database.py
"""
One-time script to build backend/data/seafood.db from:
  - FishBase (via DuckDB/Parquet)
  - MSC Fisheries CSV (manual download from fisheries.msc.org)
  - NOAA FishWatch JSON API
  - Hand-coded tables (gear impact, country management, alternatives)
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS species (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  common_name TEXT NOT NULL,
  scientific_name TEXT NOT NULL,
  vulnerability REAL,          -- FishBase 0-100 (higher = more vulnerable)
  resilience TEXT,             -- 'Very Low' | 'Low' | 'Medium' | 'High'
  iucn_code TEXT,              -- 'LC' | 'NT' | 'VU' | 'EN' | 'CR' | 'DD' | NULL
  max_age_years INTEGER,
  trophic_level REAL,
  fishbase_id INTEGER,
  is_farmed_common BOOLEAN DEFAULT FALSE,  -- commonly sold as farmed
  carnivory_ratio REAL         -- 0-1: 1=obligate carnivore (salmon), 0=herbivore
);

CREATE INDEX IF NOT EXISTS idx_species_common ON species(common_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_species_scientific ON species(scientific_name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS common_name_aliases (
  alias TEXT NOT NULL,
  scientific_name TEXT NOT NULL
  -- e.g. "salmon" -> multiple species, "Atlantic salmon" -> Salmo salar
);

CREATE INDEX IF NOT EXISTS idx_aliases ON common_name_aliases(alias COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS msc_fisheries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  species_common TEXT,
  species_scientific TEXT,
  gear_type TEXT,
  fao_area TEXT,
  country TEXT,
  msc_certified BOOLEAN NOT NULL DEFAULT FALSE,
  certification_status TEXT    -- 'Certified' | 'In Assessment' | 'Withdrawn'
);

CREATE TABLE IF NOT EXISTS noaa_species (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  common_name TEXT NOT NULL,
  scientific_name TEXT,
  fishing_rate TEXT,           -- 'Not subject to overfishing' | 'Overfishing occurring' | 'Unknown'
  population_status TEXT,      -- 'Not overfished' | 'Overfished' | 'Unknown'
  habitat_impact TEXT,
  bycatch TEXT
);

CREATE TABLE IF NOT EXISTS fishing_methods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  method_name TEXT NOT NULL UNIQUE,
  impact_score INTEGER NOT NULL,   -- 0-100 (higher = more sustainable)
  bycatch_risk TEXT,               -- 'Low' | 'Medium' | 'High'
  habitat_impact TEXT              -- 'Low' | 'Medium' | 'High'
);

CREATE TABLE IF NOT EXISTS country_management (
  country TEXT PRIMARY KEY,
  management_score INTEGER NOT NULL  -- 0-5
);

CREATE TABLE IF NOT EXISTS alternatives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  for_species TEXT NOT NULL,        -- common name of the less sustainable fish
  alt_species TEXT NOT NULL,        -- suggested better alternative
  similarity_reason TEXT            -- why this is a good substitute
);
"""
```

### 2. Gear Type Impact Table (Hand-coded)

```python
FISHING_METHODS = [
  # (method_name, impact_score, bycatch_risk, habitat_impact)
  ("Pole and line", 98, "Low", "Low"),
  ("Hook and line", 95, "Low", "Low"),
  ("Troll", 93, "Low", "Low"),
  ("Reef net", 97, "Low", "Low"),
  ("Pot / Trap", 88, "Low", "Low"),
  ("Purse seine (with FAD)", 55, "High", "Low"),
  ("Purse seine (without FAD)", 78, "Low", "Low"),
  ("Purse seine (dolphin-safe)", 72, "Low", "Low"),
  ("Gillnet", 45, "High", "Low"),
  ("Set net", 50, "Medium", "Low"),
  ("Longline (surface)", 60, "Medium", "Low"),
  ("Longline (demersal)", 40, "High", "Low"),
  ("Midwater trawl", 35, "Medium", "Low"),
  ("Otter trawl", 20, "High", "Medium"),
  ("Bottom trawl", 8, "High", "High"),
  ("Beam trawl", 5, "High", "High"),
  ("Dredge", 3, "High", "High"),
  ("Unknown", 30, "Medium", "Medium"),
]
```

### 3. Country Management Scores (Hand-coded)

```python
COUNTRY_MANAGEMENT = [
  ("Norway", 5), ("Iceland", 5), ("United States", 5),
  ("Canada", 5), ("Australia", 5), ("New Zealand", 5),
  ("United Kingdom", 4), ("European Union", 4), ("Japan", 4),
  ("Chile", 4), ("Argentina", 3), ("South Africa", 3),
  ("Peru", 2), ("Ecuador", 2), ("India", 2), ("Thailand", 2),
  ("China", 1), ("Indonesia", 1), ("Vietnam", 1), ("Bangladesh", 1),
]
```

### 4. Alternatives Table (Hand-coded Seed Data)

```python
ALTERNATIVES = [
  # (for_species, alt_species, reason)
  ("Atlantic salmon (farmed, no cert)", "Alaskan sockeye salmon", "Wild-caught, MSC-certified, similar rich flavor"),
  ("Atlantic salmon (farmed, no cert)", "Pacific coho salmon", "Sustainably farmed or wild, similar texture"),
  ("Atlantic salmon (farmed, no cert)", "US farmed rainbow trout", "Responsibly farmed, milder flavor, high omega-3"),
  ("Bluefin tuna", "Albacore tuna (pole & line)", "Pole & line caught, lower mercury, similar firm texture"),
  ("Bluefin tuna", "Yellowfin tuna (pole & line)", "More abundant, comparable for sushi/sashimi"),
  ("Bluefin tuna", "Atlantic mackerel", "Highly sustainable, rich omega-3, great smoked or grilled"),
  ("Swordfish", "Pacific halibut", "US-managed, less overfished, similar firm white flesh"),
  ("Swordfish", "Mahi-mahi (pole & line)", "Fast-reproducing, sustainable when pole & line caught"),
  ("Imported shrimp (no cert)", "US white shrimp", "Domestic, regulated, similar mild flavor"),
  ("Imported shrimp (no cert)", "US farmed shrimp (BAP certified)", "Traceable, lower environmental impact"),
  ("Imported shrimp (no cert)", "US spot prawns", "Wild-caught, sustainable, premium flavor"),
  ("Orange roughy", "Pacific cod", "Faster-reproducing, better managed"),
  ("Orange roughy", "Alaskan pollock", "Abundant, MSC-certified, mild white fish"),
  ("Shark (any)", "Pacific halibut", "Sustainable alternative for firm white fish"),
  ("Chilean sea bass", "Pacific halibut", "Sustainable alternative with similar buttery texture"),
  ("Chilean sea bass", "Alaskan black cod (sablefish)", "Wild-caught, sustainable, similar richness"),
  ("Monkfish", "US catfish (farmed)", "Sustainably farmed, similar firm texture"),
  ("Skate", "US farmed tilapia", "Responsibly farmed, comparable mild flavor"),
]
```

### 5. FishBase Ingestion

```python
fn ingest_fishbase(conn: sqlite3.Connection):
  """Download FishBase species and stocks data via DuckDB Parquet."""
  import duckdb

  # Species data
  species_df = duckdb.sql("""
    SELECT
      SpecCode as fishbase_id,
      Genus || ' ' || Species as scientific_name,
      Vulnerability as vulnerability,
      CASE
        WHEN Resilience = 'Very low'  THEN 'Very Low'
        WHEN Resilience = 'Low'       THEN 'Low'
        WHEN Resilience = 'Medium'    THEN 'Medium'
        WHEN Resilience = 'High'      THEN 'High'
        ELSE NULL
      END as resilience,
      IUCNcode as iucn_code,
      LongevityWild as max_age_years,
      DietTroph as trophic_level
    FROM read_parquet('https://fishbase.ropensci.org/fishbase/species.parquet')
    WHERE Vulnerability IS NOT NULL
      AND (Genus IS NOT NULL AND Species IS NOT NULL)
  """).df()

  # Common names
  comnames_df = duckdb.sql("""
    SELECT
      ComName as common_name,
      Genus || ' ' || Species as scientific_name
    FROM read_parquet('https://fishbase.ropensci.org/fishbase/comnames.parquet')
    WHERE Language = 'English'
  """).df()

  # Insert species (deduplicated by scientific name)
  # Insert common name aliases

fn ingest_msc(conn: sqlite3.Connection, csv_path: str):
  """Ingest MSC Fisheries CSV export from fisheries.msc.org."""
  # CSV fields: UoC, Species, Gear Type, FAO Area, Certification Status
  import csv
  with open(csv_path) as f:
    reader = csv.DictReader(f)
    for row in reader:
      conn.execute("""
        INSERT INTO msc_fisheries
          (species_common, gear_type, fao_area, msc_certified, certification_status)
        VALUES (?, ?, ?, ?, ?)
      """, (
        row.get('Species', ''),
        row.get('Gear Type', ''),
        row.get('FAO Area', ''),
        row.get('Certification Status', '').lower() == 'certified',
        row.get('Certification Status', ''),
      ))

fn ingest_noaa(conn: sqlite3.Connection):
  """Fetch NOAA FishWatch species list."""
  import urllib.request, json
  # Try the known endpoint; handle if migrated
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

### 6. Query Functions

```python
# backend/database.py
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "seafood.db"

fn get_species(common_name: str) -> dict | None:
  """Look up species by common name (case-insensitive)."""
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  # Try exact common name first, then aliases
  row = conn.execute("""
    SELECT s.* FROM species s
    JOIN common_name_aliases a ON a.scientific_name = s.scientific_name
    WHERE a.alias = ? COLLATE NOCASE
    ORDER BY s.vulnerability DESC
    LIMIT 1
  """, (common_name,)).fetchone()
  conn.close()
  return dict(row) if row else None

fn get_msc_status(scientific_name: str, gear: str | None) -> bool:
  """Check if a species+gear combo is MSC certified."""
  conn = sqlite3.connect(DB_PATH)
  row = conn.execute("""
    SELECT msc_certified FROM msc_fisheries
    WHERE species_scientific = ? COLLATE NOCASE
      AND (? IS NULL OR gear_type LIKE '%' || ? || '%')
      AND msc_certified = TRUE
    LIMIT 1
  """, (scientific_name, gear, gear)).fetchone()
  conn.close()
  return bool(row)

fn get_noaa_status(common_name: str) -> dict | None:
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  row = conn.execute("""
    SELECT * FROM noaa_species
    WHERE common_name = ? COLLATE NOCASE
    LIMIT 1
  """, (common_name,)).fetchone()
  conn.close()
  return dict(row) if row else None

fn get_gear_score(method: str) -> dict | None:
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  row = conn.execute("""
    SELECT * FROM fishing_methods
    WHERE method_name = ? COLLATE NOCASE
    LIMIT 1
  """, (method,)).fetchone()
  if not row:
    # Fuzzy fallback: find best partial match
    row = conn.execute("""
      SELECT * FROM fishing_methods
      WHERE ? LIKE '%' || method_name || '%'
         OR method_name LIKE '%' || ? || '%'
      ORDER BY impact_score DESC
      LIMIT 1
    """, (method, method)).fetchone()
  conn.close()
  return dict(row) if row else None

fn get_alternatives(species: str, min_improvement: int = 15) -> list[dict]:
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  rows = conn.execute("""
    SELECT * FROM alternatives
    WHERE for_species = ? COLLATE NOCASE
    LIMIT 3
  """, (species,)).fetchall()
  conn.close()
  return [dict(r) for r in rows]
```

## Verification

```bash
cd /Users/jordan/sussed/backend

# Build the database (downloads FishBase Parquet, ingests MSC CSV, fetches NOAA)
# NOTE: MSC CSV must be manually downloaded from fisheries.msc.org → Export
uv run python -m scripts.build_database

# Run tests
uv run pytest tests/test_database.py -v 2>&1
```

```python
# backend/tests/test_database.py
from database import get_species, get_msc_status, get_gear_score, get_alternatives

def test_salmon_lookup():
  result = get_species("Atlantic salmon")
  assert result is not None
  assert result["vulnerability"] is not None
  assert result["resilience"] in ("Very Low", "Low", "Medium", "High")

def test_bluefin_not_msc():
  # Bluefin tuna is generally not MSC certified
  result = get_msc_status("Thunnus thynnus", None)
  assert result is False

def test_pollock_noaa():
  from database import get_noaa_status
  result = get_noaa_status("Alaska pollock")
  assert result is not None
  assert "not" in result["fishing_rate"].lower() or result["fishing_rate"] == "Unknown"

def test_gear_bottom_trawl():
  result = get_gear_score("Bottom trawl")
  assert result is not None
  assert result["impact_score"] <= 10

def test_gear_pole_line():
  result = get_gear_score("Pole and line")
  assert result is not None
  assert result["impact_score"] >= 90

def test_alternatives():
  alts = get_alternatives("Bluefin tuna")
  assert len(alts) >= 1
```
