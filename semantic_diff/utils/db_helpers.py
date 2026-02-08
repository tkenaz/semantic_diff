"""
Database helpers for caching analysis results.
"""

import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS analysis_cache (
    commit_hash TEXT NOT NULL,
    author TEXT NOT NULL,
    result TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (commit_hash, author)
)
"""


@contextmanager
def get_connection():
    """Get database connection as context manager."""
    db_path = os.getenv("SEMANTIC_DIFF_CACHE_DB", "cache.db")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Initialize database schema."""
    with get_connection() as conn:
        conn.execute(CREATE_TABLE)
        conn.commit()
    logger.debug("Cache database initialized")


def get_cached_analysis(
    commit_hash: str, author: Optional[str] = None
) -> Optional[sqlite3.Row]:
    """Look up cached analysis by commit hash and optional author filter."""
    with get_connection() as conn:
        if author:
            row = conn.execute(
                "SELECT * FROM analysis_cache "
                "WHERE commit_hash = ? AND author = ? AND schema_version = ?",
                (commit_hash, author, SCHEMA_VERSION),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM analysis_cache "
                "WHERE commit_hash = ? AND schema_version = ?",
                (commit_hash, SCHEMA_VERSION),
            ).fetchone()
        return row


def save_analysis(commit_hash: str, author: str, result_json: str):
    """Save analysis result to cache."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO analysis_cache "
            "(commit_hash, author, result, schema_version) VALUES (?, ?, ?, ?)",
            (commit_hash, author, result_json, SCHEMA_VERSION),
        )
        conn.commit()


def delete_old_entries(before_date: str) -> int:
    """Delete cache entries older than given date. Returns count deleted."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM analysis_cache WHERE created_at < ?", (before_date,)
        )
        conn.commit()
        return cursor.rowcount


def generate_cache_key(content: str) -> str:
    """Generate cache key from content."""
    return hashlib.sha256(content.encode()).hexdigest()
