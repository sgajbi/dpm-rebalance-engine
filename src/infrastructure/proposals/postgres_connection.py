from __future__ import annotations

from importlib.util import find_spec
from typing import Any


def ensure_postgres_driver() -> None:
    """Fail with the repository contract error when psycopg is unavailable."""
    if find_spec("psycopg") is None:
        raise RuntimeError("PROPOSAL_POSTGRES_DRIVER_MISSING")


def connect_postgres(dsn: str) -> Any:
    """Open a proposal-store connection with mapping rows."""
    psycopg, dict_row = _import_psycopg()
    return psycopg.connect(dsn, row_factory=dict_row)


def _import_psycopg() -> tuple[Any, Any]:
    import psycopg
    from psycopg.rows import dict_row

    return psycopg, dict_row
