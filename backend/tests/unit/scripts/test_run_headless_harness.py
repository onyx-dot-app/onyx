"""Host-side contracts; no backend dependencies or live services required."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/run_headless_harness.py"
spec = importlib.util.spec_from_file_location("headless_launcher", SCRIPT)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class HeadlessContracts(unittest.TestCase):
    def test_question_selection_strips_gold_and_retains_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "questions.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "question_id": q,
                            "question": q + "?",
                            "gold_answer": "SECRET_GOLD",
                            "expected_doc_ids": ["GOLD_ID"],
                        }
                    )
                    for q in ["q1", "q2"]
                )
            )
            selected = runner.select_questions(path, ["q2", "q1"])
            self.assertEqual(
                selected,
                [
                    {"question_id": "q2", "question": "q2?"},
                    {"question_id": "q1", "question": "q1?"},
                ],
            )
            for ids in [["../q1"], ["q1", "q1"], ["missing"]]:
                with self.assertRaises(ValueError):
                    runner.select_questions(path, ids)

    def test_artifact_writer_redacts_environment_and_provider_credentials(self):
        worker_spec = importlib.util.spec_from_file_location(
            "headless_worker", SCRIPT.with_name("headless_harness_worker.py")
        )
        assert worker_spec and worker_spec.loader
        worker = importlib.util.module_from_spec(worker_spec)
        worker_spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "result.json"
            with patch.object(worker, "SECRET_VALUES", {"sensitive-test-key"}):
                worker.write_json(
                    path,
                    {
                        "message": "Error using sensitive-test-key",
                        "citations": {1: "doc-1"},
                    },
                )
            result = json.loads(path.read_text())
            self.assertEqual(result["message"], "Error using [REDACTED]")
            self.assertEqual(result["citations"], {"1": "doc-1"})

    def test_decision_capture_preserves_inputs_outputs_and_redacts_artifacts(self):
        spec = importlib.util.spec_from_file_location(
            "recording_worker", SCRIPT.with_name("headless_harness_worker.py")
        )
        assert spec is not None and spec.loader is not None
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            result = Mock()
            result.model_dump.return_value = {
                "answer": "sensitive-test-key",
                "calls": [],
            }
            inner = Mock()
            inner.decide.return_value = result
            recording = worker.RecordingDecisionModel(inner, output)
            with patch.object(worker, "SECRET_VALUES", {"sensitive-test-key"}):
                actual = recording.decide(
                    context="sensitive-test-key", remaining_tokens=1000
                )
            self.assertIs(actual, result)
            inner.decide.assert_called_once_with(
                context="sensitive-test-key", remaining_tokens=1000
            )
            self.assertEqual(
                json.loads((output / "decision-001/request.json").read_text())[
                    "context"
                ],
                "[REDACTED]",
            )
            self.assertEqual(
                json.loads((output / "decision-001/response.json").read_text())[
                    "answer"
                ],
                "[REDACTED]",
            )
            inner.decide.side_effect = RuntimeError("sensitive-provider-detail")
            with self.assertRaises(RuntimeError):
                recording.decide(context="next")
            self.assertEqual(
                json.loads((output / "decision-002/error.json").read_text()),
                {"error_type": "RuntimeError"},
            )
            self.assertTrue((output / "decision-002/timing.json").exists())

    def test_refuses_other_host_before_docker_access(self):
        with (
            patch.object(runner.socket, "gethostname", return_value="another-host"),
            patch.object(runner.subprocess, "check_output") as inspect,
        ):
            with self.assertRaises(ValueError):
                runner.inspect_runtime()
            inspect.assert_not_called()

    def test_refuses_wrong_corpus(self):
        runtime = {
            "Image": runner.IMAGE,
            "State": {"Running": True},
            "NetworkSettings": {"Networks": {"onyx_default": {}}},
            "Config": {
                "Env": ["POSTGRES_DB=production", "REDIS_HOST=onyx-corpus-v2-cache"]
            },
        }
        with (
            patch.object(
                runner.socket,
                "gethostname",
                return_value="ip-172-31-7-162.us-west-1.compute.internal",
            ),
            patch.object(
                runner.subprocess, "check_output", return_value=json.dumps([runtime])
            ),
        ):
            with self.assertRaises(ValueError):
                runner.inspect_runtime()

    def test_timeout_removes_only_created_container_and_keeps_env_off_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "arm").mkdir()
            timeout = runner.subprocess.TimeoutExpired(cmd="docker", timeout=1)
            with patch.object(
                runner.subprocess, "run", side_effect=[timeout, None]
            ) as run:
                result = runner.launch(
                    output, "PASSWORD=secret-value\n", [], "candidate", None, "arm", 1
                )
            self.assertEqual(result["status"], "host_timeout")
            create_call, remove_call = run.call_args_list
            create_argv = create_call.args[0]
            self.assertNotIn("secret-value", " ".join(create_argv))
            self.assertEqual(create_call.kwargs["input"], "PASSWORD=secret-value\n")
            container = create_argv[create_argv.index("--name") + 1]
            self.assertTrue(container.startswith("onyx-headless-"))
            self.assertEqual(
                remove_call.args[0], runner.DOCKER + ["rm", "-f", container]
            )
            self.assertNotIn(
                "secret-value", (output / "arm/container.json").read_text()
            )

    def test_summary_keeps_failures_in_latency_sample(self):
        rows = [
            {
                "arm": "candidate",
                "question_id": "q1",
                "outcome": "completed",
                "container_wall_ms": 10,
            },
            {
                "arm": "candidate",
                "question_id": "q2",
                "outcome": "host_timeout",
                "container_wall_ms": 100,
            },
        ]
        summary = runner.summarize(rows)["arms"]["candidate"]
        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["failures"], ["q2"])
        self.assertEqual(summary["container_wall_ms"]["max"], 100)


if __name__ == "__main__":
    unittest.main()
