"""SCIM Data Access Layer.

All database operations for SCIM provisioning — token management, user
mappings, and group mappings. Extends the base DAL (see ``onyx.db.dal``).

Usage from FastAPI::

    def get_scim_dal(db_session: Session = Depends(get_session)) -> ScimDAL:
        return ScimDAL(db_session)

    @router.post("/tokens")
    def create_token(dal: ScimDAL = Depends(get_scim_dal)) -> ...:
        token = dal.create_token(name=..., hashed_token=..., ...)
        dal.commit()
        return token

Usage from background tasks::

    with ScimDAL.from_tenant("tenant_abc") as dal:
        mapping = dal.create_user_mapping(external_id="idp-123", user_id=uid)
        dal.commit()
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select

from onyx.db.dal import DAL
from onyx.db.models import ScimGroupMapping
from onyx.db.models import ScimToken
from onyx.db.models import ScimUserMapping


class ScimDAL(DAL):
    """Data Access Layer for SCIM provisioning operations.

    Methods mutate but do NOT commit — call ``dal.commit()`` explicitly
    when you want to persist changes. This follows the existing ``_no_commit``
    convention and lets callers batch multiple operations into one transaction.
    """

    # ------------------------------------------------------------------
    # Token operations
    # ------------------------------------------------------------------

    def create_token(
        self,
        name: str,
        hashed_token: str,
        token_display: str,
        created_by_id: UUID,
    ) -> ScimToken:
        """Create a new SCIM bearer token.

        Only one token is active at a time — this method automatically revokes
        all existing active tokens before creating the new one.
        """
        # Revoke any currently active tokens
        active_tokens = list(
            self._session.scalars(
                select(ScimToken).where(ScimToken.is_active.is_(True))
            ).all()
        )
        for t in active_tokens:
            t.is_active = False

        token = ScimToken(
            name=name,
            hashed_token=hashed_token,
            token_display=token_display,
            created_by_id=created_by_id,
        )
        self._session.add(token)
        self._session.flush()
        return token

    def get_active_token(self) -> ScimToken | None:
        """Return the single currently active token, or None."""
        return self._session.scalar(
            select(ScimToken).where(ScimToken.is_active.is_(True))
        )

    def get_token_by_hash(self, hashed_token: str) -> ScimToken | None:
        """Look up a token by its SHA-256 hash."""
        return self._session.scalar(
            select(ScimToken).where(ScimToken.hashed_token == hashed_token)
        )

    def revoke_token(self, token_id: int) -> None:
        """Deactivate a token by ID.

        Raises:
            ValueError: If the token does not exist.
        """
        token = self._session.get(ScimToken, token_id)
        if not token:
            raise ValueError(f"SCIM token with id {token_id} not found")
        token.is_active = False

    def update_token_last_used(self, token_id: int) -> None:
        """Update the last_used_at timestamp for a token."""
        token = self._session.get(ScimToken, token_id)
        if token:
            token.last_used_at = func.now()  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # User mapping operations
    # ------------------------------------------------------------------

    def create_user_mapping(
        self,
        external_id: str,
        user_id: UUID,
    ) -> ScimUserMapping:
        """Create a mapping between a SCIM externalId and an Onyx user."""
        mapping = ScimUserMapping(external_id=external_id, user_id=user_id)
        self._session.add(mapping)
        self._session.flush()
        return mapping

    def get_user_mapping_by_external_id(
        self, external_id: str
    ) -> ScimUserMapping | None:
        """Look up a user mapping by the IdP's external identifier."""
        return self._session.scalar(
            select(ScimUserMapping).where(ScimUserMapping.external_id == external_id)
        )

    def get_user_mapping_by_user_id(self, user_id: UUID) -> ScimUserMapping | None:
        """Look up a user mapping by the Onyx user ID."""
        return self._session.scalar(
            select(ScimUserMapping).where(ScimUserMapping.user_id == user_id)
        )

    def list_user_mappings(
        self,
        start_index: int = 1,
        count: int = 100,
    ) -> tuple[list[ScimUserMapping], int]:
        """List user mappings with SCIM-style pagination.

        Args:
            start_index: 1-based start index (SCIM convention).
            count: Maximum number of results to return.

        Returns:
            A tuple of (mappings, total_count).
        """
        total = (
            self._session.scalar(select(func.count()).select_from(ScimUserMapping)) or 0
        )

        offset = max(start_index - 1, 0)
        mappings = list(
            self._session.scalars(
                select(ScimUserMapping)
                .order_by(ScimUserMapping.id)
                .offset(offset)
                .limit(count)
            ).all()
        )

        return mappings, total

    def update_user_mapping_external_id(
        self,
        mapping_id: int,
        external_id: str,
    ) -> ScimUserMapping:
        """Update the external ID on a user mapping.

        Raises:
            ValueError: If the mapping does not exist.
        """
        mapping = self._session.get(ScimUserMapping, mapping_id)
        if not mapping:
            raise ValueError(f"SCIM user mapping with id {mapping_id} not found")
        mapping.external_id = external_id
        return mapping

    def delete_user_mapping(self, mapping_id: int) -> None:
        """Delete a user mapping by ID.

        Raises:
            ValueError: If the mapping does not exist.
        """
        mapping = self._session.get(ScimUserMapping, mapping_id)
        if not mapping:
            raise ValueError(f"SCIM user mapping with id {mapping_id} not found")
        self._session.delete(mapping)

    # ------------------------------------------------------------------
    # Group mapping operations
    # ------------------------------------------------------------------

    def create_group_mapping(
        self,
        external_id: str,
        user_group_id: int,
    ) -> ScimGroupMapping:
        """Create a mapping between a SCIM externalId and an Onyx user group."""
        mapping = ScimGroupMapping(external_id=external_id, user_group_id=user_group_id)
        self._session.add(mapping)
        self._session.flush()
        return mapping

    def get_group_mapping_by_external_id(
        self, external_id: str
    ) -> ScimGroupMapping | None:
        """Look up a group mapping by the IdP's external identifier."""
        return self._session.scalar(
            select(ScimGroupMapping).where(ScimGroupMapping.external_id == external_id)
        )

    def get_group_mapping_by_group_id(
        self, user_group_id: int
    ) -> ScimGroupMapping | None:
        """Look up a group mapping by the Onyx user group ID."""
        return self._session.scalar(
            select(ScimGroupMapping).where(
                ScimGroupMapping.user_group_id == user_group_id
            )
        )

    def list_group_mappings(
        self,
        start_index: int = 1,
        count: int = 100,
    ) -> tuple[list[ScimGroupMapping], int]:
        """List group mappings with SCIM-style pagination.

        Args:
            start_index: 1-based start index (SCIM convention).
            count: Maximum number of results to return.

        Returns:
            A tuple of (mappings, total_count).
        """
        total = (
            self._session.scalar(select(func.count()).select_from(ScimGroupMapping))
            or 0
        )

        offset = max(start_index - 1, 0)
        mappings = list(
            self._session.scalars(
                select(ScimGroupMapping)
                .order_by(ScimGroupMapping.id)
                .offset(offset)
                .limit(count)
            ).all()
        )

        return mappings, total

    def delete_group_mapping(self, mapping_id: int) -> None:
        """Delete a group mapping by ID.

        Raises:
            ValueError: If the mapping does not exist.
        """
        mapping = self._session.get(ScimGroupMapping, mapping_id)
        if not mapping:
            raise ValueError(f"SCIM group mapping with id {mapping_id} not found")
        self._session.delete(mapping)
