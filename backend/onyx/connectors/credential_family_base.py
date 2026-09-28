"""Base types for credential families. See ``credential_families``."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

CREDENTIAL_FAMILY_KEY = "credential_family"


class CredentialFamily(str, Enum):
    ATLASSIAN = "atlassian"
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class FamilyCredential(BaseModel):
    """The credential shape shared by every source of one family."""


FamilyCredentialT = TypeVar("FamilyCredentialT", bound=FamilyCredential)


class FamilyCredentialCodec(ABC, Generic[FamilyCredentialT]):
    """Converts one source's credential JSON to and from its family's shape."""

    family: ClassVar[CredentialFamily]
    family_model: type[FamilyCredentialT]

    @abstractmethod
    def to_family(self, source_json: dict[str, Any]) -> FamilyCredentialT: ...

    @abstractmethod
    def from_family(self, family_credential: FamilyCredentialT) -> dict[str, Any]: ...
