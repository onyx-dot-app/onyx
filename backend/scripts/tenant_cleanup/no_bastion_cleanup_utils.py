"""
Cleanup utilities that work WITHOUT bastion access.
Control plane and data plane are in SEPARATE clusters.
"""

import csv
import json
import subprocess
import sys
from pathlib import Path


class TenantNotFoundInControlPlaneError(Exception):
    """Exception raised when tenant/table is not found in control plane."""


def find_worker_pod(context: str) -> str:
    """Find a user file processing worker pod using kubectl.

    Args:
        context: kubectl context to use
    """
    print(f"Finding user file processing worker pod in context {context}...")

    cmd = ["kubectl", "get", "po", "--context", context]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    # Parse output and find user file processing worker pod
    lines = result.stdout.strip().split("\n")
    lines = lines[1:]  # Skip header

    import random

    random.shuffle(lines)

    for line in lines:
        if "celery-worker-user-file-processing" in line and "Running" in line:
            pod_name = line.split()[0]
            print(f"Found pod: {pod_name}")
            return pod_name

    raise RuntimeError("No running user file processing worker pod found")


def find_background_pod(context: str) -> str:
    """Find a pod for control plane operations.

    Args:
        context: kubectl context to use
    """
    print(f"Finding control plane pod in context {context}...")

    cmd = ["kubectl", "get", "po", "--context", context]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    # Parse output and find suitable pod
    lines = result.stdout.strip().split("\n")
    lines = lines[1:]  # Skip header

    import random

    random.shuffle(lines)

    # Try to find control plane pods
    for line in lines:
        if (
            any(
                name in line
                for name in [
                    "background-processing-deployment",
                    "subscription-deployment",
                    "tenants-deployment",
                ]
            )
            and "Running" in line
        ):
            pod_name = line.split()[0]
            print(f"Found pod: {pod_name}")
            return pod_name

    raise RuntimeError("No suitable background pod found for control plane operations")


def confirm_step(message: str, force: bool = False) -> bool:
    """Ask for confirmation before executing a step.

    Args:
        message: The confirmation message to display
        force: If True, skip confirmation and return True

    Returns:
        True if user confirms or force is True, False otherwise
    """
    if force:
        print(f"[FORCE MODE] Skipping confirmation: {message}")
        return True

    print(f"\n{message}")
    response = input("Proceed? (y/n): ")
    return response.lower() == "y"


def execute_control_plane_query_from_pod(
    pod_name: str, query: str, context: str
) -> dict:
    """Execute a SQL query against control plane database from within a pod.

    Args:
        pod_name: The Kubernetes pod name to execute from
        query: The SQL query to execute
        context: kubectl context for control plane cluster

    Returns:
        Dict with 'success' bool, 'stdout' str, and optional 'error' str
    """
    # Create a Python script to run the query
    # This script tries multiple environment variable patterns

    # NOTE: whuang 01/08/2026: POSTGRES_CONTROL_* don't exist. This uses pattern 2 currently.

    query_script = f'''
import os
from sqlalchemy import create_engine, text

# Try to get control plane database URL from various environment patterns
control_db_url = None

# Pattern 1: POSTGRES_CONTROL_* variables
if os.environ.get("POSTGRES_CONTROL_HOST"):
    host = os.environ.get("POSTGRES_CONTROL_HOST")
    port = os.environ.get("POSTGRES_CONTROL_PORT", "5432")
    db = os.environ.get("POSTGRES_CONTROL_DB", "control")
    user = os.environ.get("POSTGRES_CONTROL_USER", "postgres")
    password = os.environ.get("POSTGRES_CONTROL_PASSWORD", "")
    if password:
        control_db_url = f"postgresql://{{user}}:{{password}}@{{host}}:{{port}}/{{db}}"

# Pattern 2: Standard POSTGRES_* variables (might point to control plane in this cluster)
if not control_db_url and os.environ.get("POSTGRES_HOST"):
    host = os.environ.get("POSTGRES_HOST")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "danswer")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if password:
        control_db_url = f"postgresql://{{user}}:{{password}}@{{host}}:{{port}}/{{db}}"

# Pattern 3: Direct URI
if not control_db_url:
    control_db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URI")

if not control_db_url:
    raise ValueError("Cannot determine control plane database connection. No suitable environment variables found.")

engine = create_engine(control_db_url)

with engine.connect() as conn:
    result = conn.execute(text("""{query}"""))

    # Check if this is a SELECT query
    if result.returns_rows:
        rows = [dict(row._mapping) for row in result]
        import json
        print(json.dumps(rows, default=str))
    else:
        # For INSERT/UPDATE/DELETE, print rowcount
        print(f"{{result.rowcount}} rows affected")

    conn.commit()
'''

    # Write the script to a temp file on the pod
    script_path = "/tmp/control_plane_query.py"

    try:
        cmd_write = ["kubectl", "exec", "--context", context, pod_name]
        cmd_write.extend(
            [
                "--",
                "bash",
                "-c",
                f"cat > {script_path} << 'EOFQUERY'\n{query_script}\nEOFQUERY",
            ]
        )

        subprocess.run(
            cmd_write,
            check=True,
            capture_output=True,
        )

        # Execute the script
        cmd_exec = ["kubectl", "exec", "--context", context, pod_name]
        cmd_exec.extend(["--", "python", script_path])

        result = subprocess.run(
            cmd_exec,
            capture_output=True,
            text=True,
            check=True,
        )

        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip() if result.stderr else "",
        }

    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "stdout": e.stdout if e.stdout else "",
            "error": e.stderr if e.stderr else str(e),
        }


