"""Guards the admin per-model reasoning cap, defaults, and temperature default."""

from typing import Any
from unittest.mock import patch

import pytest

from onyx.error_handling.exceptions import OnyxError
from onyx.llm.models import ReasoningEffort, UserMessage, resolve_reasoning_effort
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.manage.llm.models import (
    ModelConfigurationUpsertRequest,
    ensure_default_within_max,
)

_SENTINEL = object()


def _make_llm(
    reasoning_effort_default: ReasoningEffort | None = None,
    reasoning_effort_max: ReasoningEffort | None = None,
    temperature: float | None = None,
    model_name: str = "gpt-5.1",
    model_provider: str = "openai",
) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=model_provider,
        model_name=model_name,
        max_input_tokens=100000,
        temperature=temperature,
        reasoning_effort_default=reasoning_effort_default,
        reasoning_effort_max=reasoning_effort_max,
    )


def _sent_kwargs(llm: LitellmLLM, effort: ReasoningEffort) -> dict[str, Any]:
    """Run one completion and return the kwargs that reached the provider."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return _SENTINEL

    with patch("onyx.llm.litellm_singleton.litellm.completion", side_effect=completion):
        llm._completion(
            prompt=[UserMessage(content="hello")],
            tools=None,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=effort,
        )
    assert len(calls) == 1
    return calls[0]


def _effort_sent(kwargs: dict[str, Any]) -> str:
    """The effort an OpenAI-style request actually asked for."""
    return kwargs["reasoning"]["effort"]


class TestResolveReasoningEffort:
    """The resolution itself, independent of any provider wire format."""

    @pytest.mark.parametrize(
        "requested,default,maximum,expected",
        [
            # Nothing configured: the request passes through untouched.
            (ReasoningEffort.AUTO, None, None, ReasoningEffort.AUTO),
            (ReasoningEffort.HIGH, None, None, ReasoningEffort.HIGH),
            # An admin default only fills in for an unpinned request.
            (ReasoningEffort.AUTO, ReasoningEffort.HIGH, None, ReasoningEffort.HIGH),
            (ReasoningEffort.LOW, ReasoningEffort.HIGH, None, ReasoningEffort.LOW),
            # The cap wins over a session override, which is the whole point.
            (ReasoningEffort.XHIGH, None, ReasoningEffort.LOW, ReasoningEffort.LOW),
            (
                ReasoningEffort.HIGH,
                None,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.MEDIUM,
            ),
            # ...and over the admin's own default, if they disagree.
            (
                ReasoningEffort.AUTO,
                ReasoningEffort.XHIGH,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.MEDIUM,
            ),
            # Under the cap, nothing is touched.
            (ReasoningEffort.LOW, None, ReasoningEffort.HIGH, ReasoningEffort.LOW),
            # OFF is a real cap, not an absence of one.
            (ReasoningEffort.XHIGH, None, ReasoningEffort.OFF, ReasoningEffort.OFF),
            # OFF is also a real request, and survives a permissive cap.
            (ReasoningEffort.OFF, ReasoningEffort.HIGH, None, ReasoningEffort.OFF),
        ],
    )
    def test_resolution_matrix(
        self,
        requested: ReasoningEffort,
        default: ReasoningEffort | None,
        maximum: ReasoningEffort | None,
        expected: ReasoningEffort,
    ) -> None:
        assert resolve_reasoning_effort(requested, default, maximum) == expected

    @pytest.mark.parametrize(
        "maximum,expected",
        [
            (ReasoningEffort.LOW, ReasoningEffort.LOW),
            (ReasoningEffort.OFF, ReasoningEffort.OFF),
            (ReasoningEffort.HIGH, ReasoningEffort.MEDIUM),
            (ReasoningEffort.XHIGH, ReasoningEffort.MEDIUM),
        ],
    )
    def test_auto_is_concretized_before_clamping(
        self, maximum: ReasoningEffort, expected: ReasoningEffort
    ) -> None:
        """AUTO means medium downstream, so a cap below medium must bind it.

        Left as AUTO, a cap of LOW would be violated by the AUTO->medium
        mapping in OPENAI_REASONING_EFFORT.
        """
        assert resolve_reasoning_effort(ReasoningEffort.AUTO, None, maximum) == expected

    def test_auto_stays_auto_without_a_cap(self) -> None:
        """No cap means no reason to force a choice the provider can make."""
        assert (
            resolve_reasoning_effort(ReasoningEffort.AUTO, None, None)
            is ReasoningEffort.AUTO
        )


class TestEffortReachesTheProvider:
    """The resolved effort is what gets sent, not the requested one."""

    def test_cap_binds_a_session_override(self) -> None:
        llm = _make_llm(reasoning_effort_max=ReasoningEffort.LOW)
        assert _effort_sent(_sent_kwargs(llm, ReasoningEffort.XHIGH)) == "low"

    def test_default_applies_when_unpinned(self) -> None:
        llm = _make_llm(reasoning_effort_default=ReasoningEffort.HIGH)
        assert _effort_sent(_sent_kwargs(llm, ReasoningEffort.AUTO)) == "high"

    def test_session_override_beats_the_default(self) -> None:
        llm = _make_llm(reasoning_effort_default=ReasoningEffort.HIGH)
        assert _effort_sent(_sent_kwargs(llm, ReasoningEffort.LOW)) == "low"

    def test_auto_under_a_low_cap_does_not_leak_medium(self) -> None:
        """The trap this design exists to avoid."""
        llm = _make_llm(reasoning_effort_max=ReasoningEffort.LOW)
        assert _effort_sent(_sent_kwargs(llm, ReasoningEffort.AUTO)) == "low"

    def test_unset_policy_changes_nothing(self) -> None:
        llm = _make_llm()
        assert _effort_sent(_sent_kwargs(llm, ReasoningEffort.HIGH)) == "high"

    def test_off_cap_omits_reasoning_entirely(self) -> None:
        """OFF is the one level that drops the parameter rather than lowering it."""
        llm = _make_llm(reasoning_effort_max=ReasoningEffort.OFF)
        kwargs = _sent_kwargs(llm, ReasoningEffort.XHIGH)
        for key in ("reasoning", "thinking", "output_config", "reasoning_effort"):
            assert key not in kwargs


class TestProvidedModelSettings:
    """An omitted field must not clear a stored setting."""

    def test_omitted_settings_are_not_provided(self) -> None:
        """The rolling-deploy case: a client predating these fields saves a
        provider, and the admin's cap must survive it."""
        request = ModelConfigurationUpsertRequest(name="gpt-5.1", is_visible=True)
        assert not request.reasoning_effort_max_provided
        assert not request.reasoning_effort_default_provided
        assert not request.temperature_default_provided

    def test_explicit_null_is_provided(self) -> None:
        """Distinct from omission: this is an admin resetting to auto."""
        request = ModelConfigurationUpsertRequest(
            name="gpt-5.1", is_visible=True, reasoning_effort_max=None
        )
        assert request.reasoning_effort_max_provided
        assert request.reasoning_effort_max is None
        assert not request.reasoning_effort_default_provided

    def test_set_value_is_provided(self) -> None:
        request = ModelConfigurationUpsertRequest(
            name="gpt-5.1",
            is_visible=True,
            reasoning_effort_max=ReasoningEffort.HIGH,
        )
        assert request.reasoning_effort_max_provided
        assert request.reasoning_effort_max is ReasoningEffort.HIGH


