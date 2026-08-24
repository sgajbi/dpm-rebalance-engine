"""Protect explicit boundaries between individual quality gates and shared helpers."""

from __future__ import annotations

import pytest

from scripts import dead_code_gate, dependency_hygiene_gate, duplicate_code_gate


@pytest.mark.parametrize(
    ("module", "module_name"),
    [
        (dead_code_gate, "dead_code_gate"),
        (duplicate_code_gate, "duplicate_code_gate"),
        (dependency_hygiene_gate, "dependency_hygiene_gate"),
    ],
)
@pytest.mark.parametrize("shared_helper", ["finish_gate", "non_empty_string"])
def test_quality_gate_modules_do_not_proxy_shared_helpers(
    module: object, module_name: str, shared_helper: str
) -> None:
    """Unknown gate-module names must not resolve through the shared helper module."""
    with pytest.raises(AttributeError, match=shared_helper):
        getattr(module, shared_helper)
