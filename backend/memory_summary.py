#!/usr/bin/env python3

import gc
import importlib
import sys
from typing import Dict
from typing import Tuple

import psutil


def get_memory_mb() -> float:
    """Get current memory usage in MB"""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024


def measure_package_impact(package_name: str) -> Tuple[float, bool]:
    """Measure the actual memory impact of importing a package"""
    initial_memory = get_memory_mb()

    try:
        # Clear any cached modules first
        if package_name in sys.modules:
            del sys.modules[package_name]

        # Import the package
        importlib.import_module(package_name)

        # Force garbage collection to get accurate reading
        gc.collect()

        final_memory = get_memory_mb()
        return final_memory - initial_memory, True
    except ImportError as e:
        print(f"Could not import {package_name}: {e}")
        return 0.0, False
    except Exception as e:
        print(f"Error measuring {package_name}: {e}")
        return 0.0, False


def get_measured_package_impacts() -> Dict[str, float]:
    """Measure memory impact of key packages that Celery workers import"""
    packages_to_test = [
        # ML/AI packages (heavy)
        "sentence_transformers",
        "transformers",
        "torch",
        "numpy",
        "sklearn",
        "langchain",
        "langchain_community",
        # Onyx-specific heavy imports
        "onyx.indexing.embedder",
        "onyx.indexing.chunker",
        "onyx.document_index.vespa.index",
        "onyx.connectors",
        "onyx.llm.factory",
        # Database/infra
        "sqlalchemy",
        "alembic",
        "celery",
        "redis",
        "psycopg2",
        # Web frameworks
        "fastapi",
        "pydantic",
        "httpx",
        "requests",
        # Other potentially heavy
        "lxml",
        "beautifulsoup4",
        "pandas",
        "playwright",
    ]

    print("Measuring package memory impacts...")
    impacts = {}

    for package in packages_to_test:
        print(f"Testing {package}...")
        impact, success = measure_package_impact(package)
        if success and impact > 1.0:  # Only record significant impacts
            impacts[package] = impact
            print(f"  {package}: +{impact:.1f}MB")

    return impacts


def analyze_current_memory():
    """Analyze current process memory usage"""
    process = psutil.Process()
    memory_info = process.memory_info()

    print("=== Current Process Memory Analysis ===")
    print(f"RSS (Resident Set Size): {memory_info.rss / 1024 / 1024:.1f} MB")
    print(f"VMS (Virtual Memory Size): {memory_info.vms / 1024 / 1024:.1f} MB")

    # Show loaded modules count
    loaded_modules = len(sys.modules)
    print(f"Loaded Python modules: {loaded_modules}")

    # Show some of the heaviest modules loaded
    print("\nSome heavy modules currently loaded:")
    heavy_modules = [
        "torch",
        "transformers",
        "sentence_transformers",
        "numpy",
        "pandas",
        "sklearn",
        "langchain",
        "sqlalchemy",
        "fastapi",
        "celery",
    ]

    for module in heavy_modules:
        if module in sys.modules:
            print(f"  ✓ {module}")
        else:
            print(f"  ✗ {module}")


def get_container_memory_breakdown():
    """Get memory breakdown of running containers"""
    print("\n=== Docker Container Memory Usage ===")
    try:
        import subprocess

        result = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(result.stdout)
        else:
            print("Could not get docker stats")
    except Exception as e:
        print(f"Error getting container stats: {e}")


def analyze_supervisord_processes():
    """Analyze the supervisord processes and their memory"""
    print("\n=== Supervisord Process Analysis ===")

    # Find supervisord and its children
    for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            if proc.info["name"] == "supervisord" or "celery" in " ".join(
                proc.info["cmdline"] or []
            ):
                memory_mb = proc.info["memory_info"].rss / 1024 / 1024
                cmdline = " ".join(proc.info["cmdline"] or [])[:100]
                print(f"PID {proc.info['pid']}: {memory_mb:.1f}MB - {cmdline}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def main():
    print("Memory Analysis for Onyx Background Container")
    print("=" * 50)

    # Basic memory info
    analyze_current_memory()

    # Container breakdown
    get_container_memory_breakdown()

    # Process breakdown
    analyze_supervisord_processes()

    # Package impact measurement
    print("\n=== Package Memory Impact Analysis ===")
    impacts = get_measured_package_impacts()

    if impacts:
        print("\nTop memory-consuming packages:")
        sorted_impacts = sorted(impacts.items(), key=lambda x: x[1], reverse=True)
        total_measured = 0
        for package, impact in sorted_impacts[:10]:
            print(f"  {package}: {impact:.1f}MB")
            total_measured += impact
        print(f"\nTotal measured package impact: {total_measured:.1f}MB")
    else:
        print("No significant package impacts measured")


if __name__ == "__main__":
    main()
