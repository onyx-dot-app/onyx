from enum import Enum
from typing import Any, List
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class NavigationItem(BaseModel):
    link: str
    title: str
    # Right now must be one of the FA icons
    icon: str | None = None
    # NOTE: SVG must not have a width / height specified
    # This is the actual SVG as a string. Done this way to reduce
    # complexity / having to store additional "logos" in Postgres
    svg_logo: str | None = None

    @classmethod
    def model_validate(cls, *args: Any, **kwargs: Any) -> "NavigationItem":
        instance = super().model_validate(*args, **kwargs)
        if bool(instance.icon) == bool(instance.svg_logo):
            raise ValueError("Exactly one of fa_icon or svg_logo must be specified")
        return instance


class LogoDisplayStyle(str, Enum):
    LOGO_AND_NAME = "logo_and_name"
    LOGO_ONLY = "logo_only"
    NAME_ONLY = "name_only"


# Length caps for the admin-authored appearance strings.
#
# Enforced here rather than only in the form, because the form is the client
# and a client cannot be trusted to bound what it sends. Everything below is
# stored in one KV blob and served without auth, so an unbounded field is
# served to every anonymous caller.
#
# The theme page keeps its own copy for its character counters. Keep the two in
# step; `test_appearance_char_limits.py` fails when they drift.
MAX_APPLICATION_NAME_LEN: int = 50
MAX_GREETING_MESSAGE_LEN: int = 50
MAX_LOGIN_SUBTITLE_LEN: int = 100
MAX_HEADER_CONTENT_LEN: int = 100
MAX_LOWER_DISCLAIMER_CONTENT_LEN: int = 500
MAX_POPUP_HEADER_LEN: int = 100
MAX_POPUP_CONTENT_LEN: int = 500
MAX_CONSENT_SCREEN_PROMPT_LEN: int = 200

# Field name to cap, for callers that have to reconcile a stored value against
# these limits rather than reject it. `load_settings` is the one that does:
# the caps validate on deserialisation too, so a blob written before they
# existed would otherwise make the settings endpoint unreadable.
APPEARANCE_FIELD_MAX_LENGTHS: dict[str, int] = {
    "application_name": MAX_APPLICATION_NAME_LEN,
    "custom_greeting_message": MAX_GREETING_MESSAGE_LEN,
    "custom_login_subtitle": MAX_LOGIN_SUBTITLE_LEN,
    "custom_header_content": MAX_HEADER_CONTENT_LEN,
    "custom_lower_disclaimer_content": MAX_LOWER_DISCLAIMER_CONTENT_LEN,
    "custom_popup_header": MAX_POPUP_HEADER_LEN,
    "custom_popup_content": MAX_POPUP_CONTENT_LEN,
    "consent_screen_prompt": MAX_CONSENT_SCREEN_PROMPT_LEN,
}


class EnterpriseSettings(BaseModel):
    """General settings that only apply to the Enterprise Edition of Onyx

    NOTE: don't put anything sensitive in here, as this is accessible without auth."""

    application_name: str | None = Field(
        default=None, max_length=MAX_APPLICATION_NAME_LEN
    )
    use_custom_logo: bool = False
    use_custom_logotype: bool = False
    logo_display_style: LogoDisplayStyle | None = None

    # custom navigation
    custom_nav_items: List[NavigationItem] = Field(default_factory=list)

    # custom Chat components
    two_lines_for_chat_header: bool | None = None
    custom_lower_disclaimer_content: str | None = Field(
        default=None, max_length=MAX_LOWER_DISCLAIMER_CONTENT_LEN
    )
    custom_header_content: str | None = Field(
        default=None, max_length=MAX_HEADER_CONTENT_LEN
    )
    custom_popup_header: str | None = Field(
        default=None, max_length=MAX_POPUP_HEADER_LEN
    )
    custom_popup_content: str | None = Field(
        default=None, max_length=MAX_POPUP_CONTENT_LEN
    )
    enable_consent_screen: bool | None = None
    consent_screen_prompt: str | None = Field(
        default=None, max_length=MAX_CONSENT_SCREEN_PROMPT_LEN
    )
    show_first_visit_notice: bool | None = None
    custom_greeting_message: str | None = Field(
        default=None, max_length=MAX_GREETING_MESSAGE_LEN
    )
    # login page subtitle under the "Welcome to <app name>" heading. Blank
    # falls back to the default Onyx tagline.
    custom_login_subtitle: str | None = Field(
        default=None, max_length=MAX_LOGIN_SUBTITLE_LEN
    )

    # custom help link surfaced in the profile dropdown alongside the
    # built-in "Help & FAQ" item
    custom_help_link_url: str | None = None
    custom_help_link_label: str | None = None

    # hide the "Powered by Onyx" tagline under the sidebar logo
    hide_onyx_branding: bool | None = None

    @field_validator("custom_help_link_url")
    @classmethod
    def _validate_help_link_scheme(cls, v: str | None) -> str | None:
        if not v:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "custom_help_link_url must be an absolute http or https URL"
            )
        return v

    def check_validity(self) -> None:
        return


class AnalyticsScriptUpload(BaseModel):
    script: str
    secret_key: str
