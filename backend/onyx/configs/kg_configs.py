import json
import os

USE_KG_APPROACH = os.environ.get("USE_KG_APPROACH", "false").lower() == "true"


KG_IGNORE_EMAIL_DOMAINS: list[str] = json.loads(
    os.environ.get("KG_IGNORE_EMAIL_DOMAINS", "[]")
)  # must be list

# The 'own company', i.e., the name of the Onyx customer.
KG_VENDOR: str = os.environ.get("KG_OWN_COMPANY", "")

KG_VENDOR_DOMAINS: list[str] = json.loads(
    os.environ.get("KG_VENDOR_DOMAINS", "[]")
)  # must be list