def get_tenant_status(pod_name: str, tenant_id: str, context: str) -> str | None:
    """
    Get tenant status from control plane database via pod.

    Args:
        pod_name: The pod to execute the query from
        tenant_id: The tenant ID to look up
        context: kubectl context for control plane cluster

    Returns:
        Tenant status string (e.g., 'GATED_ACCESS', 'ACTIVE') or None if not found

    Raises:
        TenantNotFoundInControlPlaneError: If the tenant record is not found in the table
    """
    print(f"Fetching tenant status for tenant: {tenant_id}")

    query = f"SELECT application_status FROM tenant WHERE tenant_id = '{tenant_id}'"

    result = execute_control_plane_query_from_pod(pod_name, query, context)

    if not result["success"]:
        error_msg = result.get("error", "Unknown error")
        print(
            f"✗ Failed to get tenant status for {tenant_id}: {error_msg}",
            file=sys.stderr,
        )
        return None

    try:
        # Parse JSON output
        rows = json.loads(result["stdout"])

        if rows and len(rows) > 0:
            status = rows[0].get("application_status")
            if status:
                print(f"✓ Tenant status: {status}")
                return status

        # Tenant record not found in control plane table
        print("⚠ Tenant not found in control plane")
        raise TenantNotFoundInControlPlaneError(
            f"Tenant {tenant_id} not found in control plane database"
        )

    except TenantNotFoundInControlPlaneError:
        # Re-raise without wrapping
        raise
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"✗ Failed to parse tenant status: {e}", file=sys.stderr)
        return None


def execute_control_plane_delete(pod_name: str, query: str, context: str) -> bool:
    """Execute a DELETE query against control plane database from pod.

    Args:
        pod_name: The pod to execute the query from
        query: The DELETE query to execute
        context: kubectl context for control plane cluster

    Returns:
        True if successful, False otherwise
    """
    result = execute_control_plane_query_from_pod(pod_name, query, context)

    if result["success"]:
        print(f"    {result['stdout']}")
        return True
    else:
        print(f"    Error: {result.get('error', 'Unknown error')}", file=sys.stderr)
        return False


def read_tenant_ids_from_csv(csv_path: str) -> list[str]:
    """Read tenant IDs from CSV file.

    Args:
        csv_path: Path to CSV file

    Returns:
        List of tenant IDs
    """
    if not Path(csv_path).exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    tenant_ids = []
    with open(csv_path, "r", newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)

        # Check if tenant_id column exists
        if not reader.fieldnames or "tenant_id" not in reader.fieldnames:
            raise ValueError(
                f"CSV file must have a 'tenant_id' column. Found columns: {reader.fieldnames}"
            )

        for row in reader:
            tenant_id = row.get("tenant_id", "").strip()
            if tenant_id:
                tenant_ids.append(tenant_id)

    return tenant_ids
