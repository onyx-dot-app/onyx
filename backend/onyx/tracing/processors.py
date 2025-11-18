from __future__ import annotations

import os
import queue
import random
import threading
import time
from functools import cached_property
from typing import Any

import httpx

from .processor_interface import TracingExporter
from .processor_interface import TracingProcessor
from .spans import Span
from .traces import Trace
from onyx.utils.logger import setup_logger

logger = setup_logger(__name__)


class ConsoleSpanExporter(TracingExporter):
    """Prints the traces and spans to the console."""

    def export(self, items: list[Trace | Span[Any]]) -> None:
        for item in items:
            if isinstance(item, Trace):
                print(f"[Exporter] Export trace_id={item.trace_id}, name={item.name}")
            else:
                print(f"[Exporter] Export span: {item.export()}")


class BackendSpanExporter(TracingExporter):
    def __init__(
        self,
        api_key: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        endpoint: str = "https://api.openai.com/v1/traces/ingest",
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ):
        """
        Args:
            api_key: The API key for the "Authorization" header. Defaults to
                `os.environ["OPENAI_API_KEY"]` if not provided.
            organization: The OpenAI organization to use. Defaults to
                `os.environ["OPENAI_ORG_ID"]` if not provided.
            project: The OpenAI project to use. Defaults to
                `os.environ["OPENAI_PROJECT_ID"]` if not provided.
            endpoint: The HTTP endpoint to which traces/spans are posted.
            max_retries: Maximum number of retries upon failures.
            base_delay: Base delay (in seconds) for the first backoff.
            max_delay: Maximum delay (in seconds) for backoff growth.
        """
        self._api_key = api_key
        self._organization = organization
        self._project = project
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        # Keep a client open for connection pooling across multiple export calls
        self._client = httpx.Client(timeout=httpx.Timeout(timeout=60, connect=5.0))

    def set_api_key(self, api_key: str):
        """Set the OpenAI API key for the exporter.

        Args:
            api_key: The OpenAI API key to use. This is the same key used by the OpenAI Python
                client.
        """
        # Clear the cached property if it exists
        if "api_key" in self.__dict__:
            del self.__dict__["api_key"]

        # Update the private attribute
        self._api_key = api_key

    @cached_property
    def api_key(self):
        return self._api_key or os.environ.get("OPENAI_API_KEY")

    @cached_property
    def organization(self):
        return self._organization or os.environ.get("OPENAI_ORG_ID")

    @cached_property
    def project(self):
        return self._project or os.environ.get("OPENAI_PROJECT_ID")

    def export(self, items: list[Trace | Span[Any]]) -> None:
        if not items:
            return

        if not self.api_key:
            logger.warning("OPENAI_API_KEY is not set, skipping trace export")
            return

        data = [item.export() for item in items if item.export()]
        payload = {"data": data}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "traces=v1",
        }

        if self.organization:
            headers["OpenAI-Organization"] = self.organization

        if self.project:
            headers["OpenAI-Project"] = self.project

        # Exponential backoff loop
        attempt = 0
        delay = self.base_delay
        while True:
            attempt += 1
            try:
                response = self._client.post(
                    url=self.endpoint, headers=headers, json=payload
                )

                # If the response is successful, break out of the loop
                if response.status_code < 300:
                    logger.debug(f"Exported {len(items)} items")
                    return

                # If the response is a client error (4xx), we won't retry
                if 400 <= response.status_code < 500:
                    logger.error(
                        f"[non-fatal] Tracing client error {response.status_code}: {response.text}"
                    )
                    return

                # For 5xx or other unexpected codes, treat it as transient and retry
                logger.warning(
                    f"[non-fatal] Tracing: server error {response.status_code}, retrying."
                )
            except httpx.RequestError as exc:
                # Network or other I/O error, we'll retry
                logger.warning(f"[non-fatal] Tracing: request failed: {exc}")

            # If we reach here, we need to retry or give up
            if attempt >= self.max_retries:
                logger.error(
                    "[non-fatal] Tracing: max retries reached, giving up on this batch."
                )
                return

            # Exponential backoff + jitter
            sleep_time = delay + random.uniform(0, 0.1 * delay)  # 10% jitter
            time.sleep(sleep_time)
            delay = min(delay * 2, self.max_delay)

    def close(self):
        """Close the underlying HTTP client."""
        self._client.close()


