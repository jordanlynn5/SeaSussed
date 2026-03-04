"""Build seafood.db from FishBase (Parquet via DuckDB) and NOAA FishWatch data."""

import json
import sqlite3
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "seafood.db"

# FishBase data is hosted on HuggingFace (rfishbase v5+ snapshot)
FISHBASE_BASE = (
    "https://huggingface.co/datasets/cboettig/fishbase"
    "/resolve/main/data/fb/v25.04/parquet"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS species (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  common_name TEXT NOT NULL DEFAULT '',
  scientific_name TEXT NOT NULL UNIQUE,
  vulnerability REAL,
  resilience TEXT,
  iucn_code TEXT,
  max_age_years INTEGER,
  trophic_level REAL,
  fishbase_id INTEGER,
  is_farmed_common BOOLEAN DEFAULT FALSE,
  carnivory_ratio REAL,
  stock_exploitation TEXT
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
  fishing_rate TEXT,
  population_status TEXT,
  habitat_impact TEXT,
  bycatch TEXT
);

CREATE TABLE IF NOT EXISTS fishing_methods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  method_name TEXT NOT NULL UNIQUE,
  impact_score INTEGER NOT NULL,
  bycatch_risk TEXT,
  habitat_impact TEXT,
  educational_note TEXT
);

