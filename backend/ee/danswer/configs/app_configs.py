import os

# Applicable for OIDC Auth
OPENID_CONFIG_URL = os.environ.get("OPENID_CONFIG_URL", "")

# Applicable for SAML Auth
SAML_CONF_DIR = os.environ.get("SAML_CONF_DIR") or "/app/ee/danswer/configs/saml_config"


#####
# Auto Permission Sync
#####
NUM_PERMISSION_WORKERS = int(os.environ.get("NUM_PERMISSION_WORKERS") or 2)


STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE")

OPENAI_DEFAULT_API_KEY = os.environ.get("OPENAI_DEFAULT_API_KEY")
ANTHROPIC_DEFAULT_API_KEY = os.environ.get("ANTHROPIC_DEFAULT_API_KEY")
COHERE_DEFAULT_API_KEY = os.environ.get("COHERE_DEFAULT_API_KEY")
