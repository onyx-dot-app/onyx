"""Regenerate recommended-models.json with an OpenAI agent.

Companion to update_recommended_models.py. That script applies hardcoded
family regexes and keeps the newest match — so it happily recommends models a
vendor has superseded (the regex still matches) and can't notice age or lineup
changes. This script instead hands a compact digest of the OpenRouter catalog
to an OpenAI Responses API call with the built-in web_search tool, and lets the
model decide what each vendor actually recommends today.

The agent returns strict JSON (per-provider default + visible models + a
rationale). The script validates every pick against the catalog, reuses the
deterministic script's serialization and semantic-diff so version/updated_at
only move on real changes, and writes the file. Like the deterministic script
it never pushes — the workflow opens a reviewed PR and PR CI (provider chat
tests against every recommended model) is the gate.

Still standard-library-only on purpose: the Responses API call is one POST,
so any python3 with OPENAI_API_KEY can run it. Set OPENAI_MODEL (or --model)
to change the reasoning model.

Usage:
    python backend/scripts/update_recommended_models_agent.py            # dry-run
    python backend/scripts/update_recommended_models_agent.py --write
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from update_recommended_models import (  # ty: ignore[unresolved-import]  # noqa: E402
    OPENROUTER_MODELS_URL,
    CatalogModel,
    ProviderSection,
    RecommendedModel,
    RecommendedModelsFile,
    SectionRules,
    bump_version,
    derive_native_name,
    fetch_catalog,
    load_catalog_file,
    load_previous,
    load_rules,
    sections_equal,
    serialize,
    visible_models,
)

BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_OUTPUT = (
    BACKEND_DIR / "onyx" / "llm" / "well_known_providers" / "recommended-models.json"
)
DEFAULT_RULES = SCRIPT_DIR / "update_recommended_models_rules.json"

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_AGENT_MODEL = "gpt-5"
# Built-in web search tool on the Responses API.
WEB_SEARCH_TOOL = {"type": "web_search"}
# Cap per vendor section so the prompt stays small enough to leave room for
# web search results; catalogs list every variant ever released.
MAX_MODELS_PER_VENDOR = 50


def _output_schema(section_names: list[str]) -> dict[str, Any]:
    """Strict-mode JSON schema: dynamic keys aren't allowed, so providers is a
    list of fixed-section objects instead of an object keyed by section."""
    return {
        "type": "object",
        "properties": {
            "providers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "section": {"type": "string", "enum": section_names},
                        "default_model": {"type": "string"},
                        "additional_visible_models": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "display_name": {"type": ["string", "null"]},
                                },
                                "required": ["name", "display_name"],
                                "additionalProperties": False,
                            },
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": [
                        "section",
                        "default_model",
                        "additional_visible_models",
                        "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["providers", "summary"],
        "additionalProperties": False,
    }


PROMPT_TEMPLATE = """\
You are updating `recommended-models.json` for Onyx, an enterprise AI assistant
platform. Production deployments fetch this file from GitHub and surface exactly
these models to admins configuring providers in "Auto" mode — the default model
plus a short visible list. Your picks ship to every deployment, so recommend
only models you are confident are the vendor's current recommended lineup.

Sections and their naming conventions (native names, NOT OpenRouter ids):
- openai: strip the "openai/" prefix (e.g. "gpt-5.6-sol"). No display_name.
- anthropic: strip "anthropic/" and replace "." with "-" (e.g. "claude-opus-5").
- vertex_ai: strip the "google/" prefix (e.g. "gemini-3.1-pro-preview").
- openrouter: keep the full "vendor/id" OpenRouter id (e.g. "z-ai/glm-5.3").

Selection rules:
- Use web search against each vendor's CURRENT docs, announcements, and model
  pages. Do NOT rely on the catalog alone: vendors keep selling superseded
  models, and a model still being listed does NOT mean it is recommended.
- A model is a good pick only if the vendor currently positions it as part of
  its recommended lineup for a general-purpose enterprise assistant. If the
  vendor replaced a family with a newer line, the old line is NOT a good pick
  even if it is still sold.