class TestUpsertValidation:
    """Rejections happen at the API boundary, via OnyxError."""

    @pytest.mark.parametrize("auto", ["auto", ReasoningEffort.AUTO])
    def test_auto_is_not_storable(self, auto: object) -> None:
        """AUTO has no rank, so storing it would make the clamp raise later.
        The enum form matters: a programmatic caller can reach this directly."""
        with pytest.raises(OnyxError):
            ModelConfigurationUpsertRequest(
                name="gpt-5.1", is_visible=True, reasoning_effort_max=auto
            )

    def test_unknown_effort_rejected(self) -> None:
        with pytest.raises(OnyxError):
            ModelConfigurationUpsertRequest(
                name="gpt-5.1", is_visible=True, reasoning_effort_default="extreme"
            )

    @pytest.mark.parametrize("temperature", [-0.1, 2.1])
    def test_temperature_out_of_range_rejected(self, temperature: float) -> None:
        with pytest.raises(OnyxError):
            ModelConfigurationUpsertRequest(
                name="gpt-5.1", is_visible=True, temperature_default=temperature
            )

    def test_default_above_max_rejected(self) -> None:
        with pytest.raises(OnyxError):
            ModelConfigurationUpsertRequest(
                name="gpt-5.1",
                is_visible=True,
                reasoning_effort_max=ReasoningEffort.LOW,
                reasoning_effort_default=ReasoningEffort.HIGH,
            )

    def test_merged_policy_is_what_gets_validated(self) -> None:
        """A partial update lowering only the cap must still be checked against
        the default already stored, or the row ends up with a default the cap
        silently overrides."""
        stored_default = ReasoningEffort.HIGH
        incoming = ModelConfigurationUpsertRequest(
            name="gpt-5.1", is_visible=True, reasoning_effort_max=ReasoningEffort.LOW
        )
        merged_default = (
            incoming.reasoning_effort_default
            if incoming.reasoning_effort_default_provided
            else stored_default
        )

        with pytest.raises(OnyxError):
            ensure_default_within_max(merged_default, incoming.reasoning_effort_max)

    def test_merged_policy_accepts_a_consistent_partial_update(self) -> None:
        stored_default = ReasoningEffort.LOW
        incoming = ModelConfigurationUpsertRequest(
            name="gpt-5.1", is_visible=True, reasoning_effort_max=ReasoningEffort.HIGH
        )
        merged_default = (
            incoming.reasoning_effort_default
            if incoming.reasoning_effort_default_provided
            else stored_default
        )

        ensure_default_within_max(
            merged_default,
            incoming.reasoning_effort_max,
        )

    def test_default_equal_to_max_allowed(self) -> None:
        request = ModelConfigurationUpsertRequest(
            name="gpt-5.1",
            is_visible=True,
            reasoning_effort_max=ReasoningEffort.LOW,
            reasoning_effort_default=ReasoningEffort.LOW,
        )
        assert request.reasoning_effort_default is ReasoningEffort.LOW


class TestTemperatureDefault:
    """Temperature resolves at construction, where temperature already flows."""

    def test_explicit_temperature_is_kept(self) -> None:
        assert (
            _make_llm(temperature=0.25, model_name="gpt-4o").config.temperature == 0.25
        )

    def test_reasoning_models_still_pin_temperature_to_one(self) -> None:
        """The existing pin sits above admin policy and is unchanged."""
        llm = _make_llm(temperature=0.25)
        assert _sent_kwargs(llm, ReasoningEffort.HIGH)["temperature"] == 1
