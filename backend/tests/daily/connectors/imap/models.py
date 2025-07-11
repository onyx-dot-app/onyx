from pydantic import BaseModel

from onyx.connectors.models import Document
from tests.daily.connectors.utils import to_text_sections


class EmailDoc(BaseModel):
    subject: str
    recipients: set[str]
    body: str

    @classmethod
    def from_doc(cls, document: Document) -> "EmailDoc":
        # Acceptable to perform assertions since this class is only used in tests.
        assert document.title
        assert document.external_access

        body = " ".join(to_text_sections(iterator=iter(document.sections)))

        return cls(
            subject=document.title,
            recipients=document.external_access.external_user_emails,
            body=body,
        )
