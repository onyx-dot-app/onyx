from onyx.connectors.jira_service_management.utils import get_text_adf

def test_adf_plain_text():
    sample = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Customer service"},
                    {"type": "text", "text": "request description"}
                ]
            }
        ]
    }
    res = get_text_adf(sample)
    assert res == "Customer service request description"
