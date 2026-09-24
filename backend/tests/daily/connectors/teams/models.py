from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.connectors.models import Document, TextSection


def readers_of(
    external_access: ExternalAccess, readers_by_group: dict[str, set[str]]
) -> set[str]:
    """The people in the one group a document names. No channel is visible to
    the tenant, and the group sync names the people, not the document."""
    assert not external_access.is_public, "No Teams channel is visible to the tenant"
    assert not external_access.external_user_emails, (
        f"{external_access.external_user_emails=} should be empty for MS Teams"
    )
    group_ids = external_access.external_user_group_ids
    assert len(group_ids) == 1, f"{group_ids=} should name the channel's group alone"
    group_id = next(iter(group_ids))
    assert group_id in readers_by_group, f"The group sync lists no {group_id=}"
    readers = readers_by_group[group_id]
    assert readers, f"{group_id=} should hold the channel's members"
    return readers


class TeamsThread(BaseModel):
    thread: str
    readers: set[str]

    @classmethod
    def from_doc(
        cls, document: Document, readers_by_group: dict[str, set[str]]
    ) -> "TeamsThread":
        """The message bodies of the thread, in order. Every section is one
        message with a sender and date header and a link to itself."""
        assert document.external_access, (
            f"ExternalAccess should always be available, instead got {document=}"
        )

        bodies: list[str] = []
        for section in document.sections:
            assert isinstance(section, TextSection) and section.text, section
            assert section.link, f"Every message links to itself; {section=}"
            header, _, body = section.text.partition("\n\n")
            assert header.startswith("From: ") and "\nDate: " in header, header
            bodies.append(body)

        return cls(
            thread="".join(bodies),
            readers=readers_of(document.external_access, readers_by_group),
        )
