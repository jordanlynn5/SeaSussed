"""SQLite query functions for the SeaSussed sustainability database."""

import sqlite3
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Generator

DB_PATH = Path(__file__).parent / "data" / "seafood.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db() -> Generator[sqlite3.Connection, None, None]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@lru_cache(maxsize=512)
def get_species(common_name: str) -> dict[str, Any] | None:
    """Look up species by common name (case-insensitive). Results are cached."""
    with _db() as conn:
        row = conn.execute(
            """
            SELECT s.* FROM species s
            JOIN common_name_aliases a ON a.scientific_name = s.scientific_name
            WHERE a.alias = ? COLLATE NOCASE
            ORDER BY s.vulnerability DESC
            LIMIT 1
            """,
            (common_name,),
        ).fetchone()
        return dict(row) if row else None


@lru_cache(maxsize=512)
def get_noaa_status(common_name: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            """
            SELECT * FROM noaa_species
            WHERE common_name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (common_name,),
        ).fetchone()
        return dict(row) if row else None


@lru_cache(maxsize=256)
def get_gear_score(method: str) -> dict[str, Any] | None:
    with _db() as conn:
        row = conn.execute(
            """
            SELECT * FROM fishing_methods
            WHERE method_name = ? COLLATE NOCASE
            LIMIT 1
            """,
            (method,),
        ).fetchone()
        if not row:
            # Fuzzy partial match
            row = conn.execute(
                """
                SELECT * FROM fishing_methods
                WHERE ? LIKE '%' || method_name || '%'
                   OR method_name LIKE '%' || ? || '%'
                ORDER BY impact_score DESC
                LIMIT 1
                """,
                (method, method),
            ).fetchone()
        return dict(row) if row else None


def get_seed_alternatives(species: str) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT alt_species AS species, similarity_reason AS reason
            FROM alternatives
            WHERE for_species = ? COLLATE NOCASE
            LIMIT 3
            """,
            (species,),
        ).fetchall()
        return [dict(r) for r in rows]
