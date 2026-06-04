"""Unit tests for split input/output cost and admin per-model overrides (SQLite)."""

from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy import create_engine
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.db.models import ModelCostOverride
from onyx.llm import cost as cost_mod
from onyx.llm import cost_overrides
from onyx.llm.cost import compute_cost_cents
from onyx.tracing.flows import LLMFlow
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@compiles(PGUUID, "sqlite")
def _compile_pguuid_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "CHAR(36)"


@compiles(PGJSONB, "sqlite")
def _compile_jsonb_sqlite(_element: object, _compiler: object, **_kw: object) -> str:
    return "JSON"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine: Engine = create_engine("sqlite://")
    cast(Table, ModelCostOverride.__table__).create(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clear_override_cache() -> Generator[None, None, None]:
    # Wipe every tenant's snapshot (invalidate_override_cache is tenant-scoped).
    cost_overrides._cache.clear()
    yield
    cost_overrides._cache.clear()


class TestComputeCostCents:
    def test_known_model_splits_input_and_output(self) -> None:
        # gpt-4o: $2.50/Mtok in, $10.00/Mtok out → 1000 tok each.
        in_cents, out_cents = compute_cost_cents(
            model="gpt-4o",
            provider="openai",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert in_cents == pytest.approx(0.25)
        assert out_cents == pytest.approx(1.0)

    def test_unknown_model_returns_zero_no_raise(self) -> None:
        result = compute_cost_cents(
            model="totally-made-up-model-xyz",
            provider="nobody",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert result == (0.0, 0.0)

    def test_unknown_model_uses_configurable_fallback_rates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # With a fallback configured, an unpriced model accrues cost instead of $0.
        monkeypatch.setattr(cost_mod, "DEFAULT_LLM_INPUT_COST_PER_MTOK", 2.0)
        monkeypatch.setattr(cost_mod, "DEFAULT_LLM_OUTPUT_COST_PER_MTOK", 6.0)
        in_cents, out_cents = compute_cost_cents(
            model="totally-made-up-model-xyz",
            provider="nobody",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            cache_read_tokens=0,
        )
        assert in_cents == pytest.approx(200.0)  # 1M * $2/Mtok = $2.00 = 200c
        assert out_cents == pytest.approx(600.0)  # 1M * $6/Mtok = $6.00 = 600c

    def test_cache_read_tokens_priced_as_input(self) -> None:
        # gpt-4o: $2.50/Mtok input, $1.25/Mtok cache-read. 1000 non-cached +
        # 2000 cache-read = 1000*2.5e-6 + 2000*1.25e-6 = $0.005 = 0.5 cents.
        # Pinned exactly to catch double-counting cached tokens at full rate.
        cache_in, cache_out = compute_cost_cents(
            "gpt-4o",
            "openai",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=2000,
        )
        assert cache_in == pytest.approx(0.5)
        # Output (500 tok @ $10/Mtok) is unaffected by cache reads.
        assert cache_out == pytest.approx(0.5)

    def test_bedrock_model_priced_via_provider(self) -> None:
        # Bedrock names aren't self-identifying — without custom_llm_provider
        # litellm raises and the cost silently collapses to $0. Haiku:
        # $0.25/Mtok in, $1.25/Mtok out → 0.025c in, 0.125c out for 1000 tok.
        in_cents, out_cents = compute_cost_cents(
            model="anthropic.claude-3-haiku-20240307-v1:0",
            provider="bedrock",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert in_cents == pytest.approx(0.025)
        assert out_cents == pytest.approx(0.125)


class TestImageFlow:
    def test_image_flow_uses_image_pricing(self) -> None:
        # dall-e-3 is priced per-image ($0.04 = 4 cents), not per-token.
        in_cents, out_cents = compute_cost_cents(
            model="dall-e-3",
            provider="openai",
            input_tokens=0,
            output_tokens=0,
            flow=LLMFlow.IMAGE_GENERATION,
        )
        assert (in_cents + out_cents) == pytest.approx(4.0)

    def test_unpriced_image_model_uses_flat_constant(self) -> None:
        in_cents, out_cents = compute_cost_cents(
            model="some-unpriced-image-model",
            provider="nobody",
            input_tokens=0,
            output_tokens=0,
            flow=LLMFlow.IMAGE_EDIT,
        )
        from onyx.configs.app_configs import DEFAULT_IMAGE_COST_CENTS

        assert (in_cents + out_cents) == pytest.approx(DEFAULT_IMAGE_COST_CENTS)


class TestOverride:
    def test_override_wins_over_litellm(self, db_session: Session) -> None:
        db_session.add(
            ModelCostOverride(
                model="gpt-4o",
                input_cost_per_mtok=1.0,  # $1.00/Mtok in
                output_cost_per_mtok=2.0,  # $2.00/Mtok out
            )
        )
        db_session.commit()

        in_cents, out_cents = compute_cost_cents(
            model="gpt-4o",
            provider="openai",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            db_session=db_session,
        )
        # $1.00 = 100 cents in, $2.00 = 200 cents out.
        assert in_cents == pytest.approx(100.0)
        assert out_cents == pytest.approx(200.0)

    def test_override_counts_cache_reads_as_input(self, db_session: Session) -> None:
        db_session.add(
            ModelCostOverride(
                model="gpt-4o",
                input_cost_per_mtok=1.0,
                output_cost_per_mtok=2.0,
            )
        )
        db_session.commit()

        in_cents, _ = compute_cost_cents(
            model="gpt-4o",
            provider="openai",
            input_tokens=500_000,
            output_tokens=0,
            cache_read_tokens=500_000,
            db_session=db_session,
        )
        # (500k + 500k) tok at $1/Mtok = $1.00 = 100 cents.
        assert in_cents == pytest.approx(100.0)

    def test_override_cache_rate_applied_when_set(self, db_session: Session) -> None:
        db_session.add(
            ModelCostOverride(
                model="gpt-4o",
                input_cost_per_mtok=1.0,
                output_cost_per_mtok=2.0,
                cache_read_cost_per_mtok=0.1,  # cache reads 10x cheaper than input
            )
        )
        db_session.commit()

        in_cents, _ = compute_cost_cents(
            model="gpt-4o",
            provider="openai",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_tokens=1_000_000,
            db_session=db_session,
        )
        # 1M input @ $1 = 100c + 1M cache @ $0.10 = 10c = 110 cents.
        assert in_cents == pytest.approx(110.0)

    def test_override_cache_is_tenant_scoped(self) -> None:
        # Each tenant has its own schema/session. Tenant A's negotiated rate
        # must not leak into tenant B's cost computation.
        def _session() -> Session:
            engine = create_engine("sqlite://")
            cast(Table, ModelCostOverride.__table__).create(bind=engine)
            return sessionmaker(bind=engine)()

        tenant_a, tenant_b = _session(), _session()
        tenant_a.add(
            ModelCostOverride(
                model="gpt-4o", input_cost_per_mtok=1.0, output_cost_per_mtok=2.0
            )
        )
        tenant_a.commit()

        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_a")
        try:
            a_in, a_out = compute_cost_cents(
                "gpt-4o",
                "openai",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                db_session=tenant_a,
            )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        assert (a_in, a_out) == pytest.approx((100.0, 200.0))

        # Tenant B has no override row → falls through to litellm gpt-4o pricing,
        # NOT tenant A's cached negotiated rate.
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("tenant_b")
        try:
            b_in, b_out = compute_cost_cents(
                "gpt-4o",
                "openai",
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                db_session=tenant_b,
            )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
        # litellm gpt-4o: $2.50/Mtok in, $10.00/Mtok out.
        assert (b_in, b_out) == pytest.approx((250.0, 1000.0))


class TestGetOverride:
    def test_returns_none_when_absent(self, db_session: Session) -> None:
        assert cost_overrides.get_override(db_session, "no-such-model") is None

    def test_returns_rates_when_present(self, db_session: Session) -> None:
        db_session.add(
            ModelCostOverride(
                model="claude-x",
                input_cost_per_mtok=3.0,
                output_cost_per_mtok=15.0,
            )
        )
        db_session.commit()

        rates = cost_overrides.get_override(db_session, "claude-x")
        assert rates is not None
        assert rates == (3.0, 15.0, None)

    def test_cache_invalidation_picks_up_new_row(self, db_session: Session) -> None:
        assert cost_overrides.get_override(db_session, "late-model") is None
        db_session.add(
            ModelCostOverride(
                model="late-model",
                input_cost_per_mtok=4.0,
                output_cost_per_mtok=8.0,
            )
        )
        db_session.commit()
        # Stale cache still says None until invalidated.
        assert cost_overrides.get_override(db_session, "late-model") is None
        cost_overrides.invalidate_override_cache()
        assert cost_overrides.get_override(db_session, "late-model") == (4.0, 8.0, None)
