#!/usr/bin/env python3
"""
Mark connectors for deletion script that:
1. Finds all connectors for the specified tenant(s)
2. Cancels any scheduled indexing attempts
3. Marks each connector credential pair as DELETING
4. Triggers the cleanup task

Usage:
    python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py <tenant_id> [--force]
    python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv <csv_file_path> [--force]

Arguments:
    tenant_id        The tenant ID to process (required if not using --csv)
    --csv PATH       Path to CSV file containing tenant IDs to process
    --force          Skip all confirmation prompts (optional)

Examples:
    python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py tenant_abc123-def456-789
    python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py tenant_abc123-def456-789 --force
    python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv gated_tenants_no_query_3mo.csv
    python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv gated_tenants_no_query_3mo.csv --force
"""

import subprocess
import sys
from pathlib import Path

from scripts.tenant_cleanup.cleanup_utils import confirm_step
from scripts.tenant_cleanup.cleanup_utils import find_worker_pod
from scripts.tenant_cleanup.cleanup_utils import get_tenant_status
from scripts.tenant_cleanup.cleanup_utils import read_tenant_ids_from_csv


def run_connector_deletion(pod_name: str, tenant_id: str) -> None:
    """Mark all connector credential pairs for deletion.

    Args:
        pod_name: The Kubernetes pod name to execute on
        tenant_id: The tenant ID
    """
    print("  Marking all connector credential pairs for deletion...")

    # Get the path to the script
    script_dir = Path(__file__).parent
    mark_deletion_script = (
        script_dir / "on_pod_scripts" / "execute_connector_deletion.py"
    )

    if not mark_deletion_script.exists():
        raise FileNotFoundError(
            f"mark_connector_for_deletion.py not found at {mark_deletion_script}"
        )

    try:
        # Copy script to pod
        subprocess.run(
            [
                "kubectl",
                "cp",
                str(mark_deletion_script),
                f"{pod_name}:/tmp/mark_connector_for_deletion.py",
            ],
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "--",
                "python",
                "/tmp/mark_connector_for_deletion.py",
                tenant_id,
                "--all",
            ],
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

    except subprocess.CalledProcessError as e:
        print(
            f"  ✗ Failed to mark all connector credential pairs for deletion: {e}",
            file=sys.stderr,
        )
        if e.stderr:
            print(f"    Error details: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        print(
            f"  ✗ Failed to mark all connector credential pairs for deletion: {e}",
            file=sys.stderr,
        )
        raise


