#!/usr/bin/env python3
"""
Tenant cleanup script that works WITHOUT bastion access.
All queries run directly from pods.
Supports two-cluster architecture (data plane and control plane in separate clusters).

Usage:
    PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_cleanup_tenants.py <tenant_id> \
        --data-plane-context <context> --control-plane-context <context> [--force]

    PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_cleanup_tenants.py --csv <csv_file_path> \
        --data-plane-context <context> --control-plane-context <context> [--force]
"""

import csv
import json
import signal
import subprocess
import sys
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock

from scripts.tenant_cleanup.no_bastion_cleanup_utils import confirm_step
from scripts.tenant_cleanup.no_bastion_cleanup_utils import execute_control_plane_delete
from scripts.tenant_cleanup.no_bastion_cleanup_utils import find_background_pod
from scripts.tenant_cleanup.no_bastion_cleanup_utils import find_worker_pod
from scripts.tenant_cleanup.no_bastion_cleanup_utils import get_tenant_status
from scripts.tenant_cleanup.no_bastion_cleanup_utils import read_tenant_ids_from_csv
from scripts.tenant_cleanup.no_bastion_cleanup_utils import (
    TenantNotFoundInControlPlaneError,
)


# Global lock for thread-safe operations
_print_lock: Lock = Lock()
_csv_lock: Lock = Lock()


def signal_handler(signum: int, frame: object) -> None:
    """Handle termination signals by killing active subprocess."""
    sys.exit(1)


def setup_scripts_on_pod(pod_name: str, context: str) -> None:
    """Copy all required scripts to the pod once at the beginning.

    Args:
        pod_name: Pod to copy scripts to
        context: kubectl context for the cluster
    """
    print("Setting up scripts on pod (one-time operation)...")

    script_dir = Path(__file__).parent
    scripts_to_copy = [
        (
            "on_pod_scripts/check_documents_deleted.py",
            "/tmp/check_documents_deleted.py",
        ),
        ("on_pod_scripts/cleanup_tenant_schema.py", "/tmp/cleanup_tenant_schema.py"),
        ("on_pod_scripts/get_tenant_users.py", "/tmp/get_tenant_users.py"),
        ("on_pod_scripts/get_tenant_index_name.py", "/tmp/get_tenant_index_name.py"),
    ]

    for local_path, remote_path in scripts_to_copy:
        local_file = script_dir / local_path
        if not local_file.exists():
            raise FileNotFoundError(f"Script not found: {local_file}")

        cmd_cp = ["kubectl", "cp", "--context", context]
        cmd_cp.extend([str(local_file), f"{pod_name}:{remote_path}"])

        subprocess.run(cmd_cp, check=True, capture_output=True)

    print("✓ All scripts copied to pod")


