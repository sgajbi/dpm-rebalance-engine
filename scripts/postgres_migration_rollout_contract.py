"""Validate PostgreSQL migration rollout metadata for lotus-advise."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.postgres_migrate import _resolve_targets  # noqa: E402

DEFAULT_CONTRACT_PATH = (
    REPO_ROOT / "docs" / "standards" / "postgres-migration-rollout-contract.v1.json"
)
MIGRATIONS_ROOT = REPO_ROOT / "src" / "infrastructure" / "postgres_migrations"
REQUIRED_NAMESPACE_FIELDS = (
    "namespace_key",
    "dsn_env",
    "owned_store",
    "rollout_order",
)
REQUIRED_MIGRATION_FIELDS = (
    "namespace_key",
    "version",
    "path",
    "phase",
    "operation_class",
    "compatibility_window",
    "lock_behavior",
    "backfill",
    "rollback",
    "rehearsal",
)
REQUIRED_COMPATIBILITY_FIELDS = (
    "old_and_new_application_versions_supported",
    "minimum_rollout_window",
    "consumer_contract",
)
REQUIRED_LOCK_FIELDS = (
    "transaction_scope",
    "lock_profile",
    "online_behavior",
    "required_operator_control",
)
REQUIRED_BACKFILL_FIELDS = (
    "required",
    "checkpoint_strategy",
    "resume_strategy",
    "quarantine_strategy",
)
REQUIRED_ROLLBACK_FIELDS = (
    "forward_fix_required",
    "previous_app_version_compatible",
    "limitations",
)
REQUIRED_REHEARSAL_FIELDS = (
    "profile_key",
    "command",
    "output_path",
    "evidence_kind",
)
VALID_PHASES = {"expand", "migrate_backfill", "contract"}
INDEX_OPERATION_CLASSES = {
    "create_index",
    "create_unique_index",
    "create_expression_index",
    "create_partial_unique_index",
    "create_table_and_indexes",
}


def load_contract(path: Path = DEFAULT_CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract(
    contract: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    failures: list[str] = []
    if contract.get("schema_version") != "lotus.advise.postgres-migration-rollout.v1":
        failures.append(
            "Contract schema_version must be lotus.advise.postgres-migration-rollout.v1."
        )
    if contract.get("service_name") != "lotus-advise":
        failures.append("Contract service_name must be lotus-advise.")

    namespace_contracts = _object_list(
        contract,
        "namespaces",
        "namespace_key",
        failures,
    )
    migration_contracts = _migration_contracts(contract, failures)
    migration_root = repo_root / "src" / "infrastructure" / "postgres_migrations"
    actual_sql_files = _actual_sql_files(migration_root)
    actual_namespaces = {namespace for namespace, _version, _path in actual_sql_files}
    runner_targets = _migration_runner_targets()

    for namespace_key, namespace in namespace_contracts.items():
        failures.extend(
            _missing_fields(
                owner=f"Namespace {namespace_key}",
                item=namespace,
                required_fields=REQUIRED_NAMESPACE_FIELDS,
            )
        )

    if set(namespace_contracts) != actual_namespaces:
        failures.append(
            "Contract namespaces must match migration directories: "
            f"contract={sorted(namespace_contracts)} actual={sorted(actual_namespaces)}."
        )
    if runner_targets != actual_namespaces:
        failures.append(
            "scripts/postgres_migrate.py --target all must cover migration directories: "
            f"targets={sorted(runner_targets)} actual={sorted(actual_namespaces)}."
        )

    for namespace_key, version, sql_path in actual_sql_files:
        key = (namespace_key, version)
        migration = migration_contracts.get(key)
        if migration is None:
            failures.append(f"Migration {namespace_key}:{version} is missing rollout metadata.")
            continue
        expected_path = sql_path.relative_to(repo_root).as_posix()
        if migration.get("path") != expected_path:
            failures.append(f"Migration {namespace_key}:{version} path must be {expected_path}.")
        failures.extend(
            _validate_migration_metadata(
                namespace_key=namespace_key,
                version=version,
                migration=migration,
                sql_path=sql_path,
            )
        )

    actual_keys = {(namespace, version) for namespace, version, _path in actual_sql_files}
    for namespace_key, version in migration_contracts:
        if (namespace_key, version) not in actual_keys:
            failures.append(
                f"Migration metadata references missing SQL file: {namespace_key}:{version}."
            )

    return failures


def build_rehearsal_evidence(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "lotus.advise.postgres-migration-rehearsal-evidence.v1",
        "service_name": contract.get("service_name"),
        "contract_path": "docs/standards/postgres-migration-rollout-contract.v1.json",
        "namespaces": [
            {
                "namespace_key": namespace.get("namespace_key"),
                "rollout_order": namespace.get("rollout_order"),
                "dsn_env": namespace.get("dsn_env"),
            }
            for namespace in contract.get("namespaces", [])
        ],
        "migrations": [
            {
                "namespace_key": migration.get("namespace_key"),
                "version": migration.get("version"),
                "phase": migration.get("phase"),
                "operation_class": migration.get("operation_class"),
                "online_behavior": migration.get("lock_behavior", {}).get("online_behavior"),
                "backfill_required": migration.get("backfill", {}).get("required"),
                "rehearsal": migration.get("rehearsal", {}),
            }
            for migration in contract.get("migrations", [])
        ],
    }


def _migration_contracts(
    contract: dict[str, Any],
    failures: list[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    raw_migrations = contract.get("migrations")
    if not isinstance(raw_migrations, list) or not raw_migrations:
        failures.append("Contract must define non-empty migrations.")
        return {}

    migrations: dict[tuple[str, str], dict[str, Any]] = {}
    for index, migration in enumerate(raw_migrations):
        if not isinstance(migration, dict):
            failures.append(f"migrations[{index}] must be an object.")
            continue
        namespace_key = migration.get("namespace_key")
        version = migration.get("version")
        if not isinstance(namespace_key, str) or not namespace_key:
            failures.append(f"migrations[{index}] must define namespace_key.")
            continue
        if not isinstance(version, str) or not version:
            failures.append(f"migrations[{index}] must define version.")
            continue
        key = (namespace_key, version)
        if key in migrations:
            failures.append(f"migrations contains duplicate entry: {namespace_key}:{version}.")
        migrations[key] = migration
    return migrations


def _validate_migration_metadata(
    *,
    namespace_key: str,
    version: str,
    migration: dict[str, Any],
    sql_path: Path,
) -> list[str]:
    owner = f"Migration {namespace_key}:{version}"
    failures = _missing_fields(
        owner=owner,
        item=migration,
        required_fields=REQUIRED_MIGRATION_FIELDS,
    )
    phase = migration.get("phase")
    if phase not in VALID_PHASES:
        failures.append(f"{owner} phase must be one of {sorted(VALID_PHASES)}.")

    failures.extend(
        _validate_nested_object(
            owner=f"{owner} compatibility_window",
            item=migration.get("compatibility_window"),
            required_fields=REQUIRED_COMPATIBILITY_FIELDS,
        )
    )
    compatibility = migration.get("compatibility_window", {})
    mixed_version_supported = compatibility.get("old_and_new_application_versions_supported")
    if not isinstance(mixed_version_supported, bool):
        failures.append(f"{owner} old_and_new_application_versions_supported must be a boolean.")
    elif not mixed_version_supported:
        failures.extend(
            _require_rollout_control(
                owner=owner,
                item=compatibility,
                field="write_activation_control",
            )
        )

    failures.extend(
        _validate_nested_object(
            owner=f"{owner} lock_behavior",
            item=migration.get("lock_behavior"),
            required_fields=REQUIRED_LOCK_FIELDS,
        )
    )
    lock_behavior = migration.get("lock_behavior", {})
    operation_class = migration.get("operation_class")
    if (
        operation_class in INDEX_OPERATION_CLASSES
        and lock_behavior.get("online_behavior") == "not_applicable"
    ):
        failures.append(f"{owner} must document index online/locking behavior.")

    failures.extend(
        _validate_nested_object(
            owner=f"{owner} backfill",
            item=migration.get("backfill"),
            required_fields=REQUIRED_BACKFILL_FIELDS,
        )
    )
    backfill = migration.get("backfill", {})
    if backfill.get("required") is True and backfill.get("checkpoint_strategy") == "not_applicable":
        failures.append(f"{owner} backfill requires a checkpoint strategy.")

    failures.extend(
        _validate_nested_object(
            owner=f"{owner} rollback",
            item=migration.get("rollback"),
            required_fields=REQUIRED_ROLLBACK_FIELDS,
        )
    )
    rollback = migration.get("rollback", {})
    if rollback.get("forward_fix_required") is not True:
        failures.append(f"{owner} rollback must declare forward_fix_required=true.")
    previous_version_compatible = rollback.get("previous_app_version_compatible")
    if not isinstance(previous_version_compatible, bool):
        failures.append(f"{owner} previous_app_version_compatible must be a boolean.")
    elif not previous_version_compatible:
        failures.extend(
            _require_rollout_control(
                owner=owner,
                item=rollback,
                field="previous_version_recovery_control",
            )
        )

    failures.extend(
        _validate_nested_object(
            owner=f"{owner} rehearsal",
            item=migration.get("rehearsal"),
            required_fields=REQUIRED_REHEARSAL_FIELDS,
        )
    )
    sql = sql_path.read_text(encoding="utf-8").upper()
    if "CREATE INDEX" in sql and operation_class not in INDEX_OPERATION_CLASSES:
        failures.append(f"{owner} operation_class must classify CREATE INDEX usage.")
    return failures


def _require_rollout_control(*, owner: str, item: dict[str, Any], field: str) -> list[str]:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        return [f"{owner} must document {field} when mixed-version compatibility is false."]
    return []


def _validate_nested_object(
    *,
    owner: str,
    item: Any,
    required_fields: tuple[str, ...],
) -> list[str]:
    if not isinstance(item, dict):
        return [f"{owner} must be an object."]
    return _missing_fields(owner=owner, item=item, required_fields=required_fields)


def _object_list(
    contract: dict[str, Any],
    field_name: str,
    key_field: str,
    failures: list[str],
) -> dict[str, dict[str, Any]]:
    raw_items = contract.get(field_name)
    if not isinstance(raw_items, list) or not raw_items:
        failures.append(f"Contract must define non-empty {field_name}.")
        return {}

    items: dict[str, dict[str, Any]] = {}
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            failures.append(f"{field_name}[{index}] must be an object.")
            continue
        key = raw_item.get(key_field)
        if not isinstance(key, str) or not key:
            failures.append(f"{field_name}[{index}] must define {key_field}.")
            continue
        if key in items:
            failures.append(f"{field_name} contains duplicate {key_field}: {key}.")
        items[key] = raw_item
    return items


def _missing_fields(
    *,
    owner: str,
    item: dict[str, Any],
    required_fields: tuple[str, ...],
) -> list[str]:
    return [
        f"{owner} missing required field: {field_name}."
        for field_name in required_fields
        if field_name not in item
    ]


def _actual_sql_files(migration_root: Path) -> list[tuple[str, str, Path]]:
    sql_files: list[tuple[str, str, Path]] = []
    for namespace_path in sorted(path for path in migration_root.iterdir() if path.is_dir()):
        for sql_path in sorted(namespace_path.glob("*.sql")):
            version = sql_path.stem.split("_", maxsplit=1)[0]
            sql_files.append((namespace_path.name, version, sql_path))
    return sql_files


def _migration_runner_targets() -> set[str]:
    return {
        namespace
        for namespace, _dsn in _resolve_targets(
            "all",
            proposals_dsn="postgres://proposal",
            advisory_copilot_dsn="postgres://copilot",
            policy_packs_dsn="postgres://policy",
            workspace_dsn="postgres://workspace",
        )
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate lotus-advise PostgreSQL migration rollout contract."
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=DEFAULT_CONTRACT_PATH,
        help="Path to migration rollout contract JSON.",
    )
    parser.add_argument(
        "--emit-rehearsal-evidence",
        type=Path,
        default=None,
        help="Write machine-readable static rehearsal evidence to this path.",
    )
    args = parser.parse_args(argv)

    contract = load_contract(args.contract)
    failures = validate_contract(contract)
    if failures:
        for failure in failures:
            print(failure)
        return 1

    if args.emit_rehearsal_evidence:
        args.emit_rehearsal_evidence.parent.mkdir(parents=True, exist_ok=True)
        args.emit_rehearsal_evidence.write_text(
            json.dumps(build_rehearsal_evidence(contract), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
