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


def run_jobs() -> None:
    # command setup
    cmd_worker_primary = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.primary",
        "worker",
        "--pool=threads",
        "--concurrency=6",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=primary@%n",
        "-Q",
        "celery",
    ]

    cmd_worker_light = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.light",
        "worker",
        "--pool=threads",
        "--concurrency=16",
        "--prefetch-multiplier=8",
        "--loglevel=INFO",
        "--hostname=light@%n",
        "-Q",
        "vespa_metadata_sync,connector_deletion,doc_permissions_upsert,checkpoint_cleanup",
    ]

    cmd_worker_heavy = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.heavy",
        "worker",
        "--pool=threads",
        "--concurrency=6",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=heavy@%n",
        "-Q",
        "connector_pruning,connector_doc_permissions_sync,connector_external_group_sync",
    ]

    cmd_worker_indexing = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.indexing",
        "worker",
        "--pool=threads",
        "--concurrency=1",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=indexing@%n",
        "--queues=connector_indexing",
    ]

    cmd_worker_monitoring = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.monitoring",
        "worker",
        "--pool=threads",
        "--concurrency=1",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=monitoring@%n",
        "--queues=monitoring",
    ]

    cmd_beat = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.beat",
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

    worker_indexing_process = subprocess.Popen(
        cmd_worker_indexing, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    worker_monitoring_process = subprocess.Popen(
        cmd_worker_monitoring,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
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
    worker_indexing_thread = threading.Thread(
        target=monitor_process, args=("INDEX", worker_indexing_process)
    )
    worker_monitoring_thread = threading.Thread(
        target=monitor_process, args=("MONITORING", worker_monitoring_process)
    )
    beat_thread = threading.Thread(target=monitor_process, args=("BEAT", beat_process))

    worker_primary_thread.start()
    worker_light_thread.start()
    worker_heavy_thread.start()
    worker_indexing_thread.start()
    worker_monitoring_thread.start()
    beat_thread.start()

    worker_primary_thread.join()
    worker_light_thread.join()
    worker_heavy_thread.join()
    worker_indexing_thread.join()
    worker_monitoring_thread.join()
    beat_thread.join()


if __name__ == "__main__":
    run_jobs()
