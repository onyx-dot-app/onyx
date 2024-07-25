import os

# Applicable for OIDC Auth
OPENID_CONFIG_URL = os.environ.get("OPENID_CONFIG_URL", "")

# Applicable for SAML Auth
SAML_CONF_DIR = os.environ.get("SAML_CONF_DIR") or "/app/ee/danswer/configs/saml_config"


#####
# API Key Configs
#####
# refers to the rounds described here: https://passlib.readthedocs.io/en/stable/lib/passlib.hash.sha256_crypt.html
_API_KEY_HASH_ROUNDS_RAW = os.environ.get("API_KEY_HASH_ROUNDS")
API_KEY_HASH_ROUNDS = (
    int(_API_KEY_HASH_ROUNDS_RAW) if _API_KEY_HASH_ROUNDS_RAW else None
)


#####
# Auto Permission Sync
#####
NUM_PERMISSION_WORKERS = int(os.environ.get("NUM_PERMISSION_WORKERS") or 2)
