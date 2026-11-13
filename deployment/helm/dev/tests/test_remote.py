"""Contracts for running local Craft processes against a remote cluster profile."""

import base64
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import launch  # noqa: E402
import remote  # noqa: E402
from remote import (  # noqa: E402
    RemoteCluster,
    SecretMount,
    check_heads,
    egress_allowed,
    mounted_files,
    parse_profile,
    pick_port,
    secret_files,
    select_context,
    telepresence_problem,
)

PROFILE: dict[str, Any] = {
    "name": "craft-dev",
    "kube": {
        "context": "ctx-a",
        "allowed_contexts": ["ctx-a", "ctx-b"],
        "kubeconfig": "~/.kube/remote.yaml",
        "server": "https://api.example.test",
    },
    "aws": {
        "region": "region-1",
        "eks_cluster": "cluster-1",
        "account_id": 1234,
        "profile": "sso",
    },
    "namespaces": {"app": "onyx", "sandbox": "sandboxes", "agent": "agents"},
    "user": {"email": "dev@example.test"},
    "local_env": {"LOG_LEVEL": "DEBUG", "ENABLE_X": True},
}


def workload(**secret_volume: Any) -> dict[str, Any]:
    return {
        "metadata": {"name": "onyx-api-server"},
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": "api-server",
                            "volumeMounts": [
                                {
                                    "name": "agent-client",
                                    "mountPath": "/etc/agent",
                                    **secret_volume.pop("mount", {}),
                                },
                                {"name": "cache", "mountPath": "/var/cache/app"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "agent-client",
                            "secret": {"secretName": "client-tls", **secret_volume},
                        },
                        {"name": "cache", "emptyDir": {}},
                    ],
                }
            }
        },
    }


def secret_json(data: dict[str, bytes]) -> str:
    return json.dumps(
        {"data": {k: base64.b64encode(v).decode() for k, v in data.items()}}
    )


class ProfileTests(unittest.TestCase):
    def test_profile_parses_cluster_facts_from_data(self) -> None:
        profile = parse_profile(PROFILE)
        self.assertEqual(profile.context, "ctx-a")
        self.assertEqual(profile.allowed_contexts, ("ctx-a", "ctx-b"))
        self.assertEqual(profile.kubeconfig, Path("~/.kube/remote.yaml").expanduser())
        self.assertEqual(profile.aws_account_id, "1234")
        self.assertEqual(profile.agent_namespace, "agents")
        self.assertEqual(profile.agent_port, 7443)
        self.assertEqual(profile.user_email, "dev@example.test")
        self.assertEqual(profile.local_env, {"LOG_LEVEL": "DEBUG", "ENABLE_X": "true"})

    def test_profile_rejects_placeholders_and_unlisted_contexts(self) -> None:
        for broken in (
            {**PROFILE, "kube": {"context": "<context>"}},
            {**PROFILE, "kube": {"context": "ctx-c", "allowed_contexts": ["ctx-a"]}},
            {**PROFILE, "aws": {"region": "r"}},
            {**PROFILE, "namespaces": {"app": "onyx"}},
            {**PROFILE, "local_env": {"A": ["list"]}},
            "not a mapping",
        ):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                parse_profile(broken)

    def test_context_must_be_in_the_profile(self) -> None:
        profile = parse_profile(PROFILE)
        self.assertEqual(select_context(profile, None), "ctx-a")
        self.assertEqual(select_context(profile, "ctx-b"), "ctx-b")
        with self.assertRaisesRegex(ValueError, "refusing"):
            select_context(profile, "prod-cluster")

    def test_load_profile_reads_the_env_var_path(self) -> None:
        import yaml

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(yaml.safe_dump(PROFILE))
            with patch.dict(os.environ, {remote.PROFILE_ENV: str(path)}):
                self.assertEqual(remote.load_profile(Path(directory)).context, "ctx-a")
            with self.assertRaisesRegex(ValueError, remote.PROFILE_ENV):
                remote.load_profile(Path(directory), Path(directory) / "missing.yaml")


