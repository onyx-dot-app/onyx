from typing import Any
from uuid import UUID

from ee.onyx.utils.posthog_client import posthog
from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.utils.logger import setup_logger

logger = setup_logger()


class PostHogFeatureFlagProvider(FeatureFlagProvider):
    """
    PostHog-based feature flag provider.

    Uses PostHog's feature flag API to determine if features are enabled
    for specific users. Only active in multi-tenant mode.
    """

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        """
        Check if a feature flag is enabled for a user via PostHog.

        Args:
            flag_key: The identifier for the feature flag to check
            user_id: The unique identifier for the user
            user_properties: Optional dictionary of user properties/attributes
                           that may influence flag evaluation

        Returns:
            True if the feature is enabled for the user, False otherwise.
        """
        if not posthog:
            return False

        try:
            posthog.set(
                distinct_id=user_id,
                properties=user_properties,
            )
            is_enabled = posthog.feature_enabled(
                flag_key,
                str(user_id),
                person_properties=user_properties,
            )

            return bool(is_enabled) if is_enabled is not None else False

        except Exception as e:
            logger.error(
                "Error checking feature flag %s for user %s: %s", flag_key, user_id, e
            )
            return False

    def feature_variant_for_tenant(
        self, flag_key: str, tenant_id: str
    ) -> str | bool | None:
        if not posthog:
            return None

        try:
            return posthog.get_feature_flag(
                flag_key,
                tenant_id,
                person_properties={"tenant_id": tenant_id},
            )
        except Exception as e:
            logger.error(
                "Error fetching feature flag variant %s for tenant %s: %s",
                flag_key,
                tenant_id,
                e,
            )
            return None
