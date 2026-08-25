from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.core.diagnostics_models import DiagnosticsData
from src.core.engine_options_models import EngineOptions
from src.core.portfolio_models import Money, ShelfEntry
from src.core.target_solver_boundary import (
    decimal_to_solver_scalar,
    decimal_to_solver_vector,
    solver_output_to_decimal,
)
from src.core.universe_target_models import TargetInstrument

_SOLVER_STATUS_OPTIMAL = {"optimal", "optimal_inaccurate"}
_SOLVER_STATUS_INFEASIBLE = {"infeasible", "infeasible_inaccurate"}
_SOLVER_STATUS_UNBOUNDED = {"unbounded", "unbounded_inaccurate"}


@dataclass(frozen=True)
class _TargetSolverIndex:
    tradeable_ids: list[str]
    locked_weight: Decimal
    shelf_attrs_by_id: dict[str, dict[str, str]]
    known_attr_keys: set[str]
    indexed_tradeable: dict[str, int]


@dataclass(frozen=True)
class _TargetSolverProblem:
    variable: Any
    objective: Any
    constraints: list[Any]


@dataclass(frozen=True)
class _GroupConstraintExposure:
    tradeable_ids: list[str]
    locked_weight: Decimal


def _build_solver_attempts(cp: Any) -> tuple[tuple[Any, tuple[dict[str, Any], ...]], ...]:
    """
    Ordered solver attempts with bounded runtime and compatibility fallbacks.

    The first kwargs profile is preferred; subsequent profiles are compatibility
    fallbacks for environments where specific kwargs are unsupported.
    """
    return (
        (
            cp.OSQP,
            (
                {"max_iter": 2_000, "eps_abs": 1e-5, "eps_rel": 1e-5, "time_limit": 0.25},
                {"max_iter": 2_000, "eps_abs": 1e-5, "eps_rel": 1e-5},
                {"max_iter": 2_000},
                {},
            ),
        ),
        (
            cp.SCS,
            (
                {"max_iters": 5_000, "eps": 1e-4, "time_limit_secs": 0.5},
                {"max_iters": 5_000, "eps": 1e-4},
                {"max_iters": 5_000},
                {},
            ),
        ),
    )


def _solve_with_fallbacks(prob: Any, cp: Any) -> tuple[bool, str | None]:
    installed = _installed_solver_names(cp)
    latest_status: str | None = None

    for solver_name, kwargs_attempts in _build_solver_attempts(cp):
        if not _solver_available(solver_name=solver_name, installed=installed):
            continue

        solved, latest_status = _solve_with_solver_attempts(
            prob=prob,
            cp=cp,
            solver_name=solver_name,
            kwargs_attempts=kwargs_attempts,
            latest_status=latest_status,
        )
        if solved:
            return True, latest_status

    return False, latest_status


def _installed_solver_names(cp: Any) -> set[str]:
    try:
        return {str(s) for s in cp.installed_solvers()}
    except (AttributeError, TypeError, ValueError):
        return set()


def _solver_available(*, solver_name: Any, installed: set[str]) -> bool:
    return not installed or str(solver_name) in installed


def _solve_with_solver_attempts(
    *,
    prob: Any,
    cp: Any,
    solver_name: Any,
    kwargs_attempts: tuple[dict[str, Any], ...],
    latest_status: str | None,
) -> tuple[bool, str | None]:
    for solve_kwargs in kwargs_attempts:
        status = _solve_status(
            prob=prob,
            cp=cp,
            solver_name=solver_name,
            solve_kwargs=solve_kwargs,
        )
        if status is None:
            continue

        latest_status = status
        if latest_status in _SOLVER_STATUS_OPTIMAL:
            return True, latest_status

    return False, latest_status


def _solve_status(
    *,
    prob: Any,
    cp: Any,
    solver_name: Any,
    solve_kwargs: dict[str, Any],
) -> str | None:
    try:
        prob.solve(
            solver=solver_name,
            verbose=False,
            warm_start=False,
            **solve_kwargs,
        )
    except TypeError:
        # Binding rejected one or more kwargs; try compatibility profile.
        return None
    except (cp.SolverError, ValueError):
        # Runtime/configuration failure; still try compatibility profile.
        return None

    return str(prob.status).lower()


