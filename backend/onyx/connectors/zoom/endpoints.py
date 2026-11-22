"""Every Zoom endpoint this connector calls, declared once.

Adding a row here is the only way to reach a new endpoint, so nothing can be
called without its tier and its entitlement. The tiers come from Zoom's
published spec at https://developers.zoom.us/api-hub/meetings/methods/endpoints.json.
`operation` is Zoom's own operationId: the reference page is a client-side
router, so search that id instead of following a deep link.
"""

from enum import Enum
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from onyx.connectors.zoom.rate_limit import ZoomRateLimitTier

API_BASE_URL = "https://api.zoom.us/v2"
OAUTH_TOKEN_URL = "https://zoom.us/oauth/token"


class ZoomEntitlement(str, Enum):
    """Zoom refuses a missing licence exactly like a missing scope, so without
    this the admin is sent to re-check scopes that are already correct."""

    NONE = "none"
    WEBINAR = "webinar"


ENTITLEMENT_HINTS: dict[ZoomEntitlement, str] = {
    ZoomEntitlement.WEBINAR: (
        "Zoom refused a webinar request. Webinars need the Webinar add-on enabled "
        "for the host, and the app needs the webinar:read:admin scope. Meetings "
        "need neither, so credentials that read meetings can still fail here."
    ),
}


def normalize_session_id(identifier: str) -> str:
    """Zoom shows meeting and webinar numbers as `857 9609 3688`, and admins
    paste them that way."""
    return "".join(identifier.split())


def encode_identifier(identifier: str) -> str:
    """Zoom requires a UUID to be encoded twice when it starts with "/" or
    contains "//". User and group ids never contain a slash, so this is safe
    for them too."""
    encoded = quote(identifier, safe="")
    if identifier.startswith("/") or "//" in identifier:
        encoded = quote(encoded, safe="")
    return encoded


class ZoomEndpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    # None when Zoom hands us the URL at runtime rather than us building one.
    path: str | None
    tier: ZoomRateLimitTier
    describes: str
    requires: ZoomEntitlement = ZoomEntitlement.NONE
    operation: str = ""

    def url(self, identifier: str = "") -> str:
        if self.path is None:
            raise ValueError(f"{self.describes} has no path of its own")
        path = self.path.format(identifier=encode_identifier(identifier))
        return path if path.startswith("https://") else f"{API_BASE_URL}{path}"

    def description(self, identifier: str = "") -> str:
        """An admin reads this, so it keeps the raw identifier, not the encoded one."""
        return self.describes.format(identifier=identifier)


# Not /meetings/{id}/transcript. Against a live account that answered 404 for a
# session whose VTT was sitting in recording_files.
MEETING_RECORDINGS = ZoomEndpoint(
    path="/meetings/{identifier}/recordings",
    tier=ZoomRateLimitTier.LIGHT,
    describes="the recording files for {identifier}",
    operation="recordingGet",
)

# Zoom really names this GET recordingSettingUpdate. recordingSettingsUpdate is
# the PATCH on the same path.
RECORDING_SETTINGS = ZoomEndpoint(
    path="/meetings/{identifier}/recordings/settings",
    tier=ZoomRateLimitTier.LIGHT,
    describes="the share settings of the recording of {identifier}",
    operation="recordingSettingUpdate",
)

RECORDING_REGISTRANTS = ZoomEndpoint(
    path="/meetings/{identifier}/recordings/registrants",
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the viewers registered for the recording of {identifier}",
    operation="meetingRecordingRegistrants",
)

PAST_MEETING_DETAILS = ZoomEndpoint(
    path="/past_meetings/{identifier}",
    tier=ZoomRateLimitTier.LIGHT,
    describes="the details for {identifier}",
    operation="pastMeetingDetails",
)

PAST_MEETING_OCCURRENCES = ZoomEndpoint(
    path="/past_meetings/{identifier}/instances",
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the occurrences for {identifier}",
    operation="pastMeetings",
)

MEETING_DETAILS = ZoomEndpoint(
    path="/meetings/{identifier}",
    tier=ZoomRateLimitTier.LIGHT,
    describes="the details for meeting {identifier}",
    operation="meeting",
)

WEBINAR_DETAILS = ZoomEndpoint(
    path="/webinars/{identifier}",
    tier=ZoomRateLimitTier.LIGHT,
    describes="the details for webinar {identifier}",
    requires=ZoomEntitlement.WEBINAR,
    operation="webinar",
)

PAST_WEBINAR_OCCURRENCES = ZoomEndpoint(
    path="/past_webinars/{identifier}/instances",
    tier=ZoomRateLimitTier.LIGHT,
    describes="the occurrences for webinar {identifier}",
    requires=ZoomEntitlement.WEBINAR,
    operation="pastWebinars",
)

GROUP_MEMBERS = ZoomEndpoint(
    path="/groups/{identifier}/members",
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the members of group {identifier}",
    operation="groupMembers",
)

USERS = ZoomEndpoint(
    path="/users",
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the account's users",
    operation="users",
)

USER = ZoomEndpoint(
    path="/users/{identifier}",
    tier=ZoomRateLimitTier.LIGHT,
    describes="user {identifier}",
    operation="user",
)

USER_SETTINGS = ZoomEndpoint(
    path="/users/{identifier}/settings",
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the settings of user {identifier}",
    operation="userSettings",
)

USER_RECORDINGS = ZoomEndpoint(
    path="/users/{identifier}/recordings",
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the recordings for user {identifier}",
    operation="recordingsList",
)

# Zoom publishes no rate-limit label for this one, so the stricter tier is a
# deliberate choice rather than a default. A token lasts an hour either way.
OAUTH_TOKEN = ZoomEndpoint(
    path=OAUTH_TOKEN_URL,
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the OAuth token request",
)

# Zoom hands back a signed URL on a storage host, so there is no path to build.
TRANSCRIPT_DOWNLOAD = ZoomEndpoint(
    path=None,
    tier=ZoomRateLimitTier.MEDIUM,
    describes="the transcript download",
)
