import json

from onyx.agents.v2.evidence_context import source_card_context


def test_preserves_passages_citations_notes_and_control_state():
    passage = {
        "document": 31,
        "title": "incident",
        "content": "OOM before durable ack\n22 minutes",
        "updated_at": "date",
    }
    body = json.dumps({"results": [passage], "note": "limited authorized scope"})
    source = {
        "task": "question",
        "current_turn_state": {
            "receipts": [{"status": "success"}],
            "results": [{"result_ref": "r5", "content_preview": body}],
        },
    }
    out = json.loads(source_card_context(json.dumps(source)))
    assert out["task"] == "question"
    assert (
        out["current_turn_state"]["receipts"]
        == source["current_turn_state"]["receipts"]
    )
    assert out["current_turn_state"]["results"][1] == {"result_ref": "r5", **passage}
    assert (
        out["current_turn_state"]["results"][0]["evidence_notes"]["note"]
        == "limited authorized scope"
    )


def test_truncated_json_is_preserved_without_guessing_missing_text():
    raw = '{"results":[{"document":9,"content":"beginning'
    source = json.dumps(
        {
            "current_turn_state": {
                "results": [{"result_ref": "r1", "content_preview": raw}]
            }
        }
    )
    out = json.loads(source_card_context(source))
    assert out["current_turn_state"]["results"][0]["raw_visible_excerpt"] == raw
