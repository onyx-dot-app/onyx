#!/usr/bin/env python3
"""
Mark connectors for deletion script that works WITHOUT bastion access.
All queries run directly from pods.
Supports two-cluster architecture (data plane and control plane in separate clusters).

Usage:
    PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_mark_connectors.py <tenant_id> \
        --data-plane-context <context> --control-plane-context <context> [--force]

    PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_mark_connectors.py --csv <csv_file_path> \
        --data-plane-context <context> --control-plane-context <context> [--force] [--concurrency N]
"""

import subprocess
import sys
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

from scripts.tenant_cleanup.no_bastion_cleanup_utils import confirm_step
from scripts.tenant_cleanup.no_bastion_cleanup_utils import find_background_pod
from scripts.tenant_cleanup.no_bastion_cleanup_utils import find_worker_pod
from scripts.tenant_cleanup.no_bastion_cleanup_utils import get_tenant_status
from scripts.tenant_cleanup.no_bastion_cleanup_utils import read_tenant_ids_from_csv
from scripts.tenant_cleanup.no_bastion_cleanup_utils import (
    TenantNotFoundInControlPlaneError,
)

# Global lock for thread-safe printing
_print_lock: Lock = Lock()


def safe_print(*args: Any, **kwargs: Any) -> None:
    """Thread-safe print function."""
    with _print_lock:
        print(*args, **kwargs)


def run_connector_deletion(pod_name: str, tenant_id: str, context: str) -> None:
    """Mark all connector credential pairs for deletion.

    Args:
        pod_name: Data plane pod to execute deletion on
        tenant_id: Tenant ID to process
        context: kubectl context for data plane cluster
    """
    safe_print("  Marking all connector credential pairs for deletion...")

    # Get the path to the script
    script_dir = Path(__file__).parent
    mark_deletion_script = (
        script_dir / "on_pod_scripts" / "execute_connector_deletion.py"
    )

    if not mark_deletion_script.exists():
        raise FileNotFoundError(
            f"execute_connector_deletion.py not found at {mark_deletion_script}"
        )

    try:
        # Copy script to pod
        cmd_cp = ["kubectl", "cp", "--context", context]
        cmd_cp.extend(
            [
                str(mark_deletion_script),
                f"{pod_name}:/tmp/execute_connector_deletion.py",
            ]
        )

        subprocess.run(
            cmd_cp,
            check=True,
            capture_output=True,
        )

        # Execute script on pod
        cmd_exec = ["kubectl", "exec", "--context", context, pod_name]
        cmd_exec.extend(
            [
                "--",
                "python",
                "/tmp/execute_connector_deletion.py",
                tenant_id,
                "--all",
            ]
        )

        result = subprocess.run(cmd_exec)

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

    except subprocess.CalledProcessError as e:
        safe_print(
            f"  ✗ Failed to mark all connector credential pairs for deletion: {e}",
            file=sys.stderr,
        )
        if e.stderr:
            safe_print(f"    Error details: {e.stderr}", file=sys.stderr)
        raise
    except Exception as e:
        safe_print(
            f"  ✗ Failed to mark all connector credential pairs for deletion: {e}",
            file=sys.stderr,
        )
        raise


