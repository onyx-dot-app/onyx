import abc
from typing import Any
from uuid import UUID

from onyx.db.models import User


class FeatureFlagProvider(abc.ABC):
    """
    Abstract base class for feature flag providers.

    Implementations should provide vendor-specific logic for checking
    whether a feature flag is enabled for a given user.
    """

    @abc.abstractmethod
    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        """
        Check if a feature flag is enabled for a user.

        Args:
            flag_key: The identifier for the feature flag to check
            user_id: The unique identifier for the user
            user_properties: Optional dictionary of user properties/attributes
                           that may influence flag evaluation

        Returns:
            True if the feature is enabled for the user, False otherwise
        """
        raise NotImplementedError

    def feature_enabled_for_user_tenant(
        self, flag_key: str, user: User, tenant_id: str
    ) -> bool:
        """
        Check if a feature flag is enabled for a user.
        """
        return self.feature_enabled(
            flag_key,
            user.id,
            user_properties={"tenant_id": tenant_id, "email": user.email},
        )


class NoOpFeatureFlagProvider(FeatureFlagProvider):
    """
    No-operation feature flag provider that always returns False.

    Used as a fallback when no real feature flag provider is available
    (e.g., in MIT version without PostHog).
    """

    def feature_enabled(
        self,
        flag_key: str,
        user_id: UUID,
        user_properties: dict[str, Any] | None = None,
    ) -> bool:
        return False