def _solver_failure_reason(latest_status: str | None) -> str:
    if latest_status is None:
        return "SOLVER_ERROR"
    if latest_status in _SOLVER_STATUS_INFEASIBLE:
        return f"INFEASIBLE_{latest_status.upper()}"
    if latest_status in _SOLVER_STATUS_UNBOUNDED:
        return f"UNBOUNDED_{latest_status.upper()}"
    return f"SOLVER_NON_OPTIMAL_{latest_status.upper()}"


def _collect_infeasibility_hints(
    *,
    tradeable_ids: list[str],
    locked_weight: Decimal,
    options: EngineOptions,
    eligible_targets: dict[str, Decimal],
    shelf: list[ShelfEntry],
) -> list[str]:
    shelf_attrs_by_id = {s.instrument_id: s.attributes for s in shelf}
    indexed_tradeable = {i_id: idx for idx, i_id in enumerate(tradeable_ids)}

    hints: list[str] = []
    invested_min, invested_max = invested_weight_bounds(
        options=options,
        locked_weight=locked_weight,
    )
    append_cash_band_hint(hints=hints, invested_min=invested_min, invested_max=invested_max)
    append_single_position_capacity_hint(
        hints=hints,
        options=options,
        tradeable_count=len(tradeable_ids),
        invested_min=invested_min,
    )
    append_locked_group_weight_hints(
        hints=hints,
        options=options,
        eligible_targets=eligible_targets,
        shelf_attrs_by_id=shelf_attrs_by_id,
        indexed_tradeable=indexed_tradeable,
    )
    return hints


def invested_weight_bounds(
    *,
    options: EngineOptions,
    locked_weight: Decimal,
) -> tuple[Decimal, Decimal]:
    return (
        Decimal("1.0") - options.cash_band_max_weight - locked_weight,
        Decimal("1.0") - options.cash_band_min_weight - locked_weight,
    )


def append_cash_band_hint(
    *,
    hints: list[str],
    invested_min: Decimal,
    invested_max: Decimal,
) -> None:
    if invested_min > invested_max:
        hints.append("INFEASIBILITY_HINT_CASH_BAND_CONTRADICTION")


def append_single_position_capacity_hint(
    *,
    hints: list[str],
    options: EngineOptions,
    tradeable_count: int,
    invested_min: Decimal,
) -> None:
    if options.single_position_max_weight is None:
        return
    max_capacity = options.single_position_max_weight * Decimal(tradeable_count)
    if max_capacity < invested_min:
        hints.append("INFEASIBILITY_HINT_SINGLE_POSITION_CAPACITY")


def append_locked_group_weight_hints(
    *,
    hints: list[str],
    options: EngineOptions,
    eligible_targets: dict[str, Decimal],
    shelf_attrs_by_id: dict[str, dict[str, str]],
    indexed_tradeable: dict[str, int],
) -> None:
    for constraint_key in sorted(options.group_constraints.keys()):
        constraint = options.group_constraints[constraint_key]
        group_locked_weight, group_tradeable_count = group_constraint_exposure(
            constraint_key=constraint_key,
            eligible_targets=eligible_targets,
            shelf_attrs_by_id=shelf_attrs_by_id,
            indexed_tradeable=indexed_tradeable,
        )
        if group_locked_weight > constraint.max_weight:
            hints.append(f"INFEASIBILITY_HINT_LOCKED_GROUP_WEIGHT_{constraint_key}")
        if group_tradeable_count == 0 and group_locked_weight == Decimal("0"):
            continue


def group_constraint_exposure(
    *,
    constraint_key: str,
    eligible_targets: dict[str, Decimal],
    shelf_attrs_by_id: dict[str, dict[str, str]],
    indexed_tradeable: dict[str, int],
) -> tuple[Decimal, int]:
    attr_key, attr_val = constraint_key.split(":", 1)
    locked_weight = Decimal("0")
    tradeable_count = 0
    for instrument_id in eligible_targets:
        attrs = shelf_attrs_by_id.get(instrument_id)
        if attrs is None or attrs.get(attr_key) != attr_val:
            continue
        if instrument_id in indexed_tradeable:
            tradeable_count += 1
        else:
            locked_weight += eligible_targets[instrument_id]
    return locked_weight, tradeable_count


