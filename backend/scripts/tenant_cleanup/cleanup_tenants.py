#!/usr/bin/env python3
"""
Tenant cleanup script that:
1. Deletes all documents from Vespa
2. Drops the data plane PostgreSQL schema
3. Clean up control plane (tenants, subscription table)

Usage:
    python backend/scripts/cleanup_tenant.py <tenant_id> [--force]
    python backend/scripts/cleanup_tenant.py --csv <csv_file_path> [--force]

Arguments:
    tenant_id        The tenant ID to clean up (required if not using --csv)
    --csv PATH       Path to CSV file containing tenant IDs to clean up
    --force          Skip all confirmation prompts (optional)

Examples:
    python backend/scripts/cleanup_tenant.py tenant_abc123-def456-789
    python backend/scripts/cleanup_tenant.py tenant_abc123-def456-789 --force
    python backend/scripts/cleanup_tenant.py --csv gated_tenants_no_query_3mo.csv
    python backend/scripts/cleanup_tenant.py --csv gated_tenants_no_query_3mo.csv --force
"""

import csv
import json
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from scripts.tenant_cleanup.cleanup_utils import confirm_step
from scripts.tenant_cleanup.cleanup_utils import execute_control_plane_query
from scripts.tenant_cleanup.cleanup_utils import find_worker_pod
from scripts.tenant_cleanup.cleanup_utils import get_tenant_status
from scripts.tenant_cleanup.cleanup_utils import read_tenant_ids_from_csv


# Global variable to track active subprocess
_active_process = None


def signal_handler(signum: int, frame: object) -> None:
    """Handle termination signals by killing active subprocess."""
    global _active_process
    if _active_process:
        print(
            "\n\n⚠ Received interrupt signal. Terminating active subprocess...",
            file=sys.stderr,
        )
        try:
            _active_process.terminate()
            _active_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("  Subprocess didn't terminate, killing it...", file=sys.stderr)
            _active_process.kill()
            _active_process.wait()
        print("  Subprocess terminated.", file=sys.stderr)
    sys.exit(1)


