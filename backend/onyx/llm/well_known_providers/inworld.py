_BASIC_PREFIX = "basic "

# The OpenAI SDK builds a Bearer header from its api_key, which the router reads
# as a JWT. It gets this placeholder, so the key travels only as Basic.
INWORLD_SDK_API_KEY_PLACEHOLDER = "inworld-basic-auth"


def inworld_authorization(api_key: str) -> str:
    """Authorization header value for an Inworld API key.

    Inworld keys are already Base64 `key:secret` credentials. The router reads
    them from a Basic header and treats a Bearer value as a JWT, so the key is
    never re-encoded and never sent as Bearer.
    """
    key = api_key.strip()
    if key.lower().startswith(_BASIC_PREFIX):
        key = key[len(_BASIC_PREFIX) :].strip()
    return f"Basic {key}"
