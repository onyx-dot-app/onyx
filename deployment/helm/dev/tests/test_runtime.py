"""Contracts for shared Craft configuration and staged readiness."""

import base64
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime import Cluster, application_ready  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def test_deployed_sources_and_local_overrides_keep_secrets_in_memory(self) -> None:
        """Match Kubernetes precedence without writing resolved credentials to local files."""
        workload = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "api-server",
                                "envFrom": [
                                    {"configMapRef": {"name": "settings"}},
                                    {"secretRef": {"name": "credentials"}},
                                ],
                                "env": [
                                    {"name": "EMPTY"},
                                    {"name": "POSTGRES_HOST", "value": "database"},
                                    {"name": "COPY", "value": "$(SHARED)-$$literal"},
                                    {
                                        "name": "SELECTED",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "credentials",
                                                "key": "SHARED",
                                            }
                                        },
                                    },
                                    {
                                        "name": "UNSET",
                                        "valueFrom": {
                                            "secretKeyRef": {
                                                "name": "absent",
                                                "key": "value",
                                                "optional": True,
                                            }
                                        },
                                    },
                                ],
                            }
                        ]
                    }
                }
            }
        }

        def kube(*args: str, **_kwargs: object) -> str:
            if args[1:3] == ("configmap", "settings"):
                return json.dumps(
                    {
                        "data": {
                            "SHARED": "config",
                            "S3_ENDPOINT_URL": "http://store:8333",
                            "LOG_LEVEL": "INFO",
                        }
                    }
                )
            if args[1:3] == ("secret", "credentials"):
                return json.dumps(
                    {
                        "data": {
                            "SHARED": base64.b64encode(b"private-credential").decode()
                        }
                    }
                )
            return ""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            override = root / "personal.env"
            contents = (
                "LOG_LEVEL=DEBUG\nK8S_CONTEXT=wrong\nGEN_AI_API_KEY=<REPLACE THIS>\n"
            )
            override.write_text(contents)
            cluster = Cluster(root, "local", "team", "sandboxes")
            with (
                patch.object(Cluster, "api_workload", return_value=workload),
                patch.object(Cluster, "kube", side_effect=kube),
            ):
                env = cluster.environment(override)
            self.assertEqual(env["SELECTED"], "private-credential")
            self.assertEqual(env["COPY"], "private-credential-$literal")
            self.assertEqual(env["POSTGRES_HOST"], "database.team.svc.cluster.local")
            self.assertEqual(
                env["S3_ENDPOINT_URL"], "http://store.team.svc.cluster.local:8333"
            )
            self.assertEqual(env["LOG_LEVEL"], "DEBUG")
            self.assertEqual(env["K8S_CONTEXT"], "kind-local")
            self.assertEqual(env["SANDBOX_NAMESPACE"], "sandboxes")
            self.assertNotIn("UNSET", env)
            self.assertEqual(env["EMPTY"], "")
            self.assertEqual(override.read_text(), contents)
            self.assertEqual(list(root.iterdir()), [override])

    def test_missing_required_secret_fails_before_launch(self) -> None:
        """Reject incomplete deployed configuration before starting a local application."""
        workload = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "api-server",
                                "envFrom": [{"secretRef": {"name": "missing"}}],
                            }
                        ]
                    }
                }
            }
        }
        with (
            patch.object(Cluster, "api_workload", return_value=workload),
            patch.object(Cluster, "kube", return_value=""),
        ):
            with self.assertRaisesRegex(ValueError, "Missing secret"):
                Cluster(Path.cwd()).deployment_env()

    def test_failed_rollout_never_reports_infrastructure_ready(self) -> None:
        """Do not report usable infrastructure after a failed workload rollout."""
        workload = {
            "items": [
                {
                    "kind": "Deployment",
                    "metadata": {
                        "name": "api",
                        "labels": {"app.kubernetes.io/instance": "onyx"},
                    },
                    "spec": {"replicas": 1},
                }
            ]
        }
        output = io.StringIO()
        with (
            patch.object(
                Cluster,
                "kube",
                side_effect=[
                    json.dumps(workload),
                    subprocess.CalledProcessError(1, ["kubectl", "rollout"]),
                ],
            ),
            contextlib.redirect_stdout(output),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                Cluster(Path.cwd()).infrastructure_ready()
        self.assertNotIn("Infrastructure ready.", output.getvalue())

    def test_application_readiness_rejects_html_health_and_requires_real_payload(
        self,
    ) -> None:
        """Reject login-page responses as API health while accepting a ready API and frontend."""
        health = {"ready": False}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                api = self.path.endswith("/api/health/ready")
                body = (
                    b'{"success":true}'
                    if api and health["ready"]
                    else b"<html>login page</html>"
                )
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json" if api and health["ready"] else "text/html",
                )
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            with self.assertRaisesRegex(ValueError, "Timed out"):
                application_ready(url, timeout=0.05)
            health["ready"] = True
            with contextlib.redirect_stdout(io.StringIO()):
                application_ready(url, timeout=1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_application_readiness_rejects_non_http_urls(self) -> None:
        """Restrict readiness probes to HTTP and HTTPS endpoints."""
        with self.assertRaisesRegex(ValueError, "HTTP"):
            application_ready("file:///etc/passwd")

    def test_intercept_recovers_known_stale_agents_after_failure_or_timeout(
        self,
    ) -> None:
        """Recover stale agent identities for both failures and timeouts without restarting unrelated failures."""
        for failure in (
            subprocess.CalledProcessError(1, ["telepresence", "intercept"]),
            subprocess.TimeoutExpired(["telepresence", "intercept"], 150),
        ):
            for stale in (False, True):
                logs = (
                    'rpc error: code = NotFound desc = Session "agent:stale" not found'
                    if stale
                    else "unrelated network failure"
                )
                with (
                    self.subTest(failure=type(failure).__name__, stale=stale),
                    patch.object(Cluster, "connect"),
                    patch.object(
                        Cluster,
                        "api_workload",
                        return_value={"metadata": {"name": "api"}},
                    ),
                    patch.object(Cluster, "intercept_active", return_value=False),
                    patch.object(
                        Cluster, "command", side_effect=[failure, ""]
                    ) as command,
                    patch.object(Cluster, "kube", return_value=logs) as kube,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    if stale:
                        Cluster(Path.cwd()).intercept()
                    else:
                        with self.assertRaises(type(failure)):
                            Cluster(Path.cwd()).intercept()
                    self.assertEqual(command.call_count, 2 if stale else 1)
                    restarts = [
                        call
                        for call in kube.call_args_list
                        if call.args[:2] == ("rollout", "restart")
                    ]
                    self.assertEqual(len(restarts), int(stale))

    def test_stale_intercept_recovery_retries_only_once(self) -> None:
        """Stop after one recovery attempt if intercept creation still fails."""
        with (
            patch.object(Cluster, "connect"),
            patch.object(
                Cluster, "api_workload", return_value={"metadata": {"name": "api"}}
            ),
            patch.object(Cluster, "intercept_active", return_value=False),
            patch.object(
                Cluster,
                "command",
                side_effect=subprocess.TimeoutExpired(
                    ["telepresence", "intercept"], 150
                ),
            ) as command,
            patch.object(
                Cluster,
                "kube",
                return_value='code = NotFound desc = Session "agent:stale" not found',
            ),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                Cluster(Path.cwd()).intercept()
        self.assertEqual(command.call_count, 2)

    def test_migrations_reject_overrides_to_another_database(self) -> None:
        """Prevent personal overrides from redirecting migrations away from the selected database."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "override.env"
            path.write_text("POSTGRES_HOST=other.example.com\n")
            with patch.object(
                Cluster,
                "deployment_env",
                return_value={"POSTGRES_HOST": "postgres.external.example.com"},
            ):
                with self.assertRaisesRegex(ValueError, "POSTGRES_HOST"):
                    Cluster(Path(directory)).database_environment(path)
            path.write_text("POSTGRES_DB=another_database\n")
            with patch.object(
                Cluster, "deployment_env", return_value={"POSTGRES_HOST": "database"}
            ):
                with self.assertRaisesRegex(ValueError, "POSTGRES_DB"):
                    Cluster(Path(directory)).database_environment(path)

    def test_readiness_requires_active_intercept_in_the_selected_context(self) -> None:
        """Require the selected local API intercept instead of accepting another cluster or waiting intercept."""
        cluster = Cluster(Path.cwd(), "selected")
        active = [
            {
                "name": "api",
                "intercept_info": [{"disposition": 1, "spec": {"name": "api"}}],
            }
        ]
        correct = {
            "user_daemon": {"kubernetes_context": "kind-selected", "namespace": "onyx"}
        }
        with patch.object(
            Cluster, "command", side_effect=[json.dumps(correct), json.dumps(active)]
        ):
            self.assertTrue(cluster.intercept_active("api"))
        active[0]["intercept_info"][0]["disposition"] = 2
        with patch.object(
            Cluster, "command", side_effect=[json.dumps(correct), json.dumps(active)]
        ):
            self.assertFalse(cluster.intercept_active("api"))
        with patch.object(
            Cluster,
            "command",
            return_value=json.dumps(
                {
                    "user_daemon": {
                        "kubernetes_context": "kind-other",
                        "namespace": "onyx",
                    }
                }
            ),
        ):
            self.assertFalse(cluster.intercept_active("api"))
        with (
            patch.object(
                Cluster, "api_workload", return_value={"metadata": {"name": "api"}}
            ),
            patch.object(Cluster, "intercept_active", return_value=False),
        ):
            with self.assertRaisesRegex(ValueError, "No active API intercept"):
                cluster.application_ready("http://localhost:3000", timeout=1)
