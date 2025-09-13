#!/usr/bin/env python3
"""
CLI for running evaluations with local configurations.
"""

import argparse
import json
import os
from typing import Any

import requests
from braintrust import init_dataset
from braintrust.logger import Dataset

from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.constants import POSTGRES_WEB_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.evals.eval import eval as run_eval
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvaluationResult


def setup_session_factory():
    SqlEngine.set_app_name(POSTGRES_WEB_APP_NAME)
    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )


def load_data_local(
    braintrust_project: str,
    local_data_path: str | None,
    remote_dataset_name: str | None,
) -> Dataset | list[Any]:
    """
    Load data from either a local JSON file or remote Braintrust dataset.

    Args:
        local_data_path: Path to local JSON file
        remote_dataset_name: Name of remote Braintrust dataset

    Returns:
        List of test data for evaluation

    Raises:
        ValueError: If neither argument is provided or if provided path doesn't exist
    """
    if local_data_path and remote_dataset_name:
        raise ValueError("Cannot specify both local_data_path and remote_dataset_name")

    if remote_dataset_name:
        return init_dataset(project=braintrust_project, name=remote_dataset_name)

    if local_data_path is None:
        local_data_path = "evals/data/data.json"

    if not os.path.isfile(local_data_path):
        raise ValueError(f"Local data file does not exist: {local_data_path}")
    with open(local_data_path, "r") as f:
        return json.load(f)


def run_local(
    braintrust_project: str,
    local_data_path: str | None,
    remote_dataset_name: str | None,
    impersonation_email: str | None = None,
) -> EvaluationResult:
    """
    Run evaluation with local configurations.

    Args:
        local_data_path: Path to local JSON file
        remote_dataset_name: Name of remote Braintrust dataset
        braintrust_project: Optional Braintrust project name. If not provided,
                          will use BRAINTRUST_PROJECT environment variable.
        impersonation_email: Optional email address to impersonate for the evaluation

    Returns:
        EvaluationResult: The evaluation result
    """
    setup_session_factory()
    data = load_data_local(braintrust_project, local_data_path, remote_dataset_name)
    configuration = EvalConfigurationOptions(
        impersonation_email=impersonation_email,
        dataset_name=remote_dataset_name or "blank",
    )

    score = run_eval(data, configuration)

    return score


def run_remote(
    base_url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    impersonation_email: str | None = None,
) -> dict[str, Any]:
    """
    Trigger an eval pipeline execution on a remote server.

    Args:
        base_url: Base URL of the remote server (e.g., "https://test.onyx.app")
        api_key: API key for authentication
        payload: Optional payload to send with the request
        impersonation_email: Optional email address to impersonate for the evaluation

    Returns:
        Response from the remote server

    Raises:
        requests.RequestException: If the request fails
    """
    if payload is None:
        payload = {}

    if impersonation_email:
        payload["impersonation_email"] = impersonation_email

    payload["dataset_name"] = "Simple"

    url = f"{base_url}/evals/eval_run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run evaluations with local configurations"
    )

    parser.add_argument(
        "--local-data-path",
        type=str,
        help="Path to local JSON file containing test data",
    )

    parser.add_argument(
        "--remote-dataset-name", type=str, help="Name of remote Braintrust dataset"
    )

    parser.add_argument(
        "--braintrust-project",
        type=str,
        help="Braintrust project name",
        default="Onyx",
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    # Remote eval arguments
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://test.onyx.app",
        help="Base URL of the remote server (default: https://test.onyx.app)",
    )

    parser.add_argument(
        "--api-key",
        type=str,
        help="API key for authentication with the remote server",
    )

    parser.add_argument(
        "--remote",
        action="store_true",
        help="Run evaluation on remote server instead of locally",
    )

    parser.add_argument(
        "--impersonation-email",
        type=str,
        help="Email address to impersonate for the evaluation",
    )

    args = parser.parse_args()

    if args.local_data_path:
        print(f"Loading data from local file: {args.local_data_path}")
    elif args.remote_dataset_name:
        print(f"Loading data from remote dataset: {args.remote_dataset_name}")

    if args.remote:
        if not args.api_key:
            print("Error: --api-key is required when using --remote")
            return

        print(f"Running evaluation on remote server: {args.base_url}")
        print(f"Using API key: {args.api_key[:8]}...")

        if args.impersonation_email:
            print(f"Using impersonation email: {args.impersonation_email}")

        try:
            result = run_remote(
                args.base_url,
                args.api_key,
                impersonation_email=args.impersonation_email,
            )
            print(f"Remote evaluation triggered successfully: {result}")
        except requests.RequestException as e:
            print(f"Error triggering remote evaluation: {e}")
            return
    else:
        print(f"Using Braintrust project: {args.braintrust_project}")

        if args.impersonation_email:
            print(f"Using impersonation email: {args.impersonation_email}")

        run_local(
            args.braintrust_project,
            args.local_data_path,
            args.remote_dataset_name,
            args.impersonation_email,
        )


if __name__ == "__main__":
    main()
