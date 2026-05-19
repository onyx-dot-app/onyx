"""Tests for the Tier total ordering and tier_gate longest-prefix logic."""

import pytest

from ee.onyx.configs.license_enforcement_config import PATH_PREFIX_MIN_TIER
from ee.onyx.server.middleware.tier_gate import _required_tier
from onyx.server.settings.models import Tier
from onyx.server.settings.tier_order import tier_at_least
from onyx.server.settings.tier_order import TIER_RANK


class TestTierOrdering:
    def test_rank_is_strictly_increasing(self) -> None:
        assert (
            TIER_RANK[Tier.COMMUNITY]
            < TIER_RANK[Tier.BUSINESS]
            < TIER_RANK[Tier.ENTERPRISE]
        )

    @pytest.mark.parametrize("tier", list(Tier))
    def test_reflexive(self, tier: Tier) -> None:
        assert tier_at_least(tier, tier) is True

    @pytest.mark.parametrize(
        "current,required,expected",
        [
            (Tier.COMMUNITY, Tier.BUSINESS, False),
            (Tier.COMMUNITY, Tier.ENTERPRISE, False),
            (Tier.BUSINESS, Tier.COMMUNITY, True),
            (Tier.BUSINESS, Tier.BUSINESS, True),
            (Tier.BUSINESS, Tier.ENTERPRISE, False),
            (Tier.ENTERPRISE, Tier.COMMUNITY, True),
            (Tier.ENTERPRISE, Tier.BUSINESS, True),
            (Tier.ENTERPRISE, Tier.ENTERPRISE, True),
        ],
    )
    def test_total_ordering(
        self, current: Tier, required: Tier, expected: bool
    ) -> None:
        assert tier_at_least(current, required) is expected


class TestTierGateLongestPrefix:
    def test_longest_prefix_wins_for_scim_under_enterprise_settings(self) -> None:
        # /admin/enterprise-settings/scim is ENTERPRISE, while
        # /admin/enterprise-settings (its parent) is BUSINESS — the
        # nested SCIM path must resolve to ENTERPRISE.
        assert _required_tier("/admin/enterprise-settings/scim/token") == (
            Tier.ENTERPRISE
        )

    def test_business_path_resolves(self) -> None:
        assert _required_tier("/admin/query-history/start-export") == Tier.BUSINESS

    def test_enterprise_path_resolves(self) -> None:
        assert _required_tier("/admin/hooks/123") == Tier.ENTERPRISE

    def test_unmapped_path_returns_none(self) -> None:
        assert _required_tier("/manage/users") is None
        assert _required_tier("/chat") is None

    @pytest.mark.parametrize("prefix,expected", list(PATH_PREFIX_MIN_TIER.items()))
    def test_each_registered_prefix_resolves_to_its_tier(
        self, prefix: str, expected: Tier
    ) -> None:
        # Append a trailing segment so we exercise prefix matching, not
        # exact equality.
        assert _required_tier(f"{prefix}/anything") == expected
