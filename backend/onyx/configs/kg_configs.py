import json
import os

USE_KG_APPROACH = os.environ.get("USE_KG_APPROACH", "false").lower() == "true"

KG_OWN_EMAIL_DOMAINS: list[str] = json.loads(
    os.environ.get("KG_OWN_EMAIL_DOMAINS", "[]")
)  # must be list

KG_IGNORE_EMAIL_DOMAINS: list[str] = json.loads(
    os.environ.get("KG_IGNORE_EMAIL_DOMAINS", "[]")
)  # must be list

KG_OWN_COMPANY: str = os.environ.get("KG_OWN_COMPANY", "")
