import pytest

from onyx.server.settings import tier_order
from onyx.server.settings.models import Tier
from onyx.utils.variable_functionality import global_version


def test_current_tier_is_community_without_ee(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(global_version, "is_ee_version", lambda: False)
    assert tier_order.get_current_tier() is Tier.COMMUNITY


def test_current_tier_uses_ee_tier(
    enable_ee: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ee.onyx.utils import tier as ee_tier

    monkeypatch.setattr(ee_tier, "get_tier", lambda: Tier.ENTERPRISE)
    assert tier_order.get_current_tier() is Tier.ENTERPRISE
