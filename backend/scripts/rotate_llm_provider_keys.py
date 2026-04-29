"""Rotate OpenAI / Anthropic API keys across all tenants.

For each tenant, iterates every LLM provider (and optionally embedding and
voice providers), decrypts the stored key, and replaces it with the new key
when it matches the old one.

Usage (docker):
    docker exec -it onyx-api_server-1 \
        python -m scripts.rotate_llm_provider_keys \
            --provider openai \
            --old-key "sk-old..." \
            --new-key "sk-new..."

    # Or target both providers at once:
    docker exec -it onyx-api_server-1 \
        python -m scripts.rotate_llm_provider_keys \
            --provider openai --provider anthropic \
            --old-key "sk-old..." \
            --new-key "sk-new..."

Usage (kubernetes):
    kubectl exec -it <pod> -- \
        python -m scripts.rotate_llm_provider_keys \
            --provider anthropic \
            --old-key "sk-ant-old..." \
            --new-key "sk-ant-new..."

Pass --dry-run to preview changes without committing.
Pass --include-embedding to also rotate keys on embedding_provider rows.
Pass --include-voice to also rotate keys on voice_provider rows.
Pass --tenant-id to target a single tenant instead of all tenants.
"""

import argparse
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from sqlalchemy import select  # noqa: E402

from onyx.db.engine.sql_engine import get_session_with_tenant  # noqa: E402
from onyx.db.engine.sql_engine import SqlEngine  # noqa: E402
from onyx.db.engine.tenant_utils import get_all_tenant_ids  # noqa: E402
from onyx.db.models import CloudEmbeddingProvider  # noqa: E402
from onyx.db.models import LLMProvider  # noqa: E402
from onyx.db.models import VoiceProvider  # noqa: E402
from onyx.utils.variable_functionality import (  # noqa: E402
    set_is_ee_based_on_env_variable,
)

PROVIDER_ALIASES: dict[str, set[str]] = {
    "openai": {"openai", "openai_compatible"},
    "anthropic": {"anthropic"},
}


