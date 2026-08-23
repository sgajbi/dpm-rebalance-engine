"""Derive a stable, checkout-specific Docker Compose project name."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def compose_project_name(checkout: Path) -> str:
    """Return a valid Compose project name that is stable for one checkout."""
    resolved = checkout.resolve()
    checkout_name = re.sub(r"[^a-z0-9_-]+", "-", resolved.name.lower()).strip("-_")
    checkout_name = checkout_name or "workspace"
    path_hash = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:10]
    return f"lotus-advise-ci-local-{checkout_name}-{path_hash}"


if __name__ == "__main__":
    print(compose_project_name(Path(__file__).resolve().parents[1]))