- Do not recommend models released more than ~12 months ago unless the vendor
  still sells them as the current model for that tier.
- Cover tiers per vendor where they exist: the flagship (this becomes
  default_model), plus cheaper/faster current-tier options. Keep each list
  tight: about 3-5 models.
- Skip free tiers (":free" ids / $0 pricing), image/audio/embedding-only
  models, models without text output, and expired models.
- display_name: emit for anthropic, vertex_ai, and openrouter sections only —
  human-friendly name without the vendor prefix (e.g. "Claude Opus 5",
  "Gemini 3.1 Pro"). Omit display_name entirely for the openai section.
- Every name MUST be a native name derivable from the catalog digest below
  (exact string after the section's transform). Do not invent model names.

Output: one entry per section (section = openai | anthropic | vertex_ai |
openrouter) with default_model, additional_visible_models (include the
default), a one-paragraph rationale naming what you checked, plus a top-level
summary for the PR body.

== CURRENT recommended-models.json ==
{current_file}

== Curation rules used by the previous deterministic updater (intent reference
only — you may pick outside these families when the vendor lineup changed) ==
{rules_file}

== OpenRouter catalog digest (newest first per vendor) ==
{catalog_digest}
"""

FAILURE_CONTEXT_TEMPLATE = """\
== PREVIOUS ATTEMPT FAILED CI ==
The last generated PR failed the provider chat tests — real API calls against
each recommended model. Fix your picks based on this failure output (drop or
replace the failing models):

{failure_context}
"""

RETRY_CONTEXT_TEMPLATE = """\
== YOUR PREVIOUS OUTPUT WAS REJECTED ==
Fix these problems and try again:

{errors}
"""

# Names are provider model ids — anything with braces, spaces, or commas is a
# formatting glitch, not a pick.
VALID_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_-]*$")


def _created_date(model: CatalogModel) -> str:
    if not model.created:
        return "unknown"
    return datetime.fromtimestamp(model.created, tz=timezone.utc).date().isoformat()


def build_catalog_digest(
    catalog: list[CatalogModel],
    vendors: list[str],
    today: date,
    max_per_vendor: int,
) -> str:
    sections: list[str] = []
    for vendor in vendors:
        models: list[CatalogModel] = sorted(
            (m for m in catalog if m.id.startswith(f"{vendor}/")),
            key=lambda m: (-m.created, m.id),
        )
        lines: list[str] = [
            f"### {vendor} ({len(models)} catalog entries, newest {max_per_vendor} shown)"
        ]
        for model in models[:max_per_vendor]:
            flags: list[str] = []
            if model.is_free:
                flags.append("free")
            if "text" not in model.output_modalities:
                flags.append("no-text-output")
            if model.is_expired(today):
                flags.append("expired")
            elif model.expiration_date:
                flags.append(f"expires {model.expiration_date}")
            # OpenRouter prices are USD per token; report per million tokens.
            try:
                prompt_price = f"{float(model.pricing.get('prompt', 0)) * 1e6:.4g}"
            except (TypeError, ValueError):
                prompt_price = "?"
            lines.append(
                f"- {model.id} | {model.name} | created {_created_date(model)}"
                f" | prompt ${prompt_price}/Mtok"
                + (f" | FLAGS: {', '.join(flags)}" if flags else "")
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _api_request(
    path: str, api_key: str, timeout: float, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    request: urllib.request.Request = urllib.request.Request(  # noqa: S310
        f"{OPENAI_RESPONSES_URL}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read())


def call_responses_api(
    prompt: str,
    model: str,
    api_key: str,
    schema: dict[str, Any],
    timeout: float,
    reasoning_effort: str = "medium",
    response_id: str | None = None,
    poll_interval: float = 15.0,
) -> dict[str, Any]:
    """Submit in background mode and poll — research runs with web search
    regularly exceed what a single synchronous request tolerates. Pass
    response_id to resume polling an existing background response."""
    if response_id is None:
        body = {
            "model": model,
            "background": True,
            "reasoning": {"effort": reasoning_effort},
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
            "tools": [WEB_SEARCH_TOOL],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "recommended_models",
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        submitted: dict[str, Any] = _api_request("", api_key, 60.0, body)
        response_id = submitted.get("id")
        if not response_id:
            raise ValueError(f"No response id in submission: {submitted}")
    else:
        submitted = {}

    deadline: float = time.monotonic() + timeout
    while True:
        status: str | None = submitted.get("status")
        if status in ("completed", "failed", "cancelled", "incomplete"):
            return submitted
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Response {response_id} still {status} after {timeout}s"
            )
        time.sleep(poll_interval)
        submitted = _api_request(f"/{response_id}", api_key, 60.0)
        status = submitted.get("status")
        print(f"  response {response_id}: {status}", flush=True)


def extract_output_text(response: dict[str, Any]) -> str:
    if response.get("status") == "incomplete":
        details = response.get("incomplete_details") or {}
        raise ValueError(f"Response incomplete: {details.get('reason', 'unknown')}")
    if response.get("status") not in (None, "completed"):
        raise ValueError(
            f"Response status {response.get('status')!r}: "
            f"{json.dumps(response.get('error'))[:500]}"
        )
    texts: list[str] = []
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        texts.extend(
            content.get("text") or ""
            for content in item.get("content") or []
            if content.get("type") == "output_text"
        )
    text = "".join(texts).strip()
    if not text:
        raise ValueError("No output_text in response")
    return text


def _section_vendors(section_rules: SectionRules) -> set[str]:
    return {rule.vendor_prefix.rstrip("/") for rule in section_rules.rules}


def _alias_to_native(
    section_rules: SectionRules,
    catalog: list[CatalogModel],
) -> dict[str, str]:
    """Alias → canonical native name for this section.

    The agent may write a bare catalog id ("claude-fable-5.1") or the full
    OpenRouter id ("anthropic/claude-fable-5.1") where the file wants the
    transformed native name ("claude-fable-5-1"); map all of them so one
    naming glitch doesn't sink an otherwise-correct pick.
    """
    aliases: dict[str, str] = {}
    keep_full: bool = section_rules.id_transform == "keep_full_id"
    vendors: set[str] = _section_vendors(section_rules)
    for model in catalog:
        if not keep_full and model.id.split("/", 1)[0] not in vendors:
            continue
        native: str = derive_native_name(model, section_rules)
        aliases[model.id] = native
        aliases[native] = native
        if "/" in model.id:
            aliases[model.id.split("/", 1)[1]] = native
    return aliases


def _resolve_name(
    section_name: str,
    raw_name: str,
    aliases: dict[str, str],
    previous_names: set[str],
    strict_catalog: bool,
    errors: list[str],
    warnings: list[str],
) -> str | None:
    """Canonicalize one agent-supplied name, or None to reject.

    keep_full_id names ARE OpenRouter ids — they must exist in the catalog.
    Native sections name models in the provider's namespace: an absent
    catalog entry may just mean OpenRouter hasn't listed a real model yet,
    so it warns and PR CI arbitrates. Malformed names are always rejected.
    """
    if not raw_name or not VALID_NAME_RE.match(raw_name):
        errors.append(f"{section_name}: malformed name '{raw_name}'")
        return None
    name = aliases.get(raw_name)
    if name is not None:
        if name != raw_name:
            warnings.append(f"{section_name}: normalized '{raw_name}' -> '{name}'")
        return name
    if raw_name in previous_names:
        return raw_name
    if strict_catalog:
        errors.append(f"{section_name}: '{raw_name}' is not an OpenRouter catalog id")
        return None
    warnings.append(
        f"{section_name}: '{raw_name}' is not in the OpenRouter catalog "
        "(may be new/unlisted); PR CI will verify it"
    )
    return raw_name


def _build_provider_section(
    section_name: str,
    pick: dict[str, Any],
    section_rules: SectionRules,
    previous_section: ProviderSection,
    catalog: list[CatalogModel],
    today: date,
    errors: list[str],
    warnings: list[str],
) -> ProviderSection:
    aliases: dict[str, str] = _alias_to_native(section_rules, catalog)
    previous_names: set[str] = {m.name for m in visible_models(previous_section)}
    strict_catalog: bool = section_rules.id_transform == "keep_full_id"
    emit_display: bool = section_rules.emit_display_name

    def resolve(raw_name: str) -> str | None:
        return _resolve_name(
            section_name,
            raw_name,
            aliases,
            previous_names,
            strict_catalog,
            errors,
            warnings,
        )

    deduped: list[RecommendedModel] = []
    seen: set[str] = set()
    for entry in pick.get("additional_visible_models") or []:
        name = resolve(entry.get("name") or "")
        if name is None or name in seen:
            continue
        seen.add(name)
        display = entry.get("display_name") if emit_display else None
        deduped.append(RecommendedModel(name=name, display_name=display))

    default_name: str = pick.get("default_model") or ""
    if not default_name:
        errors.append(f"{section_name}: no default_model")
    else:
        resolved_default = resolve(default_name)
        if resolved_default is not None:
            default_name = resolved_default
            if default_name not in seen:
                deduped.insert(0, RecommendedModel(name=default_name))
                seen.add(default_name)

    # default_model first
    deduped.sort(key=lambda m: m.name != default_name)

    # Soft checks: recommend, don't reject
    catalog_by_native: dict[str, CatalogModel] = {
        derive_native_name(m, section_rules): m for m in catalog
    }
    for model in deduped:
        entry = catalog_by_native.get(model.name)
        if entry is None:
            continue
        if entry.is_free:
            warnings.append(f"{section_name}: {model.name} is a free tier")
        if "text" not in entry.output_modalities:
            warnings.append(f"{section_name}: {model.name} has no text output")
        if entry.is_expired(today):
            warnings.append(f"{section_name}: {model.name} is expired")

    return ProviderSection(
        default_model=default_name,
        additional_visible_models=deduped,
    )


def validate_and_build(
    agent_output: dict[str, Any],
    previous: RecommendedModelsFile,
    catalog: list[CatalogModel],
    rules_path: Path,
    today: date,
) -> tuple[RecommendedModelsFile, dict[str, str], list[str]]:
    """Validate agent picks against the catalog, dedupe, order default-first.

    Returns (new file, {section: rationale}, warnings). Raises on picks that
    are neither in the catalog nor already recommended — a hallucinated model
    would ship to every deployment.
    """
    rules = load_rules(rules_path)
    errors: list[str] = []
    warnings: list[str] = []
    rationales: dict[str, str] = {}
    providers: dict[str, ProviderSection] = {}

    raw_providers = agent_output.get("providers") or []
    agent_providers: dict[str | None, dict[str, Any]] = {
        entry.get("section"): entry
        for entry in raw_providers
        if isinstance(entry, dict)
    }
    missing = set(previous.providers) - set(agent_providers)
    if missing:
        errors.append(f"agent omitted sections: {sorted(missing)}")

    for section_name in previous.providers:
        if section_name not in agent_providers:
            continue
        pick = agent_providers[section_name]
        rationales[section_name] = pick.get("rationale") or ""
        providers[section_name] = _build_provider_section(
            section_name,
            pick,
            rules.sections[section_name],
            previous.providers[section_name],
            catalog,
            today,
            errors,
            warnings,
        )

    if errors:
        raise ValueError(
            "Invalid agent output:\n" + "\n".join(f"- {e}" for e in errors)
        )

    changed = any(
        not sections_equal(new, previous.providers[name])
        for name, new in providers.items()
    )
    if not changed:
        return previous, rationales, warnings
    return (
        RecommendedModelsFile(
            version=bump_version(previous.version),
            updated_at=f"{today.isoformat()}T00:00:00Z",
            providers=providers,
        ),
        rationales,
        warnings,
    )


def write_rationale(path: Path, summary: str, rationales: dict[str, str]) -> None:
    lines = ["### Why these models (agent rationale)", "", summary, ""]
    for section, rationale in rationales.items():
        if rationale:
            lines.append(f"- **{section}**: {rationale}")
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="Rewrite the file (default: dry-run)"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL") or DEFAULT_AGENT_MODEL,
        help="OpenAI model for the agent call (env: OPENAI_MODEL)",
    )
    parser.add_argument("--catalog-url", default=None)
    parser.add_argument(
        "--reasoning-effort",
        default=os.environ.get("OPENAI_REASONING_EFFORT") or "medium",
        choices=["none", "low", "medium", "high"],
        help="Reasoning effort for the agent call (env: OPENAI_REASONING_EFFORT)",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RESPONSE_ID",
        help="Poll an existing background response id instead of submitting",
    )
    parser.add_argument(
        "--catalog-file",
        type=Path,
        default=None,
        help="Read the catalog from a JSON file instead of the API",
    )
    parser.add_argument(
        "--failure-context-file",
        type=Path,
        default=None,
        help="CI failure logs from a previous attempt; the agent fixes its picks",
    )
    parser.add_argument(
        "--rationale-file",
        type=Path,
        default=None,
        help="Write a markdown rationale for the PR body",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1500.0,
        help="Max seconds to wait on the background response (default 25m)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="Agent calls before giving up (the retry gets the validation errors)",
    )
    parser.add_argument(
        "--max-vendor-models",
        type=int,
        default=MAX_MODELS_PER_VENDOR,
        help="Catalog rows per vendor in the prompt digest",
    )
    args = parser.parse_args(argv)

    api_key: str | None = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    rules = load_rules(args.rules)
    previous: RecommendedModelsFile = load_previous(args.output)
    catalog: list[CatalogModel]
    if args.catalog_file:
        catalog = load_catalog_file(args.catalog_file)
    else:
        catalog = fetch_catalog(args.catalog_url or OPENROUTER_MODELS_URL, 30.0)

    today: date = datetime.now(tz=timezone.utc).date()
    vendors: list[str] = sorted(
        {
            rule.vendor_prefix.rstrip("/")
            for s in rules.sections.values()
            for rule in s.rules
        }
    )

    prompt: str = PROMPT_TEMPLATE.format(
        current_file=args.output.read_text(),
        rules_file=args.rules.read_text(),
        catalog_digest=build_catalog_digest(
            catalog, vendors, today, args.max_vendor_models
        ),
    )
    if args.failure_context_file and args.failure_context_file.exists():
        prompt += FAILURE_CONTEXT_TEMPLATE.format(
            failure_context=args.failure_context_file.read_text()[-60_000:]
        )

    schema: dict[str, Any] = _output_schema(list(previous.providers))
    error: str | None = None
    agent_output: dict[str, Any] = {}
    recommendations: RecommendedModelsFile | None = None
    rationales: dict[str, str] = {}
    warnings: list[str] = []

    for attempt in range(args.max_attempts):
        attempt_prompt: str = prompt
        if error:
            attempt_prompt += RETRY_CONTEXT_TEMPLATE.format(errors=error)
        print(f"Calling OpenAI Responses API (model={args.model})...", flush=True)
        response: dict[str, Any] = call_responses_api(
            attempt_prompt,
            args.model,
            api_key,
            schema,
            args.timeout,
            reasoning_effort=args.reasoning_effort,
            response_id=args.resume,
        )
        args.resume = None  # resume applies to the first call only
        try:
            agent_output = json.loads(extract_output_text(response))
            recommendations, rationales, warnings = validate_and_build(
                agent_output, previous, catalog, args.rules, today
            )
            error = None
            break
        except (ValueError, json.JSONDecodeError) as e:
            error = str(e)
            print(f"Attempt {attempt + 1} rejected:\n{error}", file=sys.stderr)

    if error or recommendations is None:
        print("Agent output did not validate.", file=sys.stderr)
        return 2

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if args.rationale_file:
        write_rationale(
            args.rationale_file,
            agent_output.get("summary") or "",
            rationales,
        )

    serialized: str = serialize(recommendations)
    if serialized == args.output.read_text():
        print(f"{args.output} is up to date.")
        return 0
    if not args.write:
        print(serialized)
        print(f"{args.output} is stale (re-run with --write).", file=sys.stderr)
        return 1
    args.output.write_text(serialized)
    print(f"Updated {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
