import argparse

import requests

API_SERVER_URL = "http://localhost:3000"
API_KEY = "onyx-api-key"  # API key here, if auth is enabled


def resume_paused_connectors(
    api_server_url: str,
    api_key: str | None,
    specific_connector_sources: list[str] | None = None,
) -> None:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Get all paused connectors
    response = requests.post(
        f"{api_server_url}/api/manage/admin/connector/indexing-status",
        headers=headers,
        json={"get_all_connectors": True},
    )
    response.raise_for_status()

    indexing_status_response = response.json()

    # Iterate over all connectors and resume paused ones
    for connectors_by_source in indexing_status_response:
        if (
            specific_connector_sources
            and connectors_by_source["source"] not in specific_connector_sources
        ):
            print(f"Skipping connector source: {connectors_by_source['source']}")
            continue
        connectors = connectors_by_source["indexing_statuses"]
        for connector in connectors:
            if connector.get("cc_pair_status"):
                if connector["cc_pair_status"] == "PAUSED":
                    print(f"Resuming connector: {connector['name']}")
                    response = requests.put(
                        f"{api_server_url}/api/manage/admin/cc-pair/{connector['cc_pair_id']}/status",
                        json={"status": "ACTIVE"},
                        headers=headers,
                    )
                    response.raise_for_status()
                    print(f"Resumed connector: {connector['name']}")
                else:
                    print(f"Connector {connector['name']} is not paused")
            else:
                print(f"Connector {connector['name']} is a Federated Connector")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume paused connectors")
    parser.add_argument(
        "--api_server_url",
        type=str,
        default=API_SERVER_URL,
        help="The URL of the API server to use. If not provided, will use the default.",
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="The API key to use for authentication. If not provided, no authentication will be used.",
    )
    parser.add_argument(
        "--connector_sources",
        type=str.lower,
        nargs="+",
        help="The sources of the connectors to resume. If not provided, will resume all paused connectors.",
    )
    args = parser.parse_args()

    resume_paused_connectors(args.api_server_url, args.api_key, args.connector_sources)


if __name__ == "__main__":
    main()