class RemoteClusterTests(unittest.TestCase):
    def cluster(self, root: Path | None = None) -> RemoteCluster:
        return RemoteCluster.from_profile(root or Path.cwd(), parse_profile(PROFILE))

    def test_kubectl_always_pins_kubeconfig_and_context(self) -> None:
        cluster = self.cluster()
        with patch.object(RemoteCluster, "command", return_value="") as command:
            cluster.kube("get", "pods")
        args = command.call_args.args
        self.assertEqual(
            args[:5],
            (
                "kubectl",
                "--kubeconfig",
                str(Path("~/.kube/remote.yaml").expanduser()),
                "--context",
                "ctx-a",
            ),
        )

    def test_server_mismatch_is_refused(self) -> None:
        cluster = self.cluster()
        with patch.object(
            RemoteCluster, "command", return_value="https://api.example.test/"
        ):
            cluster.verify_server()
        with (
            patch.object(RemoteCluster, "command", return_value="https://other.test"),
            self.assertRaisesRegex(ValueError, "another API server"),
        ):
            cluster.verify_server()

    def test_local_environment_overrides_and_pins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".vscode").mkdir()
            (root / ".vscode/.env.k8s").write_text("POSTGRES_HOST=kind-db\n")
            (root / f".vscode/.env.{remote.TARGET}").write_text(
                "SANDBOX_FC_TEMPLATE=devfc-me\nSANDBOX_BACKEND=docker\n"
                "K8S_CONTEXT=prod\nSENTRY_DSN=https://mine\n"
            )
            deployed = {
                "POSTGRES_HOST": "db.example.test",
                "SENTRY_DSN": "https://shared",
                "WEB_DOMAIN": "https://remote.example.test",
                "SANDBOX_BACKEND": "kubernetes",
                "SANDBOX_RUNTIME": "firecracker",
                "SANDBOX_FC_TEMPLATE": "shared",
                "LOG_LEVEL": "INFO",
                "INTERNAL_URL": "http://onyx-api-service:8080",
            }
            with patch.dict(os.environ, {}, clear=True):
                env = self.cluster(root).local_environment(
                    profile_env={"LOG_LEVEL": "DEBUG"}, settings=deployed
                )
        self.assertEqual(env["POSTGRES_HOST"], "db.example.test")
        self.assertEqual(env["WEB_DOMAIN"], "http://localhost:3000")
        self.assertEqual(env["LOG_LEVEL"], "DEBUG")
        self.assertEqual(env["SANDBOX_FC_TEMPLATE"], "devfc-me")
        self.assertEqual(env["SENTRY_DSN"], "https://mine")
        self.assertEqual(env["SANDBOX_BACKEND"], "kubernetes")
        self.assertEqual(env["SANDBOX_RUNTIME"], "firecracker")
        self.assertEqual(env["SANDBOX_NAMESPACE"], "sandboxes")
        self.assertEqual(env["K8S_CONTEXT"], "ctx-a")
        self.assertEqual(
            env["KUBECONFIG"], str(Path("~/.kube/remote.yaml").expanduser())
        )
        self.assertEqual(
            env["INTERNAL_URL"], "http://onyx-api-service.onyx.svc.cluster.local:8080"
        )

    def test_shared_sentry_is_blank_without_a_personal_value(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {}, clear=True),
        ):
            env = self.cluster(Path(directory)).local_environment(
                settings={"SENTRY_DSN": "https://shared"}
            )
        self.assertEqual(env["SENTRY_DSN"], "")


class SecretFileTests(unittest.TestCase):
    def test_secret_volume_files_are_private_and_removed(self) -> None:
        cluster = RemoteCluster.from_profile(Path.cwd(), parse_profile(PROFILE))
        env = {
            "CERT": "/etc/agent/tls.crt",
            "CA": "/etc/agent/ca.crt",
            "CACHE": "/var/cache/app/x",
            "OTHER": "/etc/agentx/tls.crt",
        }
        data = {"tls.crt": b"cert", "ca.crt": b"ca"}
        errors = io.StringIO()
        with (
            patch.object(RemoteCluster, "kube", return_value=secret_json(data)),
            contextlib.redirect_stderr(errors),
        ):
            with secret_files(cluster, env, workload()) as resolved:
                cert = Path(resolved["CERT"])
                tmp = cert.parents[1]
                self.assertEqual(cert.read_bytes(), b"cert")
                self.assertEqual(Path(resolved["CA"]).read_bytes(), b"ca")
                self.assertEqual(stat.S_IMODE(cert.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(tmp.stat().st_mode), 0o700)
                self.assertEqual(resolved["OTHER"], "/etc/agentx/tls.crt")
            self.assertFalse(tmp.exists())
            with self.assertRaises(RuntimeError):
                with secret_files(cluster, env, workload()) as resolved:
                    tmp = Path(resolved["CERT"]).parents[1]
                    raise RuntimeError("process failed")
            self.assertFalse(tmp.exists())
        self.assertEqual(env["CERT"], "/etc/agent/tls.crt")
        self.assertIn("CACHE", errors.getvalue())
        self.assertNotIn("cert", errors.getvalue().replace("CERT", ""))

    def test_items_and_sub_path_follow_the_pod_layout(self) -> None:
        cluster = RemoteCluster.from_profile(Path.cwd(), parse_profile(PROFILE))
        data = {"tls.crt": b"cert", "tls.key": b"key"}
        spec = workload(
            items=[{"key": "tls.key", "path": "keys/client.key"}],
            mount={"mountPath": "/etc/agent/client.key", "subPath": "keys/client.key"},
        )
        with (
            patch.object(RemoteCluster, "kube", return_value=secret_json(data)),
            contextlib.redirect_stderr(io.StringIO()),
            secret_files(cluster, {"KEY": "/etc/agent/client.key"}, spec) as resolved,
        ):
            self.assertEqual(Path(resolved["KEY"]).read_bytes(), b"key")

    def test_unsafe_secret_paths_are_refused(self) -> None:
        mount = SecretMount("v", "s", "/etc/v", None, (("k", "../escape"),), False)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            mounted_files(mount, {"k": b"x"})


class HeadTests(unittest.TestCase):
    def test_matching_heads_pass(self) -> None:
        check_heads({"b"}, {"a", "b"}, {"b"})

    def test_checkout_ahead_of_shared_database_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "never migrates"):
            check_heads({"c"}, {"a", "b", "c"}, {"b"})

    def test_database_ahead_of_checkout_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "Rebase"):
            check_heads({"b"}, {"a", "b"}, {"z"})
        with self.assertRaisesRegex(ValueError, "no Alembic version"):
            check_heads({"b"}, {"a", "b"}, set())

    def test_migration_ids_read_merges_without_imports(self) -> None:
        self.assertEqual(
            remote.migration_ids(
                'import onyx.missing\nrevision = "m"\ndown_revision = ("a", "b")\n'
            ),
            ("m", {"a", "b"}),
        )
        self.assertEqual(
            remote.migration_ids('revision: str = "r"\ndown_revision: None = None\n'),
            ("r", set()),
        )

    def test_checkout_revisions_load_from_the_real_tree(self) -> None:
        heads, known = remote.local_revisions(Path(__file__).resolve().parents[4])
        self.assertTrue(heads)
        self.assertTrue(heads <= known)


