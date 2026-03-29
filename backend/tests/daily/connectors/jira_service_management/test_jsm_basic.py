"""Test file for Jira Service Management Connector."""

# This is a placeholder test file
# To run tests, you would need a real Jira environment

def test_connector_imports():
    """Test that the connector can be imported."""
    from onyx.connectors.jira_service_management import JiraServiceManagementConnector
    from onyx.connectors.jira_service_management.connector import (
        JiraServiceManagementConnector,
        JiraServiceManagementCheckpoint,
    )
    print("Imports successful!")
    print(f"Checkpoint fields: offset={JiraServiceManagementCheckpoint.__fields__}")


def test_checkpoint():
    """Test checkpoint creation."""
    from onyx.connectors.jira_service_management.connector import (
        JiraServiceManagementCheckpoint,
    )

    checkpoint = JiraServiceManagementCheckpoint(
        offset=0,
        last_updated=None,
        has_more=False,
    )
    print(f"Checkpoint created: {checkpoint}")
    assert checkpoint.offset == 0
    assert checkpoint.has_more is False
    print("Checkpoint test passed!")


if __name__ == "__main__":
    test_connector_imports()
    test_checkpoint()
    print("\nAll tests passed!")
