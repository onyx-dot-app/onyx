import argparse

import requests

API_SERVER_URL = "http://localhost:3000"
API_KEY = "onyx-api-key"  # API key here, if auth is enabled
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}


def resume_paused_connectors(
    specific_connector_sources: list[str] | None = None,
) -> None:
    # Get all paused connectors
    response = requests.get(
        f"{API_SERVER_URL}/api/manage/admin/connector/indexing-status",
        headers=HEADERS,
    )
    response.raise_for_status()

    # Convert the response to a list of ConnectorIndexingStatus objects
    connectors = [cc_pair for cc_pair in response.json()]

    # If a specific connector is provided, filter the connectors to only include that one
    if specific_connector_sources:
        connectors = [
            connector
            for connector in connectors
            if connector["connector"]["source"] in specific_connector_sources
        ]

    for connector in connectors:
        if connector["cc_pair_status"] == "PAUSED":
            print(f"Resuming connector: {connector['name']}")
            response = requests.put(
                f"{API_SERVER_URL}/api/manage/admin/cc-pair/{connector['cc_pair_id']}/status",
                json={"status": "ACTIVE"},
                headers=HEADERS,
            )
            response.raise_for_status()
            print(f"Resumed connector: {connector['name']}")

        else:
            print(f"Connector {connector['name']} is not paused")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume paused connectors")
    parser.add_argument(
        "--connector_sources",
        type=str.lower,
        nargs="+",
        help="The sources of the connectors to resume. If not provided, will resume all paused connectors.",
    )
    args = parser.parse_args()

    resume_paused_connectors(args.connector_sources)


if __name__ == "__main__":
    main()
