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
    # Check if we should use lightweight mode, defaults to True, change to False to use separate background workers
    use_lightweight = True

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
        "vespa_metadata_sync,connector_deletion,doc_permissions_upsert,checkpoint_cleanup,index_attempt_cleanup",
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
        "--queues=connector_doc_fetching,user_files_indexing",
    ]

    cmd_beat = [
        "celery",
        "-A",
        "onyx.background.celery.versioned_apps.beat",
        "beat",
        "--loglevel=INFO",
    ]

    # Prepare background worker commands based on mode
    if use_lightweight:
        print("Starting workers in LIGHTWEIGHT mode (single background worker)")
        cmd_worker_background = [
            "celery",
            "-A",
            "onyx.background.celery.versioned_apps.background",
            "worker",
            "--pool=threads",
            "--concurrency=6",
            "--prefetch-multiplier=1",
            "--loglevel=INFO",
            "--hostname=background@%n",
            "-Q",
            "connector_pruning,connector_doc_permissions_sync,connector_external_group_sync,csv_generation,kg_processing,monitoring,user_file_processing,user_file_project_sync,user_file_delete",
        ]
        background_workers = [("BACKGROUND", cmd_worker_background)]
    else:
        print("Starting workers in STANDARD mode (separate background workers)")
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
            "connector_pruning",
        ]
        cmd_worker_kg_processing = [
            "celery",
            "-A",
            "onyx.background.celery.versioned_apps.kg_processing",
            "worker",
            "--pool=threads",
            "--concurrency=2",
            "--prefetch-multiplier=1",
            "--loglevel=INFO",
            "--hostname=kg_processing@%n",
            "-Q",
            "kg_processing",
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
            "user_file_processing,user_file_project_sync,connector_doc_permissions_sync,connector_external_group_sync,csv_generation,user_file_delete",
        ]
        background_workers = [
            ("HEAVY", cmd_worker_heavy),
            ("KG_PROCESSING", cmd_worker_kg_processing),
            ("MONITORING", cmd_worker_monitoring),
            ("USER_FILE_PROCESSING", cmd_worker_user_file_processing),
        ]

    # spawn processes
    worker_primary_process = subprocess.Popen(
        cmd_worker_primary, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    worker_light_process = subprocess.Popen(
        cmd_worker_light, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    worker_docprocessing_process = subprocess.Popen(
        cmd_worker_docprocessing,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    worker_docfetching_process = subprocess.Popen(
        cmd_worker_docfetching,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    beat_process = subprocess.Popen(
        cmd_beat, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    # Spawn background worker processes based on mode
    background_processes = []
    for name, cmd in background_workers:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        background_processes.append((name, process))

    # monitor threads
    worker_primary_thread = threading.Thread(
        target=monitor_process, args=("PRIMARY", worker_primary_process)
    )
    worker_light_thread = threading.Thread(
        target=monitor_process, args=("LIGHT", worker_light_process)
    )
    worker_docprocessing_thread = threading.Thread(
        target=monitor_process, args=("DOCPROCESSING", worker_docprocessing_process)
    )
    worker_docfetching_thread = threading.Thread(
        target=monitor_process, args=("DOCFETCHING", worker_docfetching_process)
    )
    beat_thread = threading.Thread(target=monitor_process, args=("BEAT", beat_process))

    # Create monitor threads for background workers
    background_threads = []
    for name, process in background_processes:
        thread = threading.Thread(target=monitor_process, args=(name, process))
        background_threads.append(thread)

    # Start all threads
    worker_primary_thread.start()
    worker_light_thread.start()
    worker_docprocessing_thread.start()
    worker_docfetching_thread.start()
    beat_thread.start()

    for thread in background_threads:
        thread.start()

    # Wait for all threads
    worker_primary_thread.join()
    worker_light_thread.join()
    worker_docprocessing_thread.join()
    worker_docfetching_thread.join()
    beat_thread.join()

    for thread in background_threads:
        thread.join()


if __name__ == "__main__":
    run_jobs()
