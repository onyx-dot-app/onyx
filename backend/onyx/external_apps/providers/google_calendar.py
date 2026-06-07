from onyx.configs.app_configs import EXT_APP_GOOGLE_CALENDAR_CLIENT_ID
from onyx.configs.app_configs import EXT_APP_GOOGLE_CALENDAR_CLIENT_SECRET
from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.actions import EndpointSpec
from onyx.external_apps.providers.actions import ExternalAppAction
from onyx.external_apps.providers.actions import RestRoute
from onyx.external_apps.providers.base import OnyxManagedExtApp
from onyx.external_apps.providers.google_base import GoogleOAuthProvider


# Google Calendar REST v3 (https://www.googleapis.com/calendar/v3/...); the
# action is HTTP method + path. Method disambiguates list/create on the shared
# `/events` collection and read/update/delete on `/events/{id}`.
class GoogleCalendarAction(ExternalAppAction):
    """Strongly-typed catalog ids for the Google Calendar provider."""

    CALENDARS_READ = "gcal.calendars.read"
    EVENTS_READ = "gcal.events.read"
    FREEBUSY_READ = "gcal.freebusy.read"
    EVENTS_CREATE = "gcal.events.create"
    EVENTS_UPDATE = "gcal.events.update"
    EVENTS_DELETE = "gcal.events.delete"


_EVENTS_COLLECTION = "/calendar/v3/calendars/{calendarId}/events"
_EVENT_ITEM = "/calendar/v3/calendars/{calendarId}/events/{eventId}"
_ENDPOINTS: list[EndpointSpec] = [
    EndpointSpec(
        id=GoogleCalendarAction.CALENDARS_READ,
        normalised_name="List calendars",
        description="List the calendars on the user's calendar list.",
        matches=(
            RestRoute(method="GET", path="/calendar/v3/users/{userId}/calendarList"),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleCalendarAction.EVENTS_READ,
        normalised_name="Read events",
        description="List events in a calendar or fetch a single event.",
        matches=(
            RestRoute(method="GET", path=_EVENTS_COLLECTION),
            RestRoute(method="GET", path=_EVENT_ITEM),
        ),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleCalendarAction.FREEBUSY_READ,
        normalised_name="Query free/busy",
        description="Query busy intervals across calendars.",
        matches=(RestRoute(method="POST", path="/calendar/v3/freeBusy"),),
        default_policy=EndpointPolicy.ALWAYS,
    ),
    EndpointSpec(
        id=GoogleCalendarAction.EVENTS_CREATE,
        normalised_name="Create an event",
        description="Create a new event on a calendar.",
        matches=(RestRoute(method="POST", path=_EVENTS_COLLECTION),),
    ),
    EndpointSpec(
        id=GoogleCalendarAction.EVENTS_UPDATE,
        normalised_name="Update an event",
        description="Modify an existing event.",
        matches=(
            RestRoute(method="PUT", path=_EVENT_ITEM),
            RestRoute(method="PATCH", path=_EVENT_ITEM),
        ),
    ),
    EndpointSpec(
        id=GoogleCalendarAction.EVENTS_DELETE,
        normalised_name="Delete an event",
        description="Permanently delete an event.",
        matches=(RestRoute(method="DELETE", path=_EVENT_ITEM),),
    ),
]


class GoogleCalendarProvider(GoogleOAuthProvider, OnyxManagedExtApp):
    spec = GoogleOAuthProvider.build_spec(
        app_type=ExternalAppType.GOOGLE_CALENDAR,
        app_name="Google Calendar",
        scope="https://www.googleapis.com/auth/calendar",
        upstream_url_patterns=["https://www\\.googleapis\\.com/calendar/.*"],
        description=(
            "Read and create events on your Google Calendar from inside Onyx Craft."
        ),
        google_api_name="Google Calendar API",
        endpoint_catalog=_ENDPOINTS,
    )

    managed_org_credentials = {
        "client_id": EXT_APP_GOOGLE_CALENDAR_CLIENT_ID,
        "client_secret": EXT_APP_GOOGLE_CALENDAR_CLIENT_SECRET,
    }