def build_target_trace(
    model: Any,
    eligible_targets: dict[str, Decimal],
    buy_list: list[str],
    total_val: Decimal,
    base_ccy: str,
) -> list[TargetInstrument]:
    buy_set = set(buy_list)
    model_targets = list(model.targets)
    model_target_ids = {target.instrument_id for target in model_targets}

    return [
        *_model_target_trace_entries(
            model_targets=model_targets,
            eligible_targets=eligible_targets,
            total_val=total_val,
            base_ccy=base_ccy,
        ),
        *_implicit_target_trace_entries(
            eligible_targets=eligible_targets,
            model_target_ids=model_target_ids,
            buy_set=buy_set,
            total_val=total_val,
            base_ccy=base_ccy,
        ),
    ]


def _model_target_trace_entries(
    *,
    model_targets: list[Any],
    eligible_targets: dict[str, Decimal],
    total_val: Decimal,
    base_ccy: str,
) -> list[TargetInstrument]:
    return [
        _model_target_trace_entry(
            target=target,
            final_weight=eligible_targets.get(target.instrument_id, Decimal("0.0")),
            total_val=total_val,
            base_ccy=base_ccy,
        )
        for target in model_targets
    ]


def _model_target_trace_entry(
    *,
    target: Any,
    final_weight: Decimal,
    total_val: Decimal,
    base_ccy: str,
) -> TargetInstrument:
    return _target_instrument_trace(
        instrument_id=target.instrument_id,
        model_weight=target.weight,
        final_weight=final_weight,
        total_val=total_val,
        base_ccy=base_ccy,
        tags=_model_target_tags(
            model_weight=target.weight,
            final_weight=final_weight,
        ),
    )


def _model_target_tags(*, model_weight: Decimal, final_weight: Decimal) -> list[str]:
    tags = []
    if model_weight > final_weight:
        tags.append("CAPPED_BY_MAX_WEIGHT")
    if final_weight > model_weight:
        tags.append("REDISTRIBUTED_RECIPIENT")
    return tags


def _implicit_target_trace_entries(
    *,
    eligible_targets: dict[str, Decimal],
    model_target_ids: set[str],
    buy_set: set[str],
    total_val: Decimal,
    base_ccy: str,
) -> list[TargetInstrument]:
    trace: list[TargetInstrument] = []
    for i_id, final_w in eligible_targets.items():
        if i_id in model_target_ids:
            continue
        trace.append(
            _target_instrument_trace(
                instrument_id=i_id,
                model_weight=Decimal("0.0"),
                final_weight=final_w,
                total_val=total_val,
                base_ccy=base_ccy,
                tags=[
                    _implicit_target_tag(
                        instrument_id=i_id,
                        final_weight=final_w,
                        buy_set=buy_set,
                    )
                ],
            )
        )

    return trace


def _implicit_target_tag(
    *,
    instrument_id: str,
    final_weight: Decimal,
    buy_set: set[str],
) -> str:
    if instrument_id in buy_set or final_weight == 0:
        return "IMPLICIT_SELL_TO_ZERO"
    return "LOCKED_POSITION"


def _target_instrument_trace(
    *,
    instrument_id: str,
    model_weight: Decimal,
    final_weight: Decimal,
    total_val: Decimal,
    base_ccy: str,
    tags: list[str],
) -> TargetInstrument:
    return TargetInstrument(
        instrument_id=instrument_id,
        model_weight=model_weight,
        final_weight=final_weight,
        final_value=Money(amount=total_val * final_weight, currency=base_ccy),
        tags=tags,
    )


def _redistribute_sell_only_excess(
    eligible_targets: dict[str, Decimal],
    buy_list: list[str],
    sell_only_excess: Decimal,
) -> str:
    if sell_only_excess <= Decimal("0.0"):
        return "READY"

    recipients = {k: v for k, v in eligible_targets.items() if k in buy_list}
    total_recipient_weight = sum(recipients.values())
    if total_recipient_weight <= Decimal("0.0"):
        return "PENDING_REVIEW"

    for i_id, recipient_weight in recipients.items():
        eligible_targets[i_id] = recipient_weight + (
            sell_only_excess * (recipient_weight / total_recipient_weight)
        )
    return "READY"