def mark_tenant_connectors_for_deletion(tenant_id: str, force: bool = False) -> None:
    """
    Main function to mark all connectors for a tenant for deletion.

    Args:
        tenant_id: The tenant ID to process
        force: If True, skip all confirmation prompts
    """
    print(f"Processing connectors for tenant: {tenant_id}")

    # Check tenant status first
    print(f"\n{'=' * 80}")
    try:
        tenant_status = get_tenant_status(tenant_id)

        # If tenant is not GATED_ACCESS, require explicit confirmation even in force mode
        if tenant_status and tenant_status != "GATED_ACCESS":
            print(
                f"\n⚠️  WARNING: Tenant status is '{tenant_status}', not 'GATED_ACCESS'!"
            )
            print(
                "This tenant may be active and should not have connectors deleted without careful review."
            )
            print(f"{'=' * 80}\n")

            # Always ask for confirmation if not gated, even in force mode
            response = input(
                "Are you ABSOLUTELY SURE you want to proceed? Type 'yes' to confirm: "
            )
            if response.lower() != "yes":
                print("Operation aborted - tenant is not GATED_ACCESS")
                return
        elif tenant_status == "GATED_ACCESS":
            print("✓ Tenant status is GATED_ACCESS - safe to proceed")
        elif tenant_status is None:
            print("⚠️  WARNING: Could not determine tenant status!")
            response = input("Continue anyway? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                print("Operation aborted - could not verify tenant status")
                return
    except Exception as e:
        print(f"⚠️  WARNING: Failed to check tenant status: {e}")
        response = input("Continue anyway? Type 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Operation aborted - could not verify tenant status")
            return
    print(f"{'=' * 80}\n")

    # Find heavy worker pod for operations
    try:
        pod_name = find_worker_pod()
    except Exception as e:
        print(f"✗ Failed to find heavy worker pod: {e}", file=sys.stderr)
        print("Cannot proceed with marking connectors for deletion")
        return

    # Confirm before proceeding
    if not confirm_step(
        f"Mark all connector credential pairs for deletion for tenant {tenant_id}?",
        force,
    ):
        print("Operation cancelled by user")
        return

    run_connector_deletion(pod_name, tenant_id)

    # Print summary
    print(
        f"✓ Marked all connector credential pairs for deletion for tenant {tenant_id}"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py <tenant_id> [--force]"
        )
        print(
            "       python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv <csv_file_path> [--force]"
        )
        print("\nArguments:")
        print(
            "  tenant_id        The tenant ID to process (required if not using --csv)"
        )
        print("  --csv PATH       Path to CSV file containing tenant IDs to process")
        print("  --force          Skip all confirmation prompts (optional)")
        print("\nExamples:")
        print(
            "  python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py tenant_abc123-def456-789"
        )
        print(
            "  python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py tenant_abc123-def456-789 --force"
        )
        print(
            "  python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv gated_tenants_no_query_3mo.csv"
        )
        print(
            "  python backend/scripts/tenant_cleanup/mark_connectors_for_deletion.py --csv gated_tenants_no_query_3mo.csv --force"
        )
        sys.exit(1)

    # Parse arguments
    force = "--force" in sys.argv
    tenant_ids = []

    # Check for CSV mode
    if "--csv" in sys.argv:
        try:
            csv_index = sys.argv.index("--csv")
            if csv_index + 1 >= len(sys.argv):
                print("Error: --csv flag requires a file path", file=sys.stderr)
                sys.exit(1)

            csv_path = sys.argv[csv_index + 1]
            tenant_ids = read_tenant_ids_from_csv(csv_path)

            if not tenant_ids:
                print("Error: No tenant IDs found in CSV file", file=sys.stderr)
                sys.exit(1)

            print(f"Found {len(tenant_ids)} tenant(s) in CSV file: {csv_path}")

        except Exception as e:
            print(f"Error reading CSV file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Single tenant mode
        tenant_ids = [sys.argv[1]]

    # Initial confirmation (unless --force is used)
    if not force:
        print(f"\n{'=' * 80}")
        print("MARK CONNECTORS FOR DELETION - CONFIRMATION REQUIRED")
        print(f"{'=' * 80}")
        if len(tenant_ids) == 1:
            print(f"Tenant ID: {tenant_ids[0]}")
        else:
            print(f"Number of tenants: {len(tenant_ids)}")
            print(f"Tenant IDs: {', '.join(tenant_ids[:5])}")
            if len(tenant_ids) > 5:
                print(f"            ... and {len(tenant_ids) - 5} more")

        print(
            f"Mode: {'FORCE (no confirmations)' if force else 'Interactive (will ask for confirmation at each step)'}"
        )
        print("\nThis will:")
        print("  1. Fetch all connector credential pairs for each tenant")
        print("  2. Cancel any scheduled indexing attempts for each connector")
        print("  3. Mark each connector credential pair status as DELETING")
        print("  4. Trigger the connector deletion task")
        print(f"\n{'=' * 80}")
        print("WARNING: This will mark connectors for deletion!")
        print("The actual deletion will be performed by the background celery worker.")
        print(f"{'=' * 80}\n")

        response = input("Are you sure you want to proceed? Type 'yes' to confirm: ")

        if response.lower() != "yes":
            print("Operation aborted by user")
            sys.exit(0)
    else:
        if len(tenant_ids) == 1:
            print(
                f"⚠ FORCE MODE: Marking connectors for deletion for {tenant_ids[0]} without confirmations"
            )
        else:
            print(
                f"⚠ FORCE MODE: Marking connectors for deletion for {len(tenant_ids)} tenants without confirmations"
            )

    # Process each tenant
    failed_tenants = []
    successful_tenants = []

    for idx, tenant_id in enumerate(tenant_ids, 1):
        if len(tenant_ids) > 1:
            print(f"\n{'=' * 80}")
            print(f"Processing tenant {idx}/{len(tenant_ids)}: {tenant_id}")
            print(f"{'=' * 80}")

        try:
            mark_tenant_connectors_for_deletion(tenant_id, force)
            successful_tenants.append(tenant_id)
        except Exception as e:
            print(
                f"✗ Failed to process tenant {tenant_id}: {e}",
                file=sys.stderr,
            )
            failed_tenants.append((tenant_id, str(e)))

            # If not in force mode and there are more tenants, ask if we should continue
            if not force and idx < len(tenant_ids):
                response = input(
                    f"\nContinue with remaining {len(tenant_ids) - idx} tenant(s)? (y/n): "
                )
                if response.lower() != "y":
                    print("Operation aborted by user")
                    break

    # Print summary if multiple tenants
    if len(tenant_ids) > 1:
        print(f"\n{'=' * 80}")
        print("OPERATION SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total tenants: {len(tenant_ids)}")
        print(f"Successful: {len(successful_tenants)}")
        print(f"Failed: {len(failed_tenants)}")

        if failed_tenants:
            print("\nFailed tenants:")
            for tenant_id, error in failed_tenants:
                print(f"  - {tenant_id}: {error}")

        print(f"{'=' * 80}")

        if failed_tenants:
            sys.exit(1)


if __name__ == "__main__":
    main()
