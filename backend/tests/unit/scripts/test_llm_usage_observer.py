import concurrent.futures
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[3] / "scripts/llm_usage_observer.py"
spec = importlib.util.spec_from_file_location("usage_observer", SOURCE)
assert spec is not None and spec.loader is not None
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ObserverTests(unittest.TestCase):
    def test_parallel_calls_preserve_results_and_keep_records_separate(self):
        class Ledger:
            def estimate_tokens(self, prompt, _tools):
                return len(prompt)

            def reserve_llm_call(self, **kwargs):
                time.sleep(0.002)
                return SimpleNamespace(
                    prompt_tokens=kwargs["prompt_tokens"],
                    max_output_tokens=128000,
                    token_reservation=128000 + kwargs["prompt_tokens"],
                )

            def record_success(self, reservation, usage):
                pass

            def record_failure(self, reservation):
                pass

        class LLM:
            def invoke(self, *, prompt, response, ledger):
                size = ledger.estimate_tokens(prompt, None)
                reservation = ledger.reserve_llm_call(
                    prompt_tokens=size, requested_max_output_tokens=None
                )
                ledger.record_success(reservation, response.usage)
                return response

        def write(path, value):
            path.write_text(json.dumps(value))

        original = LLM.invoke
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            restore = observer.install_usage_observer(
                Ledger, LLM, output, write, operation=lambda: "test"
            )
            try:

                def call(i):
                    usage = SimpleNamespace(
                        model_dump=lambda **_kwargs: {
                            "prompt_tokens": i + 1,
                            "completion_tokens": i,
                            "total_tokens": 2 * i + 1,
                        }
                    )
                    response = SimpleNamespace(
                        choice=SimpleNamespace(finish_reason="stop"), usage=usage
                    )
                    returned = LLM().invoke(
                        prompt="x" * (i + 1), response=response, ledger=Ledger()
                    )
                    self.assertIs(returned, response)

                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(call, range(12)))
                records = [
                    json.loads(p.read_text()) for p in output.glob("llm-call-*.json")
                ]
                self.assertEqual(len(records), 12)
                self.assertEqual(len({r["call_id"] for r in records}), 12)
                for r in records:
                    self.assertEqual(
                        r["reserved_prompt_tokens"], r["usage"]["prompt_tokens"]
                    )
                    self.assertEqual(r["output_allowance_tokens"], 128000)
                    self.assertGreaterEqual(r["reservation_acquisition_ms"], 0)
                    self.assertLessEqual(r["granted_at_ms"], r["released_at_ms"])
                    self.assertNotIn("prompt", r)
            finally:
                restore()
        self.assertIs(LLM.invoke, original)

    def test_failure_is_reraised_without_recording_exception_text(self):
        class Ledger:
            def estimate_tokens(self, *args, **kwargs):
                pass

            def reserve_llm_call(self, *args, **kwargs):
                pass

            def record_success(self, *args, **kwargs):
                pass

            def record_failure(self, *args, **kwargs):
                pass

        class LLM:
            def invoke(self):
                raise ValueError("provider-secret-value")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            restore = observer.install_usage_observer(
                Ledger,
                LLM,
                output,
                lambda p, v: p.write_text(json.dumps(v)),
                operation=lambda: "test",
            )
            try:
                with self.assertRaisesRegex(ValueError, "provider-secret-value"):
                    LLM().invoke()
                raw = next(output.glob("llm-call-*.json")).read_text()
                r = json.loads(raw)
                self.assertNotIn("provider-secret-value", raw)
                self.assertEqual(r["error_type"], "ValueError")
                self.assertIsNone(r["usage"])
            finally:
                restore()


if __name__ == "__main__":
    unittest.main()