def _rotate_llm_providers(
    tenant_id: str,
    provider_names: set[str],
    old_key: str,
    new_key: str,
    dry_run: bool,
    include_embedding: bool,
    include_voice: bool,
) -> dict[str, int]:
    """Returns {table_name: count_of_rows_rotated}."""
    counts: dict[str, int] = {}

    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        # --- llm_provider ---
        llm_rows = db_session.execute(select(LLMProvider)).scalars().all()
        rotated = 0
        for row in llm_rows:
            if row.provider not in provider_names:
                continue
            if row.api_key is None:
                continue
            try:
                decrypted = row.api_key.get_value(apply_mask=False)
            except Exception as e:
                print(
                    f"  WARN: llm_provider id={row.id} name={row.name!r} "
                    f"— could not decrypt: {e}"
                )
                continue
            if decrypted == old_key:
                if not dry_run:
                    row.api_key = new_key  # ty: ignore[invalid-assignment]
                rotated += 1
                print(
                    f"  {'[DRY RUN] ' if dry_run else ''}"
                    f"llm_provider id={row.id} name={row.name!r} "
                    f"provider={row.provider!r} -> rotated"
                )
        if rotated:
            counts["llm_provider"] = rotated

        # --- embedding_provider ---
        if include_embedding:
            emb_rows = (
                db_session.execute(select(CloudEmbeddingProvider)).scalars().all()
            )
            rotated = 0
            for row in emb_rows:
                if row.provider_type.value not in provider_names:
                    continue
                if row.api_key is None:
                    continue
                try:
                    decrypted = row.api_key.get_value(apply_mask=False)
                except Exception as e:
                    print(
                        f"  WARN: embedding_provider type={row.provider_type!r} "
                        f"— could not decrypt: {e}"
                    )
                    continue
                if decrypted == old_key:
                    if not dry_run:
                        row.api_key = new_key  # ty: ignore[invalid-assignment]
                    rotated += 1
                    print(
                        f"  {'[DRY RUN] ' if dry_run else ''}"
                        f"embedding_provider type={row.provider_type!r} -> rotated"
                    )
            if rotated:
                counts["embedding_provider"] = rotated

        # --- voice_provider ---
        if include_voice:
            voice_rows = db_session.execute(select(VoiceProvider)).scalars().all()
            rotated = 0
            for row in voice_rows:
                if row.provider_type not in provider_names:
                    continue
                if row.api_key is None:
                    continue
                try:
                    decrypted = row.api_key.get_value(apply_mask=False)
                except Exception as e:
                    print(
                        f"  WARN: voice_provider id={row.id} name={row.name!r} "
                        f"— could not decrypt: {e}"
                    )
                    continue
                if decrypted == old_key:
                    if not dry_run:
                        row.api_key = new_key  # ty: ignore[invalid-assignment]
                    rotated += 1
                    print(
                        f"  {'[DRY RUN] ' if dry_run else ''}"
                        f"voice_provider id={row.id} name={row.name!r} -> rotated"
                    )
            if rotated:
                counts["voice_provider"] = rotated

        if not dry_run:
            db_session.commit()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate OpenAI/Anthropic API keys across all tenants."
    )
    parser.add_argument(
        "--provider",
        action="append",
        required=True,
        choices=list(PROVIDER_ALIASES.keys()),
        help="Provider(s) to rotate. Can be specified multiple times.",
    )
    parser.add_argument("--old-key", required=True, help="The current (old) API key.")
    parser.add_argument(
        "--new-key", required=True, help="The replacement (new) API key."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing.",
    )
    parser.add_argument(
        "--include-embedding",
        action="store_true",
        help="Also rotate keys in the embedding_provider table.",
    )
    parser.add_argument(
        "--include-voice",
        action="store_true",
        help="Also rotate keys in the voice_provider table.",
    )

    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Target a specific tenant schema. Omit to rotate across all tenants.",
    )

    args = parser.parse_args()

    provider_names: set[str] = set()
    for p in args.provider:
        provider_names |= PROVIDER_ALIASES[p]

    set_is_ee_based_on_env_variable()
    SqlEngine.init_engine(pool_size=5, max_overflow=2)

    if args.dry_run:
        print("DRY RUN — no changes will be made\n")

    if args.tenant_id:
        tenant_ids = [args.tenant_id]
    else:
        tenant_ids = get_all_tenant_ids()

    print(f"Targeting {len(tenant_ids)} tenant(s)")
    print(f"Provider filter: {provider_names}")
    print(
        f"Tables: llm_provider"
        f"{', embedding_provider' if args.include_embedding else ''}"
        f"{', voice_provider' if args.include_voice else ''}"
    )
    print()

    total_rotated: dict[str, int] = {}
    failed_tenants: list[str] = []

    for tid in tenant_ids:
        print(f"Tenant: {tid}")
        try:
            counts = _rotate_llm_providers(
                tenant_id=tid,
                provider_names=provider_names,
                old_key=args.old_key,
                new_key=args.new_key,
                dry_run=args.dry_run,
                include_embedding=args.include_embedding,
                include_voice=args.include_voice,
            )
            if not counts:
                print("  (no matching keys)")
            for table, count in counts.items():
                total_rotated[table] = total_rotated.get(table, 0) + count
        except Exception as e:
            print(f"  ERROR: {e}")
            failed_tenants.append(tid)

    print(f"\n{'=' * 40}")
    print("Summary:")
    if total_rotated:
        for table, count in sorted(total_rotated.items()):
            print(
                f"  {table}: {count} row(s) "
                f"{'would be ' if args.dry_run else ''}rotated"
            )
    else:
        print("  No keys matched.")

    if failed_tenants:
        print(f"\nFAILED tenants ({len(failed_tenants)}): {failed_tenants}")
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
