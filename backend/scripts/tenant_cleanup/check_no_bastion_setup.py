#!/usr/bin/env python3
"""
Verification script to check if your environment is ready for no-bastion tenant cleanup.

Usage:
    python scripts/tenant_cleanup/check_no_bastion_setup.py
"""

import subprocess
import sys


def print_header(text: str) -> None:
    """Print a formatted header."""
    print(f"\n{'=' * 80}")
    print(f"  {text}")
    print(f"{'=' * 80}\n")


def check_kubectl_access() -> bool:
    """Check if kubectl is installed and can access the cluster."""
    print("Checking kubectl access...")

    try:
        result = subprocess.run(
            ["kubectl", "version", "--client", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            print(f"✅ kubectl is installed: {result.stdout.strip()}")

            # Try to access cluster
            result = subprocess.run(
                ["kubectl", "get", "ns"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                print("✅ kubectl can access the cluster")
                return True
            else:
                print("❌ kubectl cannot access the cluster")
                print(f"   Error: {result.stderr}")
                return False
        else:
            print("❌ kubectl is not installed or not in PATH")
            return False

    except FileNotFoundError:
        print("❌ kubectl is not installed")
        return False
    except subprocess.TimeoutExpired:
        print("❌ kubectl command timed out")
        return False
    except Exception as e:
        print(f"❌ Error checking kubectl: {e}")
        return False


def check_worker_pods() -> tuple[bool, list[str]]:
    """Check if worker pods are running."""
    print("\nChecking for worker pods...")

    try:
        result = subprocess.run(
            ["kubectl", "get", "po"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

        lines = result.stdout.strip().split("\n")
        worker_pods = []

        for line in lines[1:]:  # Skip header
            if "celery-worker-user-file-processing" in line and "Running" in line:
                pod_name = line.split()[0]
                worker_pods.append(pod_name)

        if worker_pods:
            print(f"✅ Found {len(worker_pods)} running worker pod(s):")
            for pod in worker_pods[:3]:  # Show first 3
                print(f"   - {pod}")
            if len(worker_pods) > 3:
                print(f"   ... and {len(worker_pods) - 3} more")
            return True, worker_pods
        else:
            print("❌ No running celery-worker-user-file-processing pods found")
            print("   Available pods:")
            for line in lines[1:6]:  # Show first 5 pods
                print(f"   {line}")
            return False, []

    except subprocess.CalledProcessError as e:
        print(f"❌ Error getting pods: {e}")
        return False, []
    except Exception as e:
        print(f"❌ Error checking worker pods: {e}")
        return False, []


def check_pod_exec_permission(pod_name: str) -> bool:
    """Check if we can exec into a pod."""
    print("\nChecking pod exec permissions...")

    try:
        result = subprocess.run(
            ["kubectl", "exec", pod_name, "--", "echo", "test"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and "test" in result.stdout:
            print(f"✅ Can exec into pod: {pod_name}")
            return True
        else:
            print(f"❌ Cannot exec into pod: {pod_name}")
            print(f"   Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print(f"❌ Exec command timed out for pod: {pod_name}")
        return False
    except Exception as e:
        print(f"❌ Error checking exec permission: {e}")
        return False


def check_pod_db_access(pod_name: str) -> dict:
    """Check if pod has database environment variables."""
    print("\nChecking database access from pod...")

    checks = {
        "control_plane": False,
        "data_plane": False,
    }

    try:
        # Check for control plane DB env vars
        result = subprocess.run(
            ["kubectl", "exec", pod_name, "--", "env"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            env_output = result.stdout

            # Check control plane access
            if any(
                var in env_output
                for var in [
                    "POSTGRES_CONTROL_URI",
                    "POSTGRES_CONTROL_HOST",
                ]
            ):
                print("✅ Pod has control plane database environment variables")
                checks["control_plane"] = True
            else:
                print(
                    "⚠️  Pod may not have control plane database environment variables"
                )
                print("   (This might be okay if they're dynamically loaded)")

            # Check data plane access
            if any(
                var in env_output
                for var in ["POSTGRES_URI", "POSTGRES_HOST", "DATABASE_URL"]
            ):
                print("✅ Pod has data plane database environment variables")
                checks["data_plane"] = True
            else:
                print("❌ Pod does not have data plane database environment variables")

        return checks

    except Exception as e:
        print(f"❌ Error checking database access: {e}")
        return checks


def check_required_scripts() -> bool:
    """Check if the required on_pod_scripts exist."""
    print("\nChecking for required scripts...")

    from pathlib import Path

    script_dir = Path(__file__).parent
    required_scripts = [
        "on_pod_scripts/understand_tenants.py",
        "on_pod_scripts/execute_connector_deletion.py",
        "on_pod_scripts/check_documents_deleted.py",
        "on_pod_scripts/cleanup_tenant_schema.py",
        "on_pod_scripts/get_tenant_index_name.py",
        "on_pod_scripts/get_tenant_users.py",
    ]

    all_exist = True
    for script in required_scripts:
        script_path = script_dir / script
        if script_path.exists():
            print(f"✅ {script}")
        else:
            print(f"❌ {script} - NOT FOUND")
            all_exist = False

    return all_exist


def main() -> None:
    print_header("No-Bastion Tenant Cleanup - Setup Verification")

    all_checks_passed = True

    # 1. Check kubectl access
    if not check_kubectl_access():
        all_checks_passed = False

    # 2. Check for worker pods
    has_pods, worker_pods = check_worker_pods()
    if not has_pods:
        all_checks_passed = False
        print("\n⚠️  Cannot proceed without running worker pods")
        print_header("SETUP VERIFICATION FAILED")
        sys.exit(1)

    # Use first worker pod for remaining checks
    test_pod = worker_pods[0]

    # 3. Check exec permissions
    if not check_pod_exec_permission(test_pod):
        all_checks_passed = False

    # 4. Check database access
    db_checks = check_pod_db_access(test_pod)
    if not db_checks["data_plane"]:
        all_checks_passed = False

    # 5. Check required scripts
    if not check_required_scripts():
        all_checks_passed = False

    # Summary
    print_header("VERIFICATION SUMMARY")

    if all_checks_passed and db_checks["control_plane"]:
        print("✅ ALL CHECKS PASSED!")
        print("\nYou're ready to run tenant cleanup without bastion access.")
        print("\nNext steps:")
        print("1. Read QUICK_START_NO_BASTION.md for commands")
        print(
            "2. Run: PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_analyze_tenants.py"
        )
        sys.exit(0)
    elif all_checks_passed:
        print("⚠️  MOSTLY READY (with warnings)")
        print("\nYou can proceed, but control plane access may need verification.")
        print("Try running Step 1 and see if it works.")
        print("\nNext steps:")
        print(
            "1. Run: PYTHONPATH=. python scripts/tenant_cleanup/no_bastion_analyze_tenants.py"
        )
        print("2. If it fails with DB errors, check pod environment variables")
        sys.exit(0)
    else:
        print("❌ SETUP VERIFICATION FAILED")
        print("\nPlease fix the issues above before proceeding.")
        print("\nCommon fixes:")
        print("- Install kubectl: https://kubernetes.io/docs/tasks/tools/")
        print("- Configure cluster access: kubectl config use-context <context>")
        print("- Check pod status: kubectl get po")
        sys.exit(1)


if __name__ == "__main__":
    main()
