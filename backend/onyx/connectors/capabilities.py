"""Shared capability vocabulary for connectors.

A leaf module: both the capability-check framework and the source-operations
layer tag things with capabilities, and neither may import the other for it.
"""

from enum import Enum


class CredentialCapability(str, Enum):
    """
    User-visible capabilities a credential may or may not support for a source.
    """

    INDEXING = "indexing"
    DOC_PERMISSION_SYNC = "doc_permission_sync"
    EXTERNAL_GROUP_SYNC = "external_group_sync"
