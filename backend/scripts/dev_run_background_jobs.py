import argparse
import os
import subprocess
import threading


def monitor_process(process_name: str, process: subprocess.Popen) -> None:
    assert process.stdout is not None

    while True:
        output = process.stdout.readline()

        if output:
            print(f"{process_name}: {output.strip()}")

        if process.poll() is not None:
            break


def run_jobs(exclude_indexing: bool) -> None:
    # command setup
    cmd_worker_primary = [
        "celery",
        "-A",
        "ee.danswer.background.celery.celery_app",
        "worker",
        "--pool=threads",
        "--concurrency=6",
        "--loglevel=INFO",
        "-n",
        "primary@%n",
        "-Q",
        "celery",
    ]

    cmd_worker_light = [
        "celery",
        "-A",
        "ee.danswer.background.celery.celery_app",
        "worker",
        "--pool=threads",
        "--concurrency=16",
        "--loglevel=INFO",
        "-n",
        "light@%n",
        "-Q",
        "vespa_metadata_sync,connector_deletion",
    ]

    cmd_worker_heavy = [
        "celery",
        "-A",
        "ee.danswer.background.celery.celery_app",
        "worker",
        "--pool=threads",
        "--concurrency=6",
        "--loglevel=INFO",
        "-n",
        "heavy@%n",
        "-Q",
        "connector_pruning",
    ]

    cmd_beat = [
        "celery",
        "-A",
        "ee.danswer.background.celery.celery_app",
        "beat",
        "--loglevel=INFO",
    ]

    # spawn processes
    worker_primary_process = subprocess.Popen(
        cmd_worker_primary, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    worker_light_process = subprocess.Popen(
        cmd_worker_light, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    worker_heavy_process = subprocess.Popen(
        cmd_worker_heavy, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    beat_process = subprocess.Popen(
        cmd_beat, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    # monitor threads
    worker_primary_thread = threading.Thread(
        target=monitor_process, args=("PRIMARY", worker_primary_process)
    )
    worker_light_thread = threading.Thread(
        target=monitor_process, args=("LIGHT", worker_light_process)
    )
    worker_heavy_thread = threading.Thread(
        target=monitor_process, args=("HEAVY", worker_heavy_process)
    )
    beat_thread = threading.Thread(target=monitor_process, args=("BEAT", beat_process))

    worker_primary_thread.start()
    worker_light_thread.start()
    worker_heavy_thread.start()
    beat_thread.start()

    if not exclude_indexing:
        update_env = os.environ.copy()
        update_env["PYTHONPATH"] = "."
        cmd_indexing = ["python", "danswer/background/update.py"]

        indexing_process = subprocess.Popen(
            cmd_indexing,
            env=update_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        indexing_thread = threading.Thread(
            target=monitor_process, args=("INDEXING", indexing_process)
        )

        indexing_thread.start()
        indexing_thread.join()

    worker_primary_thread.join()
    worker_light_thread.join()
    worker_heavy_thread.join()
    beat_thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run background jobs.")
    parser.add_argument(
        "--no-indexing", action="store_true", help="Do not run indexing process"
    )
    args = parser.parse_args()

    run_jobs(args.no_indexing)
