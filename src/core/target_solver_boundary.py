"""Typed numeric boundary for the optional target-generation solver stack."""

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, TypeAlias

SolverScalar: TypeAlias = float
SOLVER_OUTPUT_QUANTUM = Decimal("0.0001")


def decimal_to_solver_scalar(decimal_input: Decimal) -> SolverScalar:
    """Convert a finite Decimal only at the solver-facing numeric boundary."""
    if not decimal_input.is_finite():
        raise ValueError("solver input must be finite")
    solver_scalar = float(decimal_input)
    return solver_scalar


def decimal_to_solver_vector(
    decimal_inputs: Iterable[Decimal],
    np_module: Any,
) -> Any:
    """Build the solver's ordered numeric vector without changing domain inputs."""
    return np_module.array(
        [decimal_to_solver_scalar(decimal_input) for decimal_input in decimal_inputs],
        dtype=float,
    )


def solver_output_to_decimal(solver_output: object) -> Decimal:
    """Re-enter the domain as a finite, canonically quantized Decimal."""
    if solver_output is None:
        raise ValueError("solver output must be present")
    try:
        parsed = Decimal(str(solver_output))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("solver output must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError("solver output must be finite")
    return parsed.quantize(SOLVER_OUTPUT_QUANTUM)
