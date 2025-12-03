#!/usr/bin/env python3
"""
Tenant analysis script that works WITHOUT bastion access.
Control plane and data plane are in SEPARATE clusters.

Usage:
    PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_analyze_tenants.py \
        [--skip-cache] \
        [--data-plane-context <context>] \
        [--control-plane-context <context>]
"""

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any

from scripts.tenant_cleanup.no_bastion_cleanup_utils import find_background_pod
from scripts.tenant_cleanup.no_bastion_cleanup_utils import find_worker_pod


def collect_tenant_data(
    pod_name: str, context: str | None = None
) -> list[dict[str, Any]]:
    """Run the understand_tenants script on the data plane pod."""
    print(f"\nCollecting tenant data from data plane pod {pod_name}...")

    # Get the path to the understand_tenants script
    script_dir = Path(__file__).parent
    understand_tenants_script = script_dir / "on_pod_scripts" / "understand_tenants.py"

    if not understand_tenants_script.exists():
        raise FileNotFoundError(
            f"understand_tenants.py not found at {understand_tenants_script}"
        )

    # Copy script to pod
    print("Copying script to pod...")
    cmd_cp = [
        "kubectl",
        "cp",
        str(understand_tenants_script),
        f"{pod_name}:/tmp/understand_tenants.py",
    ]
    if context:
        cmd_cp.extend(["--context", context])

    subprocess.run(cmd_cp, check=True, capture_output=True)

    # Execute script on pod
    print("Executing script on pod (this may take a while)...")
    cmd_exec = ["kubectl", "exec", pod_name]
    if context:
        cmd_exec.extend(["--context", context])
    cmd_exec.extend(["--", "python", "/tmp/understand_tenants.py"])

    result = subprocess.run(cmd_exec, capture_output=True, text=True, check=True)

    # Show progress messages from stderr
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Parse JSON from stdout
    try:
        tenant_data = json.loads(result.stdout)
        print(f"Successfully collected data for {len(tenant_data)} tenants")
        return tenant_data
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON output: {e}", file=sys.stderr)
        print(f"stdout: {result.stdout[:500]}", file=sys.stderr)
        raise


def collect_control_plane_data_from_pod(
    pod_name: str, context: str | None = None
) -> list[dict[str, Any]]:
    """Collect control plane data by running a query on a control plane pod."""
    print(f"\nCollecting control plane data from pod {pod_name}...")

    # Create a script to query the control plane database
    query_script = """
import json
import os
from sqlalchemy import create_engine, text

# Try to get database URL from various environment patterns
control_db_url = None

# Pattern 1: POSTGRES_CONTROL_* variables
if os.environ.get("POSTGRES_CONTROL_HOST"):
    host = os.environ.get("POSTGRES_CONTROL_HOST")
    port = os.environ.get("POSTGRES_CONTROL_PORT", "5432")
    db = os.environ.get("POSTGRES_CONTROL_DB", "control")
    user = os.environ.get("POSTGRES_CONTROL_USER", "postgres")
    password = os.environ.get("POSTGRES_CONTROL_PASSWORD", "")
    if password:
        control_db_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

# Pattern 2: Standard POSTGRES_* variables (in control plane cluster)
if not control_db_url and os.environ.get("POSTGRES_HOST"):
    host = os.environ.get("POSTGRES_HOST")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "danswer")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if password:
        control_db_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

if not control_db_url:
    raise ValueError("Cannot determine control plane database connection")

engine = create_engine(control_db_url)

with engine.connect() as conn:
    result = conn.execute(
        text(
            "SELECT tenant_id, stripe_customer_id, created_at, active_seats, "
            "creator_email, referral_source, application_status FROM tenant"
        )
    )
    rows = [dict(row._mapping) for row in result]
    print(json.dumps(rows, default=str))
"""

    # Write the script to a temp file
    script_path = "/tmp/query_control_plane.py"

    print("  Creating control plane query script on pod...")
    cmd_write = ["kubectl", "exec", pod_name]
    if context:
        cmd_write.extend(["--context", context])
    cmd_write.extend(
        ["--", "bash", "-c", f"cat > {script_path} << 'EOF'\n{query_script}\nEOF"]
    )

    subprocess.run(cmd_write, check=True, capture_output=True)

    # Execute the script on the pod
    print("  Executing control plane query on pod...")
    cmd_exec = ["kubectl", "exec", pod_name]
    if context:
        cmd_exec.extend(["--context", context])
    cmd_exec.extend(["--", "python", script_path])

    result = subprocess.run(cmd_exec, capture_output=True, text=True, check=True)

    # Parse JSON output
    try:
        control_plane_data = json.loads(result.stdout)
        print(
            f"✓ Successfully collected {len(control_plane_data)} tenant records from control plane"
        )
        return control_plane_data
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON output: {e}", file=sys.stderr)
        print(f"stdout: {result.stdout[:500]}", file=sys.stderr)
        raise


