"""Project and validate exact constraints from the authoritative dependency lock."""

import tomllib
from pathlib import Path

from packaging.utils import canonicalize_name


def write_authoritative_lock_constraints(
    lock_path: Path,
    output_path: Path,
    *,
    refreshed_direct_constraints: dict[str, str],
) -> dict[str, str]:
    constraints, direct_packages = _read_authoritative_lock(lock_path)
    for name, version in refreshed_direct_constraints.items():
        if name not in constraints:
            raise RuntimeError(f"Direct requirement {name} is absent from the lock")
        if name not in direct_packages:
            raise RuntimeError(f"Direct requirement {name} is not recorded as direct in the lock")
        constraints[name] = version
    rendered = "# Generated at runtime from uv.lock; do not edit.\n" + "\n".join(
        f"{name}=={constraints[name]}" for name in sorted(constraints)
    )
    output_path.write_text(f"{rendered}\n", encoding="utf-8")
    return constraints


def validate_installed_packages_against_lock(
    installed_packages: object,
    constraints: dict[str, str],
) -> None:
    if not isinstance(installed_packages, list):
        raise RuntimeError("Installed dependency inventory is not a package list")
    for package in installed_packages:
        name, version = _package_identity(package, source="Installed dependency inventory")
        locked_version = constraints.get(name)
        if locked_version is None:
            raise RuntimeError(f"Installed dependency {name}=={version} is absent from the lock")
        if version != locked_version:
            raise RuntimeError(
                f"Installed dependency {name}=={version} does not match {locked_version}"
            )


def _read_authoritative_lock(lock_path: Path) -> tuple[dict[str, str], set[str]]:
    try:
        payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Cannot read authoritative dependency lock {lock_path}: {exc}") from exc
    packages = payload.get("package", [])
    if not isinstance(packages, list):
        raise RuntimeError("Authoritative dependency lock package inventory must be a list")
    constraints: dict[str, str] = {}
    direct_packages: set[str] = set()
    for package in packages:
        name, version = _package_identity(package, source="Authoritative dependency lock")
        direct = package.get("direct")
        if not isinstance(direct, bool):
            raise RuntimeError(f"Authoritative dependency lock package {name} needs boolean direct")
        previous_version = constraints.setdefault(name, version)
        if previous_version != version:
            raise RuntimeError(f"Lock contains conflicting versions for {name}")
        if direct:
            direct_packages.add(name)
    if not constraints:
        raise RuntimeError("Authoritative dependency lock contains no package constraints")
    return constraints, direct_packages


def _package_identity(package: object, *, source: str) -> tuple[str, str]:
    if not isinstance(package, dict):
        raise RuntimeError(f"{source} contains a malformed package")
    name = canonicalize_name(str(package.get("name") or ""))
    version = str(package.get("version") or "")
    if not name or not version:
        raise RuntimeError(f"{source} packages must include name and version")
    return name, version
