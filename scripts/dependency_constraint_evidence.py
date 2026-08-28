"""Project and validate exact constraints from the authoritative dependency lock."""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.utils import canonicalize_name


def validate_authoritative_lock(lock_path: Path) -> None:
    _read_authoritative_lock(lock_path)


def write_authoritative_lock_constraints(
    lock_path: Path,
    output_path: Path,
    *,
    refreshed_direct_constraints: dict[str, str],
) -> dict[str, str]:
    package_constraints, direct_lock_packages = _read_authoritative_lock(lock_path)
    for name, version in refreshed_direct_constraints.items():
        if name not in package_constraints:
            raise RuntimeError(
                f"Direct requirement {name} is absent from the authoritative dependency lock; "
                "refresh the lock through the governed dependency workflow first"
            )
        if name not in direct_lock_packages:
            raise RuntimeError(
                f"Direct requirement {name} is not recorded as direct in the authoritative "
                "dependency lock"
            )
        package_constraints[name] = version

    output_path.write_text(
        "# Generated at runtime from uv.lock; do not edit.\n"
        + "\n".join(f"{name}=={package_constraints[name]}" for name in sorted(package_constraints))
        + "\n",
        encoding="utf-8",
    )
    return package_constraints


def validate_installed_packages_against_lock(
    installed_packages: object,
    package_constraints: dict[str, str],
) -> None:
    if not isinstance(installed_packages, list):
        raise RuntimeError("Installed dependency inventory is not a package list")
    for package in installed_packages:
        if not isinstance(package, dict):
            raise RuntimeError("Installed dependency inventory contains a malformed package")
        name = canonicalize_name(str(package.get("name") or ""))
        version = str(package.get("version") or "")
        if not name or not version:
            raise RuntimeError("Installed dependency inventory packages require name and version")
        locked_version = package_constraints.get(name)
        if locked_version is None:
            raise RuntimeError(
                f"Installed dependency {name}=={version} is absent from the authoritative lock; "
                "the refreshed graph must be locked before license evidence can be generated"
            )
        if version != locked_version:
            raise RuntimeError(
                f"Installed dependency {name}=={version} does not match authoritative lock "
                f"version {locked_version}"
            )


def _read_authoritative_lock(lock_path: Path) -> tuple[dict[str, str], set[str]]:
    try:
        lock_payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Cannot read authoritative dependency lock {lock_path}: {exc}") from exc

    package_constraints: dict[str, str] = {}
    direct_lock_packages: set[str] = set()
    for package in lock_payload.get("package", []):
        if not isinstance(package, dict):
            raise RuntimeError("Authoritative dependency lock contains a malformed package")
        name = canonicalize_name(str(package.get("name") or ""))
        version = str(package.get("version") or "")
        if not name or not version:
            raise RuntimeError(
                "Authoritative dependency lock packages must include name and version"
            )
        direct = package.get("direct")
        if not isinstance(direct, bool):
            raise RuntimeError(
                f"Authoritative dependency lock package {name} must declare direct as a boolean"
            )
        previous_version = package_constraints.setdefault(name, version)
        if previous_version != version:
            raise RuntimeError(
                f"Authoritative dependency lock contains conflicting versions for {name}"
            )
        if direct:
            direct_lock_packages.add(name)
    if not package_constraints:
        raise RuntimeError("Authoritative dependency lock contains no package constraints")
    return package_constraints, direct_lock_packages
