from onyx.connectors.jira_service_management.models import (
    JsmComment,
    JsmRequest,
    JsmSla,
)


def test_jsm_request_from_raw() -> None:
    request = JsmRequest.from_raw(
        {
            "issueId": "10001",
            "issueKey": "SD-1",
            "requestType": {"id": "1", "name": "Password reset"},
            "currentStatus": {"name": "Open"},
            "serviceDesk": {"id": "1", "name": "IT Help"},
            "reporter": {"displayName": "Ann", "emailAddress": "ann@example.com"},
            "organization": [{"name": "Acme"}, {"id": "2"}, "junk"],
            "createdDate": "2023-01-01T11:00:00.000+0000",
            "updatedDate": "2023-01-01T12:00:00.000+0000",
            "unknownField": {"kept": True},
        }
    )
    assert request.issue_key == "SD-1"
    assert request.request_type_name == "Password reset"
    assert request.status == "Open"
    assert request.service_desk_id == "1"
    assert request.service_desk_name == "IT Help"
    assert request.reporter_name == "Ann"
    assert request.organizations == ["Acme"]
    assert request.created == "2023-01-01T11:00:00.000+0000"


def test_jsm_request_from_raw_tolerates_missing_fields() -> None:
    request = JsmRequest.from_raw({})
    assert request.issue_key is None
    assert request.request_type_name is None
    assert request.organizations == []


def test_jsm_comment_from_raw_visibility_flag() -> None:
    public = JsmComment.from_raw(
        {"body": "hello", "public": True, "author": {"displayName": "Ann"}}
    )
    internal = JsmComment.from_raw(
        {
            "body": {"type": "doc", "content": []},
            "public": False,
            "author": {"displayName": "Agent", "emailAddress": "agent@example.com"},
        }
    )
    assert public.public is True
    assert internal.public is False
    assert internal.author_email == "agent@example.com"
    # A comment without the flag is customer-visible.
    assert JsmComment.from_raw({"body": "x"}).public is True


def test_jsm_sla_from_raw_ongoing_and_completed() -> None:
    ongoing = JsmSla.from_raw(
        {
            "name": "Time to resolution",
            "ongoingCycle": {"breached": True},
            "goalDuration": {"friendly": "4h"},
        }
    )
    assert ongoing.name == "Time to resolution"
    assert ongoing.breached is True
    assert ongoing.goal == "4h"

    completed = JsmSla.from_raw(
        {"name": "First response", "completedCycles": [{"breached": False}]}
    )
    assert completed.breached is False
    assert completed.goal is None

    no_cycle = JsmSla.from_raw({"name": "Paused"})
    assert no_cycle.breached is None
