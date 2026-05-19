from onyx.configs.app_configs import MASK_CREDENTIAL_PREFIX
from onyx.configs.app_configs import PASSWORD_MAX_LENGTH
from onyx.configs.app_configs import PASSWORD_MIN_LENGTH
from onyx.configs.app_configs import PASSWORD_REQUIRE_DIGIT
from onyx.configs.app_configs import PASSWORD_REQUIRE_LOWERCASE
from onyx.configs.app_configs import PASSWORD_REQUIRE_SPECIAL_CHAR
from onyx.configs.app_configs import PASSWORD_REQUIRE_UPPERCASE
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.configs.app_configs import USER_DIRECTORY_ADMIN_ONLY
from onyx.configs.app_configs import VALID_EMAIL_DOMAINS
from onyx.configs.constants import KV_SECURITY_SETTINGS_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.security.models import SecuritySettings
from onyx.utils.logger import setup_logger

logger = setup_logger()


def load_raw_security_settings() -> SecuritySettings:
    """Load the raw SecuritySettings from KV. Fields that the admin has not
    saved remain None — the caller decides whether to apply env fallbacks.
    """
    kv_store = get_kv_store()
    try:
        stored = kv_store.load(KV_SECURITY_SETTINGS_KEY)
        return (
            SecuritySettings.model_validate(stored) if stored else SecuritySettings()
        )
    except KvKeyNotFoundError:
        return SecuritySettings()
    except Exception as e:
        logger.error("Error loading security settings from KV store: %s", str(e))
        return SecuritySettings()


def load_security_settings() -> SecuritySettings:
    """Load SecuritySettings with env-var fallbacks applied to any field the
    admin has not explicitly saved. This is the form callers should use when
    making policy decisions — every field is non-None.
    """
    settings = load_raw_security_settings()

    if settings.user_directory_admin_only is None:
        settings.user_directory_admin_only = USER_DIRECTORY_ADMIN_ONLY
    if settings.track_external_idp_expiry is None:
        settings.track_external_idp_expiry = TRACK_EXTERNAL_IDP_EXPIRY
    if settings.mask_credential_prefix is None:
        settings.mask_credential_prefix = MASK_CREDENTIAL_PREFIX
    if settings.valid_email_domains is None:
        settings.valid_email_domains = list(VALID_EMAIL_DOMAINS)
    if settings.password_min_length is None:
        settings.password_min_length = PASSWORD_MIN_LENGTH
    if settings.password_max_length is None:
        settings.password_max_length = PASSWORD_MAX_LENGTH
    if settings.password_require_uppercase is None:
        settings.password_require_uppercase = PASSWORD_REQUIRE_UPPERCASE
    if settings.password_require_lowercase is None:
        settings.password_require_lowercase = PASSWORD_REQUIRE_LOWERCASE
    if settings.password_require_digit is None:
        settings.password_require_digit = PASSWORD_REQUIRE_DIGIT
    if settings.password_require_special_char is None:
        settings.password_require_special_char = PASSWORD_REQUIRE_SPECIAL_CHAR

    return settings


def store_security_settings(settings: SecuritySettings) -> None:
    get_kv_store().store(KV_SECURITY_SETTINGS_KEY, settings.model_dump())
