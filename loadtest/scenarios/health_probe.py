"""Health-probe user for the worker / threadpool concurrency experiment.

Hits the api-server /health endpoint on a fixed cadence, independent of the
chat load, and fails any probe slower than the liveness SLA. Run it alongside a
heavy chat workload (ThreadHogUser or DeepResearchUser) and watch the
``HEALTH:probe`` failure rate: when it climbs, the threadpool / event loop is
saturated enough that Kubernetes' liveness probe would start killing the pod.

This is the direct, measurable analogue of the production liveness-kill — the
liveness probe is ``httpGet /health``, ``timeoutSeconds: 10``,
``failureThreshold: 3``, so a probe slower than 10s is a failed liveness check
and three in a row kill the container.

Run (pin probes + drive saturation, then sweep api.workers / threadpoolSize):

    locust ThreadHogUser HealthProbeUser -u 50 -r 5 --host "$LOCUST_HOST"

Env:
    ONYX_HEALTH_PATH      probe path (default /health; use /api/health when
                          LOCUST_HOST points at the web/nginx host rather than
                          the api Service directly)
    ONYX_HEALTH_PROBES    number of probe users to pin (default 1)
    ONYX_HEALTH_INTERVAL  seconds between probes (default 1.0)
    ONYX_HEALTH_SLA_MS    fail a probe slower than this (default 10000, the
                          liveness timeoutSeconds)
"""

from __future__ import annotations

import os
import time

from locust import constant_pacing
from locust import HttpUser
from locust import task
from onyx_client.env import env_float
from onyx_client.env import env_int


class HealthProbeUser(HttpUser):
    # Pin an exact number of probes regardless of -u so the cadence stays stable
    # as the chat load scales up.
    fixed_count = env_int("ONYX_HEALTH_PROBES", 1)
    wait_time = constant_pacing(env_float("ONYX_HEALTH_INTERVAL", 1.0))

    def on_start(self) -> None:
        # When LOCUST_HOST points at an internal Service (to bypass an external
        # ALB/WAF), set ONYX_HOST_HEADER so in-cluster nginx routes by Host.
        host_header = os.environ.get("ONYX_HOST_HEADER")
        if host_header:
            self.client.headers["Host"] = host_header
        self._path = os.environ.get("ONYX_HEALTH_PATH", "/health")
        self._sla_ms = env_float("ONYX_HEALTH_SLA_MS", 10000.0)

    @task
    def probe(self) -> None:
        start = time.perf_counter()
        try:
            with self.client.get(
                self._path,
                name="HEALTH:probe",
                catch_response=True,
                # Cap the wait a bit past the SLA so a wedged /health is recorded
                # as a (slow) failure instead of blocking the probe forever.
                timeout=self._sla_ms / 1000.0 + 5.0,
            ) as response:
                elapsed_ms = (time.perf_counter() - start) * 1000
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                elif elapsed_ms > self._sla_ms:
                    # Past the liveness timeout → this probe would have counted
                    # as a liveness failure (3 in a row kill the pod).
                    response.failure(
                        f"slow {elapsed_ms:.0f}ms > {self._sla_ms:.0f}ms SLA"
                    )
                else:
                    response.success()
        except Exception as exc:
            # Timeout / connection error: the probe never came back in time,
            # which is exactly what a liveness failure looks like.
            self.environment.events.request.fire(
                request_type="GET",
                name="HEALTH:probe",
                response_time=(time.perf_counter() - start) * 1000,
                response_length=0,
                exception=exc,
                context={},
            )