class BatchTraceProcessor(TracingProcessor):
    """Some implementation notes:
    1. Using Queue, which is thread-safe.
    2. Using a background thread to export spans, to minimize any performance issues.
    3. Spans are stored in memory until they are exported.
    """

    def __init__(
        self,
        exporter: TracingExporter,
        max_queue_size: int = 8192,
        max_batch_size: int = 128,
        schedule_delay: float = 5.0,
        export_trigger_ratio: float = 0.7,
    ):
        """
        Args:
            exporter: The exporter to use.
            max_queue_size: The maximum number of spans to store in the queue. After this, we will
                start dropping spans.
            max_batch_size: The maximum number of spans to export in a single batch.
            schedule_delay: The delay between checks for new spans to export.
            export_trigger_ratio: The ratio of the queue size at which we will trigger an export.
        """
        self._exporter = exporter
        self._queue: queue.Queue[Trace | Span[Any]] = queue.Queue(
            maxsize=max_queue_size
        )
        self._max_queue_size = max_queue_size
        self._max_batch_size = max_batch_size
        self._schedule_delay = schedule_delay
        self._shutdown_event = threading.Event()

        # The queue size threshold at which we export immediately.
        self._export_trigger_size = max(1, int(max_queue_size * export_trigger_ratio))

        # Track when we next *must* perform a scheduled export
        self._next_export_time = time.time() + self._schedule_delay

        # We lazily start the background worker thread the first time a span/trace is queued.
        self._worker_thread: threading.Thread | None = None
        self._thread_start_lock = threading.Lock()

    def _ensure_thread_started(self) -> None:
        # Fast path without holding the lock
        if self._worker_thread and self._worker_thread.is_alive():
            return

        # Double-checked locking to avoid starting multiple threads
        with self._thread_start_lock:
            if self._worker_thread and self._worker_thread.is_alive():
                return

            self._worker_thread = threading.Thread(target=self._run, daemon=True)
            self._worker_thread.start()

    def on_trace_start(self, trace: Trace) -> None:
        # Ensure the background worker is running before we enqueue anything.
        self._ensure_thread_started()

        try:
            self._queue.put_nowait(trace)
        except queue.Full:
            logger.warning("Queue is full, dropping trace.")

    def on_trace_end(self, trace: Trace) -> None:
        # We send traces via on_trace_start, so we don't need to do anything here.
        pass

    def on_span_start(self, span: Span[Any]) -> None:
        # We send spans via on_span_end, so we don't need to do anything here.
        pass

    def on_span_end(self, span: Span[Any]) -> None:
        # Ensure the background worker is running before we enqueue anything.
        self._ensure_thread_started()

        try:
            self._queue.put_nowait(span)
        except queue.Full:
            logger.warning("Queue is full, dropping span.")

    def shutdown(self, timeout: float | None = None):
        """
        Called when the application stops. We signal our thread to stop, then join it.
        """
        self._shutdown_event.set()

        # Only join if we ever started the background thread; otherwise flush synchronously.
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        else:
            # No background thread: process any remaining items synchronously.
            self._export_batches(force=True)

    def force_flush(self):
        """
        Forces an immediate flush of all queued spans.
        """
        self._export_batches(force=True)

    def _run(self):
        while not self._shutdown_event.is_set():
            current_time = time.time()
            queue_size = self._queue.qsize()

            # If it's time for a scheduled flush or queue is above the trigger threshold
            if (
                current_time >= self._next_export_time
                or queue_size >= self._export_trigger_size
            ):
                self._export_batches(force=False)
                # Reset the next scheduled flush time
                self._next_export_time = time.time() + self._schedule_delay
            else:
                # Sleep a short interval so we don't busy-wait.
                time.sleep(0.2)

        # Final drain after shutdown
        self._export_batches(force=True)

    def _export_batches(self, force: bool = False):
        """Drains the queue and exports in batches. If force=True, export everything.
        Otherwise, export up to `max_batch_size` repeatedly until the queue is completely empty.
        """
        while True:
            items_to_export: list[Span[Any] | Trace] = []

            # Gather a batch of spans up to max_batch_size
            while not self._queue.empty() and (
                force or len(items_to_export) < self._max_batch_size
            ):
                try:
                    items_to_export.append(self._queue.get_nowait())
                except queue.Empty:
                    # Another thread might have emptied the queue between checks
                    break

            # If we collected nothing, we're done
            if not items_to_export:
                break

            # Export the batch
            self._exporter.export(items_to_export)


# Create a shared global instance:
_global_exporter = BackendSpanExporter()
_global_processor = BatchTraceProcessor(_global_exporter)


def default_exporter() -> BackendSpanExporter:
    """The default exporter, which exports traces and spans to the backend in batches."""
    return _global_exporter


def default_processor() -> BatchTraceProcessor:
    """The default processor, which exports traces and spans to the backend in batches."""
    return _global_processor
