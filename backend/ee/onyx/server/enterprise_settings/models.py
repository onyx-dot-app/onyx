from enum import Enum
from typing import Any
from typing import List

from pydantic import BaseModel
from pydantic import Field


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


class EnterpriseSettings(BaseModel):
    """General settings that only apply to the Enterprise Edition of Onyx

    NOTE: don't put anything sensitive in here, as this is accessible without auth."""

    application_name: str | None = None
    use_custom_logo: bool = False
    use_custom_logotype: bool = False
    logo_display_style: LogoDisplayStyle | None = None

    # custom navigation
    custom_nav_items: List[NavigationItem] = Field(default_factory=list)

    # custom Chat components
    two_lines_for_chat_header: bool | None = None
    custom_lower_disclaimer_content: str | None = None
    custom_header_content: str | None = None
    custom_popup_header: str | None = None
    custom_popup_content: str | None = None
    enable_consent_screen: bool | None = None
    consent_screen_prompt: str | None = None
    show_first_visit_notice: bool | None = None
    custom_greeting_message: str | None = None

    def check_validity(self) -> None:
        return


class AnalyticsScriptUpload(BaseModel):
    script: str
    secret_key: str
