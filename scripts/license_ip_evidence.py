"""Generate and validate Lotus Advise license/IP release evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_NAME = "lotus-advise"
POLICY_PATH = Path("docs/standards/license-ip-policy.v1.json")
INVENTORY_PATH = Path("docs/standards/license-ip-inventory.v1.json")
NOTICE_PATH = Path("NOTICE.md")
LICENSE_OPERATOR_RE = re.compile(r"\s+(?:AND|OR|WITH)\s+|[()]")
ISOLATED_ENV_FLAG = "LOTUS_ADVISE_LICENSE_IP_ISOLATED"


@dataclass(frozen=True)
class RequirementRoot:
    name: str
    declared_name: str
    specifier: str
    pinned_version: str | None
    extras: tuple[str, ...]
    dependency_group: str
    source_file: str
    direct: bool = True


@dataclass(frozen=True)
class LicensePolicy:
    allowed_terms: frozenset[str]
    review_required_terms: frozenset[str]
    prohibited_terms: frozenset[str]
    exceptions: tuple[dict[str, Any], ...]


def parse_requirement_roots(
    requirement_file: Path, *, dependency_group: str
) -> tuple[RequirementRoot, ...]:
    return tuple(
        _parse_requirement_file(requirement_file.resolve(), dependency_group, visited=set())
    )


def build_license_inventory(
    *,
    runtime_requirements: Path,
    development_requirements: Path,
    policy: LicensePolicy,
    commit_sha: str,
    image_digest: str,
    repository_url: str,
    generated_at_utc: str,
    distributions: Iterable[metadata.Distribution] | None = None,
) -> dict[str, Any]:
    distribution_index = _distribution_index(distributions or metadata.distributions())
    runtime_roots = parse_requirement_roots(runtime_requirements, dependency_group="runtime")
    development_roots = parse_requirement_roots(
        development_requirements,
        dependency_group="development",
    )
    root_by_name = _merge_requirement_roots(runtime_roots + development_roots)
    graph_membership = _dependency_graph_membership(
        roots=runtime_roots + development_roots,
        distribution_index=distribution_index,
    )
    package_records = _package_license_records(
        root_by_name=root_by_name,
        graph_membership=graph_membership,
        distribution_index=distribution_index,
        policy=policy,
    )
    return {
        "schema_version": "lotus.license-ip-inventory.v1",
        "service_name": SERVICE_NAME,
        "repository_url": repository_url,
        "git_commit_sha": commit_sha,
        "image_digest": image_digest,
        "generated_at_utc": generated_at_utc,
        "release_graphs": {
            "runtime": _display_path(runtime_requirements),
            "development": _display_path(development_requirements),
        },
        "policy": {
            "path": POLICY_PATH.as_posix(),
            "schema_version": "lotus.license-ip-policy.v1",
        },
        "notice_file": NOTICE_PATH.as_posix(),
        "packages": package_records,
        "summary": _inventory_summary(package_records),
    }


def load_policy(path: Path) -> LicensePolicy:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return LicensePolicy(
        allowed_terms=frozenset(str(item) for item in payload.get("allowed_license_terms", ())),
        review_required_terms=frozenset(
            str(item) for item in payload.get("review_required_license_terms", ())
        ),
        prohibited_terms=frozenset(
            str(item) for item in payload.get("prohibited_license_terms", ())
        ),
        exceptions=tuple(dict(item) for item in payload.get("approved_exceptions", ())),
    )


def validate_license_inventory(inventory: dict[str, Any], policy: LicensePolicy) -> list[str]:
    failures: list[str] = []
    if inventory.get("schema_version") != "lotus.license-ip-inventory.v1":
        failures.append("License inventory schema_version must be lotus.license-ip-inventory.v1")
    if inventory.get("service_name") != SERVICE_NAME:
        failures.append(f"License inventory service_name must be {SERVICE_NAME}")
    if not str(inventory.get("git_commit_sha") or "").strip():
        failures.append("License inventory must include git_commit_sha")
    if not str(inventory.get("image_digest") or "").strip():
        failures.append("License inventory must include image_digest")
    if not isinstance(inventory.get("packages"), list) or not inventory["packages"]:
        failures.append("License inventory must include at least one package")
        return failures

    today = date.today()
    for package in inventory["packages"]:
        package_name = str(package.get("name") or "")
        if package.get("metadata_matches_requirement_pin") is False:
            failures.append(
                f"{package_name} installed metadata version {package.get('installed_version')} "
                f"does not match pinned version {package.get('version')}; install requirements "
                "before regenerating license/IP inventory."
            )
        license_term = str(package.get("license_term") or "")
        expected_classification, expected_exception = _classify_license(
            package_name=package_name,
            license_term=license_term,
            policy=policy,
            today=today,
        )
        classification = str(package.get("policy_classification") or "")
        if classification != expected_classification:
            failures.append(
                f"{package_name} license classification {classification} does not match "
                f"policy-derived classification {expected_classification}"
            )
        if _exception_evidence(package) != _exception_evidence(expected_exception or {}):
            failures.append(f"{package_name} license exception evidence is stale")
        if classification == "PROHIBITED":
            failures.append(f"{package_name} uses prohibited license {package.get('license_term')}")
        if classification == "REVIEW_REQUIRED":
            failures.append(
                f"{package_name} requires license/IP review for {package.get('license_term')}"
            )
        failures.extend(_validate_exception_posture(package, policy, today=today))
    return failures


def validate_license_inventory_against_expected(
    inventory: dict[str, Any],
    expected_inventory: dict[str, Any],
    policy: LicensePolicy,
) -> list[str]:
    failures = validate_license_inventory(inventory, policy)
    if _normalized_inventory(inventory) != _normalized_inventory(expected_inventory):
        failures.append(
            "License/IP inventory is stale. Regenerate with `make license-ip-inventory`."
        )
    missing_transitive_packages = _missing_expected_transitive_package_names(
        inventory,
        expected_inventory,
    )
    if missing_transitive_packages:
        failures.append(
            "License/IP inventory is stale. Missing transitive package evidence: "
            + ", ".join(missing_transitive_packages)
        )
    stale_transitive_packages = _stale_expected_transitive_package_names(
        inventory,
        expected_inventory,
    )
    if stale_transitive_packages:
        failures.append(
            "License/IP inventory is stale. Stale transitive package evidence: "
            + ", ".join(stale_transitive_packages)
        )
    return failures


def write_inventory(inventory: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_requirement_file(
    path: Path,
    dependency_group: str,
    *,
    visited: set[Path],
) -> list[RequirementRoot]:
    resolved = path.resolve()
    if resolved in visited:
        return []
    visited.add(resolved)
    roots: list[RequirementRoot] = []
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            _, include_target = line.split(maxsplit=1)
            roots.extend(
                _parse_requirement_file(
                    (resolved.parent / include_target.strip()).resolve(),
                    dependency_group,
                    visited=visited,
                )
            )
            continue
        if line.startswith("-"):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue
        roots.append(
            RequirementRoot(
                name=canonicalize_name(requirement.name),
                declared_name=requirement.name,
                specifier=str(requirement.specifier),
                pinned_version=_exact_pinned_version(requirement),
                extras=tuple(sorted(requirement.extras)),
                dependency_group=dependency_group,
                source_file=resolved.relative_to(REPO_ROOT).as_posix()
                if resolved.is_relative_to(REPO_ROOT)
                else resolved.as_posix(),
            )
        )
    return roots


def _merge_requirement_roots(roots: Iterable[RequirementRoot]) -> dict[str, RequirementRoot]:
    merged: dict[str, RequirementRoot] = {}
    for root in roots:
        merged.setdefault(root.name, root)
    return merged


def _distribution_index(
    distributions: Iterable[metadata.Distribution],
) -> dict[str, metadata.Distribution]:
    indexed: dict[str, metadata.Distribution] = {}
    for distribution in distributions:
        name = _metadata_value(distribution.metadata, "Name")
        if name:
            indexed[canonicalize_name(name)] = distribution
    return indexed


def _dependency_graph_membership(
    *,
    roots: Iterable[RequirementRoot],
    distribution_index: dict[str, metadata.Distribution],
) -> dict[str, set[str]]:
    membership: dict[str, set[str]] = {}
    for root in roots:
        _walk_dependency_graph(
            package_name=root.name,
            dependency_group=root.dependency_group,
            extras=root.extras,
            distribution_index=distribution_index,
            membership=membership,
            visited=set(),
        )
    return membership


def _walk_dependency_graph(
    *,
    package_name: str,
    dependency_group: str,
    extras: tuple[str, ...],
    distribution_index: dict[str, metadata.Distribution],
    membership: dict[str, set[str]],
    visited: set[str],
) -> None:
    normalized_name = canonicalize_name(package_name)
    if normalized_name in visited:
        return
    visited.add(normalized_name)
    membership.setdefault(normalized_name, set()).add(dependency_group)
    distribution = distribution_index.get(normalized_name)
    if distribution is None:
        return
    for requirement_text in distribution.requires or ():
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement:
            continue
        if not _requirement_applies(requirement, extras=extras):
            continue
        _walk_dependency_graph(
            package_name=requirement.name,
            dependency_group=dependency_group,
            extras=tuple(sorted(requirement.extras)),
            distribution_index=distribution_index,
            membership=membership,
            visited=visited,
        )


def _requirement_applies(requirement: Requirement, *, extras: tuple[str, ...]) -> bool:
    if requirement.marker is None:
        return True
    if not extras:
        return bool(requirement.marker.evaluate({"extra": ""}))
    return any(requirement.marker.evaluate({"extra": extra}) for extra in extras)


def _package_license_records(
    *,
    root_by_name: dict[str, RequirementRoot],
    graph_membership: dict[str, set[str]],
    distribution_index: dict[str, metadata.Distribution],
    policy: LicensePolicy,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for package_name in sorted(graph_membership):
        distribution = distribution_index.get(package_name)
        root = root_by_name.get(package_name)
        metadata_matches_pin = _metadata_matches_requirement_pin(
            root=root,
            distribution=distribution,
        )
        license_term = _license_term(
            distribution.metadata if distribution and metadata_matches_pin else None
        )
        classification, exception = _classify_license(
            package_name=package_name,
            license_term=license_term,
            policy=policy,
            today=date.today(),
        )
        records.append(
            {
                "name": package_name,
                "declared_name": root.declared_name if root else package_name,
                "version": _package_version(root=root, distribution=distribution),
                "installed_version": distribution.version if distribution else None,
                "relationship": "direct" if root else "transitive",
                "dependency_groups": sorted(graph_membership[package_name]),
                "source_files": sorted({root.source_file}) if root else [],
                "license_term": license_term,
                "policy_classification": classification,
                "exception_id": exception.get("id") if exception else None,
                "exception_owner": exception.get("owner") if exception else None,
                "exception_expires_on": exception.get("expires_on") if exception else None,
                "metadata_available": distribution is not None and metadata_matches_pin,
                "metadata_matches_requirement_pin": metadata_matches_pin,
            }
        )
    return records


def _exact_pinned_version(requirement: Requirement) -> str | None:
    pins = [
        str(specifier.version)
        for specifier in SpecifierSet(str(requirement.specifier))
        if specifier.operator == "=="
    ]
    if len(pins) == 1:
        return pins[0]
    return None


def _package_version(
    *,
    root: RequirementRoot | None,
    distribution: metadata.Distribution | None,
) -> str | None:
    if root and root.pinned_version:
        return root.pinned_version
    if distribution:
        return distribution.version
    return None


def _metadata_matches_requirement_pin(
    *,
    root: RequirementRoot | None,
    distribution: metadata.Distribution | None,
) -> bool:
    if distribution is None:
        return False
    if root is None or root.pinned_version is None:
        return True
    return distribution.version == root.pinned_version


def _classify_license(
    *,
    package_name: str,
    license_term: str,
    policy: LicensePolicy,
    today: date,
) -> tuple[str, dict[str, Any] | None]:
    exception = _matching_exception(package_name, license_term, policy)
    if exception is not None and _exception_expiry(exception) >= today:
        return "APPROVED_EXCEPTION", exception
    if license_term in policy.prohibited_terms:
        return "PROHIBITED", exception
    if not license_term or license_term == "UNKNOWN":
        return "REVIEW_REQUIRED", exception
    if license_term in policy.review_required_terms:
        return "REVIEW_REQUIRED", exception
    if _all_license_terms_allowed(license_term, policy.allowed_terms):
        return "ALLOWED", exception
    return "REVIEW_REQUIRED", exception


def _all_license_terms_allowed(license_term: str, allowed_terms: frozenset[str]) -> bool:
    parts = [part.strip() for part in LICENSE_OPERATOR_RE.split(license_term) if part.strip()]
    return bool(parts) and all(part in allowed_terms for part in parts)


def _matching_exception(
    package_name: str,
    license_term: str,
    policy: LicensePolicy,
) -> dict[str, Any] | None:
    normalized_name = canonicalize_name(package_name)
    for exception in policy.exceptions:
        exception_package = canonicalize_name(str(exception.get("package") or ""))
        exception_license = str(exception.get("license_term") or "")
        if exception_package != normalized_name:
            continue
        if exception_license not in {"*", license_term}:
            continue
        return exception
    return None


def _validate_exception_posture(
    package: dict[str, Any],
    policy: LicensePolicy,
    *,
    today: date,
) -> list[str]:
    package_name = str(package.get("name") or "")
    license_term = str(package.get("license_term") or "")
    exception = _matching_exception(package_name, license_term, policy)
    if exception is None:
        return []
    expires_on = _exception_expiry(exception)
    if expires_on < today:
        return [f"{package_name} license exception {exception.get('id')} expired on {expires_on}"]
    return []


def _exception_expiry(exception: dict[str, Any]) -> date:
    return date.fromisoformat(str(exception.get("expires_on") or "1970-01-01"))


def _exception_evidence(exception: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    exception_id = exception.get("exception_id") or exception.get("id")
    owner = exception.get("exception_owner") or exception.get("owner")
    expires_on = exception.get("exception_expires_on") or exception.get("expires_on")
    return (
        str(exception_id) if exception_id else None,
        str(owner) if owner else None,
        str(expires_on) if expires_on else None,
    )


def _license_term(package_metadata: metadata.PackageMetadata | None) -> str:
    if package_metadata is None:
        return "UNKNOWN"
    expression = _metadata_value(package_metadata, "License-Expression")
    if expression:
        return _bounded_license_text(expression)
    license_value = _metadata_value(package_metadata, "License")
    if license_value and len(license_value) <= 80:
        return _bounded_license_text(license_value)
    classifier_term = _license_term_from_classifiers(package_metadata.get_all("Classifier", []))
    return classifier_term or "UNKNOWN"


def _license_term_from_classifiers(classifiers: Iterable[str]) -> str | None:
    for classifier in classifiers:
        if not classifier.startswith("License ::"):
            continue
        tail = classifier.rsplit("::", maxsplit=1)[-1].strip()
        mapped = {
            "Apache Software License": "Apache-2.0",
            "BSD License": "BSD-3-Clause",
            "MIT License": "MIT",
            "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
        }.get(tail)
        return mapped or tail
    return None


def _bounded_license_text(value: str) -> str:
    return " ".join(value.split())[:160] or "UNKNOWN"


def _metadata_value(package_metadata: metadata.PackageMetadata, key: str) -> str | None:
    values = package_metadata.get_all(key, [])
    if not values:
        return None
    value = values[0]
    return str(value).strip() if value else None


def _inventory_summary(package_records: list[dict[str, Any]]) -> dict[str, Any]:
    by_classification: dict[str, int] = {}
    for package in package_records:
        classification = str(package["policy_classification"])
        by_classification[classification] = by_classification.get(classification, 0) + 1
    return {
        "package_count": len(package_records),
        "direct_package_count": sum(
            1 for package in package_records if package["relationship"] == "direct"
        ),
        "transitive_package_count": sum(
            1 for package in package_records if package["relationship"] == "transitive"
        ),
        "classifications": dict(sorted(by_classification.items())),
    }


def _normalized_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        key: value
        for key, value in inventory.items()
        if key
        not in {
            "generated_at_utc",
            "git_commit_sha",
            "image_digest",
            "packages",
            "summary",
        }
    }
    direct_packages = [
        dict(package)
        for package in inventory.get("packages", [])
        if package.get("relationship") == "direct"
    ]
    normalized["direct_packages"] = sorted(
        direct_packages,
        key=lambda package: str(package.get("name") or ""),
    )
    return normalized


def _missing_expected_transitive_package_names(
    inventory: dict[str, Any],
    expected_inventory: dict[str, Any],
) -> list[str]:
    current_names = set(_transitive_package_freshness_map(inventory))
    expected_names = set(_transitive_package_freshness_map(expected_inventory))
    return sorted(name for name in expected_names - current_names if name)


def _stale_expected_transitive_package_names(
    inventory: dict[str, Any],
    expected_inventory: dict[str, Any],
) -> list[str]:
    current_packages = _transitive_package_freshness_map(inventory)
    expected_packages = _transitive_package_freshness_map(expected_inventory)
    return sorted(
        name
        for name, expected_package in expected_packages.items()
        if name in current_packages and current_packages[name] != expected_package
    )


def _transitive_package_freshness_map(
    inventory: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    for package in inventory.get("packages", []):
        if package.get("relationship") != "transitive":
            continue
        name = str(package.get("name") or "")
        if not name:
            continue
        packages[name] = {
            "dependency_groups": sorted(
                str(group) for group in package.get("dependency_groups", [])
            ),
            "exception_id": package.get("exception_id"),
            "exception_owner": package.get("exception_owner"),
            "exception_expires_on": package.get("exception_expires_on"),
        }
    return packages


def _git_commit_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(REPO_ROOT):
        return resolved.relative_to(REPO_ROOT).as_posix()
    return resolved.as_posix()


def _build_inventory_from_args(args: argparse.Namespace) -> dict[str, Any]:
    policy = load_policy(REPO_ROOT / args.policy)
    return build_license_inventory(
        runtime_requirements=REPO_ROOT / args.runtime_requirements,
        development_requirements=REPO_ROOT / args.development_requirements,
        policy=policy,
        commit_sha=args.commit_sha,
        image_digest=args.image_digest,
        repository_url=args.repository_url,
        generated_at_utc=args.generated_at_utc,
    )


def _run_in_isolated_environment(
    args: argparse.Namespace,
    *,
    venv_root: Path | None = None,
) -> int:
    if os.environ.get(ISOLATED_ENV_FLAG) == "1":
        raise RuntimeError("nested license/IP isolated execution is not supported")

    if venv_root is not None:
        return _run_with_isolated_venv(args, venv_root)

    with tempfile.TemporaryDirectory(prefix="lotus-advise-license-ip-") as temp_dir:
        return _run_with_isolated_venv(args, Path(temp_dir) / "venv")


def _run_with_isolated_venv(args: argparse.Namespace, venv_root: Path) -> int:
    create_result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_root)],
        cwd=REPO_ROOT,
        check=False,
    )
    if create_result.returncode != 0:
        return create_result.returncode

    venv_python = _venv_python(venv_root)
    install_env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    for requirement_file in (
        args.runtime_requirements,
        args.development_requirements,
    ):
        install_result = subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-r",
                str(REPO_ROOT / requirement_file),
            ],
            cwd=REPO_ROOT,
            env=install_env,
            check=False,
        )
        if install_result.returncode != 0:
            return install_result.returncode

    execution_env = {**os.environ, ISOLATED_ENV_FLAG: "1"}
    execution_result = subprocess.run(
        [
            str(venv_python),
            str(REPO_ROOT / "scripts" / "license_ip_evidence.py"),
            args.command,
            "--runtime-requirements",
            str(args.runtime_requirements),
            "--development-requirements",
            str(args.development_requirements),
            "--policy",
            str(args.policy),
            "--inventory",
            str(args.inventory),
            "--repository-url",
            str(args.repository_url),
            "--commit-sha",
            str(args.commit_sha),
            "--image-digest",
            str(args.image_digest),
            "--generated-at-utc",
            str(args.generated_at_utc),
            "--no-isolation",
        ],
        cwd=REPO_ROOT,
        env=execution_env,
        check=False,
    )
    return execution_result.returncode


def _venv_python(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def _add_inventory_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--runtime-requirements", default="requirements-prod.txt")
    parser.add_argument("--development-requirements", default="requirements-dev.txt")
    parser.add_argument("--policy", default=POLICY_PATH.as_posix())
    parser.add_argument("--inventory", default=INVENTORY_PATH.as_posix())
    parser.add_argument("--repository-url", default="https://github.com/sgajbi/lotus-advise")
    parser.add_argument("--commit-sha", default=os.environ.get("GIT_SHA") or _git_commit_sha())
    parser.add_argument("--image-digest", default=os.environ.get("IMAGE_DIGEST", "unknown"))
    parser.add_argument(
        "--generated-at-utc",
        default=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    parser.add_argument(
        "--isolated",
        action="store_true",
        help=(
            "Build or check evidence in a temporary venv installed from the governed "
            "requirements files instead of the caller's ambient Python environment."
        ),
    )
    parser.add_argument(
        "--no-isolation",
        action="store_false",
        dest="isolated",
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(isolated=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    write_inventory_parser = subparsers.add_parser("write-inventory")
    _add_inventory_arguments(write_inventory_parser)
    check_inventory_parser = subparsers.add_parser("check-inventory")
    _add_inventory_arguments(check_inventory_parser)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.isolated:
        return _run_in_isolated_environment(args)
    expected_inventory = _build_inventory_from_args(args)
    policy = load_policy(REPO_ROOT / args.policy)
    if args.command == "write-inventory":
        failures = validate_license_inventory(expected_inventory, policy)
        write_inventory(expected_inventory, REPO_ROOT / args.inventory)
    else:
        current_inventory = json.loads((REPO_ROOT / args.inventory).read_text(encoding="utf-8"))
        failures = validate_license_inventory_against_expected(
            current_inventory,
            expected_inventory,
            policy,
        )
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
