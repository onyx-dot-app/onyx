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
        "vespa_metadata_sync,connector_deletion,doc_permissions_upsert,checkpoint_cleanup,index_attempt_cleanup,opensearch_migration",
    ]

    cmd_worker_docprocessing = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.docprocessing",
        "worker",
        "--pool=threads",
        "--concurrency=6",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=docprocessing@%n",
        "--queues=docprocessing",
    ]

    cmd_worker_docfetching = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.docfetching",
        "worker",
        "--pool=threads",
        "--concurrency=1",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=docfetching@%n",
        "--queues=connector_doc_fetching",
    ]

    cmd_worker_heavy = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.heavy",
        "worker",
        "--pool=threads",
        "--concurrency=4",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=heavy@%n",
        "-Q",
        "connector_pruning,connector_doc_permissions_sync,connector_external_group_sync,csv_generation,sandbox",
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
        "-Q",
        "monitoring",
    ]

    cmd_worker_user_file_processing = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.user_file_processing",
        "worker",
        "--pool=threads",
        "--concurrency=2",
        "--prefetch-multiplier=1",
        "--loglevel=INFO",
        "--hostname=user_file_processing@%n",
        "-Q",
        "user_file_processing,user_file_project_sync,user_file_delete",
    ]

    cmd_beat = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.beat",
        "beat",
        "--loglevel=INFO",
    ]

    all_workers = [
        ("PRIMARY", cmd_worker_primary),
        ("LIGHT", cmd_worker_light),
        ("DOCPROCESSING", cmd_worker_docprocessing),
        ("DOCFETCHING", cmd_worker_docfetching),
        ("HEAVY", cmd_worker_heavy),
        ("MONITORING", cmd_worker_monitoring),
        ("USER_FILE_PROCESSING", cmd_worker_user_file_processing),
        ("BEAT", cmd_beat),
    ]

    processes = []
    for name, cmd in all_workers:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        processes.append((name, process))

    threads = []
    for name, process in processes:
        thread = threading.Thread(target=monitor_process, args=(name, process))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()


if __name__ == "__main__":
    run_jobs()
