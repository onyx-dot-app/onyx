import re
import traceback
from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import Annotated, Any, Generic, Literal
from urllib.parse import urlparse

import requests
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.form_state import (
    ConfigT,
    FormState,
    validate_form_state,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    UnreachableValidationError,
)
from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.source_operations import SourceOperations
from onyx.db.enums import AccessType, CapabilityCheckTrigger
from onyx.utils.logger import setup_logger
from onyx.utils.redaction import scrub_sensitive_values

logger = setup_logger()


# Findings: structured information a capability check discovers about what a
# credential and config reach, beside its pass/fail outcome. A finding names what
# it describes with a closed ``key``; the frontend turns the key into a localized
# label, so findings carry no display text. ``field_name`` names the config field
# a finding informs, for a form that offers the finding's options in that field.
# Findings stay conservative: names and ids of containers (drives, spaces,
# channels, mailboxes) and counts. Never document content, and never lists of
# users: users are a count. A container name can still name a person, for
# example a personal Confluence space.

# TODO(evan-onyx): a search endpoint for sources whose listings exceed this.
MAX_FINDING_OPTIONS: int = 1000
# Longest option value, label or detail. Bounds the stored report and every
# draft snapshot write.
MAX_FINDING_TEXT_LENGTH: int = 500


class CheckFindingKey(str, Enum):
    SHARED_DRIVES = "shared_drives"
    VISIBLE_ORGANIZATION_USERS = "visible_organization_users"
    VISIBLE_SPACES = "visible_spaces"
    READABLE_CHANNELS = "readable_channels"
    READABLE_MAILBOXES = "readable_mailboxes"
    READABLE_DRIVES = "readable_drives"


class CheckFindingType(str, Enum):
    COUNT = "count"
    OPTIONS = "options"


class CountFinding(BaseModel):
    type: Literal[CheckFindingType.COUNT] = CheckFindingType.COUNT
    key: CheckFindingKey
    field_name: str | None = None
    count: int = Field(ge=0)
    # The listing stopped at a cap, so the real count is at least ``count``.
    at_least: bool = False


class FindingOption(BaseModel):
    # What a form puts in the config field: an id or a URL.
    value: str = Field(max_length=MAX_FINDING_TEXT_LENGTH)
    # What the admin reads.
    label: str = Field(max_length=MAX_FINDING_TEXT_LENGTH)
    # An optional second line.
    detail: str | None = Field(default=None, max_length=MAX_FINDING_TEXT_LENGTH)


class OptionsFinding(BaseModel):
    type: Literal[CheckFindingType.OPTIONS] = CheckFindingType.OPTIONS
    key: CheckFindingKey
    field_name: str | None = None
    options: list[FindingOption] = Field(max_length=MAX_FINDING_OPTIONS)
    # The listing stopped at MAX_FINDING_OPTIONS.
    truncated: bool = False


CheckFinding = Annotated[CountFinding | OptionsFinding, Field(discriminator="type")]

_CHECK_FINDING_ADAPTER: TypeAdapter[CheckFinding] = TypeAdapter(CheckFinding)


def parse_known_findings(raw: Any) -> list[CheckFinding]:
    """Keeps the findings this version understands. A stored finding with a
    newer type or key is dropped, not an error, so a report written by a newer
    version still reads."""
    if not isinstance(raw, list):
        return []
    known: list[CheckFinding] = []
    for item in raw:
        try:
            known.append(_CHECK_FINDING_ADAPTER.validate_python(item))
        except ValidationError:
            logger.debug("Dropping an unknown capability check finding")
    return known


# Advisories: free text a check adds to its result, at any status. An advisory
# says what the check could not verify or what the admin should know, for
# example "the channel is empty, so thread reads were not verified".
# Advisories are not findings: the findings setting does not hide them, so they
# must not list what the credential reaches.
MAX_ADVISORY_LENGTH: int = 1000
MAX_CHECK_ADVISORIES: int = 20


