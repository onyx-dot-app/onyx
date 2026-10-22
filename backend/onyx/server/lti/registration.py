"""Public Canvas Developer Key metadata, available before LTI is configured."""

from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from onyx.configs.app_configs import WEB_DOMAIN


router = APIRouter(prefix="/auth/lti")


@router.get("/registration.json")
def lti_registration() -> JSONResponse:
    """Publish only public tool metadata using the configured deployment URL.

    Never derive registration URLs from request headers or include LTI/OAuth
    credentials. Canvas fetches this document without an Onyx session.
    """
    base_url = WEB_DOMAIN.rstrip("/")
    launch_url = f"{base_url}/auth/lti/launch"
    return JSONResponse(
        content={
            "title": "Onyx AI Tutor",
            "description": "AI learning assistant for Canvas courses",
            "oidc_initiation_url": f"{base_url}/auth/lti/login",
            "target_link_uri": launch_url,
            "scopes": [
                "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
            ],
            "extensions": [
                {
                    "domain": urlparse(base_url).netloc,
                    "tool_id": "onyx-learning-assistant",
                    "platform": "canvas.instructure.com",
                    "privacy_level": "public",
                    "settings": {
                        "text": "Onyx AI Tutor",
                        "icon_url": f"{base_url}/logo.png",
                        "selection_height": 800,
                        "selection_width": 1200,
                        "placements": [
                            {
                                "enabled": True,
                                "placement": "link_selection",
                                "message_type": "LtiResourceLinkRequest",
                                "target_link_uri": launch_url,
                                "text": "Onyx AI Tutor",
                            },
                            {
                                "enabled": True,
                                "placement": "course_navigation",
                                "message_type": "LtiResourceLinkRequest",
                                "target_link_uri": launch_url,
                                "text": "Onyx AI Tutor",
                                "default": "enabled",
                                "visibility": "members",
                            },
                        ],
                    },
                }
            ],
            "public_jwk_url": f"{base_url}/auth/lti/jwks",
            "custom_fields": {
                "user_id": "$Canvas.user.id",
                "course_id": "$Canvas.course.id",
                "course_name": "$Canvas.course.name",
                "account_id": "$Canvas.account.id",
                "account_name": "$Canvas.account.name",
                "context_id_history": "$Context.id.history",
            },
        },
        headers={"Cache-Control": "no-store"},
    )
