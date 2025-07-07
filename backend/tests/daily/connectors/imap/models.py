from pydantic import BaseModel

from onyx.connectors.models import Document


class EmailDoc(BaseModel):
    subject: str

    @classmethod
    def from_doc(cls, document: Document) -> "EmailDoc":
        assert document.title  # Acceptable since this will only be used in tests.

        return cls(
            subject=document.title,
        )
