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
    cmd_worker = [
        "celery",
        "-A",
        "ee.danswer.background.celery",
        "worker",
        "--pool=threads",
        "--autoscale=3,10",
        "--loglevel=INFO",
        "--concurrency=1",
    ]

    cmd_beat = [
        "celery",
        "-A",
        "ee.danswer.background.celery",
        "beat",
        "--loglevel=INFO",
    ]

    worker_process = subprocess.Popen(
        cmd_worker, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    beat_process = subprocess.Popen(
        cmd_beat, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    worker_thread = threading.Thread(
        target=monitor_process, args=("WORKER", worker_process)
    )
    beat_thread = threading.Thread(target=monitor_process, args=("BEAT", beat_process))

    worker_thread.start()
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
    try:
        update_env = os.environ.copy()
        update_env["PYTHONPATH"] = "."
        cmd_perm_sync = ["python", "ee.danswer/background/permission_sync.py"]

        indexing_process = subprocess.Popen(
            cmd_perm_sync,
            env=update_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        perm_sync_thread = threading.Thread(
            target=monitor_process, args=("INDEXING", indexing_process)
        )
        perm_sync_thread.start()
        perm_sync_thread.join()
    except Exception:
        pass

    worker_thread.join()
    beat_thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run background jobs.")
    parser.add_argument(
        "--no-indexing", action="store_true", help="Do not run indexing process"
    )
    args = parser.parse_args()

    run_jobs(args.no_indexing)
