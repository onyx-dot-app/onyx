#!/usr/bin/env python3
"""
Script to measure memory usage of Celery workers.
This script launches a Celery worker process and monitors its memory consumption.
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from typing import Optional

import psutil


def format_bytes(bytes_val: int) -> str:
    """Convert bytes to human readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} TB"


def get_process_memory_info(pid: int) -> Optional[dict]:
    """Get detailed memory information for a process."""
    try:
        process = psutil.Process(pid)
        memory_info = process.memory_info()
        memory_percent = process.memory_percent()

        # Get memory details
        details = {
            "rss": memory_info.rss,  # Physical memory currently used
            "vms": memory_info.vms,  # Virtual memory size
            "percent": memory_percent,
            "num_threads": process.num_threads(),
            "status": process.status(),
            "create_time": process.create_time(),
        }

        # Try to get additional memory info if available
        try:
            memory_full_info = process.memory_full_info()
            details.update(
                {
                    "uss": memory_full_info.uss,  # Unique Set Size
                    "pss": memory_full_info.pss,  # Proportional Set Size
                    "shared": memory_full_info.shared,  # Shared memory
                }
            )
        except (AttributeError, psutil.AccessDenied):
            pass

        return details
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def monitor_celery_worker(
    celery_app: str,
    worker_args: list[str],
    monitor_duration: int = 60,
    sample_interval: int = 5,
    baseline_only: bool = False,
) -> None:
    """Launch and monitor a Celery worker process."""

    # Build the command
    cmd = [sys.executable, "-m", "celery", "-A", celery_app, "worker"] + worker_args

    print(f"Launching Celery worker: {' '.join(cmd)}")
    print(f"Monitor duration: {monitor_duration}s, Sample interval: {sample_interval}s")
    print("-" * 80)

    # Launch the worker process
    process = None
    try:
        # Set environment to avoid some startup issues
        env = os.environ.copy()
        env["CELERY_ALWAYS_EAGER"] = "False"

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=os.setsid,  # Create new process group
        )

        print(f"Worker started with PID: {process.pid}")

        # Wait for worker to start up
        print("Waiting for worker to initialize...")
        startup_time = 10
        for i in range(startup_time):
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                print("Worker failed to start:")
                print(f"STDOUT: {stdout.decode()}")
                print(f"STDERR: {stderr.decode()}")
                return
            time.sleep(1)
            if i % 2 == 0:
                print(f"  Startup: {i+1}/{startup_time}s")

        print("Worker initialized. Starting memory monitoring...")
        print()

        # Monitor memory usage
        start_time = time.time()
        sample_count = 0
        max_memory = {"rss": 0, "vms": 0, "time": 0}

        # Print header
        print(
            f"{'Time':<8} {'RSS':<12} {'VMS':<12} {'Mem%':<8} {'USS':<12} {'PSS':<12} {'Shared':<12} {'Threads':<8}"
        )
        print("-" * 88)

        while True:
            current_time = time.time()
            elapsed = current_time - start_time

            # Get memory info
            mem_info = get_process_memory_info(process.pid)
            if mem_info is None:
                print("Process no longer exists")
                break

            # Track maximum memory usage
            if mem_info["rss"] > max_memory["rss"]:
                max_memory = {
                    "rss": mem_info["rss"],
                    "vms": mem_info["vms"],
                    "time": elapsed,
                }

            # Format and display current stats
            rss_str = format_bytes(mem_info["rss"])
            vms_str = format_bytes(mem_info["vms"])
            uss_str = format_bytes(mem_info.get("uss", 0))
            pss_str = format_bytes(mem_info.get("pss", 0))
            shared_str = format_bytes(mem_info.get("shared", 0))

            print(
                f"{elapsed:7.1f}s {rss_str:<12} {vms_str:<12} {mem_info['percent']:6.1f}% "
                f"{uss_str:<12} {pss_str:<12} {shared_str:<12} {mem_info['num_threads']:<8}"
            )

            sample_count += 1

            # Check if we should stop monitoring
            if baseline_only and sample_count >= 3:
                print(f"\nBaseline measurement complete after {sample_count} samples.")
                break
            elif elapsed >= monitor_duration:
                print(f"\nMonitoring complete after {elapsed:.1f}s")
                break

            time.sleep(sample_interval)

        # Print summary
        print("\n" + "=" * 80)
        print("MEMORY USAGE SUMMARY")
        print("=" * 80)
        print(
            f"Peak RSS Memory: {format_bytes(max_memory['rss'])} (at {max_memory['time']:.1f}s)"
        )
        print(f"Peak VMS Memory: {format_bytes(max_memory['vms'])}")
        print(f"Total Samples: {sample_count}")
        print(f"Worker PID: {process.pid}")

        # Get final memory breakdown
        final_mem = get_process_memory_info(process.pid)
        if final_mem:
            print("\nFinal Memory Breakdown:")
            print(f"  RSS (Physical): {format_bytes(final_mem['rss'])}")
            print(f"  VMS (Virtual):  {format_bytes(final_mem['vms'])}")
            if "uss" in final_mem:
                print(f"  USS (Unique):   {format_bytes(final_mem['uss'])}")
            if "pss" in final_mem:
                print(f"  PSS (Proportional): {format_bytes(final_mem['pss'])}")
            if "shared" in final_mem:
                print(f"  Shared Memory:  {format_bytes(final_mem['shared'])}")
            print(f"  Memory Percent: {final_mem['percent']:.2f}%")
            print(f"  Threads:        {final_mem['num_threads']}")

    except KeyboardInterrupt:
        print("\nMonitoring interrupted by user")

    except Exception as e:
        print(f"Error monitoring worker: {e}")

    finally:
        # Clean up the worker process
        if process and process.poll() is None:
            print(f"\nShutting down worker (PID: {process.pid})...")
            try:
                # Try graceful shutdown first
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)

                # Wait up to 10 seconds for graceful shutdown
                for _ in range(10):
                    if process.poll() is not None:
                        break
                    time.sleep(1)

                # Force kill if still running
                if process.poll() is None:
                    print("Force killing worker...")
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()

                print("Worker shut down successfully")

            except Exception as e:
                print(f"Error shutting down worker: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor memory usage of Celery workers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor docprocessing worker for 60 seconds
  python measure_celery_memory.py

  # Monitor specific worker with custom duration
  python measure_celery_memory.py --app onyx.background.celery.versioned_apps.primary --duration 120

  # Quick baseline measurement (just startup memory)
  python measure_celery_memory.py --baseline

  # Monitor with custom worker arguments
  python measure_celery_memory.py --worker-args="--loglevel=DEBUG --concurrency=2"
        """,
    )

    parser.add_argument(
        "--app",
        "-A",
        default="onyx.background.celery.versioned_apps.docprocessing",
        help="Celery app to monitor (default: docprocessing worker)",
    )

    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        default=60,
        help="Monitoring duration in seconds (default: 60)",
    )

    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=5,
        help="Sample interval in seconds (default: 5)",
    )

    parser.add_argument(
        "--baseline",
        "-b",
        action="store_true",
        help="Just measure baseline startup memory (3 samples)",
    )

    parser.add_argument(
        "--worker-args",
        default="--loglevel=INFO",
        help="Additional arguments to pass to the worker (default: --loglevel=INFO)",
    )

    args = parser.parse_args()

    # Parse worker arguments
    worker_args = args.worker_args.split() if args.worker_args else []

    print("=" * 80)
    print("CELERY WORKER MEMORY MONITOR")
    print("=" * 80)
    print(f"App: {args.app}")
    print(f"Args: {' '.join(worker_args)}")

    monitor_celery_worker(
        celery_app=args.app,
        worker_args=worker_args,
        monitor_duration=args.duration,
        sample_interval=args.interval,
        baseline_only=args.baseline,
    )


if __name__ == "__main__":
    main()