CREATE TABLE IF NOT EXISTS alternatives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  for_species TEXT NOT NULL,
  alt_species TEXT NOT NULL,
  similarity_reason TEXT
);
"""

FISHING_METHODS = [
    (
        "Pole and line",
        98,
        "Low",
        "Low",
        "Each fish is caught individually on a single hook — the most selective fishing method "
        "in use. Near-zero bycatch and no seafloor impact. The gold standard for tuna fishing.",
    ),
    (
        "Hook and line",
        95,
        "Low",
        "Low",
        "Individual hooks catch fish one at a time. Highly selective, very low bycatch, "
        "and no habitat damage. Common for nearshore species.",
    ),
    (
        "Troll",
        93,
        "Low",
        "Low",
        "Lines with baited hooks are dragged slowly behind a boat. Selective and low-impact "
        "with minimal bycatch and no seafloor damage.",
    ),
    (
        "Reef net",
        97,
        "Low",
        "Low",
        "A stationary net suspended between anchored boats captures fish swimming between them. "
        "Extremely selective with near-zero bycatch — used primarily for wild salmon in the "
        "Pacific Northwest.",
    ),
    (
        "Pot / Trap",
        88,
        "Low",
        "Low",
        "Caged traps placed on the seafloor are retrieved after fish or shellfish enter. "
        "Relatively selective with low bycatch. Non-target species can often be released alive.",
    ),
    (
        "Purse seine (with FAD)",
        55,
        "High",
        "Low",
        "A large net encircles a Fish Aggregating Device (FAD) — an artificial floating "
        "structure that attracts many species. High bycatch risk: juvenile tuna, sharks, rays, "
        "and sea turtles are commonly caught and discarded.",
    ),
    (
        "Purse seine (without FAD)",
        78,
        "Low",
        "Low",
        "A large net surrounds a free-swimming school of fish. Without FADs, bycatch is "
        "significantly lower. Commonly used for mackerel, herring, and sardines.",
    ),
    (
        "Purse seine (dolphin-safe)",
        72,
        "Low",
        "Low",
        "Encircles tuna found swimming near dolphin pods in the Eastern Pacific — without "
        "intentionally trapping dolphins. Reduces dolphin mortality but some non-target "
        "bycatch remains.",
    ),
    (
        "Gillnet",
        45,
        "High",
        "Low",
        "A wall of near-invisible netting catches fish by their gills. High bycatch including "
        "dolphins, sea turtles, and seabirds. Some fisheries have implemented observer programs "
        "and modified gear to reduce bycatch.",
    ),
    (
        "Set net",
        50,
        "Medium",
        "Low",
        "A stationary gillnet anchored to the seafloor or surface. Similar bycatch risks to "
        "drift gillnets. Impact varies significantly by location and target species.",
    ),
    (
        "Longline (surface)",
        60,
        "Medium",
        "Low",
        "A main line with hundreds of baited hooks set near the surface. High bycatch of "
        "seabirds, sea turtles, and sharks. Can be substantially reduced with bird-scaring "
        "lines, circle hooks, and setting lines at night.",
    ),
    (
        "Longline (demersal)",
        40,
        "High",
        "Low",
        "Baited hooks set on or near the seafloor. High bycatch of non-target bottom fish. "
        "Used for halibut, cod, and sablefish. Impact varies by gear modifications and location.",
    ),
    (
        "Midwater trawl",
        35,
        "Medium",
        "Low",
        "A large net dragged through the water column without touching the seafloor. Lower "
        "habitat impact than bottom trawling, but moderate bycatch of non-target pelagic fish.",
    ),
    (
        "Otter trawl",
        20,
        "High",
        "Medium",
        "A cone-shaped net dragged along or near the seafloor, held open by flat boards. "
        "Moderate-to-high seafloor disturbance and high bycatch of juvenile fish and "
        "non-target species.",
    ),
    (
        "Bottom trawl",
        8,
        "High",
        "High",
        "A heavy net dragged along the seafloor, crushing everything in its path. Destroys "
        "coral reefs, sponge gardens, and seafloor structures that took centuries to form. "
        "Very high bycatch. Considered one of the most environmentally destructive fishing "
        "methods in use today.",
    ),
    (
        "Beam trawl",
        5,
        "High",
        "High",
        "A trawl net held open by a rigid steel beam, dragged along the seafloor. Heavier "
        "and more damaging than otter trawls. Commonly used for flatfish and shrimp. "
        "High bycatch and severe seafloor habitat destruction.",
    ),
    (
        "Dredge",
        3,
        "High",
        "High",
        "A metal cage dragged along the seafloor to collect shellfish. Extremely destructive "
        "to seagrass beds, coral reefs, and other benthic habitat. High non-target bycatch. "
        "One of the most habitat-damaging methods in use.",
    ),
    (
        "Unknown",
        30,
        "Medium",
        "Medium",
        "The fishing method wasn't shown on this product's page. Fishing gear is one of the "
        "biggest factors in environmental impact — ranging from pole & line (near-zero bycatch) "
        "to bottom trawl (highly destructive). Look for gear type information on the packaging "
        "or retailer website.",
    ),
]

ALTERNATIVES = [
    (
        "Atlantic salmon (farmed)",
        "Alaska sockeye salmon",
        "Wild-caught Pacific salmon, similar rich flavor",
    ),
    (
        "Atlantic salmon (farmed)",
        "US farmed rainbow trout",
        "Responsibly farmed, similar texture, high omega-3",
    ),
    (
        "Bluefin tuna",
        "Albacore tuna (pole & line)",
        "Pole & line caught, similar firm texture, lower mercury",
    ),
    (
        "Bluefin tuna",
        "Yellowfin tuna (pole & line)",
        "More abundant, comparable for sushi/sashimi",
    ),
    (
        "Swordfish",
        "Pacific halibut",
        "US-managed, similar firm white flesh",
    ),
    (
        "Imported shrimp",
        "US white shrimp",
        "Domestic, regulated, similar mild flavor",
    ),
    (
        "Imported shrimp",
        "Alaska spot prawns",
        "Wild-caught, sustainable, premium flavor",
    ),
    (
        "Orange roughy",
        "Alaskan pollock",
        "Abundant, MSC-certified, mild white fish",
    ),
    (
        "Shark",
        "Pacific halibut",
        "Sustainable firm white fish alternative",
    ),
    (
        "Chilean sea bass",
        "Alaskan black cod (sablefish)",
        "Wild-caught, similarly rich and buttery",
    ),
]

# ---------------------------------------------------------------------------
# Supplementary data: grocery-product common names + shellfish species
# that FishBase (finfish-focused) doesn't cover or uses different names for.
# These are the exact names Gemini returns from grocery product screenshots.
# ---------------------------------------------------------------------------

# Extra aliases to insert AFTER FishBase ingest.
# Format: (alias, scientific_name_must_exist_in_species_table)
SUPPLEMENTARY_ALIASES = [
    # Sockeye salmon — Gemini returns "Alaska sockeye salmon"; FishBase only has "Sockeye salmon"
    ("Alaska sockeye salmon", "Oncorhynchus nerka"),
    ("Wild Alaska sockeye salmon", "Oncorhynchus nerka"),
    ("Bristol Bay sockeye salmon", "Oncorhynchus nerka"),
    ("Copper River sockeye salmon", "Oncorhynchus nerka"),
    # Chinook / King salmon
    ("King salmon", "Oncorhynchus tshawytscha"),
    ("Wild King salmon", "Oncorhynchus tshawytscha"),
    ("Alaska King salmon", "Oncorhynchus tshawytscha"),
    # Coho
    ("Silver salmon", "Oncorhynchus kisutch"),
    ("Wild coho salmon", "Oncorhynchus kisutch"),
    # Pollock
    ("Wild Alaska pollock", "Gadus chalcogrammus"),
    ("Alaskan pollock", "Gadus chalcogrammus"),
    # Atlantic cod
    ("Cod", "Gadus morhua"),
    ("North Atlantic cod", "Gadus morhua"),
    # Bluefin tuna
    ("Atlantic bluefin tuna", "Thunnus thynnus"),
    ("Pacific bluefin tuna", "Thunnus orientalis"),
]

# Hand-coded seed species for shellfish and other non-FishBase species.
# Data sourced from peer-reviewed FishBase-equivalent sources (SeaLifeBase, FAO).
# Format: (scientific_name, vulnerability, resilience, iucn_code,
#          trophic_level, carnivory_ratio, stock_exploitation, common_name)
SUPPLEMENTARY_SPECIES = [
    # Pacific oyster — filter feeder, farmed globally, excellent sustainability
    (
        "Magallana gigas",
        28.0,      # low vulnerability (fast-growing bivalve)
        "High",    # high resilience
        "LC",      # IUCN Least Concern
        2.1,       # trophic level: filter feeder
        0.0,       # carnivory_ratio: pure filter feeder
        "not overexploited",
        "Pacific oyster",
    ),
    # Eastern oyster (US farmed)
    (
        "Crassostrea virginica",
        30.0,
        "High",
        "LC",
        2.1,
        0.0,
        "not overexploited",
        "Eastern oyster",
    ),
    # Blue mussel — farmed, very sustainable
    (
        "Mytilus edulis",
        25.0,
        "High",
        "LC",
        2.1,
        0.0,
        "not overexploited",
        "Blue mussel",
    ),
    # Whiteleg shrimp — most-farmed shrimp globally
    (
        "Litopenaeus vannamei",
        50.0,
        "High",
        "LC",
        2.4,
        0.25,      # low carnivory (omnivore, fed plant-heavy diet in aquaculture)
        "fully exploited",
        "Whiteleg shrimp",
    ),
    # Atlantic scallop — US managed, hook-and-line plus dredge
    (
        "Placopecten magellanicus",
        40.0,
        "Medium",
        "LC",
        2.5,
        0.0,
        "not overexploited",
        "Sea scallop",
    ),
]

# Supplementary NOAA entries for species with grocery-common names not in the seed.
SUPPLEMENTARY_NOAA = [
    ("Alaska sockeye salmon", "Oncorhynchus nerka",
     "Not subject to overfishing", "Not overfished",
     "Low impact; managed by ADF&G", "Very low with selective gear"),
    ("Wild Alaska sockeye salmon", "Oncorhynchus nerka",
     "Not subject to overfishing", "Not overfished",
     "Low impact; managed by ADF&G", "Very low with selective gear"),
    ("Pacific oyster", "Magallana gigas",
     "Not subject to overfishing", "Not overfished",
     "Aquaculture; filters and improves water quality", "Not applicable for farmed"),
    ("Whiteleg shrimp", "Litopenaeus vannamei",
     "Unknown", "Unknown",
     "Pond aquaculture; varies by farm", "Not applicable for farmed"),
]

# IUCN code → stock_exploitation mapping
# LC = Least Concern → not overexploited
# NT = Near Threatened → fully exploited
# VU/EN/CR = threatened categories → overexploited
# DD/NE = Data Deficient / Not Evaluated → NULL
_IUCN_TO_EXPLOITATION = {
    "LC": "not overexploited",
    "NT": "fully exploited",
    "VU": "overexploited",
    "EN": "overexploited",
    "CR": "overexploited",
}

# Static NOAA FishWatch data for key grocery species.
# The NOAA FishWatch API (fishwatch.gov/api/species) no longer returns JSON.
# This seed covers the US species most commonly found in grocery stores.
# Format: (common_name, scientific_name, fishing_rate, population_status, habitat_impact, bycatch)
NOAA_SPECIES_SEED = [
    (
        "Alaska pollock",
        "Gadus chalcogrammus",
        "Not subject to overfishing",
        "Not overfished",
        "Midwater trawls have minimal seafloor impact",
        "Minimal bycatch with excluder devices",
    ),
    (
        "Pacific salmon",
        "Oncorhynchus spp.",
        "Not subject to overfishing",
        "Not overfished",
        "Low habitat impact with hook and line and reef nets",
        "Very low with selective gear",
    ),
    (
        "Sockeye salmon",
        "Oncorhynchus nerka",
        "Not subject to overfishing",
        "Not overfished",
        "Low impact; gillnets and seines used in managed fisheries",
        "Low with proper gear",
    ),
    (
        "Chinook salmon",
        "Oncorhynchus tshawytscha",
        "Not subject to overfishing",
        "Not overfished",
        "Low habitat impact",
        "Low with selective gear",
    ),
    (
        "Coho salmon",
        "Oncorhynchus kisutch",
        "Not subject to overfishing",
        "Not overfished",
        "Low habitat impact",
        "Low with selective gear",
    ),
    (
        "Atlantic cod",
        "Gadus morhua",
        "Overfishing occurring",
        "Overfished",
        "Otter trawls cause seafloor disturbance",
        "High bycatch of non-target species",
    ),
    (
        "Pacific halibut",
        "Hippoglossus stenolepis",
        "Not subject to overfishing",
        "Not overfished",
        "Hook and line causes minimal seafloor impact",
        "Low bycatch with hook and line",
    ),
    (
        "Atlantic halibut",
        "Hippoglossus hippoglossus",
        "Unknown",
        "Overfished",
        "Bottom trawls cause seafloor disturbance",
        "High non-target bycatch",
    ),
    (
        "Swordfish",
        "Xiphias gladius",
        "Not subject to overfishing",
        "Not overfished",
        "Minimal seafloor impact with longlines",
        "Bycatch of sea turtles, sharks, and seabirds possible",
    ),
    (
        "Yellowfin tuna",
        "Thunnus albacares",
        "Not subject to overfishing",
        "Not overfished",
        "Minimal seafloor impact",
        "Bycatch varies by gear type",
    ),
    (
        "Albacore tuna",
        "Thunnus alalunga",
        "Not subject to overfishing",
        "Not overfished",
        "Low impact with pole and line or troll gear",
        "Very low with pole and line",
    ),
    (
        "Bluefin tuna",
        "Thunnus thynnus",
        "Overfishing occurring",
        "Overfished",
        "Minimal seafloor impact",
        "Bycatch of non-target species in purse seine",
    ),
    (
        "Mahi mahi",
        "Coryphaena hippurus",
        "Not subject to overfishing",
        "Not overfished",
        "Minimal seafloor impact",
        "Some bycatch with longlines",
    ),
    (
        "Tilapia",
        "Oreochromis niloticus",
        "Unknown",
        "Unknown",
        "Aquaculture; minimal wild impact",
        "Not applicable for farmed",
    ),
    (
        "Shrimp",
        "Penaeus spp.",
        "Unknown",
        "Unknown",
        "Trawls can damage seafloor habitat",
        "High bycatch with shrimp trawls",
    ),
    (
        "Gulf shrimp",
        "Penaeus aztecus",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls cause seafloor disturbance",
        "High bycatch; bycatch reduction devices required",
    ),
    (
        "Dungeness crab",
        "Cancer magister",
        "Not subject to overfishing",
        "Not overfished",
        "Pot fishing has minimal seafloor impact",
        "Low bycatch; non-target species can be released alive",
    ),
    (
        "Snow crab",
        "Chionoecetes opilio",
        "Not subject to overfishing",
        "Not overfished",
        "Pot fishing has low seafloor impact",
        "Low bycatch with pot gear",
    ),
    (
        "American lobster",
        "Homarus americanus",
        "Not subject to overfishing",
        "Not overfished",
        "Pot fishing has minimal seafloor impact",
        "Low bycatch with pot gear",
    ),
    (
        "Oysters",
        "Crassostrea virginica",
        "Not subject to overfishing",
        "Not overfished",
        "Farmed oysters improve water quality",
        "Not applicable for farmed",
    ),
    (
        "Salmon (farmed)",
        "Salmo salar",
        "Unknown",
        "Unknown",
        "Aquaculture; varies by operation",
        "Not applicable for farmed",
    ),
    (
        "Catfish",
        "Ictalurus punctatus",
        "Not subject to overfishing",
        "Not overfished",
        "US farmed catfish in ponds; low environmental impact",
        "Not applicable for farmed",
    ),
    (
        "Sablefish",
        "Anoplopoma fimbria",
        "Not subject to overfishing",
        "Not overfished",
        "Hook and line and pots have low habitat impact",
        "Low bycatch with pot gear",
    ),
    (
        "Pacific sardines",
        "Sardinops sagax",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine has minimal seafloor impact",
        "Very low bycatch with purse seine",
    ),
    (
        "Pacific mackerel",
        "Scomber japonicus",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine has minimal seafloor impact",
        "Low bycatch",
    ),
    (
        "Atlantic mackerel",
        "Scomber scombrus",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine has minimal seafloor impact",
        "Low bycatch",
    ),
    (
        "Orange roughy",
        "Hoplostethus atlanticus",
        "Overfishing occurring",
        "Overfished",
        "Deep-sea trawls damage vulnerable coral habitats",
        "High bycatch of deep-sea species",
    ),
    (
        "Chilean sea bass",
        "Dissostichus eleginoides",
        "Unknown",
        "Unknown",
        "Longlining; some illegal fishing occurs",
        "Seabird bycatch a concern",
    ),
    (
        "Shark",
        "Various",
        "Overfishing occurring",
        "Overfished",
        "Varies by species and gear",
        "Often caught as bycatch in other fisheries",
    ),
    (
        "Clams",
        "Mercenaria mercenaria",
        "Not subject to overfishing",
        "Not overfished",
        "Dredging can disturb seafloor habitat",
        "Low bycatch",
    ),
    (
        "Scallops",
        "Placopecten magellanicus",
        "Not subject to overfishing",
        "Not overfished",
        "Dredging can damage seafloor habitat",
        "Some bycatch of juvenile fish",
    ),
    (
        "Rainbow trout",
        "Oncorhynchus mykiss",
        "Not subject to overfishing",
        "Not overfished",
        "Farmed in freshwater ponds and raceways; low wild impact",
        "Not applicable for farmed",
    ),
    (
        "Pacific rockfish",
        "Sebastes spp.",
        "Not subject to overfishing",
        "Not overfished",
        "Hook and line and trawl; varies by species and location",
        "Low bycatch with hook and line",
    ),
    (
        "Lingcod",
        "Ophiodon elongatus",
        "Not subject to overfishing",
        "Not overfished",
        "Hook and line has minimal seafloor impact",
        "Low bycatch with hook and line",
    ),
    (
        "Pacific cod",
        "Gadus macrocephalus",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls can damage seafloor habitat",
        "Bycatch of other groundfish possible",
    ),
    (
        "Spiny lobster",
        "Panulirus argus",
        "Not subject to overfishing",
        "Not overfished",
        "Traps have minimal seafloor impact",
        "Low bycatch with trap gear",
    ),
    (
        "Striped bass",
        "Morone saxatilis",
        "Not subject to overfishing",
        "Not overfished",
        "Hook and line has minimal habitat impact",
        "Low bycatch with recreational fishing methods",
    ),
    (
        "Monkfish",
        "Lophius americanus",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls and gillnets; some seafloor disturbance",
        "Bycatch of non-target groundfish",
    ),
    (
        "Haddock",
        "Melanogrammus aeglefinus",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls and longlines; habitat impact varies",
        "Bycatch of cod and other groundfish possible",
    ),
    (
        "Flounder",
        "Paralichthys spp.",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls cause seafloor disturbance",
        "Bycatch of juvenile fish",
    ),
    (
        "Sole",
        "Microstomus pacificus",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls and otter trawls; seafloor disturbance",
        "Bycatch of non-target flatfish",
    ),
    (
        "Squid",
        "Doryteuthis opalescens",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine and jigging have minimal seafloor impact",
        "Low bycatch with jig gear",
    ),
    (
        "Herring",
        "Clupea harengus",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine has minimal seafloor impact",
        "Very low bycatch with purse seine",
    ),
    (
        "Anchovy",
        "Engraulis mordax",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine has minimal seafloor impact",
        "Very low bycatch with purse seine",
    ),
    (
        "Pollock (Atlantic)",
        "Pollachius virens",
        "Not subject to overfishing",
        "Not overfished",
        "Bottom trawls can disturb seafloor habitat",
        "Bycatch of other groundfish possible",
    ),
    (
        "King crab",
        "Paralithodes camtschaticus",
        "Not subject to overfishing",
        "Not overfished",
        "Pot fishing has minimal seafloor impact",
        "Low bycatch with pot gear",
    ),
    (
        "Blue crab",
        "Callinectes sapidus",
        "Unknown",
        "Unknown",
        "Crab pots have minimal seafloor impact",
        "Low bycatch with pot gear",
    ),
    (
        "Mussels",
        "Mytilus edulis",
        "Not subject to overfishing",
        "Not overfished",
        "Aquaculture; low environmental impact; can improve water quality",
        "Not applicable for farmed",
    ),
    (
        "Sea scallops",
        "Placopecten magellanicus",
        "Not subject to overfishing",
        "Not overfished",
        "Dredging can damage seafloor habitat; rotational areas in use",
        "Some bycatch of juvenile fish; habitat recovery programs active",
    ),
    (
        "Skipjack tuna",
        "Katsuwonus pelamis",
        "Not subject to overfishing",
        "Not overfished",
        "Purse seine and pole and line; minimal seafloor impact",
        "Bycatch varies greatly by gear; pole and line very low",
    ),
    (
        "Wahoo",
        "Acanthocybium solandri",
        "Unknown",
        "Unknown",
        "Trolling has minimal seafloor impact",
        "Low bycatch with troll gear",
    ),
    (
        "Pompano",
        "Trachinotus carolinus",
        "Not subject to overfishing",
        "Not overfished",
        "Aquaculture and hook and line; low environmental impact",
        "Not applicable for farmed",
    ),
]


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_fishing_methods(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO fishing_methods
          (method_name, impact_score, bycatch_risk, habitat_impact, educational_note)
        VALUES (?, ?, ?, ?, ?)
        """,
        FISHING_METHODS,
    )
    conn.commit()
    print(f"  Seeded {len(FISHING_METHODS)} fishing methods")


