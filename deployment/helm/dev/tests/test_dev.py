"""Exercise lifecycle tooling without a Docker daemon or Kubernetes cluster."""

import argparse
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

SPEC = importlib.util.spec_from_file_location(
    "onyx_dev", Path(__file__).parents[1] / "dev.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load development CLI")
dev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dev)


def options(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "cluster_name": "test",
        "namespace": "onyx",
        "sandbox_namespace": "sandboxes",
        "only": "sandbox",
        "check": False,
        "force": False,
        "reuse": False,
        "load_only": False,
        "apply": False,
        "build_cache": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class DevTests(unittest.TestCase):
    def test_doctor_reports_invalid_image_without_exposing_secrets(self) -> None:
        server_version = "v1.37.0"
        template_image = dev.IMAGES["sandbox"][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".venv").symlink_to(
                Path(sys.executable).parent.parent, target_is_directory=True
            )
            (root / ".vscode").mkdir()
            env_file = root / ".vscode/.env.k8s"
            env_file.write_text(
                "POSTGRES_HOST=onyx-pg-rw\nSANDBOX_PROXY_HOST=proxy\n"
                f"SANDBOX_CONTAINER_IMAGE={dev.IMAGES['sandbox'][0]}\nONYX_SERVER_URL=http://localhost\n"
                "ONYX_SANDBOX_PUSH_PRIVATE_KEY=private-value\nGEN_AI_API_KEY=secret-value\n"
                "K8S_CONTEXT=kind-test\nSANDBOX_BACKEND=kubernetes\nSANDBOX_NAMESPACE=sandboxes\n"
            )

            def probe(
                command: tuple[str, ...], **_kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                if "-c" in command:
                    from dotenv import dotenv_values

                    env = dotenv_values(env_file)
                    body = json.dumps(
                        {
                            "missing": [],
                            "model_key": bool(env.get("GEN_AI_API_KEY")),
                            "image": env.get("SANDBOX_CONTAINER_IMAGE")
                            == dev.IMAGES["sandbox"][0],
                        }
                    )
                    return subprocess.CompletedProcess(
                        command, 0, stdout=body, stderr=""
                    )
                if command[0] == "docker":
                    body = "29.0.0"
                elif "version" in command:
                    body = json.dumps(
                        {
                            "clientVersion": {"gitVersion": "v1.37.1"},
                            "serverVersion": {"gitVersion": server_version},
                        }
                    )
                elif "podtemplate" in command:
                    body = json.dumps(
                        {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "name": name,
                                            "image": template_image,
                                            "imagePullPolicy": "IfNotPresent",
                                        }
                                        for name in (
                                            "sandbox",
                                            "sandbox-init",
                                            "sidecar",
                                        )
                                    ]
                                }
                            }
                        }
                    )
                elif "nodes" in command:
                    body = json.dumps(
                        {
                            "items": [
                                {
                                    "status": {
                                        "conditions": [
                                            {"type": "Ready", "status": "True"}
                                        ]
                                    }
                                }
                            ]
                        }
                    )
                else:
                    body = json.dumps(
                        {
                            "user_daemon": {
                                "version": "2.31.2",
                                "status": "Connected",
                                "kubernetes_context": "kind-test",
                                "namespace": "onyx",
                            },
                            "root_daemon": {"running": True},
                        }
                    )
                return subprocess.CompletedProcess(command, 0, stdout=body, stderr="")

            output = io.StringIO()
            with (
                patch.object(dev, "ROOT", root),
                patch.object(dev.shutil, "which", return_value="/usr/bin/tool"),
                patch.object(dev.subprocess, "run", side_effect=probe),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(dev.doctor(options()), 0)
                env_file.write_text(
                    env_file.read_text().replace(
                        f"SANDBOX_CONTAINER_IMAGE={dev.IMAGES['sandbox'][0]}",
                        "SANDBOX_CONTAINER_IMAGE=wrong:tag",
                    )
                )
                self.assertEqual(dev.doctor(options()), 1)
                env_file.write_text(
                    env_file.read_text().replace(
                        "SANDBOX_CONTAINER_IMAGE=wrong:tag",
                        f"SANDBOX_CONTAINER_IMAGE={dev.IMAGES['sandbox'][0]}",
                    )
                )
                server_version = "v1.33.1"
                self.assertEqual(dev.doctor(options()), 1)
                server_version = "v1.37.0"
                template_image = "sandbox:edge"
                self.assertEqual(dev.doctor(options()), 1)
            self.assertNotIn("private-value", output.getvalue())
            self.assertNotIn("secret-value", output.getvalue())
            self.assertIn("Effective sandbox image matches", output.getvalue())

    def test_doctor_continues_after_unavailable_tools_and_timeouts(self) -> None:
        output = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(dev, "ROOT", Path(directory)),
            patch.object(
                dev.shutil,
                "which",
                side_effect=lambda name: None if name == "helm" else "/usr/bin/tool",
            ),
            patch.object(
                dev.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("probe", 20),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(dev.doctor(options()), 1)
        self.assertIn("helm: missing", output.getvalue())
        self.assertIn("socket permissions", output.getvalue())
        self.assertIn("API unavailable", output.getvalue())
        self.assertIn("Checkout Python environment", output.getvalue())

    def test_fingerprint_detects_dirty_untracked_and_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            (root / "backend").mkdir()
            source = root / "backend/source.py"
            source.write_text("original")
            subprocess.run(["git", "-C", directory, "add", "."], check=True)
            with patch.object(dev, "ROOT", root):
                original = dev.source_hash("backend")
                source.write_text("dirty")
                self.assertNotEqual(original, dev.source_hash("backend"))
                source.write_text("original")
                self.assertEqual(original, dev.source_hash("backend"))
                (root / "backend/new.py").write_text("untracked")
                added = dev.source_hash("backend")
                self.assertNotEqual(original, added)
                source.unlink()
                self.assertNotEqual(added, dev.source_hash("backend"))

    def test_refresh_patches_main_and_init_images_without_deleting_pods(self) -> None:
        calls: list[tuple[str, ...]] = []
        template = {
            "template": {
                "spec": {
                    "containers": [{"name": "sandbox"}],
                    "initContainers": [{"name": "sandbox-init"}, {"name": "sidecar"}],
                }
            }
        }

        def run(*args: str, **_kwargs: object) -> str:
            calls.append(args)
            return (
                json.dumps(template) if "get" in args and "podtemplate" in args else ""
            )

        with (
            patch.object(dev, "nodes"),
            patch.object(dev, "source_hash", return_value="new"),
            patch.object(
                dev,
                "inspect_image",
                return_value={"Config": {"Labels": {dev.SOURCE_LABEL: "old"}}},
            ),
            patch.object(dev, "run", side_effect=run),
        ):
            self.assertEqual(dev.images(options()), 0)
        build = next(call for call in calls if call[:2] == ("docker", "build"))
        self.assertIn(f"{dev.LABEL}=true", build)
        command = next(call for call in calls if "patch" in call)
        self.assertIn("kind-test", command)
        self.assertIn("sandboxes", command)
        patches = json.loads(command[-1])
        self.assertEqual(len(patches), 6)
        self.assertFalse(any("delete" in call for call in calls))

    def test_startup_reuses_old_image_without_a_build(self) -> None:
        with (
            patch.object(dev, "nodes"),
            patch.object(dev, "source_hash", return_value="new"),
            patch.object(dev, "inspect_image", return_value={"Config": {"Labels": {}}}),
            patch.object(dev, "run") as run,
        ):
            dev.images(options(reuse=True, load_only=True))
        self.assertFalse(
            any(call.args[:2] == ("docker", "build") for call in run.call_args_list)
        )
        self.assertEqual(run.call_count, 1)

    def test_reuse_missing_image_fails_without_building(self) -> None:
        with (
            patch.object(dev, "nodes"),
            patch.object(dev, "source_hash", return_value="new"),
            patch.object(dev, "inspect_image", return_value=None),
            patch.object(dev, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "missing"):
                dev.images(options(reuse=True))
        run.assert_not_called()

    def test_check_reports_dirty_source_and_never_mutates_runtime(self) -> None:
        with (
            patch.object(dev, "nodes"),
            patch.object(dev, "source_hash", return_value="new"),
            patch.object(
                dev,
                "inspect_image",
                return_value={"Config": {"Labels": {dev.SOURCE_LABEL: "old"}}},
            ),
            patch.object(dev, "run") as run,
        ):
            self.assertEqual(dev.images(options(check=True)), 1)
        run.assert_not_called()

    def test_daemon_error_is_not_a_missing_image(self) -> None:
        failure = subprocess.CompletedProcess([], 1, "", "permission denied")
        with (
            patch.object(dev, "run"),
            patch.object(dev.subprocess, "run", return_value=failure),
        ):
            with self.assertRaisesRegex(ValueError, "permission denied"):
                dev.inspect_image("test")

    def test_cleanup_preserves_other_checkouts_and_referenced_images(self) -> None:
        calls: list[tuple[str, ...]] = []

        def run(*args: str, **_kwargs: object) -> str:
            calls.append(args)
            if args[:3] == ("docker", "image", "ls"):
                return "ours\nother\nused"
            return "container" if "ancestor=used" in args else ""

        def inspect(image: str) -> dict[str, object]:
            return {
                "Config": {
                    "Labels": {
                        dev.OWNER_LABEL: "other" if image == "other" else str(dev.ROOT)
                    }
                }
            }

        with (
            patch.object(dev, "run", side_effect=run),
            patch.object(dev, "inspect_image", side_effect=inspect),
        ):
            dev.clean(options(apply=True))
        removed = [call for call in calls if call[:3] == ("docker", "image", "rm")]
        self.assertEqual(removed, [("docker", "image", "rm", "ours")])
        self.assertFalse(any("prune" in call for call in calls))

    def test_cleanup_is_preview_by_default_even_for_build_cache(self) -> None:
        with patch.object(dev, "run", return_value="") as run:
            dev.clean(options(build_cache=True))
        self.assertFalse(
            any(
                "prune" in call.args or "rm" in call.args for call in run.call_args_list
            )
        )

    def test_pause_preserves_other_telepresence_connection_and_all_volumes(
        self,
    ) -> None:
        with (
            patch.object(dev, "nodes", return_value=["test-control", "test-worker"]),
            patch.object(
                dev,
                "run",
                return_value=json.dumps(
                    {"user_daemon": {"kubernetes_context": "production"}}
                ),
            ) as run,
        ):
            dev.pause_resume(options(command="pause"))
        self.assertEqual(
            run.call_args.args, ("docker", "stop", "test-control", "test-worker")
        )
        self.assertFalse(
            any("quit" in call.args or "rm" in call.args for call in run.call_args_list)
        )

    def test_pause_disconnects_selected_cluster_before_stopping_nodes(self) -> None:
        with (
            patch.object(dev, "nodes", return_value=["test-control"]),
            patch.object(
                dev,
                "run",
                return_value=json.dumps(
                    {"user_daemon": {"kubernetes_context": "kind-test"}}
                ),
            ) as run,
        ):
            dev.pause_resume(options(command="pause"))
        self.assertEqual(run.call_args_list[-2].args, ("telepresence", "quit"))
        self.assertEqual(
            run.call_args_list[-1].args, ("docker", "stop", "test-control")
        )

    def test_migration_rejects_non_cluster_database_before_connecting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "env"
            env_file.write_text("POSTGRES_HOST=production.example.com\n")
            with (
                patch.object(
                    dev.Cluster,
                    "deployment_env",
                    return_value={"POSTGRES_HOST": "onyx-pg-rw"},
                ),
                patch.object(dev, "nodes"),
                patch.object(dev, "run") as run,
            ):
                with self.assertRaisesRegex(ValueError, "POSTGRES_HOST"):
                    dev.migrate(options(operation="upgrade", env_file=env_file))
            run.assert_not_called()

    def test_migration_refuses_running_application_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "env"
            env_file.write_text("POSTGRES_HOST=onyx-pg-rw\n")
            process = SimpleNamespace(
                pid=123,
                info={
                    "cmdline": [str(dev.ROOT / "deployment/helm/dev/launch.py"), "api"],
                    "cwd": str(dev.ROOT / "backend"),
                    "uids": SimpleNamespace(real=dev.os.getuid()),
                },
            )
            with (
                patch.object(
                    dev.Cluster,
                    "deployment_env",
                    return_value={"POSTGRES_HOST": "onyx-pg-rw"},
                ),
                patch.object(dev, "nodes"),
                patch.object(dev, "run"),
                patch("psutil.process_iter", return_value=[process]),
                patch.object(dev.subprocess, "run") as migrate,
            ):
                with self.assertRaisesRegex(ValueError, "PID 123"):
                    dev.migrate(options(operation="upgrade", env_file=env_file))
            migrate.assert_not_called()

    def test_migration_ignores_container_and_other_checkout_processes(self) -> None:
        processes = [
            SimpleNamespace(
                pid=index,
                info={
                    "cmdline": ["uvicorn", "onyx.main:app"],
                    "cwd": directory,
                    "uids": SimpleNamespace(real=dev.os.getuid()),
                },
            )
            for index, directory in enumerate((None, "/app", "/other-checkout"))
        ]
        with (
            patch.object(dev.Cluster, "database_environment", return_value={}),
            patch("psutil.process_iter", return_value=processes),
            patch.object(dev, "run"),
            patch.object(dev.subprocess, "run") as migrate,
        ):
            dev.migrate(options(operation="upgrade", env_file=None))
        self.assertEqual(migrate.call_count, 3)

    def test_failed_migration_stops_without_postcheck(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "env"
            env_file.write_text("POSTGRES_HOST=onyx-pg-rw\nPOSTGRES_PASSWORD=test\n")
            with (
                patch.object(
                    dev.Cluster,
                    "deployment_env",
                    return_value={"POSTGRES_HOST": "onyx-pg-rw"},
                ),
                patch.object(dev, "nodes"),
                patch.object(dev, "run") as connect,
                patch("psutil.process_iter", return_value=[]),
                patch.object(
                    dev.subprocess,
                    "run",
                    side_effect=[
                        subprocess.CompletedProcess([], 0),
                        subprocess.CalledProcessError(1, ["alembic"]),
                    ],
                ) as migrate,
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    dev.migrate(options(operation="upgrade", env_file=env_file))
            self.assertEqual(migrate.call_count, 2)
            self.assertEqual(
                migrate.call_args.kwargs["env"]["POSTGRES_HOST"],
                "onyx-pg-rw.onyx.svc.cluster.local",
            )
            self.assertIn("kind-test", connect.call_args.args)


if __name__ == "__main__":
    unittest.main()