def get_tenant_index_name(pod_name: str, tenant_id: str) -> str:
    """Get the default index name for the given tenant by running script on pod."""
    print(f"Getting default index name for tenant: {tenant_id}")

    # Get the path to the script
    script_dir = Path(__file__).parent
    index_name_script = script_dir / "on_pod_scripts" / "get_tenant_index_name.py"

    if not index_name_script.exists():
        raise FileNotFoundError(
            f"get_tenant_index_name.py not found at {index_name_script}"
        )

    try:
        # Copy script to pod
        print("  Copying script to pod...")
        subprocess.run(
            [
                "kubectl",
                "cp",
                str(index_name_script),
                f"{pod_name}:/tmp/get_tenant_index_name.py",
            ],
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        print("  Executing script on pod...")
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "--",
                "python",
                "/tmp/get_tenant_index_name.py",
                tenant_id,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Show progress messages from stderr
        if result.stderr:
            print(f"  {result.stderr}", end="")

        # Parse JSON result from stdout
        result_data = json.loads(result.stdout)
        status = result_data.get("status")

        if status == "success":
            index_name = result_data.get("index_name")
            print(f"✓ Found index name: {index_name}")
            return index_name
        else:
            message = result_data.get("message", "Unknown error")
            raise RuntimeError(f"Failed to get index name: {message}")

    except subprocess.CalledProcessError as e:
        print(
            f"✗ Failed to get index name for tenant {tenant_id}: {e}", file=sys.stderr
        )
        if e.stderr:
            print(f"  Error details: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        print(
            f"✗ Failed to get index name for tenant {tenant_id}: {e}", file=sys.stderr
        )
        raise


def get_tenant_users(pod_name: str, tenant_id: str) -> list[str]:
    """Get list of user emails from the tenant's data plane schema.

    Args:
        pod_name: The Kubernetes pod name to execute on
        tenant_id: The tenant ID to query

    Returns:
        List of user email addresses, or empty list if query fails
    """
    print(f"Fetching user emails for tenant: {tenant_id}")

    # Get the path to the script
    script_dir = Path(__file__).parent
    get_users_script = script_dir / "on_pod_scripts" / "get_tenant_users.py"

    if not get_users_script.exists():
        raise FileNotFoundError(f"get_tenant_users.py not found at {get_users_script}")

    try:
        # Copy script to pod
        print("  Copying script to pod...")
        subprocess.run(
            [
                "kubectl",
                "cp",
                str(get_users_script),
                f"{pod_name}:/tmp/get_tenant_users.py",
            ],
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        print("  Executing script on pod...")
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "--",
                "python",
                "/tmp/get_tenant_users.py",
                tenant_id,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Show progress messages from stderr
        if result.stderr:
            print(f"  {result.stderr}", end="")

        # Parse JSON result from stdout
        result_data = json.loads(result.stdout)
        status = result_data.get("status")

        if status == "success":
            users = result_data.get("users", [])
            if users:
                print(f"✓ Found {len(users)} user(s):")
                for email in users:
                    print(f"    - {email}")
            else:
                print("  No users found in tenant")
            return users
        else:
            message = result_data.get("message", "Unknown error")
            print(f"⚠ Could not fetch users: {message}")
            return []

    except subprocess.CalledProcessError as e:
        print(f"⚠ Failed to get users for tenant {tenant_id}: {e}")
        if e.stderr:
            print(f"  Error details: {e.stderr}")
        return []
    except Exception as e:
        print(f"⚠ Failed to get users for tenant {tenant_id}: {e}")
        return []


def check_documents_deleted(pod_name: str, tenant_id: str) -> None:
    """Check if all documents and connector credential pairs have been deleted.

    Raises RuntimeError if any ConnectorCredentialPairs or Documents remain.
    """
    print(f"Checking for remaining documents in tenant: {tenant_id}")

    # Get the path to the script
    script_dir = Path(__file__).parent
    check_script = script_dir / "on_pod_scripts" / "check_documents_deleted.py"

    if not check_script.exists():
        raise FileNotFoundError(
            f"check_documents_deleted.py not found at {check_script}"
        )

    try:
        # Copy script to pod
        print("  Copying script to pod...")
        subprocess.run(
            [
                "kubectl",
                "cp",
                str(check_script),
                f"{pod_name}:/tmp/check_documents_deleted.py",
            ],
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        print("  Executing check on pod...")
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "--",
                "python",
                "/tmp/check_documents_deleted.py",
                tenant_id,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Show progress messages from stderr
        if result.stderr:
            print(f"  {result.stderr}", end="")

        # Parse JSON result from stdout
        result_data = json.loads(result.stdout)
        status = result_data.get("status")

        if status == "success":
            message = result_data.get("message")
            print(f"✓ {message}")
        elif status == "not_found":
            message = result_data.get("message", "Schema not found")
            print(f"⚠ {message}")
        else:
            message = result_data.get("message", "Unknown error")
            cc_count = result_data.get("connector_credential_pair_count", 0)
            doc_count = result_data.get("document_count", 0)
            error_details = f"{message}"
            if cc_count > 0 or doc_count > 0:
                error_details += f"\n  ConnectorCredentialPairs: {cc_count}\n  Documents: {doc_count}"
            raise RuntimeError(error_details)

    except subprocess.CalledProcessError as e:
        print(
            f"✗ Failed to check documents for tenant {tenant_id}: {e}",
            file=sys.stderr,
        )
        if e.stderr:
            print(f"  Error details: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        print(
            f"✗ Failed to check documents for tenant {tenant_id}: {e}",
            file=sys.stderr,
        )
        raise


def drop_data_plane_schema(pod_name: str, tenant_id: str) -> None:
    """Drop the PostgreSQL schema for the given tenant by running script on pod."""
    print(f"Dropping data plane schema for tenant: {tenant_id}")

    # Get the path to the cleanup script
    script_dir = Path(__file__).parent
    schema_cleanup_script = script_dir / "on_pod_scripts" / "cleanup_tenant_schema.py"

    if not schema_cleanup_script.exists():
        raise FileNotFoundError(
            f"cleanup_tenant_schema.py not found at {schema_cleanup_script}"
        )

    try:
        # Copy script to pod
        print("  Copying script to pod...")
        subprocess.run(
            [
                "kubectl",
                "cp",
                str(schema_cleanup_script),
                f"{pod_name}:/tmp/cleanup_tenant_schema.py",
            ],
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        print("  Executing schema cleanup on pod...")
        result = subprocess.run(
            [
                "kubectl",
                "exec",
                pod_name,
                "--",
                "python",
                "/tmp/cleanup_tenant_schema.py",
                tenant_id,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Show progress messages from stderr
        if result.stderr:
            print(f"  {result.stderr}", end="")

        # Parse JSON result from stdout
        result_data = json.loads(result.stdout)
        status = result_data.get("status")
        message = result_data.get("message")

        if status == "success":
            print(f"✓ {message}")
        elif status == "not_found":
            print(f"⚠ {message}")
        else:
            print(f"✗ {message}", file=sys.stderr)
            raise RuntimeError(message)

    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to drop schema for tenant {tenant_id}: {e}", file=sys.stderr)
        if e.stderr:
            print(f"  Error details: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"✗ Failed to drop schema for tenant {tenant_id}: {e}", file=sys.stderr)
        raise


def cleanup_control_plane(tenant_id: str, force: bool = False) -> None:
    """
    Clean up control plane data (tenants table, subscription table, etc.)

    Deletes from tables in this order:
    1. tenant_notification (foreign key to tenant)
    2. tenant_config (foreign key to tenant)
    3. subscription (foreign key to tenant)
    4. tenant (primary table)
    """
    print(f"Cleaning up control plane data for tenant: {tenant_id}")

    # Delete in order respecting foreign key constraints
    delete_queries = [
        (
            "tenant_notification",
            "DELETE FROM tenant_notification WHERE tenant_id = '{tenant_id}';",
        ),
        ("tenant_config", "DELETE FROM tenant_config WHERE tenant_id = '{tenant_id}';"),
        ("subscription", "DELETE FROM subscription WHERE tenant_id = '{tenant_id}';"),
        ("tenant", "DELETE FROM tenant WHERE tenant_id = '{tenant_id}';"),
    ]

    try:
        for table_name, query in delete_queries:
            formatted_query = query.format(tenant_id=tenant_id)
            print(f"  Deleting from {table_name}...")

            if not confirm_step(f"Delete from {table_name}?", force):
                print(f"  Skipping deletion from {table_name}")
                continue

            result = execute_control_plane_query(formatted_query)

            if result.stdout:
                # Extract row count from output (e.g., "DELETE 5")
                print(f"    {result.stdout.strip()}")

        print(f"✓ Successfully cleaned up control plane data for tenant: {tenant_id}")

    except subprocess.CalledProcessError as e:
        print(
            f"✗ Failed to clean up control plane for tenant {tenant_id}: {e}",
            file=sys.stderr,
        )
        if e.stderr:
            print(f"  Error details: {e.stderr}", file=sys.stderr)
        raise


def cleanup_tenant(tenant_id: str, pod_name: str, force: bool = False) -> bool:
    """
    Main cleanup function that orchestrates all cleanup steps.

    Args:
        tenant_id: The tenant ID to clean up
        pod_name: The Kubernetes pod name to execute operations on
        force: If True, skip all confirmation prompts

    Returns:
        True if cleanup was performed, False if skipped
    """
    print(f"Starting cleanup for tenant: {tenant_id}")

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
                "This tenant may be active and should not be deleted without careful review."
            )
            print(f"{'=' * 80}\n")

            if force:
                print(f"Skipping cleanup for tenant {tenant_id} in force mode")
                return False

            # Always ask for confirmation if not gated, even in force mode
            response = input(
                "Are you ABSOLUTELY SURE you want to proceed? Type 'yes' to confirm: "
            )
            if response.lower() != "yes":
                print("Cleanup aborted - tenant is not GATED_ACCESS")
                return False
        elif tenant_status == "GATED_ACCESS":
            print("✓ Tenant status is GATED_ACCESS - safe to proceed with cleanup")
        elif tenant_status is None:
            print("⚠️  WARNING: Could not determine tenant status!")

            if force:
                print(f"Skipping cleanup for tenant {tenant_id} in force mode")
                return False

            response = input("Continue anyway? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                print("Cleanup aborted - could not verify tenant status")
                return False
    except Exception as e:
        print(f"⚠️  WARNING: Failed to check tenant status: {e}")

        if force:
            print(f"Skipping cleanup for tenant {tenant_id} in force mode")
            return False

        response = input("Continue anyway? Type 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Cleanup aborted - could not verify tenant status")
            return False
    print(f"{'=' * 80}\n")

    # Fetch tenant users for informational purposes (non-blocking)
    # Skip in force mode as it's only informational
    if not force:
        print(f"\n{'=' * 80}")
        try:
            get_tenant_users(pod_name, tenant_id)
        except Exception as e:
            print(f"⚠ Could not fetch tenant users: {e}")
        print(f"{'=' * 80}\n")

    # Step 1: Make sure all documents are deleted
    print(f"\n{'=' * 80}")
    print("Step 1/3: Checking for remaining ConnectorCredentialPairs and Documents")
    print(f"{'=' * 80}")
    try:
        check_documents_deleted(pod_name, tenant_id)
    except Exception as e:
        print(f"✗ Document check failed: {e}", file=sys.stderr)
        print(
            "\nPlease ensure all ConnectorCredentialPairs and Documents are deleted before running cleanup."
        )
        print(
            "You may need to mark connectors for deletion and wait for cleanup to complete."
        )
        return False
    print(f"{'=' * 80}\n")

    # Step 2: Drop data plane schema
    if confirm_step(
        f"Step 2/3: Drop data plane schema '{tenant_id}' (CASCADE - will delete all tables, functions, etc.)",
        force,
    ):
        try:
            drop_data_plane_schema(pod_name, tenant_id)
        except Exception as e:
            print(f"✗ Failed at schema cleanup step: {e}", file=sys.stderr)
            if not force:
                response = input("Continue with control plane cleanup? (y/n): ")
                if response.lower() != "y":
                    print("Cleanup aborted by user")
                    return False
            else:
                print("[FORCE MODE] Continuing despite schema cleanup failure")
    else:
        print("Step 2 skipped by user")

    # Step 3: Clean up control plane
    if confirm_step(
        "Step 3/3: Delete control plane records (tenant_notification, tenant_config, subscription, tenant)",
        force,
    ):
        try:
            cleanup_control_plane(tenant_id, force)
        except Exception as e:
            print(f"✗ Failed at control plane cleanup step: {e}", file=sys.stderr)
            if not force:
                print("Control plane cleanup failed")
            else:
                print("[FORCE MODE] Control plane cleanup failed but continuing")
    else:
        print("Step 3 skipped by user")
        return False

    print(f"\n{'=' * 80}")
    print(f"✓ Cleanup completed for tenant: {tenant_id}")
    print(f"{'=' * 80}")
    return True


def main() -> None:
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if len(sys.argv) < 2:
        print("Usage: python backend/scripts/cleanup_tenant.py <tenant_id> [--force]")
        print(
            "       python backend/scripts/cleanup_tenant.py --csv <csv_file_path> [--force]"
        )
        print("\nArguments:")
        print(
            "  tenant_id        The tenant ID to clean up (required if not using --csv)"
        )
        print("  --csv PATH       Path to CSV file containing tenant IDs to clean up")
        print("  --force          Skip all confirmation prompts (optional)")
        print("\nExamples:")
        print("  python backend/scripts/cleanup_tenant.py tenant_abc123-def456-789")
        print(
            "  python backend/scripts/cleanup_tenant.py tenant_abc123-def456-789 --force"
        )
        print(
            "  python backend/scripts/cleanup_tenant.py --csv gated_tenants_no_query_3mo.csv"
        )
        print(
            "  python backend/scripts/cleanup_tenant.py --csv gated_tenants_no_query_3mo.csv --force"
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
        print("TENANT CLEANUP - CONFIRMATION REQUIRED")
        print(f"{'=' * 80}")
        if len(tenant_ids) == 1:
            print(f"Tenant ID: {tenant_ids[0]}")
        else:
            print(f"Number of tenants: {len(tenant_ids)}")
            print(f"Tenant IDs: {', '.join(tenant_ids[:5])}")
            if len(tenant_ids) > 5:
                print(f"            ... and {len(tenant_ids) - 5} more")

        print("Index Name: Will be fetched automatically when deleting Vespa documents")
        print(
            f"Mode: {'FORCE (no confirmations)' if force else 'Interactive (will ask for confirmation at each step)'}"
        )
        print("\nThis will:")
        print("  1. Delete ALL Vespa documents for this tenant")
        print("  2. Drop the data plane PostgreSQL schema (CASCADE)")
        print("  3. Clean up control plane data:")
        print("     - Delete from tenant_notification table")
        print("     - Delete from tenant_config table")
        print("     - Delete from subscription table")
        print("     - Delete from tenant table")
        print(f"\n{'=' * 80}")
        print("WARNING: This operation is IRREVERSIBLE!")
        print(f"{'=' * 80}\n")

        response = input("Are you sure you want to proceed? Type 'yes' to confirm: ")

        if response.lower() != "yes":
            print("Cleanup aborted by user")
            sys.exit(0)
    else:
        if len(tenant_ids) == 1:
            print(
                f"⚠ FORCE MODE: Running cleanup for {tenant_ids[0]} without confirmations"
            )
        else:
            print(
                f"⚠ FORCE MODE: Running cleanup for {len(tenant_ids)} tenants without confirmations"
            )

    # Find heavy worker pod once for all tenants
    try:
        pod_name = find_worker_pod()
        print(f"✓ Found worker pod: {pod_name}\n")
    except Exception as e:
        print(f"✗ Failed to find heavy worker pod: {e}", file=sys.stderr)
        print("Cannot proceed with cleanup")
        sys.exit(1)

    # Run cleanup for each tenant
    failed_tenants = []
    successful_tenants = []
    skipped_tenants = []

    # Open CSV file for writing successful cleanups in real-time
    csv_output_path = "cleaned_tenants.csv"
    with open(csv_output_path, "w", newline="") as csv_file:
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["tenant_id", "cleaned_at"])
        csv_file.flush()  # Ensure header is written immediately

        print(f"Writing successful cleanups to: {csv_output_path}\n")

        for idx, tenant_id in enumerate(tenant_ids, 1):
            if len(tenant_ids) > 1:
                print(f"\n{'=' * 80}")
                print(f"Processing tenant {idx}/{len(tenant_ids)}: {tenant_id}")
                print(f"{'=' * 80}")

            try:
                was_cleaned = cleanup_tenant(tenant_id, pod_name, force)

                if was_cleaned:
                    # Only record if actually cleaned up (not skipped)
                    successful_tenants.append(tenant_id)

                    # Write to CSV immediately after successful cleanup
                    timestamp = datetime.utcnow().isoformat()
                    csv_writer.writerow([tenant_id, timestamp])
                    csv_file.flush()  # Ensure real-time write
                    print(f"✓ Recorded cleanup in {csv_output_path}")
                else:
                    skipped_tenants.append(tenant_id)
                    print(f"⚠ Tenant {tenant_id} was skipped (not recorded in CSV)")

            except Exception as e:
                print(f"✗ Cleanup failed for tenant {tenant_id}: {e}", file=sys.stderr)
                failed_tenants.append((tenant_id, str(e)))

                # If not in force mode and there are more tenants, ask if we should continue
                if not force and idx < len(tenant_ids):
                    response = input(
                        f"\nContinue with remaining {len(tenant_ids) - idx} tenant(s)? (y/n): "
                    )
                    if response.lower() != "y":
                        print("Cleanup aborted by user")
                        break

    # Print summary
    if len(tenant_ids) == 1:
        if successful_tenants:
            print(f"\n✓ Successfully cleaned tenant written to: {csv_output_path}")
        elif skipped_tenants:
            print("\n⚠ Tenant was skipped")
    elif len(tenant_ids) > 1:
        print(f"\n{'=' * 80}")
        print("CLEANUP SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total tenants: {len(tenant_ids)}")
        print(f"Successful: {len(successful_tenants)}")
        print(f"Skipped: {len(skipped_tenants)}")
        print(f"Failed: {len(failed_tenants)}")
        print(f"\nSuccessfully cleaned tenants written to: {csv_output_path}")

        if skipped_tenants:
            print(f"\nSkipped tenants ({len(skipped_tenants)}):")
            for tenant_id in skipped_tenants:
                print(f"  - {tenant_id}")

        if failed_tenants:
            print(f"\nFailed tenants ({len(failed_tenants)}):")
            for tenant_id, error in failed_tenants:
                print(f"  - {tenant_id}: {error}")

        print(f"{'=' * 80}")

        if failed_tenants:
            sys.exit(1)


if __name__ == "__main__":
    main()