class TelepresenceAndNetworkTests(unittest.TestCase):
    def status(self, **user: Any) -> dict[str, Any]:
        return {
            "user_daemon": {
                "status": "Connected",
                "kubernetes_context": "ctx-a",
                "kubernetes_server": "https://api.example.test",
                "namespace": "onyx",
                **user,
            },
            "root_daemon": {"running": True},
        }

    def test_connection_must_match_the_profile(self) -> None:
        server = "https://api.example.test"
        self.assertIsNone(telepresence_problem(self.status(), "ctx-a", "onyx", server))
        for status, reason in (
            (self.status(status="Disconnected"), "not connected"),
            (self.status(kubernetes_context="kind-onyx-dev"), "another context"),
            (self.status(kubernetes_server="https://x"), "another API server"),
            (self.status(namespace="default"), "namespace"),
            ({**self.status(), "root_daemon": {"running": False}}, "root daemon"),
        ):
            problem = telepresence_problem(status, "ctx-a", "onyx", server)
            self.assertIsNotNone(problem)
            self.assertIn(reason, problem or "")

    def test_port_prefers_8080_then_any_free_port(self) -> None:
        self.assertEqual(pick_port(9001, lambda _: False), 9001)
        self.assertEqual(pick_port(None, lambda _: True), 8080)
        self.assertNotEqual(pick_port(None, lambda _: False), 8080)

    def test_egress_allowlist(self) -> None:
        self.assertTrue(egress_allowed("203.0.113.7", ["203.0.113.0/24"]))
        self.assertFalse(egress_allowed("198.51.100.1", ["203.0.113.7/32"]))


class LauncherTests(unittest.TestCase):
    def test_celery_is_refused_before_any_cluster_access(self) -> None:
        with (
            patch.object(
                sys, "argv", ["launch.py", "--target", remote.TARGET, "celery"]
            ),
            patch.object(remote, "load_profile") as load,
            self.assertRaisesRegex(ValueError, "Celery"),
        ):
            launch.main()
        load.assert_not_called()

    def test_api_refuses_a_disconnected_telepresence_before_reading_secrets(
        self,
    ) -> None:
        with (
            patch.object(sys, "argv", ["launch.py", "--target", remote.TARGET, "api"]),
            patch.object(remote, "load_profile", return_value=parse_profile(PROFILE)),
            patch.object(RemoteCluster, "verify_server"),
            patch.object(remote, "telepresence_status", return_value={}),
            patch.object(RemoteCluster, "api_workload") as api_workload,
            patch.object(launch, "run_api") as run_api,
            self.assertRaisesRegex(ValueError, "telepresence connect"),
        ):
            launch.main()
        api_workload.assert_not_called()
        run_api.assert_not_called()

    def test_api_refuses_a_head_mismatch_and_removes_secret_files(self) -> None:
        created: list[Path] = []
        real_mkdtemp = tempfile.mkdtemp

        def mkdtemp(**kwargs: Any) -> str:
            path = real_mkdtemp(**kwargs)
            created.append(Path(path))
            return path

        with (
            patch.object(sys, "argv", ["launch.py", "--target", remote.TARGET, "api"]),
            patch.object(remote, "load_profile", return_value=parse_profile(PROFILE)),
            patch.object(RemoteCluster, "verify_server"),
            patch.object(remote, "require_telepresence"),
            patch.object(RemoteCluster, "api_workload", return_value=workload()),
            patch.object(RemoteCluster, "local_environment", return_value={}),
            patch.object(RemoteCluster, "kube", return_value=secret_json({})),
            patch.object(remote.tempfile, "mkdtemp", side_effect=mkdtemp),
            patch.object(remote, "local_revisions", return_value=({"c"}, {"b", "c"})),
            patch.object(remote, "db_revisions", return_value={"b"}),
            patch.object(launch, "run_api") as run_api,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(ValueError, "never migrates"),
        ):
            launch.main()
        run_api.assert_not_called()
        self.assertTrue(created)
        self.assertFalse(any(path.exists() for path in created))


if __name__ == "__main__":
    unittest.main()
