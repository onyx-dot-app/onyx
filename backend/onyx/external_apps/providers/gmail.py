from onyx.db.enums import ExternalAppType
from onyx.external_apps.providers.google_base import GoogleOAuthProvider


class GmailProvider(GoogleOAuthProvider):
    spec = GoogleOAuthProvider.build_spec(
        app_type=ExternalAppType.GMAIL,
        app_name="Gmail",
        # gmail.modify covers read, send, label, and trash — but not permanent
        # delete, which keeps the integration safer by default.
        scope="https://www.googleapis.com/auth/gmail.modify",
        upstream_url_patterns=["https://gmail\\.googleapis\\.com/gmail/.*"],
        description=(
            "Read, search, and send email from your Gmail account inside Onyx Craft."
        ),
        google_api_name="Gmail API",
    )
