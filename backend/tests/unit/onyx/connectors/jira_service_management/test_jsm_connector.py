from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector


def test_jsm_issue_to_document_parses_adf_and_comments() -> None:
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    sample_issue = {
        "key": "ITSM-42",
        "fields": {
            "summary": "VPN gateway unreachable from Huntsville enclave",
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Users cannot connect to VPN."}]}],
            },
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "customfield_10010": {"requestType": {"name": "Incident"}},
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "SecOps Engineer"},
                        "body": "Restarted wireguard interface wg0.",
                    }
                ]
            },
            "updated": "2026-11-08T18:00:00.000+0000",
        },
    }
    doc = connector._issue_to_document(sample_issue)
    assert doc.id == "jsm:ITSM-42"
    assert "VPN gateway unreachable" in doc.semantic_identifier
    assert "Users cannot connect to VPN." in doc.sections[0].text
    assert "Restarted wireguard interface wg0." in doc.sections[0].text
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["request_type"] == "Incident"
