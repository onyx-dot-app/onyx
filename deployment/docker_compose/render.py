#!/usr/bin/env python3
"""Render flat docker-compose files from canonical service fragments.

Source of truth lives under `src/`:
  * `src/services/<name>.yml` — canonical per-service definitions
  * `src/deployments/<name>.yml` — composition + per-deployment overrides

Each deployment file has the following top-level keys:
  * `name`          — compose project name
  * `include`       — list of service fragment names to pull in from src/services/
  * `services`      — per-service field overrides, deep-merged into the fragments
  * `volumes`       — top-level named-volume declarations
  * `networks`      — top-level network declarations (optional)

Run `python render.py` to (re)write the top-level `docker-compose.*.yml` files.
Run `python render.py --check` for the pre-commit hook (exits non-zero on drift).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
SERVICES_DIR = SRC / "services"
DEPLOYMENTS_DIR = SRC / "deployments"

# Maps src/deployments/<key>.yml → top-level output filename
DEPLOYMENTS: dict[str, str] = {
    "default": "docker-compose.yml",
    "prod": "docker-compose.prod.yml",
    "prod-cloud": "docker-compose.prod-cloud.yml",
    "prod-no-letsencrypt": "docker-compose.prod-no-letsencrypt.yml",
    "multitenant-dev": "docker-compose.multitenant-dev.yml",
}

BANNER = (
    "# =============================================================================\n"
    "# GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "# Source: deployment/docker_compose/src/deployments/{name}.yml\n"
    "# Regenerate with: python deployment/docker_compose/render.py\n"
    "# =============================================================================\n"
)


def _env_to_dict(env: Any) -> dict[str, Any]:
    """Normalize compose `environment:` to a dict.

    Accepts either dict form ({KEY: value}) or list form (["KEY=value", ...]).
    """
    if env is None:
        return {}
    if isinstance(env, dict):
        return dict(env)
    if isinstance(env, list):
        out: dict[str, Any] = {}
        for item in env:
            if not isinstance(item, str):
                raise ValueError(f"environment list entry must be string, got {item!r}")
            key, sep, value = item.partition("=")
            out[key] = value if sep else None
        return out
    raise ValueError(f"environment must be dict or list, got {type(env).__name__}")


def _depends_on_to_dict(dep: Any) -> dict[str, Any]:
    """Normalize compose `depends_on:` to dict form."""
    if dep is None:
        return {}
    if isinstance(dep, dict):
        return dict(dep)
    if isinstance(dep, list):
        return {svc: {"condition": "service_started"} for svc in dep}
    raise ValueError(f"depends_on must be dict or list, got {type(dep).__name__}")


def _merge_service(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a service override on top of a base service definition.

    Rules:
      * Dicts merge recursively, override wins on key collisions.
      * Lists are replaced wholesale by the override.
      * Scalars are replaced.
      * `environment` is normalized to dict on both sides and key-merged.
      * `depends_on` is normalized to dict on both sides and key-merged.
    """
    out = dict(base)
    for key, ov in override.items():
        if key == "environment":
            merged_env = _env_to_dict(base.get("environment"))
            merged_env.update(_env_to_dict(ov))
            out["environment"] = merged_env
            continue
        if key == "depends_on":
            merged_dep = _depends_on_to_dict(base.get("depends_on"))
            merged_dep.update(_depends_on_to_dict(ov))
            out["depends_on"] = merged_dep
            continue
        if key in base and isinstance(base[key], dict) and isinstance(ov, dict):
            out[key] = _merge_dict(base[key], ov)
        else:
            out[key] = ov
    return out


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, ov in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(ov, dict):
            out[key] = _merge_dict(base[key], ov)
        else:
            out[key] = ov
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse as a mapping")
    return data


def _load_fragment(name: str) -> dict[str, Any]:
    """Load src/services/<name>.yml and return the single service definition."""
    path = SERVICES_DIR / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Service fragment not found: {path}")
    doc = _load_yaml(path)
    services = doc.get("services") or {}
    if name not in services:
        raise ValueError(f"{path} must define services.{name}")
    return services[name]


class _ComposeDumper(yaml.SafeDumper):
    """Dumper that emits readable, deterministic compose YAML.

    * Keys are emitted in declaration order (`sort_keys=False`).
    * Multi-line strings use literal block scalars so commands stay readable.
    """


def _str_representer(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


def _none_representer(dumper: yaml.SafeDumper, _value: None) -> yaml.ScalarNode:
    # Compose convention: `db_volume:` (bare key) rather than `db_volume: null`.
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


_ComposeDumper.add_representer(str, _str_representer)
_ComposeDumper.add_representer(type(None), _none_representer)


def render(name: str) -> str:
    """Render a deployment to a YAML string (without the banner)."""
    deployment_path = DEPLOYMENTS_DIR / f"{name}.yml"
    deployment = _load_yaml(deployment_path)

    project_name = deployment.get("name")
    if not project_name:
        raise ValueError(f"{deployment_path} must define `name:`")

    include = deployment.get("include") or []
    if not isinstance(include, list):
        raise ValueError(f"{deployment_path}: `include:` must be a list")

    overrides = deployment.get("services") or {}
    if not isinstance(overrides, dict):
        raise ValueError(f"{deployment_path}: `services:` must be a mapping")

    # Build merged services in include-order so the rendered file orders them
    # consistently. Overrides for services not in `include:` are still emitted
    # (rare, but useful for one-off services like Craft sandboxes).
    merged_services: dict[str, Any] = {}
    for service_name in include:
        base = _load_fragment(service_name)
        ov = overrides.get(service_name) or {}
        merged_services[service_name] = _merge_service(base, ov)

    for service_name, ov in overrides.items():
        if service_name not in merged_services:
            merged_services[service_name] = ov

    out: dict[str, Any] = {"name": project_name, "services": merged_services}

    for top_key in ("volumes", "networks", "configs", "secrets"):
        if top_key in deployment:
            out[top_key] = deployment[top_key]

    return yaml.dump(
        out,
        Dumper=_ComposeDumper,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    )


def render_all() -> dict[str, str]:
    """Render every deployment. Returns {output_path: content} mapping."""
    return {
        DEPLOYMENTS[name]: BANNER.format(name=name) + "\n" + render(name)
        for name in DEPLOYMENTS
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail (exit 1) if any rendered file would change instead of writing.",
    )
    args = parser.parse_args()

    rendered = render_all()
    drift: list[str] = []
    for filename, content in rendered.items():
        target = HERE / filename
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        if existing == content:
            continue
        if args.check:
            drift.append(filename)
            continue
        target.write_text(content, encoding="utf-8")
        print(f"wrote {filename}")

    if args.check and drift:
        print(
            "ERROR: rendered docker-compose files are out of date.\n"
            "Run: python deployment/docker_compose/render.py\n"
            "Drifted files:\n  - "
            + "\n  - ".join(drift),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
