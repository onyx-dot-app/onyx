from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.connectors.models import Document, TextSection


class TeamsThread(BaseModel):
    thread: str
    external_access: ExternalAccess

    @classmethod
    def from_doc(cls, document: Document) -> "TeamsThread":
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
            external_access=document.external_access,
        )
