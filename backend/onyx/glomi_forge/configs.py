"""Configuration for the glomi_forge feature (Daytona + Pi delivery runtime).

Strangler module — parallel to server/features/build (opencode Craft). Gated by
ENABLE_GLOMI_FORGE; when off, nothing here should run.
"""
import os

ENABLE_GLOMI_FORGE = os.environ.get("ENABLE_GLOMI_FORGE", "").lower() == "true"

# Self-hosted Daytona control-plane endpoint + key. For local dev this points at
# the docker-compose stack; in prod at the in-cluster Daytona API.
DAYTONA_API_URL = os.environ.get("DAYTONA_API_URL") or None
DAYTONA_API_KEY = os.environ.get("DAYTONA_API_KEY") or None

# Snapshot (OCI image) that the landing-page template builds in.
GLOMI_FORGE_DEFAULT_SNAPSHOT = os.environ.get(
    "GLOMI_FORGE_DEFAULT_SNAPSHOT", "glomi-landing-page"
)
LANDING_PAGE_TEMPLATE_ID = "landing_page"

# Port the in-sandbox Next.js dev server listens on; exposed via Daytona preview.
SANDBOX_PREVIEW_PORT = int(os.environ.get("GLOMI_FORGE_PREVIEW_PORT", "3000"))
