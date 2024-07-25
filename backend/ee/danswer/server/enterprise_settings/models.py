from pydantic import BaseModel


class EnterpriseSettings(BaseModel):
    """General settings that only apply to the Enterprise Edition of Danswer

    NOTE: don't put anything sensitive in here, as this is accessible without auth."""

    application_name: str | None = None
    use_custom_logo: bool = False

    # custom Chat components
    custom_header_content: str | None = None
    custom_popup_header: str | None = None
    custom_popup_content: str | None = None

    def check_validity(self) -> None:
        return


class AnalyticsScriptUpload(BaseModel):
    script: str
    secret_key: str