def seed_alternatives(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO alternatives (for_species, alt_species, similarity_reason)
        VALUES (?, ?, ?)
        """,
        ALTERNATIVES,
    )
    conn.commit()
    print(f"  Seeded {len(ALTERNATIVES)} alternative entries")


def seed_supplementary_data(conn: sqlite3.Connection) -> None:
    """Insert supplementary species + aliases after FishBase ingest.

    This covers grocery-common names Gemini returns that FishBase doesn't
    include (primarily shellfish) and aliases for species where FishBase
    uses a different common name than what appears on grocery packaging.
    """
    # Insert supplementary species (shellfish etc. not in FishBase)
    for (sci, vuln, res, iucn, trophic, carnivory, exploit, common) in SUPPLEMENTARY_SPECIES:
        exploit_val = exploit if exploit else None
        conn.execute(
            """
            INSERT OR IGNORE INTO species
              (scientific_name, vulnerability, resilience, iucn_code,
               trophic_level, carnivory_ratio, stock_exploitation, common_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sci, vuln, res, iucn, trophic, carnivory, exploit_val, common),
        )
        # Also insert the common name as an alias
        conn.execute(
            "INSERT OR IGNORE INTO common_name_aliases (alias, scientific_name) VALUES (?, ?)",
            (common, sci),
        )

    # Insert supplementary aliases (grocery names → existing FishBase species)
    for alias, sci in SUPPLEMENTARY_ALIASES:
        conn.execute(
            "INSERT OR IGNORE INTO common_name_aliases (alias, scientific_name) VALUES (?, ?)",
            (alias, sci),
        )

    # Insert supplementary NOAA entries
    conn.executemany(
        """
        INSERT OR IGNORE INTO noaa_species
          (common_name, scientific_name, fishing_rate, population_status,
           habitat_impact, bycatch)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        SUPPLEMENTARY_NOAA,
    )

    conn.commit()
    print(
        f"  Seeded {len(SUPPLEMENTARY_SPECIES)} supplementary species, "
        f"{len(SUPPLEMENTARY_ALIASES)} aliases, "
        f"{len(SUPPLEMENTARY_NOAA)} NOAA entries"
    )


def ingest_fishbase(conn: sqlite3.Connection) -> None:
    """Download FishBase species + stocks + ecology data via DuckDB Parquet.

    Data hosted on HuggingFace (rfishbase v5 snapshot, v25.04).
    Column locations differ from older ropensci.org hosting:
      - Resilience: stocks table (not species)
      - IUCN_Code:  stocks table (not species)
      - DietTroph:  ecology table (not species)
    """
    import duckdb

    sp_url = f"{FISHBASE_BASE}/species.parquet"
    st_url = f"{FISHBASE_BASE}/stocks.parquet"
    ec_url = f"{FISHBASE_BASE}/ecology.parquet"
    cn_url = f"{FISHBASE_BASE}/comnames.parquet"

    print("  Fetching FishBase species data…")
    species_df = duckdb.sql(f"""
        SELECT
          s.SpecCode      AS fishbase_id,
          s.Genus || ' ' || s.Species AS scientific_name,
          s.Vulnerability AS vulnerability,
          s.LongevityWild AS max_age_years
        FROM read_parquet('{sp_url}') s
        WHERE s.Vulnerability IS NOT NULL
          AND s.Genus IS NOT NULL AND s.Species IS NOT NULL
    """).df()
    print(f"  Fetched {len(species_df)} species rows")

    # stocks: Resilience + IUCN_Code — one row per stock; take most severe per species.
    # CTE ranks each metric numerically first, then maps back to labels in the outer SELECT.
    print("  Fetching FishBase stocks data (Resilience + IUCN)…")
    stocks_df = duckdb.sql(f"""
        WITH stocks_agg AS (
          SELECT
            sp.Genus || ' ' || sp.Species AS scientific_name,
            MIN(CASE st.Resilience
              WHEN 'Very low' THEN 1 WHEN 'Low' THEN 2
              WHEN 'Medium'   THEN 3 WHEN 'High' THEN 4
              ELSE 5 END) AS resilience_rank,
            MAX(CASE st.IUCN_Code
              WHEN 'CR' THEN 6 WHEN 'EN' THEN 5 WHEN 'VU' THEN 4
              WHEN 'NT' THEN 3 WHEN 'LC' THEN 2 WHEN 'DD' THEN 1
              ELSE 0 END) AS iucn_rank
          FROM read_parquet('{st_url}') st
          JOIN read_parquet('{sp_url}') sp ON st.SpecCode = sp.SpecCode
          WHERE sp.Genus IS NOT NULL AND sp.Species IS NOT NULL
          GROUP BY sp.Genus, sp.Species
        )
        SELECT
          scientific_name,
          CASE resilience_rank
            WHEN 1 THEN 'Very Low' WHEN 2 THEN 'Low'
            WHEN 3 THEN 'Medium'   WHEN 4 THEN 'High'
            ELSE NULL END AS resilience,
          CASE iucn_rank
            WHEN 6 THEN 'CR' WHEN 5 THEN 'EN' WHEN 4 THEN 'VU'
            WHEN 3 THEN 'NT' WHEN 2 THEN 'LC' WHEN 1 THEN 'DD'
            ELSE NULL END AS iucn_code
        FROM stocks_agg
    """).df()
    print(f"  Fetched {len(stocks_df)} stocks summary rows")

    # ecology: DietTroph — take mean per species (multiple ecology records possible)
    print("  Fetching FishBase ecology data (trophic level)…")
    ecology_df = duckdb.sql(f"""
        SELECT
          sp.Genus || ' ' || sp.Species AS scientific_name,
          AVG(ec.DietTroph) AS trophic_level
        FROM read_parquet('{ec_url}') ec
        JOIN read_parquet('{sp_url}') sp ON ec.SpecCode = sp.SpecCode
        WHERE ec.DietTroph IS NOT NULL
          AND sp.Genus IS NOT NULL AND sp.Species IS NOT NULL
        GROUP BY sp.Genus, sp.Species
    """).df()
    print(f"  Fetched {len(ecology_df)} ecology rows")

    # Common English names
    print("  Fetching FishBase common names (English)…")
    comnames_df = duckdb.sql(f"""
        SELECT
          cn.ComName AS alias,
          sp.Genus || ' ' || sp.Species AS scientific_name
        FROM read_parquet('{cn_url}') cn
        JOIN read_parquet('{sp_url}') sp ON cn.SpecCode = sp.SpecCode
        WHERE cn.Language = 'English'
          AND cn.ComName IS NOT NULL
          AND sp.Genus IS NOT NULL AND sp.Species IS NOT NULL
    """).df()
    print(f"  Fetched {len(comnames_df)} common name aliases")

    # Merge all into species_df
    species_df = (
        species_df
        .merge(stocks_df, on="scientific_name", how="left")
        .merge(ecology_df, on="scientific_name", how="left")
    )

    # Derive stock_exploitation from iucn_code
    species_df["stock_exploitation"] = species_df["iucn_code"].map(
        lambda c: _IUCN_TO_EXPLOITATION.get(str(c), None) if c is not None else None
    )

    # Insert species rows (batch — 36k rows, much faster than row-by-row loop)
    species_rows = [
        (
            row["scientific_name"],
            _safe(row.get("fishbase_id")),
            _safe(row.get("vulnerability")),
            _safe(row.get("resilience")),
            _safe(row.get("iucn_code")),
            _safe(row.get("max_age_years")),
            _safe(row.get("trophic_level")),
            _safe(row.get("stock_exploitation")),
        )
        for _, row in species_df.iterrows()
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO species
          (scientific_name, fishbase_id, vulnerability, resilience, iucn_code,
           max_age_years, trophic_level, stock_exploitation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        species_rows,
    )
    conn.commit()
    print(f"  Inserted {len(species_rows)} species")

    # Insert common name aliases
    alias_rows = [(row["alias"], row["scientific_name"]) for _, row in comnames_df.iterrows()]
    conn.executemany(
        "INSERT OR IGNORE INTO common_name_aliases (alias, scientific_name) VALUES (?, ?)",
        alias_rows,
    )
    conn.commit()
    print(f"  Inserted {len(alias_rows)} common name aliases")

    # Set best common_name per species (most frequent English name)
    name_counts = comnames_df.groupby(["scientific_name", "alias"]).size().reset_index(name="count")
    best_names = (
        name_counts.sort_values("count", ascending=False).drop_duplicates("scientific_name")
    )
    name_updates = [(row["alias"], row["scientific_name"]) for _, row in best_names.iterrows()]
    conn.executemany(
        "UPDATE species SET common_name = ? WHERE scientific_name = ?",
        name_updates,
    )
    conn.commit()
    print(f"  Updated common_name for {len(name_updates)} species")


def _safe(val: object) -> object:
    """Convert NaN/NaT to None for SQLite."""
    import math

    if val is None:
        return None
    try:
        if math.isnan(float(val)):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    return val


def _fetch_live_noaa() -> list[dict[str, str]] | None:
    """Attempt to fetch live NOAA FishWatch data from fallback URLs.

    Returns a list of species dicts, or None if all URLs are unavailable.
    The API has returned HTML instead of JSON since early 2026.
    """
    urls_to_try = [
        "https://www.fishwatch.gov/api/species",
        "https://www.fisheries.noaa.gov/api/species",
    ]
    for url in urls_to_try:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8").strip()
                if not raw.startswith("[") and not raw.startswith("{"):
                    continue  # HTML response — not JSON
                data = json.loads(raw)
            print(f"  Also fetched live NOAA data from {url}")
            return data if isinstance(data, list) else list(data.values())
        except Exception as exc:
            print(f"  INFO: live NOAA API unavailable ({exc}); using static seed only")
    return None


def ingest_noaa(conn: sqlite3.Connection) -> None:
    """Seed NOAA species data.

    The NOAA FishWatch API (fishwatch.gov/api/species) no longer returns JSON as of 2026.
    We use a curated static seed of key grocery species (NOAA_SPECIES_SEED) and attempt
    to supplement with live API data if available.
    """
    conn.executemany(
        """
        INSERT OR IGNORE INTO noaa_species
          (common_name, scientific_name, fishing_rate, population_status,
           habitat_impact, bycatch)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        NOAA_SPECIES_SEED,
    )
    conn.commit()
    print(f"  Seeded {len(NOAA_SPECIES_SEED)} NOAA species (static)")

    live_data = _fetch_live_noaa()
    if live_data is None:
        return

    live_rows = [
        (
            sp.get("Species Name", ""),
            sp.get("Scientific Name", ""),
            sp.get("Fishing Rate", "Unknown"),
            sp.get("Population", "Unknown"),
            sp.get("Habitat Impacts", ""),
            sp.get("Bycatch", ""),
        )
        for sp in live_data
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO noaa_species
          (common_name, scientific_name, fishing_rate, population_status,
           habitat_impact, bycatch)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        live_rows,
    )
    conn.commit()
    if live_rows:
        print(f"  Supplemented with {len(live_rows)} live NOAA rows")


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing {DB_PATH}")

    print(f"Building {DB_PATH}…")
    conn = sqlite3.connect(DB_PATH)

    print("Creating schema…")
    create_schema(conn)

    print("Seeding fishing methods…")
    seed_fishing_methods(conn)

    print("Seeding alternatives…")
    seed_alternatives(conn)

    print("Ingesting FishBase data…")
    ingest_fishbase(conn)

    print("Ingesting NOAA FishWatch data…")
    ingest_noaa(conn)

    print("Seeding supplementary species + aliases…")
    seed_supplementary_data(conn)

    print("species rows:", conn.execute("SELECT COUNT(*) FROM species").fetchone()[0])
    print("aliases rows:", conn.execute("SELECT COUNT(*) FROM common_name_aliases").fetchone()[0])
    print("noaa rows:", conn.execute("SELECT COUNT(*) FROM noaa_species").fetchone()[0])
    print("methods rows:", conn.execute("SELECT COUNT(*) FROM fishing_methods").fetchone()[0])
    conn.close()

    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nDone. {DB_PATH} — {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