class CheckAdvisory(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def _bounded(cls, message: str) -> str:
        if len(message) <= MAX_ADVISORY_LENGTH:
            return message
        return message[: MAX_ADVISORY_LENGTH - 1] + "…"


class CheckOutput(BaseModel):
    """What a passing check returns: findings, and advisories about what it
    could not verify."""

    findings: list[CheckFinding] = []
    advisories: list[CheckAdvisory] = Field(default=[], max_length=MAX_CHECK_ADVISORIES)


class CheckNotApplicableError(Exception):
    """Raised by a check that learns at run time that it does not apply, for
    example a Grid-only check on a workspace that is not on Enterprise Grid.
    The result is SKIPPED and not applicable, like a check that the config
    excludes."""


class CapabilityCheckStatus(str, Enum):
    PASSED = "passed"
    # A ``ConnectorValidationError``-family failure: real and actionable.
    FAILED = "failed"
    # The check started but did not finish, or it could not decide: a timeout,
    # a rate limit, an unexpected response (``UnexpectedValidationError`` or
    # any unrecognized exception). Never proof that the credential is broken.
    INCOMPLETE = "incomplete"
    # Legacy: INCOMPLETE before it had its own value. Stored reports and run
    # history still hold it; no check result is written with it.
    INDETERMINATE = "indeterminate"
    # The check needs state (connector instance or config) that was not
    # supplied.
    SKIPPED = "skipped"


INCOMPLETE_STATUSES: frozenset[CapabilityCheckStatus] = frozenset(
    {CapabilityCheckStatus.INCOMPLETE, CapabilityCheckStatus.INDETERMINATE}
)


class CheckErrorKind(str, Enum):
    """Why a check FAILED or is INCOMPLETE, for the form to show the right
    detail without reading the message."""

    # The source rejected the credential.
    REJECTED = "rejected"
    # The credential signs in, but lacks a permission or scope.
    PERMISSION = "permission"
    # Any other actionable failure: a setting or the source rules it out.
    INVALID = "invalid"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNREACHABLE = "unreachable"
    # An error the check does not know.
    UNEXPECTED = "unexpected"


# Kinds that say nothing lasting about the credential: running the check again
# can give a different result.
TRANSIENT_ERROR_KINDS: frozenset[CheckErrorKind] = frozenset(
    {
        CheckErrorKind.RATE_LIMITED,
        CheckErrorKind.TIMEOUT,
        CheckErrorKind.UNREACHABLE,
        CheckErrorKind.UNEXPECTED,
    }
)


# Kinds whose cause the check does not know: their result keeps a stack trace.
_UNKNOWN_CAUSE_ERROR_KINDS: frozenset[CheckErrorKind] = frozenset(
    {CheckErrorKind.TIMEOUT, CheckErrorKind.UNREACHABLE, CheckErrorKind.UNEXPECTED}
)
# Bounds what a result stores of the source's response and of a stack trace:
# results live in stored reports and in every draft snapshot write.
MAX_RESPONSE_EXCERPT_CHARS: int = 500
MAX_STACK_TRACE_CHARS: int = 4000
# How much of a response body is redacted before the excerpt is cut from it.
# Far past the excerpt, so a secret cut at this bound never reaches it.
_MAX_REDACTED_BODY_CHARS: int = 64 * 1024
# A URL anywhere in a text, with any scheme. Each match is rebuilt by
# ``_safe_location``, the parser the request line uses too.
_URL_PATTERN = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s'\"<>]+", re.IGNORECASE)
_UNPARSABLE_URL = "[URL]"


class CheckErrorDetail(BaseModel):
    """What support needs about a check that did not pass, beyond its
    message. The form shows it as Error Details."""

    # The source's HTTP status, request and response, when the error carries
    # an HTTP response. The request has no query string, which can hold
    # secrets.
    status_code: int | None = None
    request: str | None = None
    response_excerpt: str | None = None
    # Only when the cause is unknown: a timeout, an unreachable source or an
    # unexpected error.
    stack_trace: str | None = None


def _safe_location(url: str) -> str:
    """A URL's host, port and path only: its user info, parameters, query
    string and fragment can hold secrets. A URL that does not parse is
    replaced whole."""
    try:
        parsed = urlparse(url)
        port = parsed.port
        host = parsed.hostname or ""
    except ValueError:
        return _UNPARSABLE_URL
    return f"{host}{f':{port}' if port else ''}{parsed.path}"


def _request_line(method: str | None, url: str | None) -> str | None:
    if url is None:
        return None
    location = _safe_location(url)
    return f"{method} {location}" if method else location


def credential_strings(credential_json: Any) -> list[str]:
    """Every string in a credential's values, nested ones included, to redact
    from what a check stores."""
    if isinstance(credential_json, str):
        return [credential_json]
    if isinstance(credential_json, dict):
        return [
            text
            for value in credential_json.values()
            for text in credential_strings(value)
        ]
    if isinstance(credential_json, list):
        return [text for value in credential_json for text in credential_strings(value)]
    return []


def _scrubbed(text: str, secrets: Iterable[str]) -> str:
    without_urls = _URL_PATTERN.sub(lambda match: _safe_location(match[0]), text)
    return scrub_sensitive_values(without_urls, secrets)


def _http_detail(error: BaseException) -> CheckErrorDetail | None:
    """The HTTP response of the first error in the chain that has one, with
    the whole body: ``check_error_detail`` redacts it, then cuts it. The
    chain follows the cause, else the context the traceback would show."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, SourceApiError):
            return CheckErrorDetail(
                status_code=current.status_code,
                request=_request_line(current.method, current.url),
                response_excerpt=current.body or None,
            )
        if isinstance(current, requests.HTTPError) and current.response is not None:
            response = current.response
            return CheckErrorDetail(
                status_code=response.status_code,
                request=_request_line(
                    response.request.method if response.request else None,
                    response.url,
                ),
                response_excerpt=response.text or None,
            )
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return None


def check_error_detail(
    error: Exception, error_kind: CheckErrorKind, secrets: Iterable[str]
) -> CheckErrorDetail | None:
    """The detail of a check's exception: the HTTP response it carries, and a
    stack trace when the cause is unknown. None when it has neither. URL query
    strings and every value of ``secrets`` (the run's credential values) are
    removed from the response and the trace before either is cut to size,
    so a cut cannot leave part of a secret."""
    secrets = list(secrets)
    detail = _http_detail(error) or CheckErrorDetail()
    if detail.response_excerpt is not None:
        detail.response_excerpt = _scrubbed(
            detail.response_excerpt[:_MAX_REDACTED_BODY_CHARS], secrets
        )[:MAX_RESPONSE_EXCERPT_CHARS]
    if error_kind in _UNKNOWN_CAUSE_ERROR_KINDS:
        trace = _scrubbed("".join(traceback.format_exception(error)), secrets)
        detail.stack_trace = trace[-MAX_STACK_TRACE_CHARS:]
    return detail if detail != CheckErrorDetail() else None


class CheckNotRunReason(str, Enum):
    """Why a SKIPPED check did not run, when a gate of the run stopped it."""

    # A check it depends on FAILED.
    DEPENDENCY_FAILED = "dependency_failed"
    # A check it depends on is INCOMPLETE.
    DEPENDENCY_INCOMPLETE = "dependency_incomplete"
    # A check it depends on was SKIPPED for a reason of its own, such as a
    # setting it needs.
    DEPENDENCY_SKIPPED = "dependency_skipped"
    # The source rate limited an earlier check, so the run stopped.
    RATE_LIMITED = "rate_limited"


_UNREACHABLE_ERROR_KINDS: frozenset[CheckErrorKind] = frozenset(
    {CheckErrorKind.TIMEOUT, CheckErrorKind.UNREACHABLE}
)


def check_error_kind(error: Exception) -> CheckErrorKind:
    """The kind of a check's exception, per the check exception contract."""
    if isinstance(error, (CredentialExpiredError, CredentialInvalidError)):
        return CheckErrorKind.REJECTED
    if isinstance(error, InsufficientPermissionsError):
        return CheckErrorKind.PERMISSION
    if isinstance(error, ConnectorValidationError):
        return CheckErrorKind.INVALID
    if isinstance(error, RateLimitedValidationError):
        return CheckErrorKind.RATE_LIMITED
    if isinstance(error, TimeoutError):
        return CheckErrorKind.TIMEOUT
    if isinstance(error, UnreachableValidationError):
        return CheckErrorKind.UNREACHABLE
    return CheckErrorKind.UNEXPECTED


class CapabilityVerdict(str, Enum):
    PASSED = "passed"
    # Only non-required checks failed: the capability works with caveats.
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"
    SKIPPED = "skipped"
    # The source does not have this capability (e.g. no group sync for Slack).
    NOT_APPLICABLE = "not_applicable"


class CapabilityCheckContext(BaseModel):
    """Inputs available to a capability check at run time.

    ``connector`` and ``connector_specific_config`` are None for config-less
    credential-time runs; the runner skips checks that declare a requirement on
    them. ``instantiation_error`` is set when connector construction failed for
    a supplied config; the runner surfaces it on instance-requiring checks
    instead of skipping them.

    ``source_operations`` is the gateway migrated checks compose; it is None for
    sources without one. ``connector`` serves the fallback path only: migrated
    checks need no connector instance.
    """

    # ``BaseConnector`` and ``SourceOperations`` are not pydantic types;
    # validate by isinstance.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: DocumentSource
    credential_json: dict[str, Any]
    connector: BaseConnector | None = None
    connector_specific_config: dict[str, Any] | None = None
    # The access type the connector is (or will be) created with. None when the
    # caller does not know it; checks limited to some access types then run.
    access_type: AccessType | None = None
    instantiation_error: Exception | None = None
    source_operations: SourceOperations | None = None

    @cached_property
    def form_state(self) -> FormState[Any] | None:
        """``connector_specific_config`` validated field by field against the
        source's config model. None when there is no config, or the source has
        no connector class."""
        if self.connector_specific_config is None:
            return None
        mapping = CONNECTOR_CLASS_MAP.get(self.source)
        if mapping is None:
            return None
        return validate_form_state(mapping.config_class, self.connector_specific_config)


_PERM_SYNC_CAPABILITIES = frozenset(
    {
        CredentialCapability.DOC_PERMISSION_SYNC,
        CredentialCapability.EXTERNAL_GROUP_SYNC,
    }
)
_PERM_SYNCED_ACCESS_TYPES = frozenset(AccessType.perm_synced_types())


class CapabilityCheck(ABC, Generic[ConfigT]):
    """
    A named probe of one permission/capability assumption a connector makes.

    Concrete checks pass their metadata to ``__init__`` and implement ``run``,
    which raises a ``ValidationError``-family exception on failure and returns
    nothing or a ``CheckOutput`` on success; the runner maps exceptions to
    statuses.

    A check that reads the connector config sets ``config_class`` to the source's
    ``ConnectorConfig`` and reads it through ``config``. It declares:

    - ``requires_fields``: config fields that must hold a value for the check
      to mean anything. Name only fields with no usable empty state: a field
      whose absence means "all" (e.g. no channel filter) is read with its
      default instead.
    - ``access_types``: the access types the check applies to. Omitted or
      None, a check applies to all of them, except a permission-sync check,
      which applies to the permission-synced ones. Pass ``frozenset(AccessType)``
      to make a permission-sync check apply to all of them.
    - ``applies``: a predicate on the form state, for anything the two
      declarations above cannot express.

    ``validates_binding`` marks a check that proves the credential works with
    the credential-bound fields (e.g. it signs in to the site URL). Such a
    check may require only bound fields. A create form can wait on these
    checks before it unlocks the rest of the configuration.
    """

    # The source's config model. None for checks that never read the config.
    config_class: type[ConfigT] | None = None

    def __init__(
        self,
        *,
        capability: CredentialCapability,
        check_id: str,
        display_name: str,
        required: bool = True,
        requires_connector_instance: bool = True,
        requires_connector_config: bool = False,
        requires_fields: frozenset[str] = frozenset(),
        access_types: frozenset[AccessType] | None = None,
        timeout_seconds: float | None = None,
        is_fallback: bool = False,
        remediation: str | None = None,
        docs_link: str | None = None,
        validates_binding: bool = False,
        discovery: bool = False,
        fails_when_unreachable: bool = False,
        depends_on: tuple[str, ...] = (),
    ) -> None:
        self.capability = capability
        self.check_id = check_id
        self.display_name = display_name
        # Required checks gate the capability verdict; non-required checks only
        # downgrade PASSED to PASSED_WITH_WARNINGS (partial capability). A
        # discovery check is never required.
        self.required = required and not discovery
        # Retrieves findings (``findings.py``) that take much longer to gather
        # than validation. It never counts toward the verdict, runs after the
        # validation checks of its run, and does not run at pairing creation.
        self.discovery = discovery
        self.requires_connector_instance = requires_connector_instance
        # Needs a config to read, even if every field it reads is optional.
        # Implied by a non-empty ``requires_fields``.
        self.requires_connector_config = requires_connector_config or bool(
            requires_fields
        )
        self.requires_fields = requires_fields
        self.access_types = (
            access_types
            if access_types is not None
            else _PERM_SYNCED_ACCESS_TYPES
            if capability in _PERM_SYNC_CAPABILITIES
            else None
        )
        # Per-check hang guard in seconds; None falls back to the
        # ``CAPABILITY_CHECK_TIMEOUT_SECONDS`` default. Timing out maps to
        # INCOMPLETE, except as ``fails_when_unreachable`` says.
        self.timeout_seconds = timeout_seconds
        # True for synthesized wrappers around the legacy validation blobs
        # (``validate_connector_settings`` / ``validate_perm_sync``) rather than
        # named per-permission probes.
        self.is_fallback = is_fallback
        self.remediation = remediation
        self.docs_link = docs_link
        self.validates_binding = validates_binding
        # A sign-in check: on a form run, a timeout or an unreachable source
        # FAILS it, because Onyx cannot use the account. Other runs keep it
        # INCOMPLETE, so a slow source never holds indexing.
        self.fails_when_unreachable = fails_when_unreachable
        # The check_ids this check runs after. A dependency that FAILED, is
        # INCOMPLETE or did not run stops the check. One that does not apply is
        # left out, so a check can list alternatives (e.g. both token types'
        # sign-in checks).
        self.depends_on = depends_on

    def outcome_status(
        self, error_kind: CheckErrorKind, form_run: bool
    ) -> CapabilityCheckStatus:
        """The status of a check that raised an error of ``error_kind``."""
        if error_kind not in TRANSIENT_ERROR_KINDS or (
            form_run
            and self.fails_when_unreachable
            and error_kind in _UNREACHABLE_ERROR_KINDS
        ):
            return CapabilityCheckStatus.FAILED
        return CapabilityCheckStatus.INCOMPLETE

    @abstractmethod
    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        """Probes the capability; raises on failure, returns on success. A
        passing check may return a ``CheckOutput``: findings (what the
        credential and config reach) and advisories (what it could not
        verify)."""

    @property
    def reads_connector_config(self) -> bool:
        """True when the check reads the config, so an invalid field fails it.
        A check can read the config without requiring one: a config-less run
        then reads the defaults."""
        return self.requires_connector_config or self.config_class is not None

    def applies(
        self,
        form_state: FormState[ConfigT],  # noqa: ARG002
    ) -> bool:
        """False when the check means nothing for this form state. Called only
        for a config-reading check on a run with a config, once every
        ``requires_fields`` field is provided."""
        return True

    def config(self, context: CapabilityCheckContext) -> ConfigT:
        """The connector config, typed. Fields that were not provided hold their
        defaults; the runner guarantees ``requires_fields`` are provided."""
        if self.config_class is None:
            raise TypeError(
                f"{type(self).__name__} reads the config but sets no config_class."
            )
        return form_config(context, self.config_class)


def form_config(
    context: CapabilityCheckContext, config_class: type[ConfigT]
) -> ConfigT:
    """The context's connector config as ``config_class``, for helpers shared by
    several checks. Defaults only on a config-less run."""
    if context.form_state is None:
        return config_class.model_construct()
    if context.form_state.config_class is not config_class:
        raise TypeError(
            f"Expected a {config_class.__name__} form state, not "
            f"{context.form_state.config_class.__name__}."
        )
    return context.form_state.config


class CapabilityCheckResult(BaseModel):
    capability: CredentialCapability
    check_id: str
    display_name: str
    required: bool
    status: CapabilityCheckStatus
    # Exception text for failures, skip reason for skips, empty on success.
    message: str = ""
    # Exception class name, for support diagnosis.
    error_type: str | None = None
    # Why a FAILED or INCOMPLETE check did not pass.
    error_kind: CheckErrorKind | None = None
    error_detail: CheckErrorDetail | None = None
    # Why a SKIPPED check did not run, and the dependency that stopped it.
    not_run_reason: CheckNotRunReason | None = None
    blocked_by: str | None = None
    # The row's text: a short line of what the check found or what is wrong,
    # and up to three lines of what happened and what is needed. None when
    # the check gives none; ``message`` stays the full text for support.
    summary: str | None = None
    description: str | None = None
    is_fallback: bool = False
    remediation: str | None = None
    docs_link: str | None = None
    duration_ms: int | None = None
    # False for a SKIPPED check that does not apply to the access type or the
    # config. It does not count toward the verdict.
    applicable: bool = True
    validates_binding: bool = False
    # A discovery check: never part of the verdict.
    discovery: bool = False
    # What a passing check found. Empty for every other status.
    findings: list[CheckFinding] = []
    advisories: list[CheckAdvisory] = []

    @field_validator("findings", mode="before")
    @classmethod
    def _known_findings(cls, findings: Any) -> Any:
        return parse_known_findings(findings)


class CredentialCapabilityReport(BaseModel):
    """The full outcome of one capability-check run for a credential."""

    credential_id: int
    source: DocumentSource
    # None means a config-less credential-time run.
    connector_id: int | None = None
    checked_at: datetime
    trigger: CapabilityCheckTrigger
    verdicts: dict[CredentialCapability, CapabilityVerdict]
    check_results: list[CapabilityCheckResult]

    def required_failures(self) -> list[CapabilityCheckResult]:
        """The failed checks that block indexing: required and applicable."""
        return [
            result
            for result in self.check_results
            if result.required
            and result.applicable
            and result.status == CapabilityCheckStatus.FAILED
        ]


class PendingCheck(BaseModel):
    """A named check with no result yet, as its definition describes it."""

    capability: CredentialCapability
    check_id: str
    display_name: str
    required: bool


class NamedCheckRun(BaseModel):
    """The outcome of the named checks after the blocking budget."""

    # Results of the checks that finished, reused draft results included.
    finished_results: list[CapabilityCheckResult]
    # Checks that were still running at the end of the budget.
    unfinished_checks: list[PendingCheck]

    @property
    def unfinished_check_ids(self) -> frozenset[str]:
        return frozenset(check.check_id for check in self.unfinished_checks)

    @property
    def failed_required_results(self) -> list[CapabilityCheckResult]:
        """The finished required checks that failed. Only these block a
        pairing."""
        return [
            result
            for result in self.finished_results
            if result.required and result.status == CapabilityCheckStatus.FAILED
        ]


class ProposedPairingValidation(BaseModel):
    """The result of validating a pairing state that is not stored."""

    # Set when the credential binding, the connector construction, or the
    # legacy validation failed. The named checks do not run then.
    validation_error: str | None = None
    # Named checks only: the finished results, and the checks still running at
    # the end of the blocking budget, by id and with their definitions.
    check_results: list[CapabilityCheckResult] = []
    unfinished_check_ids: frozenset[str] = frozenset()
    unfinished_checks: list[PendingCheck] = []

    @property
    def blocks_pairing(self) -> bool:
        """True when the validation failed or a finished required check
        failed."""
        return self.validation_error is not None or any(
            result.required and result.status == CapabilityCheckStatus.FAILED
            for result in self.check_results
        )


def aggregate_capability_verdict(
    applicable: bool,
    results: Sequence[CapabilityCheckResult],
) -> CapabilityVerdict:
    """Rolls the per-check results of one capability up into a single verdict.

    Pure function, evaluated in strict precedence order. Required checks gate
    the verdict: a required FAILED is FAILED, and a required INCOMPLETE or
    SKIPPED leaves the capability's core unverified, so no pass-ish claim may be
    made. Non-required failures and incomplete checks only downgrade to
    PASSED_WITH_WARNINGS (partial capability); non-required skips do not
    downgrade at all. Checks that do not apply are left out. An empty result
    list aggregates to SKIPPED: a capability is never PASSED on the basis of
    having checked nothing.
    """
    if not applicable:
        return CapabilityVerdict.NOT_APPLICABLE
    results = [
        result for result in results if result.applicable and not result.discovery
    ]
    if any(
        result.status == CapabilityCheckStatus.FAILED and result.required
        for result in results
    ):
        return CapabilityVerdict.FAILED
    if any(
        result.status in INCOMPLETE_STATUSES and result.required for result in results
    ):
        return CapabilityVerdict.INDETERMINATE
    if any(
        result.status == CapabilityCheckStatus.SKIPPED and result.required
        for result in results
    ):
        return CapabilityVerdict.SKIPPED
    if any(
        result.status == CapabilityCheckStatus.FAILED
        or result.status in INCOMPLETE_STATUSES
        for result in results
    ):
        return CapabilityVerdict.PASSED_WITH_WARNINGS
    if all(result.status == CapabilityCheckStatus.SKIPPED for result in results):
        return CapabilityVerdict.SKIPPED
    return CapabilityVerdict.PASSED


def compute_capability_verdicts(
    applicable_capabilities: set[CredentialCapability],
    results: Sequence[CapabilityCheckResult],
) -> dict[CredentialCapability, CapabilityVerdict]:
    """Computes a verdict for every capability, applicable or not."""
    return {
        capability: aggregate_capability_verdict(
            capability in applicable_capabilities,
            [result for result in results if result.capability == capability],
        )
        for capability in CredentialCapability
    }