def get_tenant_index_name(pod_name: str, tenant_id: str, context: str) -> str:
    """Get the default index name for the given tenant by running script on pod.

    Args:
        pod_name: Data plane pod to execute on
        tenant_id: Tenant ID to process
        context: kubectl context for data plane cluster
    """
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
        cmd_cp = ["kubectl", "cp", "--context", context]
        cmd_cp.extend(
            [
                str(index_name_script),
                f"{pod_name}:/tmp/get_tenant_index_name.py",
            ]
        )

        subprocess.run(
            cmd_cp,
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        print("  Executing script on pod...")
        cmd_exec = ["kubectl", "exec", "--context", context, pod_name]
        cmd_exec.extend(
            [
                "--",
                "python",
                "/tmp/get_tenant_index_name.py",
                tenant_id,
            ]
        )

        result = subprocess.run(
            cmd_exec,
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


def get_tenant_users(pod_name: str, tenant_id: str, context: str) -> list[str]:
    """Get list of user emails from the tenant's data plane schema.

    Args:
        pod_name: Data plane pod to execute on
        tenant_id: Tenant ID to process
        context: kubectl context for data plane cluster
    """
    # Script is already on pod from setup_scripts_on_pod()
    try:
        # Execute script on pod
        cmd_exec = ["kubectl", "exec", "--context", context, pod_name]
        cmd_exec.extend(
            [
                "--",
                "python",
                "/tmp/get_tenant_users.py",
                tenant_id,
            ]
        )

        result = subprocess.run(
            cmd_exec,
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


def check_documents_deleted(pod_name: str, tenant_id: str, context: str) -> None:
    """Check if all documents and connector credential pairs have been deleted.

    Args:
        pod_name: Data plane pod to execute on
        tenant_id: Tenant ID to process
        context: kubectl context for data plane cluster
    """
    # Script is already on pod from setup_scripts_on_pod()
    try:
        # Execute script on pod
        cmd_exec = ["kubectl", "exec", "--context", context, pod_name]
        cmd_exec.extend(
            [
                "--",
                "python",
                "/tmp/check_documents_deleted.py",
                tenant_id,
            ]
        )

        result = subprocess.run(
            cmd_exec,
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


def drop_data_plane_schema(pod_name: str, tenant_id: str, context: str) -> None:
    """Drop the PostgreSQL schema for the given tenant by running script on pod.

    Args:
        pod_name: Data plane pod to execute on
        tenant_id: Tenant ID to process
        context: kubectl context for data plane cluster
    """
    # Script is already on pod from setup_scripts_on_pod()
    try:
        # Execute script on pod
        cmd_exec = ["kubectl", "exec", "--context", context, pod_name]
        cmd_exec.extend(
            [
                "--",
                "python",
                "/tmp/cleanup_tenant_schema.py",
                tenant_id,
            ]
        )

        result = subprocess.run(
            cmd_exec,
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


def cleanup_control_plane(
    pod_name: str, tenant_id: str, context: str, force: bool = False
) -> None:
    """Clean up control plane data via pod queries.

    Args:
        pod_name: Control plane pod to execute on
        tenant_id: Tenant ID to process
        context: kubectl context for control plane cluster
        force: Skip confirmations if True
    """
    print(f"Cleaning up control plane data for tenant: {tenant_id}")

    # Delete in order respecting foreign key constraints
    delete_queries = [
        (
            "tenant_notification",
            f"DELETE FROM tenant_notification WHERE tenant_id = '{tenant_id}'",
        ),
        ("tenant_config", f"DELETE FROM tenant_config WHERE tenant_id = '{tenant_id}'"),
        ("subscription", f"DELETE FROM subscription WHERE tenant_id = '{tenant_id}'"),
        ("tenant", f"DELETE FROM tenant WHERE tenant_id = '{tenant_id}'"),
    ]

    try:
        for table_name, query in delete_queries:
            print(f"  Deleting from {table_name}...")

            if not confirm_step(f"Delete from {table_name}?", force):
                print(f"  Skipping deletion from {table_name}")
                continue

            execute_control_plane_delete(pod_name, query, context)

        print(f"✓ Successfully cleaned up control plane data for tenant: {tenant_id}")

    except Exception as e:
        print(
            f"✗ Failed to clean up control plane for tenant {tenant_id}: {e}",
            file=sys.stderr,
        )
        raise


def cleanup_tenant(
    tenant_id: str,
    data_plane_pod: str,
    control_plane_pod: str,
    data_plane_context: str,
    control_plane_context: str,
    force: bool = False,
) -> bool:
    """Main cleanup function that orchestrates all cleanup steps.

    Args:
        tenant_id: Tenant ID to process
        data_plane_pod: Data plane pod for schema operations
        control_plane_pod: Control plane pod for tenant record operations
        data_plane_context: kubectl context for data plane cluster
        control_plane_context: kubectl context for control plane cluster
        force: Skip confirmations if True
    """
    print(f"Starting cleanup for tenant: {tenant_id}")

    # Track if tenant was not found in control plane (for force mode)
    tenant_not_found_in_control_plane = False

    # Check tenant status first (from control plane)
    print(f"\n{'=' * 80}")
    try:
        tenant_status = get_tenant_status(
            control_plane_pod, tenant_id, control_plane_context
        )

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

            # Always ask for confirmation if not gated
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
    except TenantNotFoundInControlPlaneError as e:
        # Tenant/table not found in control plane
        error_str = str(e)
        print(f"⚠️  WARNING: Tenant not found in control plane: {error_str}")
        tenant_not_found_in_control_plane = True

        if force:
            print(
                "[FORCE MODE] Tenant not found in control plane - continuing with dataplane cleanup only"
            )
        else:
            response = input("Continue anyway? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                print("Cleanup aborted - tenant not found in control plane")
                return False
    except Exception as e:
        # Other errors (not "not found")
        error_str = str(e)
        print(f"⚠️  WARNING: Failed to check tenant status: {error_str}")

        if force:
            print(f"Skipping cleanup for tenant {tenant_id} in force mode")
            return False

        response = input("Continue anyway? Type 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Cleanup aborted - could not verify tenant status")
            return False
    print(f"{'=' * 80}\n")

    # Fetch tenant users for informational purposes (non-blocking) from data plane
    if not force:
        print(f"\n{'=' * 80}")
        try:
            get_tenant_users(data_plane_pod, tenant_id, data_plane_context)
        except Exception as e:
            print(f"⚠ Could not fetch tenant users: {e}")
        print(f"{'=' * 80}\n")

    # Step 1: Make sure all documents are deleted (data plane)
    print(f"\n{'=' * 80}")
    print("Step 1/3: Checking for remaining ConnectorCredentialPairs and Documents")
    print(f"{'=' * 80}")
    try:
        check_documents_deleted(data_plane_pod, tenant_id, data_plane_context)
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
            drop_data_plane_schema(data_plane_pod, tenant_id, data_plane_context)
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

    # Step 3: Clean up control plane (skip if tenant not found in control plane with --force)
    if tenant_not_found_in_control_plane:
        print(f"\n{'=' * 80}")
        print(
            "Step 3/3: Skipping control plane cleanup (tenant not found in control plane)"
        )
        print(f"{'=' * 80}\n")
    elif confirm_step(
        "Step 3/3: Delete control plane records (tenant_notification, tenant_config, subscription, tenant)",
        force,
    ):
        try:
            cleanup_control_plane(
                control_plane_pod, tenant_id, control_plane_context, force
            )
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
        print(
            "Usage: PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_cleanup_tenants.py <tenant_id> \\"
        )
        print(
            "           --data-plane-context <context> --control-plane-context <context> [--force]"
        )
        print(
            "       PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_cleanup_tenants.py --csv <csv_file_path> \\"
        )
        print(
            "           --data-plane-context <context> --control-plane-context <context> [--force]"
        )
        print("\nThis version runs ALL operations from pods (no bastion required)")
        print("\nArguments:")
        print(
            "  tenant_id                   The tenant ID to clean up (required if not using --csv)"
        )
        print(
            "  --csv PATH                  Path to CSV file containing tenant IDs to clean up"
        )
        print("  --force                     Skip all confirmation prompts (optional)")
        print(
            "  --concurrency N             Process N tenants concurrently (default: 1)"
        )
        print(
            "  --data-plane-context CTX    Kubectl context for data plane cluster (required)"
        )
        print(
            "  --control-plane-context CTX Kubectl context for control plane cluster (required)"
        )
        sys.exit(1)

    # Parse arguments
    force = "--force" in sys.argv
    tenant_ids = []

    # Parse concurrency
    concurrency: int = 1
    if "--concurrency" in sys.argv:
        try:
            concurrency_index = sys.argv.index("--concurrency")
            if concurrency_index + 1 >= len(sys.argv):
                print("Error: --concurrency flag requires a number", file=sys.stderr)
                sys.exit(1)
            concurrency = int(sys.argv[concurrency_index + 1])
            if concurrency < 1:
                print("Error: concurrency must be at least 1", file=sys.stderr)
                sys.exit(1)
        except ValueError:
            print("Error: --concurrency value must be an integer", file=sys.stderr)
            sys.exit(1)

    # Validate: concurrency > 1 requires --force
    if concurrency > 1 and not force:
        print(
            "Error: --concurrency > 1 requires --force flag (interactive mode not supported with parallel processing)",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse contexts (required)
    data_plane_context: str | None = None
    control_plane_context: str | None = None

    if "--data-plane-context" in sys.argv:
        try:
            idx = sys.argv.index("--data-plane-context")
            if idx + 1 >= len(sys.argv):
                print(
                    "Error: --data-plane-context requires a context name",
                    file=sys.stderr,
                )
                sys.exit(1)
            data_plane_context = sys.argv[idx + 1]
        except ValueError:
            pass

    if "--control-plane-context" in sys.argv:
        try:
            idx = sys.argv.index("--control-plane-context")
            if idx + 1 >= len(sys.argv):
                print(
                    "Error: --control-plane-context requires a context name",
                    file=sys.stderr,
                )
                sys.exit(1)
            control_plane_context = sys.argv[idx + 1]
        except ValueError:
            pass

    # Validate required contexts
    if not data_plane_context:
        print(
            "Error: --data-plane-context is required",
            file=sys.stderr,
        )
        sys.exit(1)

    if not control_plane_context:
        print(
            "Error: --control-plane-context is required",
            file=sys.stderr,
        )
        sys.exit(1)

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
        print("TENANT CLEANUP - NO BASTION VERSION")
        print(f"{'=' * 80}")
        if len(tenant_ids) == 1:
            print(f"Tenant ID: {tenant_ids[0]}")
        else:
            print(f"Number of tenants: {len(tenant_ids)}")
            print(f"Tenant IDs: {', '.join(tenant_ids[:5])}")
            if len(tenant_ids) > 5:
                print(f"            ... and {len(tenant_ids) - 5} more")

        print("\nThis will:")
        print("  1. Check for remaining documents and connector credential pairs")
        print("  2. Drop the data plane PostgreSQL schema (CASCADE)")
        print("  3. Clean up control plane data (all via pod queries)")
        print(f"\n{'=' * 80}")
        print("WARNING: This operation is IRREVERSIBLE!")
        print(f"{'=' * 80}\n")

        response = input("Are you sure you want to proceed? Type 'yes' to confirm: ")

        if response.lower() != "yes":
            print("Cleanup aborted by user")
            sys.exit(0)
    else:
        print(
            f"⚠ FORCE MODE: Running cleanup for {len(tenant_ids)} tenant(s) without confirmations"
        )

    # Find pods in both clusters before processing
    try:
        print("Finding data plane worker pod...")
        data_plane_pod = find_worker_pod(data_plane_context)
        print(f"✓ Using data plane worker pod: {data_plane_pod}")

        print("Finding control plane pod...")
        control_plane_pod = find_background_pod(control_plane_context)
        print(f"✓ Using control plane pod: {control_plane_pod}\n")

        # Copy all scripts to data plane pod once
        setup_scripts_on_pod(data_plane_pod, data_plane_context)
        print()
    except Exception as e:
        print(f"✗ Failed to find required pods or setup scripts: {e}", file=sys.stderr)
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
        csv_file.flush()

        print(f"Writing successful cleanups to: {csv_output_path}\n")

        if concurrency == 1:
            # Sequential processing
            for idx, tenant_id in enumerate(tenant_ids, 1):
                if len(tenant_ids) > 1:
                    print(f"\n{'=' * 80}")
                    print(f"Processing tenant {idx}/{len(tenant_ids)}: {tenant_id}")
                    print(f"{'=' * 80}")

                try:
                    was_cleaned = cleanup_tenant(
                        tenant_id,
                        data_plane_pod,
                        control_plane_pod,
                        data_plane_context,
                        control_plane_context,
                        force,
                    )

                    if was_cleaned:
                        successful_tenants.append(tenant_id)

                        # Write to CSV immediately after successful cleanup
                        timestamp = datetime.utcnow().isoformat()
                        csv_writer.writerow([tenant_id, timestamp])
                        csv_file.flush()
                        print(f"✓ Recorded cleanup in {csv_output_path}")
                    else:
                        skipped_tenants.append(tenant_id)
                        print(f"⚠ Tenant {tenant_id} was skipped (not recorded in CSV)")

                except Exception as e:
                    print(
                        f"✗ Cleanup failed for tenant {tenant_id}: {e}", file=sys.stderr
                    )
                    failed_tenants.append((tenant_id, str(e)))

                    # If not in force mode and there are more tenants, ask if we should continue
                    if not force and idx < len(tenant_ids):
                        response = input(
                            f"\nContinue with remaining {len(tenant_ids) - idx} tenant(s)? (y/n): "
                        )
                        if response.lower() != "y":
                            print("Cleanup aborted by user")
                            break
        else:
            # Parallel processing
            print(
                f"Processing {len(tenant_ids)} tenant(s) with concurrency={concurrency}\n"
            )

            def process_tenant(tenant_id: str) -> tuple[str, bool, str | None]:
                """Process a single tenant. Returns (tenant_id, was_cleaned, error_message)."""
                try:
                    was_cleaned = cleanup_tenant(
                        tenant_id,
                        data_plane_pod,
                        control_plane_pod,
                        data_plane_context,
                        control_plane_context,
                        force,
                    )
                    return (tenant_id, was_cleaned, None)
                except Exception as e:
                    return (tenant_id, False, str(e))

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                # Submit all tasks
                future_to_tenant = {
                    executor.submit(process_tenant, tenant_id): tenant_id
                    for tenant_id in tenant_ids
                }

                # Process results as they complete
                completed = 0
                for future in as_completed(future_to_tenant):
                    completed += 1
                    tenant_id, was_cleaned, error = future.result()

                    if error:
                        with _print_lock:
                            print(
                                f"[{completed}/{len(tenant_ids)}] ✗ Failed: {tenant_id}: {error}",
                                file=sys.stderr,
                            )
                        failed_tenants.append((tenant_id, error))
                    elif was_cleaned:
                        with _csv_lock:
                            timestamp = datetime.utcnow().isoformat()
                            csv_writer.writerow([tenant_id, timestamp])
                            csv_file.flush()
                        successful_tenants.append(tenant_id)
                        with _print_lock:
                            print(
                                f"[{completed}/{len(tenant_ids)}] ✓ Cleaned: {tenant_id}"
                            )
                    else:
                        skipped_tenants.append(tenant_id)
                        with _print_lock:
                            print(
                                f"[{completed}/{len(tenant_ids)}] ⊘ Skipped: {tenant_id}"
                            )

    # Print summary
    if len(tenant_ids) > 1:
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
