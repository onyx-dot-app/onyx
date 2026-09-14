"""Braintrust export for isolated v2 workers, using the existing Onyx processor."""

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def trace_question(args, write_json):
    project_id = os.environ.get("HARNESS_BRAINTRUST_PROJECT_ID")
    if args.arm != "candidate" or not project_id:
        yield
        return

    logging.disable(logging.CRITICAL)
    import braintrust

    from onyx.tracing.braintrust_tracing_processor import BraintrustTracingProcessor
    from onyx.tracing.framework import set_trace_processors
    from onyx.tracing.framework.create import trace

    question = json.loads(Path(args.question).read_text())
    config = json.loads(Path(args.config).read_text())
    metadata = {
        "harness": "v2",
        "question_id": question["question_id"],
        "experiment": config.get("experiment_name", Path(args.output).parent.name),
        "policy": config["policy"],
        "model": config["model"],
    }
    # Authenticate before spending tokens on a run that cannot be exported.
    braintrust.login(api_key=os.environ["BRAINTRUST_API_KEY"], force_login=True)
    logger = braintrust.init_logger(
        project_id=project_id,
        api_key=os.environ["BRAINTRUST_API_KEY"],
        async_flush=False,
    )
    processor = BraintrustTracingProcessor(logger)
    set_trace_processors([processor])
    root = logger.start_span(
        name=f"harness-v2/{question['question_id']}",
        type=braintrust.SpanTypeAttribute.TASK,
        input=question["question"],
        metadata=metadata,
        set_current=True,
    )
    receipt = {
        "project_id": project_id,
        "question_id": question["question_id"],
        "url": root.link(),
        "root_span_id": root.id,
        "flushed": False,
    }
    output = Path(args.output)
    write_json(output / "braintrust.json", receipt)
    try:
        with trace("harness-v2", metadata=metadata):
            yield
    finally:
        try:
            result_path = output / "result.json"
            if result_path.exists():
                result = json.loads(result_path.read_text())
                root.log(
                    output=result.get("answer"),
                    metadata={
                        "outcome": result.get("outcome"),
                        "run_id": result.get("run_id"),
                        "usage": result.get("usage"),
                    },
                )
            root.unset_current()
            root.end()
            processor.force_flush()
            receipt["flushed"] = True
            receipt["url"] = root.link()
            write_json(output / "braintrust.json", receipt)
        except Exception as exc:
            receipt["export_error_type"] = type(exc).__name__
            write_json(output / "braintrust.json", receipt)
            raise
        finally:
            set_trace_processors([])
