#!/usr/bin/env python3
"""
CLI for running evaluations with local configurations.
"""

import argparse
import json
import os
from typing import Any

import braintrust
import requests

from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.constants import POSTGRES_WEB_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.evals.eval import run_eval
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.tracing.braintrust_tracing import setup_braintrust_if_creds_available


def setup_session_factory() -> None:
    SqlEngine.set_app_name(POSTGRES_WEB_APP_NAME)
    SqlEngine.init_engine(
        pool_size=POSTGRES_API_SERVER_POOL_SIZE,
        max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
    )


def load_data_local(
    local_data_path: str,
) -> list[dict[str, dict[str, str]]]:
    if not os.path.isfile(local_data_path):
        raise ValueError(f"Local data file does not exist: {local_data_path}")
    with open(local_data_path, "r") as f:
        return json.load(f)


def run_local(
    local_data_path: str | None,
    remote_dataset_name: str | None,
    search_permissions_email: str | None = None,
    no_send_logs: bool = False,
) -> EvalationAck:
    """
    Run evaluation with local configurations.

    Args:
        local_data_path: Path to local JSON file
        remote_dataset_name: Name of remote Braintrust dataset
        search_permissions_email: Optional email address to impersonate for the evaluation

    Returns:
        EvalationAck: The evaluation result
    """
    setup_session_factory()
    setup_braintrust_if_creds_available()

    if search_permissions_email is None:
        raise ValueError("search_permissions_email is required for local evaluation")

    configuration = EvalConfigurationOptions(
        search_permissions_email=search_permissions_email,
        dataset_name=remote_dataset_name or "blank",
        no_send_logs=no_send_logs,
    )

    if remote_dataset_name:
        score = run_eval(
            configuration=configuration, remote_dataset_name=remote_dataset_name
        )
    else:
        if local_data_path is None:
            raise ValueError(
                "local_data_path or remote_dataset_name is required for local evaluation"
            )
        data = load_data_local(local_data_path)
        score = run_eval(configuration=configuration, data=data)

    return score


def run_remote(
    base_url: str,
    api_key: str,
    remote_dataset_name: str,
    search_permissions_email: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Trigger an eval pipeline execution on a remote server.

    Args:
        base_url: Base URL of the remote server (e.g., "https://test.onyx.app")
        api_key: API key for authentication
        payload: Optional payload to send with the request
        search_permissions_email: Email address to use for the evaluation. Search will have the permissions of this user.

    Returns:
        Response from the remote server

    Raises:
        requests.RequestException: If the request fails
    """
    if payload is None:
        payload = {}

    payload["search_permissions_email"] = search_permissions_email
    payload["dataset_name"] = remote_dataset_name

    url = f"{base_url}/api/evals/eval_run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload)

    response.raise_for_status()
    return response.json()


def main() -> None:
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
        "--remote-dataset-name",
        type=str,
        help="Name of remote Braintrust dataset",
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
        "--search-permissions-email",
        type=str,
        help="Email address to impersonate for the evaluation",
    )

    parser.add_argument(
        "--no-send-logs",
        action="store_true",
        help="Do not send logs to the remote server",
        default=False,
    )

    args = parser.parse_args()

    if args.local_data_path:
        print(f"Loading data from local file: {args.local_data_path}")
    elif args.remote_dataset_name:
        print(f"Loading data from remote dataset: {args.remote_dataset_name}")
        dataset = braintrust.init_dataset(
            project=args.braintrust_project, name=args.remote_dataset_name
        )
        dataset_size = len(list(dataset.fetch()))
        print(f"Dataset size: {dataset_size}")
    if args.remote:
        if not args.api_key:
            print("Using API Key from ONYX_EVAL_API_KEY")
        api_key: str = (
            args.api_key if args.api_key else os.environ.get("ONYX_EVAL_API_KEY", "")
        )
        print(f"Running evaluation on remote server: {args.base_url}")

        if args.search_permissions_email:
            print(f"Using search permissions email: {args.search_permissions_email}")

        try:
            result = run_remote(
                args.base_url,
                api_key,
                args.remote_dataset_name,
                search_permissions_email=args.search_permissions_email,
            )
            print(f"Remote evaluation triggered successfully: {result}")
        except requests.RequestException as e:
            print(f"Error triggering remote evaluation: {e}")
            return
    else:
        print(f"Using Braintrust project: {args.braintrust_project}")

        if args.search_permissions_email:
            print(f"Using search permissions email: {args.search_permissions_email}")

        run_local(
            local_data_path=args.local_data_path,
            remote_dataset_name=args.remote_dataset_name,
            search_permissions_email=args.search_permissions_email,
            no_send_logs=args.no_send_logs,
        )


if __name__ == "__main__":
    main()
