from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import target_generation
from src.core.models import DiagnosticsData, EngineOptions, ShelfEntry
from src.core.target_solver_boundary import (
    decimal_to_solver_scalar,
    decimal_to_solver_vector,
    solver_output_to_decimal,
)


class _FakeNumpy:
    def __init__(self) -> None:
        self.calls: list[tuple[list[float], object]] = []

    def array(self, values, *, dtype):
        normalized = list(values)
        self.calls.append((normalized, dtype))
        return normalized


@dataclass(frozen=True)
class _FakeExpression:
    label: str

    def __add__(self, other):
        return _FakeExpression(f"{self.label}+{other}")

    def __ge__(self, other):
        return (self.label, ">=", other)

    def __getitem__(self, index):
        return _FakeExpression(f"{self.label}[{index}]")

    def __le__(self, other):
        return (self.label, "<=", other)

    def __sub__(self, other):
        return _FakeExpression(f"{self.label}-{other}")


class _FakeCp:
    def Minimize(self, objective):
        return ("minimize", objective)

    def Variable(self, length):
        return _FakeExpression(f"variable:{length}")

    def sum(self, expression):
        return _FakeExpression("sum")

    def sum_squares(self, expression):
        return ("sum_squares", expression)


def test_solver_boundary_preserves_zero_near_boundary_and_quantized_output() -> None:
    assert decimal_to_solver_scalar(Decimal("0")) == 0.0
    assert decimal_to_solver_scalar(Decimal("0.0000001")) == pytest.approx(0.0000001)
    assert solver_output_to_decimal(0.123456) == Decimal("0.1235")
    assert solver_output_to_decimal(0.0) == Decimal("0.0000")


def test_solver_boundary_rejects_non_finite_inputs_and_outputs() -> None:
    with pytest.raises(ValueError, match="solver input must be finite"):
        decimal_to_solver_scalar(Decimal("NaN"))
    with pytest.raises(ValueError, match="solver output must be present"):
        solver_output_to_decimal(None)
    with pytest.raises(ValueError, match="solver output must be finite"):
        solver_output_to_decimal(float("inf"))


def test_solver_boundary_rejects_non_numeric_solver_outputs() -> None:
    with pytest.raises(ValueError, match="solver output must be numeric"):
        solver_output_to_decimal("not-a-number")


def test_solver_boundary_builds_ordered_numeric_vector() -> None:
    np_module = _FakeNumpy()

    vector = decimal_to_solver_vector(
        [Decimal("0.0000001"), Decimal("0")],
        np_module,
    )

    assert vector == [pytest.approx(0.0000001), 0.0]
    assert np_module.calls[0][0] == [pytest.approx(0.0000001), 0.0]


def test_target_solver_problem_keeps_decimal_constraints_at_one_boundary() -> None:
    fake_numpy = _FakeNumpy()
    solver_index = target_generation._build_target_solver_index(
        eligible_targets={
            "BUY_A": Decimal("0.0000001"),
            "BUY_B": Decimal("0"),
            "LOCKED_TECH": Decimal("0.10"),
        },
        buy_list=["BUY_A", "BUY_B"],
        shelf=[
            ShelfEntry(
                instrument_id="BUY_A",
                status="APPROVED",
                attributes={"sector": "TECH"},
            ),
            ShelfEntry(
                instrument_id="BUY_B",
                status="APPROVED",
                attributes={"sector": "OTHER"},
            ),
            ShelfEntry(
                instrument_id="LOCKED_TECH",
                status="SELL_ONLY",
                attributes={"sector": "TECH"},
            ),
        ],
    )
    diagnostics = DiagnosticsData(data_quality={})
    problem = target_generation._build_target_solver_problem(
        cp=_FakeCp(),
        np=fake_numpy,
        model=SimpleNamespace(
            targets=[
                SimpleNamespace(instrument_id="BUY_A", weight=Decimal("0.0000001")),
                SimpleNamespace(instrument_id="BUY_B", weight=Decimal("0")),
            ]
        ),
        solver_index=solver_index,
        eligible_targets={
            "BUY_A": Decimal("0.0000001"),
            "BUY_B": Decimal("0"),
            "LOCKED_TECH": Decimal("0.10"),
        },
        options=EngineOptions(
            cash_band_min_weight=Decimal("0.10"),
            cash_band_max_weight=Decimal("0.10"),
            single_position_max_weight=Decimal("0.80"),
            group_constraints={"sector:TECH": {"max_weight": "0.60"}},
        ),
        diagnostics=diagnostics,
    )

    assert fake_numpy.calls[0][0] == [pytest.approx(0.0000001), 0.0]
    numeric_limits = [constraint[-1] for constraint in problem.constraints[1:]]
    assert numeric_limits == [pytest.approx(0.80), pytest.approx(0.80), 0.80, 0.60]
    assert diagnostics.warnings == []


def test_apply_solved_weights_reenters_domain_as_quantized_decimal() -> None:
    eligible_targets = {"BUY_A": Decimal("0"), "BUY_B": Decimal("0")}

    target_generation._apply_solved_weights(
        eligible_targets=eligible_targets,
        solver_index=SimpleNamespace(tradeable_ids=["BUY_A", "BUY_B"]),
        w=SimpleNamespace(value=[-0.00001, 0.123456]),
    )

    assert eligible_targets == {"BUY_A": Decimal("0.0000"), "BUY_B": Decimal("0.1235")}


def test_target_generation_has_no_direct_numeric_conversion() -> None:
    source = Path(target_generation.__file__).read_text(encoding="utf-8")

    assert "float(" not in source
    assert "target_solver_boundary" in source