def _build_target_solver_index(
    *,
    eligible_targets: dict[str, Decimal],
    buy_list: list[str],
    shelf: list[ShelfEntry],
) -> _TargetSolverIndex:
    buy_ids = set(buy_list)
    tradeable_ids = _target_tradeable_ids(eligible_targets=eligible_targets, buy_ids=buy_ids)
    shelf_attrs_by_id = _shelf_attrs_by_instrument_id(shelf)
    return _TargetSolverIndex(
        tradeable_ids=tradeable_ids,
        locked_weight=_target_locked_weight(eligible_targets=eligible_targets, buy_ids=buy_ids),
        shelf_attrs_by_id=shelf_attrs_by_id,
        known_attr_keys=_known_shelf_attr_keys(shelf_attrs_by_id),
        indexed_tradeable={i_id: idx for idx, i_id in enumerate(tradeable_ids)},
    )


def _target_tradeable_ids(
    *,
    eligible_targets: dict[str, Decimal],
    buy_ids: set[str],
) -> list[str]:
    return [instrument_id for instrument_id in eligible_targets if instrument_id in buy_ids]


def _target_locked_weight(
    *,
    eligible_targets: dict[str, Decimal],
    buy_ids: set[str],
) -> Decimal:
    return sum(
        (
            weight
            for instrument_id, weight in eligible_targets.items()
            if instrument_id not in buy_ids
        ),
        Decimal("0"),
    )


def _shelf_attrs_by_instrument_id(shelf: list[ShelfEntry]) -> dict[str, dict[str, str]]:
    return {entry.instrument_id: entry.attributes for entry in shelf}


def _known_shelf_attr_keys(shelf_attrs_by_id: dict[str, dict[str, str]]) -> set[str]:
    return {key for attrs in shelf_attrs_by_id.values() for key in attrs}


def _append_cash_band_constraints(
    *,
    cp: Any,
    w: Any,
    constraints: list[Any],
    locked_weight: Decimal,
    options: EngineOptions,
) -> None:
    invested_min = Decimal("1.0") - options.cash_band_max_weight - locked_weight
    invested_max = Decimal("1.0") - options.cash_band_min_weight - locked_weight
    constraints.append(cp.sum(w) >= decimal_to_solver_scalar(invested_min))
    constraints.append(cp.sum(w) <= decimal_to_solver_scalar(invested_max))


def _append_group_constraints(
    *,
    cp: Any,
    w: Any,
    constraints: list[Any],
    solver_index: _TargetSolverIndex,
    eligible_targets: dict[str, Decimal],
    options: EngineOptions,
    diagnostics: DiagnosticsData,
) -> None:
    for constraint_key in sorted(options.group_constraints.keys()):
        constraint = options.group_constraints[constraint_key]
        attr_key, attr_val = constraint_key.split(":", 1)

        if attr_key not in solver_index.known_attr_keys:
            diagnostics.warnings.append(f"UNKNOWN_CONSTRAINT_ATTRIBUTE_{attr_key}")
            continue

        exposure = _solver_group_constraint_exposure(
            attr_key=attr_key,
            attr_val=attr_val,
            solver_index=solver_index,
            eligible_targets=eligible_targets,
        )
        if not exposure.tradeable_ids and exposure.locked_weight == Decimal("0"):
            continue

        group_locked_weight = exposure.locked_weight
        group_expr = cp.sum(
            [w[solver_index.indexed_tradeable[i_id]] for i_id in exposure.tradeable_ids]
        ) + decimal_to_solver_scalar(group_locked_weight)
        constraints.append(group_expr <= decimal_to_solver_scalar(constraint.max_weight))


def _solver_group_constraint_exposure(
    *,
    attr_key: str,
    attr_val: str,
    solver_index: _TargetSolverIndex,
    eligible_targets: dict[str, Decimal],
) -> _GroupConstraintExposure:
    tradeable_ids: list[str] = []
    locked_weight = Decimal("0")
    for instrument_id in eligible_targets:
        attrs = solver_index.shelf_attrs_by_id.get(instrument_id)
        if attrs is None or attrs.get(attr_key) != attr_val:
            continue
        if instrument_id in solver_index.indexed_tradeable:
            tradeable_ids.append(instrument_id)
        else:
            locked_weight += eligible_targets[instrument_id]
    return _GroupConstraintExposure(
        tradeable_ids=tradeable_ids,
        locked_weight=locked_weight,
    )