def analyze_tenants(
    tenants: list[dict[str, Any]], control_plane_data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Analyze tenant activity data and return gated tenants with no query in last 3 months."""

    print(f"\n{'=' * 80}")
    print(f"TENANT ANALYSIS REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 80}")
    print(f"Total tenants analyzed: {len(tenants)}\n")

    # Create a lookup dict for control plane data by tenant_id
    control_plane_lookup = {}
    for row in control_plane_data:
        tenant_id = row.get("tenant_id")
        tenant_status = row.get("application_status")
        if tenant_id:
            control_plane_lookup[tenant_id] = tenant_status

    # Calculate cutoff dates
    one_month_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    three_month_cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    # Categorize tenants into 4 groups
    gated_no_query_3_months = []  # GATED_ACCESS + no query in last 3 months
    gated_query_1_3_months = []  # GATED_ACCESS + query between 1-3 months
    gated_query_1_month = []  # GATED_ACCESS + query in last 1 month
    everyone_else = []  # All other tenants

    for tenant in tenants:
        tenant_id = tenant.get("tenant_id")
        last_query_time = tenant.get("last_query_time")
        tenant_status = control_plane_lookup.get(tenant_id, "UNKNOWN")

        is_gated = tenant_status == "GATED_ACCESS"

        # Parse last query time
        if last_query_time:
            query_time = datetime.fromisoformat(last_query_time.replace("Z", "+00:00"))
        else:
            query_time = None

        # Categorize
        if is_gated:
            if query_time is None or query_time <= three_month_cutoff:
                gated_no_query_3_months.append(tenant)
            elif query_time <= one_month_cutoff:
                gated_query_1_3_months.append(tenant)
            else:  # query_time > one_month_cutoff
                gated_query_1_month.append(tenant)
        else:
            everyone_else.append(tenant)

    # Calculate document counts for each group
    gated_no_query_docs = sum(
        t.get("num_documents", 0) for t in gated_no_query_3_months
    )
    gated_1_3_month_docs = sum(
        t.get("num_documents", 0) for t in gated_query_1_3_months
    )
    gated_1_month_docs = sum(t.get("num_documents", 0) for t in gated_query_1_month)
    everyone_else_docs = sum(t.get("num_documents", 0) for t in everyone_else)

    print("=" * 80)
    print("TENANT CATEGORIZATION BY GATED ACCESS STATUS AND ACTIVITY")
    print("=" * 80)

    print("\n1. GATED_ACCESS + No query in last 3 months:")
    print(f"   Count: {len(gated_no_query_3_months):,}")
    print(f"   Total documents: {gated_no_query_docs:,}")
    print(
        f"   Avg documents per tenant: {gated_no_query_docs / len(gated_no_query_3_months) if gated_no_query_3_months else 0:.2f}"
    )

    print("\n2. GATED_ACCESS + Query between 1-3 months ago:")
    print(f"   Count: {len(gated_query_1_3_months):,}")
    print(f"   Total documents: {gated_1_3_month_docs:,}")
    print(
        f"   Avg documents per tenant: {gated_1_3_month_docs / len(gated_query_1_3_months) if gated_query_1_3_months else 0:.2f}"
    )

    print("\n3. GATED_ACCESS + Query in last 1 month:")
    print(f"   Count: {len(gated_query_1_month):,}")
    print(f"   Total documents: {gated_1_month_docs:,}")
    print(
        f"   Avg documents per tenant: {gated_1_month_docs / len(gated_query_1_month) if gated_query_1_month else 0:.2f}"
    )

    print("\n4. Everyone else (non-GATED_ACCESS):")
    print(f"   Count: {len(everyone_else):,}")
    print(f"   Total documents: {everyone_else_docs:,}")
    print(
        f"   Avg documents per tenant: {everyone_else_docs / len(everyone_else) if everyone_else else 0:.2f}"
    )

    total_docs = (
        gated_no_query_docs
        + gated_1_3_month_docs
        + gated_1_month_docs
        + everyone_else_docs
    )
    print(f"\nTotal documents across all tenants: {total_docs:,}")

    # Top 100 tenants by document count
    print("\n" + "=" * 80)
    print("TOP 100 TENANTS BY DOCUMENT COUNT")
    print("=" * 80)

    # Sort all tenants by document count
    sorted_tenants = sorted(
        tenants, key=lambda t: t.get("num_documents", 0), reverse=True
    )

    top_100 = sorted_tenants[:100]

    print(
        f"\n{'Rank':<6} {'Tenant ID':<45} {'Documents':>12} {'Users':>8} {'Last Query':<12} {'Group'}"
    )
    print("-" * 130)

    for idx, tenant in enumerate(top_100, 1):
        tenant_id = tenant.get("tenant_id", "Unknown")
        num_docs = tenant.get("num_documents", 0)
        num_users = tenant.get("num_users", 0)
        last_query = tenant.get("last_query_time", "Never")
        tenant_status = control_plane_lookup.get(tenant_id, "UNKNOWN")

        # Format the last query time
        if last_query and last_query != "Never":
            try:
                query_dt = datetime.fromisoformat(last_query.replace("Z", "+00:00"))
                last_query_str = query_dt.strftime("%Y-%m-%d")
            except Exception:
                last_query_str = last_query[:10] if len(last_query) > 10 else last_query
        else:
            last_query_str = "Never"

        # Determine group
        if tenant_status == "GATED_ACCESS":
            if last_query and last_query != "Never":
                query_time = datetime.fromisoformat(last_query.replace("Z", "+00:00"))
                if query_time <= three_month_cutoff:
                    group = "Gated - No query (3mo)"
                elif query_time <= one_month_cutoff:
                    group = "Gated - Query (1-3mo)"
                else:
                    group = "Gated - Query (1mo)"
            else:
                group = "Gated - No query (3mo)"
        else:
            group = f"Other ({tenant_status})"

        print(
            f"{idx:<6} {tenant_id:<45} {num_docs:>12,} {num_users:>8} {last_query_str:<12} {group}"
        )

    # Summary stats for top 100
    top_100_docs = sum(t.get("num_documents", 0) for t in top_100)

    print("\n" + "-" * 110)
    print(f"Top 100 total documents: {top_100_docs:,}")
    print(
        f"Percentage of all documents: {(top_100_docs / total_docs * 100) if total_docs > 0 else 0:.2f}%"
    )

    # Additional insights
    print("\n" + "=" * 80)
    print("ADDITIONAL INSIGHTS")
    print("=" * 80)

    # Tenants with no documents
    no_docs = [t for t in tenants if t.get("num_documents", 0) == 0]
    print(
        f"\nTenants with 0 documents: {len(no_docs):,} ({len(no_docs) / len(tenants) * 100:.2f}%)"
    )

    # Tenants with no users
    no_users = [t for t in tenants if t.get("num_users", 0) == 0]
    print(
        f"Tenants with 0 users: {len(no_users):,} ({len(no_users) / len(tenants) * 100:.2f}%)"
    )

    # Document distribution quartiles
    doc_counts = sorted([t.get("num_documents", 0) for t in tenants])
    if doc_counts:
        print("\nDocument count distribution:")
        print(f"  Median: {doc_counts[len(doc_counts) // 2]:,}")
        print(f"  75th percentile: {doc_counts[int(len(doc_counts) * 0.75)]:,}")
        print(f"  90th percentile: {doc_counts[int(len(doc_counts) * 0.90)]:,}")
        print(f"  95th percentile: {doc_counts[int(len(doc_counts) * 0.95)]:,}")
        print(f"  99th percentile: {doc_counts[int(len(doc_counts) * 0.99)]:,}")
        print(f"  Max: {doc_counts[-1]:,}")

    return gated_no_query_3_months


def find_recent_tenant_data() -> tuple[list[dict[str, Any]] | None, str | None]:
    """Find the most recent tenant data file if it's less than 7 days old."""
    current_dir = Path.cwd()
    tenant_data_files = list(current_dir.glob("tenant_data_*.json"))

    if not tenant_data_files:
        return None, None

    # Sort by modification time, most recent first
    tenant_data_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    most_recent = tenant_data_files[0]

    # Check if file is less than 7 days old
    file_age = datetime.now().timestamp() - most_recent.stat().st_mtime
    seven_days_in_seconds = 7 * 24 * 60 * 60

    if file_age < seven_days_in_seconds:
        file_age_days = file_age / (24 * 60 * 60)
        print(
            f"\n✓ Found recent tenant data: {most_recent.name} (age: {file_age_days:.1f} days)"
        )

        with open(most_recent, "r") as f:
            tenant_data = json.load(f)

        return tenant_data, str(most_recent)

    return None, None


def main() -> None:
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Analyze tenant data WITHOUT bastion access - control plane and data plane are separate clusters"
    )
    parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Skip cached tenant data and collect fresh data from pod",
    )
    parser.add_argument(
        "--data-plane-context",
        type=str,
        help="Kubectl context for data plane cluster (optional)",
    )
    parser.add_argument(
        "--control-plane-context",
        type=str,
        help="Kubectl context for control plane cluster (optional)",
    )
    args = parser.parse_args()

    try:
        # Step 1: Check for recent tenant data (< 7 days old) unless --skip-cache is set
        tenant_data = None
        cached_file = None

        if not args.skip_cache:
            tenant_data, cached_file = find_recent_tenant_data()

        if tenant_data:
            print(f"Using cached tenant data from: {cached_file}")
            print(f"Total tenants in cache: {len(tenant_data)}")
        else:
            if args.skip_cache:
                print("\n⚠ Skipping cache (--skip-cache flag set)")

            # Find data plane worker pod
            print("\n" + "=" * 80)
            print("CONNECTING TO DATA PLANE CLUSTER")
            print("=" * 80)
            data_plane_pod = find_worker_pod(args.data_plane_context)

            # Collect tenant data from data plane
            tenant_data = collect_tenant_data(data_plane_pod, args.data_plane_context)

            # Save raw data to file with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"tenant_data_{timestamp}.json"
            with open(output_file, "w") as f:
                json.dump(tenant_data, f, indent=2, default=str)
            print(f"\n✓ Raw data saved to: {output_file}")

        # Step 2: Collect control plane data from control plane cluster
        print("\n" + "=" * 80)
        print("CONNECTING TO CONTROL PLANE CLUSTER")
        print("=" * 80)
        control_plane_pod = find_background_pod(args.control_plane_context)
        control_plane_data = collect_control_plane_data_from_pod(
            control_plane_pod, args.control_plane_context
        )

        # Step 3: Analyze the data and get gated tenants without recent queries
        gated_no_query_3_months = analyze_tenants(tenant_data, control_plane_data)

        # Step 4: Export to CSV (sorted by num_documents descending)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_file = f"gated_tenants_no_query_3mo_{timestamp}.csv"

        # Sort by num_documents in descending order
        sorted_tenants = sorted(
            gated_no_query_3_months,
            key=lambda t: t.get("num_documents", 0),
            reverse=True,
        )

        with open(csv_file, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "tenant_id",
                "num_documents",
                "num_users",
                "last_query_time",
                "days_since_last_query",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            now = datetime.now(timezone.utc)
            for tenant in sorted_tenants:
                # Calculate days since last query
                last_query_time = tenant.get("last_query_time")
                if last_query_time:
                    try:
                        query_dt = datetime.fromisoformat(
                            last_query_time.replace("Z", "+00:00")
                        )
                        days_since = str((now - query_dt).days)
                    except Exception:
                        days_since = "N/A"
                else:
                    days_since = "Never"

                writer.writerow(
                    {
                        "tenant_id": tenant.get("tenant_id", ""),
                        "num_documents": tenant.get("num_documents", 0),
                        "num_users": tenant.get("num_users", 0),
                        "last_query_time": last_query_time or "Never",
                        "days_since_last_query": days_since,
                    }
                )

        print(f"\n✓ CSV exported to: {csv_file}")
        print(
            f"  Total gated tenants with no query in last 3 months: {len(gated_no_query_3_months)}"
        )

    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}", file=sys.stderr)
        if e.stderr:
            print(f"stderr: {e.stderr}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
