import csv
import os
import random
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class TenantNotFoundInControlPlaneError(Exception):
    """Exception raised when tenant/table is not found in control plane."""


@dataclass
class ControlPlaneConfig:
    """Configuration for connecting to the control plane database."""

    db_url: str
    bastion_host: str
    pem_file_location: str


def find_worker_pod() -> str:
    """Find a user file processing worker pod using kubectl."""
    print("Finding user file processing worker pod...")

    result = subprocess.run(
        ["kubectl", "get", "po"], capture_output=True, text=True, check=True
    )

    # Parse output and find user file processing worker pod
    lines = result.stdout.strip().split("\n")
    lines = lines[1:]  # Skip header
    random.shuffle(lines)
    for line in lines:
        if "celery-worker-user-file-processing" in line and "Running" in line:
            pod_name = line.split()[0]
            print(f"Found pod: {pod_name}")
            return pod_name

    raise RuntimeError("No running user file processing worker pod found")


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


def get_control_plane_config() -> ControlPlaneConfig:
    """Get control plane database configuration from environment variables.

    Returns:
        ControlPlaneConfig with db_url, bastion_host, and pem_file_location

    Raises:
        ValueError: If any required environment variable is not set
    """
    rds_host = os.environ.get("CONTROL_PLANE_RDS_HOST")
    if not rds_host:
        raise ValueError("CONTROL_PLANE_RDS_HOST is not set")

    rds_password = os.environ.get("CONTROL_PLANE_RDS_PASSWORD")
    if not rds_password:
        raise ValueError("CONTROL_PLANE_RDS_PASSWORD is not set")

    bastion_host = os.environ.get("BASTION_HOST")
    if not bastion_host:
        raise ValueError("BASTION_HOST is not set")

    pem_file_location = os.environ.get("PEM_FILE_LOCATION")
    if not pem_file_location:
        raise ValueError("PEM_FILE_LOCATION is not set")

    db_url = f"postgresql://postgres:{rds_password}@{rds_host}:5432/control"

    return ControlPlaneConfig(
        db_url=db_url,
        bastion_host=bastion_host,
        pem_file_location=pem_file_location,
    )


def _build_remote_command(args: list[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in args)


def _escape_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def execute_control_plane_query(
    query: str, tuple_only: bool = False
) -> subprocess.CompletedProcess:
    """Execute a SQL query against the control plane database via SSH.

    Args:
        query: The SQL query to execute
        tuple_only: If True, use psql's tuple-only mode (-t flag) for cleaner output

    Returns:
        subprocess.CompletedProcess with the result

    Raises:
        subprocess.CalledProcessError: If the command fails
    """
    config = get_control_plane_config()
    db_url = config.db_url
    bastion_host = config.bastion_host
    pem_file_location = config.pem_file_location

    remote_command_parts = ["psql", db_url]
    if tuple_only:
        remote_command_parts.append("-t")
    remote_command_parts.extend(["-c", query])

    result = subprocess.run(
        [
            "ssh",
            "-i",
            pem_file_location,
            f"ec2-user@{bastion_host}",
            _build_remote_command(remote_command_parts),
        ],
        shell=False,
        check=True,
        capture_output=True,
        text=True,
    )

    return result


def get_tenant_status(tenant_id: str) -> str | None:
    """
    Get tenant status from control plane database.

    Returns:
        Tenant status string (e.g., 'GATED_ACCESS', 'ACTIVE') or None if not found

    Raises:
        TenantNotFoundInControlPlaneError: If the tenant table/relation does not exist
    """
    print(f"Fetching tenant status for tenant: {tenant_id}")

    safe_tenant_id = _escape_sql_literal(tenant_id)
    query = (
        "SELECT application_status FROM tenant "
        f"WHERE tenant_id = '{safe_tenant_id}';"
    )

    try:
        result = execute_control_plane_query(query, tuple_only=True)

        # Parse the output - psql returns the value with whitespace
        status = result.stdout.strip()

        if status:
            print(f"✓ Tenant status: {status}")
            return status
        else:
            print("⚠ Tenant not found in control plane")
            raise TenantNotFoundInControlPlaneError(
                f"Tenant {tenant_id} not found in control plane database"
            )
    except TenantNotFoundInControlPlaneError:
        # Re-raise without wrapping
        raise
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        print(
            f"✗ Failed to get tenant status for {tenant_id}: {error_msg}",
            file=sys.stderr,
        )
        return None


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