def _build_target_solver_problem(
    *,
    cp: Any,
    np: Any,
    model: Any,
    solver_index: _TargetSolverIndex,
    eligible_targets: dict[str, Decimal],
    options: EngineOptions,
    diagnostics: DiagnosticsData,
) -> _TargetSolverProblem:
    model_weights = {t.instrument_id: t.weight for t in model.targets}
    w_model = decimal_to_solver_vector(
        (model_weights.get(i_id, Decimal("0.0")) for i_id in solver_index.tradeable_ids),
        np,
    )
    w = cp.Variable(len(solver_index.tradeable_ids))

    objective = cp.Minimize(cp.sum_squares(w - w_model))
    constraints = [w >= 0]
    _append_cash_band_constraints(
        cp=cp,
        w=w,
        constraints=constraints,
        locked_weight=solver_index.locked_weight,
        options=options,
    )

    if options.single_position_max_weight is not None:
        constraints.append(w <= decimal_to_solver_scalar(options.single_position_max_weight))

    _append_group_constraints(
        cp=cp,
        w=w,
        constraints=constraints,
        solver_index=solver_index,
        eligible_targets=eligible_targets,
        options=options,
        diagnostics=diagnostics,
    )
    return _TargetSolverProblem(variable=w, objective=objective, constraints=constraints)


def _apply_solved_weights(
    *,
    eligible_targets: dict[str, Decimal],
    solver_index: _TargetSolverIndex,
    w: Any,
) -> None:
    for idx, i_id in enumerate(solver_index.tradeable_ids):
        solved_weight = solver_output_to_decimal(max(w.value[idx], 0.0))
        eligible_targets[i_id] = solved_weight


def generate_targets_solver(
    model: Any,
    eligible_targets: dict[str, Decimal],
    buy_list: list[str],
    sell_only_excess: Decimal,
    shelf: list[ShelfEntry],
    options: EngineOptions,
    total_val: Decimal,
    base_ccy: str,
    diagnostics: DiagnosticsData,
) -> tuple[list[TargetInstrument], str]:
    dependencies = load_target_solver_dependencies()
    if dependencies is None:
        diagnostics.warnings.append("SOLVER_ERROR")
        return [], "BLOCKED"
    cp = dependencies[0]
    np = dependencies[1]

    status = _redistribute_sell_only_excess(eligible_targets, buy_list, sell_only_excess)
    solver_index = _build_target_solver_index(
        eligible_targets=eligible_targets,
        buy_list=buy_list,
        shelf=shelf,
    )

    if not solver_index.tradeable_ids:
        return build_target_trace(model, eligible_targets, buy_list, total_val, base_ccy), status

    problem = _build_target_solver_problem(
        cp=cp,
        np=np,
        model=model,
        solver_index=solver_index,
        eligible_targets=eligible_targets,
        options=options,
        diagnostics=diagnostics,
    )
    prob = cp.Problem(problem.objective, problem.constraints)
    solved, latest_status = _solve_with_fallbacks(prob, cp)

    if not solved:
        reason = _solver_failure_reason(latest_status)
        diagnostics.warnings.append(reason)
        if reason.startswith("INFEASIBLE_"):
            diagnostics.warnings.extend(
                _collect_infeasibility_hints(
                    tradeable_ids=solver_index.tradeable_ids,
                    locked_weight=solver_index.locked_weight,
                    options=options,
                    eligible_targets=eligible_targets,
                    shelf=shelf,
                )
            )
        return [], "BLOCKED"

    _apply_solved_weights(
        eligible_targets=eligible_targets,
        solver_index=solver_index,
        w=problem.variable,
    )

    return build_target_trace(model, eligible_targets, buy_list, total_val, base_ccy), status


def load_target_solver_dependencies() -> tuple[Any, Any] | None:
    import importlib

    try:
        return (
            importlib.import_module("cvxpy"),
            importlib.import_module("numpy"),
        )
    except (ImportError, OSError):
        return None
