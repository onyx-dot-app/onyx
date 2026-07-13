from onyx.db.enums import HookFailStrategy
from onyx.db.enums import HookPoint
from onyx.hooks.points.base import HookPointSpec
from onyx.indexing.document_push import DocumentPushPayload
from onyx.indexing.document_push import DocumentPushResponse

__all__ = ["DocumentPushPayload", "DocumentPushResponse", "DocumentPushSpec"]


class DocumentPushSpec(HookPointSpec):
    """Hook point that fires after a document is successfully indexed.

    The payload/response models are owned by onyx.indexing.document_push — the
    hook is one of two delivery mechanisms for the same payload (the other is
    the env-config-driven sink, which takes precedence when set).

    Call site: immediately after the document is written to the index, before
    the next document in the batch. Runs only for public connectors in
    single-tenant deployments.

    This hook is fire-and-forget — the response body is ignored. Use it to
    push indexed documents to an external system (e.g. a wiki, data warehouse,
    or audit log).
    """

    hook_point = HookPoint.DOCUMENT_PUSH
    display_name = "Document Push"
    description = (
        "Fires after each document is successfully indexed. "
        "Push indexed documents to an external destination such as a wiki or data warehouse. "
        "Only fires for public connectors in single-tenant deployments."
    )
    default_timeout_seconds = 30.0
    fail_hard_description = "The indexing batch will fail."
    default_fail_strategy = HookFailStrategy.SOFT
    docs_url = (
        "https://docs.onyx.app/admins/advanced_configs/hook_extensions#document-push"
    )

    payload_model = DocumentPushPayload
    response_model = DocumentPushResponse