def mark_tenant_connectors_for_deletion(
    tenant_id: str,
    data_plane_pod: str,
    control_plane_pod: str,
    data_plane_context: str,
    control_plane_context: str,
    force: bool = False,
) -> None:
    """Main function to mark all connectors for a tenant for deletion.

    Args:
        tenant_id: Tenant ID to process
        data_plane_pod: Data plane pod for connector operations
        control_plane_pod: Control plane pod for status checks
        data_plane_context: kubectl context for data plane cluster
        control_plane_context: kubectl context for control plane cluster
        force: Skip confirmations if True
    """
    safe_print(f"Processing connectors for tenant: {tenant_id}")

    # Check tenant status first (from control plane)
    safe_print(f"\n{'=' * 80}")
    try:
        tenant_status = get_tenant_status(
            control_plane_pod, tenant_id, control_plane_context
        )

        # If tenant is not GATED_ACCESS, require explicit confirmation even in force mode
        if tenant_status and tenant_status != "GATED_ACCESS":
            safe_print(
                f"\n⚠️  WARNING: Tenant status is '{tenant_status}', not 'GATED_ACCESS'!"
            )
            safe_print(
                "This tenant may be active and should not have connectors deleted without careful review."
            )
            safe_print(f"{'=' * 80}\n")

            # Always ask for confirmation if not gated, even in force mode
            if not force:
                response = input(
                    "Are you ABSOLUTELY SURE you want to proceed? Type 'yes' to confirm: "
                )
                if response.lower() != "yes":
                    safe_print("Operation aborted - tenant is not GATED_ACCESS")
                    raise RuntimeError(f"Tenant {tenant_id} is not GATED_ACCESS")
            else:
                raise RuntimeError(f"Tenant {tenant_id} is not GATED_ACCESS")
        elif tenant_status == "GATED_ACCESS":
            safe_print("✓ Tenant status is GATED_ACCESS - safe to proceed")
        elif tenant_status is None:
            safe_print("⚠️  WARNING: Could not determine tenant status!")
            if not force:
                response = input("Continue anyway? Type 'yes' to confirm: ")
                if response.lower() != "yes":
                    safe_print("Operation aborted - could not verify tenant status")
                    raise RuntimeError(
                        f"Could not verify tenant status for {tenant_id}"
                    )
            else:
                raise RuntimeError(f"Could not verify tenant status for {tenant_id}")
    except TenantNotFoundInControlPlaneError as e:
        # Tenant/table not found in control plane
        error_str = str(e)
        safe_print(f"⚠️  WARNING: Tenant not found in control plane: {error_str}")

        if force:
            safe_print(
                "[FORCE MODE] Tenant not found in control plane - continuing with connector deletion anyway"
            )
        else:
            response = input("Continue anyway? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                safe_print("Operation aborted - tenant not found in control plane")
                raise RuntimeError(f"Tenant {tenant_id} not found in control plane")
    except RuntimeError:
        # Re-raise RuntimeError (from status checks above) without wrapping
        raise
    except Exception as e:
        safe_print(f"⚠️  WARNING: Failed to check tenant status: {e}")
        if not force:
            response = input("Continue anyway? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                safe_print("Operation aborted - could not verify tenant status")
                raise
        else:
            raise RuntimeError(f"Failed to check tenant status for {tenant_id}")
    safe_print(f"{'=' * 80}\n")

    # Confirm before proceeding (only in non-force mode)
    if not confirm_step(
        f"Mark all connector credential pairs for deletion for tenant {tenant_id}?",
        force,
    ):
        safe_print("Operation cancelled by user")
        raise ValueError("Operation cancelled by user")

    run_connector_deletion(data_plane_pod, tenant_id, data_plane_context)

    # Print summary
    safe_print(
        f"✓ Marked all connector credential pairs for deletion for tenant {tenant_id}"
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: PYTHONPATH=. python scripts/tenant_cleanup/"
            "no_bastion_mark_connectors.py <tenant_id> \\"
        )
        print(
            "           --data-plane-context <context> --control-plane-context <context> [--force]"
        )
        print(
            "       PYTHONPATH=. python scripts/tenant_cleanup/"
            "no_bastion_mark_connectors.py --csv <csv_file_path> \\"
        )
        print(
            "           --data-plane-context <context> --control-plane-context <context> [--force] [--concurrency N]"
        )
        print("\nThis version runs ALL operations from pods (no bastion required)")
        print("\nArguments:")
        print(
            "  tenant_id                   The tenant ID to process (required if not using --csv)"
        )
        print(
            "  --csv PATH                  Path to CSV file containing tenant IDs to process"
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
    tenant_ids: list[str] = []

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

    # Check for CSV mode
    if "--csv" in sys.argv:
        try:
            csv_index: int = sys.argv.index("--csv")
            if csv_index + 1 >= len(sys.argv):
                print("Error: --csv flag requires a file path", file=sys.stderr)
                sys.exit(1)

            csv_path: str = sys.argv[csv_index + 1]
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

    # Find pods in both clusters before processing
    try:
        print("Finding data plane worker pod...")
        data_plane_pod: str = find_worker_pod(data_plane_context)
        print(f"✓ Using data plane worker pod: {data_plane_pod}")

        print("Finding control plane pod...")
        control_plane_pod: str = find_background_pod(control_plane_context)
        print(f"✓ Using control plane pod: {control_plane_pod}")
    except Exception as e:
        print(f"✗ Failed to find required pods: {e}", file=sys.stderr)
        print("Cannot proceed with marking connectors for deletion")
        sys.exit(1)

    # Initial confirmation (unless --force is used)
    if not force:
        print(f"\n{'=' * 80}")
        print("MARK CONNECTORS FOR DELETION - NO BASTION VERSION")
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
        print(f"Concurrency: {concurrency} tenant(s) at a time")
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
                f"⚠ FORCE MODE: Marking connectors for deletion for {len(tenant_ids)} tenants "
                f"(concurrency: {concurrency}) without confirmations"
            )

    # Process tenants (in parallel if concurrency > 1)
    failed_tenants: list[tuple[str, str]] = []
    successful_tenants: list[str] = []

    if concurrency == 1:
        # Sequential processing
        for idx, tenant_id in enumerate(tenant_ids, 1):
            if len(tenant_ids) > 1:
                print(f"\n{'=' * 80}")
                print(f"Processing tenant {idx}/{len(tenant_ids)}: {tenant_id}")
                print(f"{'=' * 80}")

            try:
                mark_tenant_connectors_for_deletion(
                    tenant_id,
                    data_plane_pod,
                    control_plane_pod,
                    data_plane_context,
                    control_plane_context,
                    force,
                )
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
    else:
        # Parallel processing
        print(
            f"\nProcessing {len(tenant_ids)} tenant(s) with concurrency={concurrency}"
        )

        def process_tenant(tenant_id: str) -> tuple[str, bool, str | None]:
            """Process a single tenant. Returns (tenant_id, success, error_message)."""
            try:
                mark_tenant_connectors_for_deletion(
                    tenant_id,
                    data_plane_pod,
                    control_plane_pod,
                    data_plane_context,
                    control_plane_context,
                    force,
                )
                return (tenant_id, True, None)
            except Exception as e:
                return (tenant_id, False, str(e))

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            # Submit all tasks
            future_to_tenant = {
                executor.submit(process_tenant, tenant_id): tenant_id
                for tenant_id in tenant_ids
            }

            # Process results as they complete
            completed: int = 0
            for future in as_completed(future_to_tenant):
                completed += 1
                tenant_id, success, error = future.result()

                if success:
                    successful_tenants.append(tenant_id)
                    safe_print(
                        f"[{completed}/{len(tenant_ids)}] ✓ Successfully processed {tenant_id}"
                    )
                else:
                    failed_tenants.append((tenant_id, error or "Unknown error"))
                    safe_print(
                        f"[{completed}/{len(tenant_ids)}] ✗ Failed to process {tenant_id}: {error}",
                        file=sys.stderr,
                    )

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
