from onyx.llm.utils import model_needs_formatting_reenabled


def test_gpt_5_exact_match() -> None:
    """Test that gpt-5 model name exactly matches."""
    assert model_needs_formatting_reenabled("gpt-5") is True


def test_o3_exact_match() -> None:
    """Test that o3 model name exactly matches."""
    assert model_needs_formatting_reenabled("o3") is True


def test_o1_exact_match() -> None:
    """Test that o1 model name exactly matches."""
    assert model_needs_formatting_reenabled("o1") is True


def test_gpt_5_with_provider_prefix() -> None:
    """Test that gpt-5 with provider prefix matches."""
    assert model_needs_formatting_reenabled("openai/gpt-5") is True


def test_o3_with_provider_prefix() -> None:
    """Test that o3 with provider prefix matches."""
    assert model_needs_formatting_reenabled("openai/o3") is True


def test_o1_with_provider_prefix() -> None:
    """Test that o1 with provider prefix matches."""
    assert model_needs_formatting_reenabled("openai/o1") is True


def test_gpt_5_with_suffix() -> None:
    """Test that gpt-5 with suffix matches."""
    assert model_needs_formatting_reenabled("gpt-5-preview") is True
    assert model_needs_formatting_reenabled("gpt-5-mini") is True
    assert model_needs_formatting_reenabled("gpt-5-turbo") is True


def test_o3_with_suffix() -> None:
    """Test that o3 with suffix matches."""
    assert model_needs_formatting_reenabled("o3-mini") is True
    assert model_needs_formatting_reenabled("o3-preview") is True
    assert model_needs_formatting_reenabled("o3-max") is True


def test_o1_with_suffix() -> None:
    """Test that o1 with suffix matches."""
    assert model_needs_formatting_reenabled("o1-preview") is True
    assert model_needs_formatting_reenabled("o1-mini") is True
    assert model_needs_formatting_reenabled("o1-max") is True


def test_gpt_5_with_provider_and_suffix() -> None:
    """Test that gpt-5 with provider prefix and suffix matches."""
    assert model_needs_formatting_reenabled("openai/gpt-5-preview") is True
    assert model_needs_formatting_reenabled("openai/gpt-5-mini") is True


def test_o3_with_provider_and_suffix() -> None:
    """Test that o3 with provider prefix and suffix matches."""
    assert model_needs_formatting_reenabled("openai/o3-mini") is True
    assert model_needs_formatting_reenabled("openai/o3-preview") is True


def test_o1_with_provider_and_suffix() -> None:
    """Test that o1 with provider prefix and suffix matches."""
    assert model_needs_formatting_reenabled("openai/o1-preview") is True
    assert model_needs_formatting_reenabled("openai/o1-mini") is True


def test_gpt_5_with_space_boundary() -> None:
    """Test that gpt-5 with space boundary matches."""
    assert model_needs_formatting_reenabled("openai gpt-5") is True
    assert model_needs_formatting_reenabled("gpt-5 preview") is True


def test_o3_with_space_boundary() -> None:
    """Test that o3 with space boundary matches."""
    assert model_needs_formatting_reenabled("openai o3") is True
    assert model_needs_formatting_reenabled("o3 mini") is True


def test_o1_with_space_boundary() -> None:
    """Test that o1 with space boundary matches."""
    assert model_needs_formatting_reenabled("openai o1") is True
    assert model_needs_formatting_reenabled("o1 preview") is True


def test_gpt_5_with_slash_boundary() -> None:
    """Test that gpt-5 with slash boundary matches."""
    assert model_needs_formatting_reenabled("provider/gpt-5") is True
    assert model_needs_formatting_reenabled("gpt-5/version") is True


def test_o3_with_slash_boundary() -> None:
    """Test that o3 with slash boundary matches."""
    assert model_needs_formatting_reenabled("provider/o3") is True
    assert model_needs_formatting_reenabled("o3/version") is True


def test_o1_with_slash_boundary() -> None:
    """Test that o1 with slash boundary matches."""
    assert model_needs_formatting_reenabled("provider/o1") is True
    assert model_needs_formatting_reenabled("o1/version") is True


def test_gpt_4_does_not_match() -> None:
    """Test that gpt-4 does not match."""
    assert model_needs_formatting_reenabled("gpt-4") is False
    assert model_needs_formatting_reenabled("gpt-4-turbo") is False
    assert model_needs_formatting_reenabled("gpt-4o") is False
    assert model_needs_formatting_reenabled("openai/gpt-4") is False


def test_gpt_3_5_does_not_match() -> None:
    """Test that gpt-3.5-turbo does not match."""
    assert model_needs_formatting_reenabled("gpt-3.5-turbo") is False
    assert model_needs_formatting_reenabled("openai/gpt-3.5-turbo") is False


def test_o2_does_not_match() -> None:
    """Test that o2 does not match."""
    assert model_needs_formatting_reenabled("o2") is False
    assert model_needs_formatting_reenabled("o2-preview") is False
    assert model_needs_formatting_reenabled("openai/o2") is False


def test_o4_does_not_match() -> None:
    """Test that o4 does not match."""
    assert model_needs_formatting_reenabled("o4") is False
    assert model_needs_formatting_reenabled("o4-mini") is False
    assert model_needs_formatting_reenabled("openai/o4") is False


def test_other_models_do_not_match() -> None:
    """Test that other common models do not match."""
    assert model_needs_formatting_reenabled("claude-3-5-sonnet-20241022") is False
    assert model_needs_formatting_reenabled("gemini-1.5-pro") is False
    assert model_needs_formatting_reenabled("llama3.1") is False
    assert model_needs_formatting_reenabled("mistral-large") is False


def test_case_sensitivity() -> None:
    """Test that model names are case-sensitive."""
    assert model_needs_formatting_reenabled("GPT-5") is False
    assert model_needs_formatting_reenabled("O3") is False
    assert model_needs_formatting_reenabled("O1") is False
    assert model_needs_formatting_reenabled("Gpt-5") is False


def test_models_with_gpt_5_in_middle() -> None:
    """Test that models containing gpt-5 in the middle match."""
    assert model_needs_formatting_reenabled("something-gpt-5-suffix") is True
    assert model_needs_formatting_reenabled("prefix/gpt-5/suffix") is True


def test_models_with_o3_in_middle() -> None:
    """Test that models containing o3 in the middle match."""
    assert model_needs_formatting_reenabled("something-o3-suffix") is True
    assert model_needs_formatting_reenabled("prefix/o3/suffix") is True


def test_models_with_o1_in_middle() -> None:
    """Test that models containing o1 in the middle match."""
    assert model_needs_formatting_reenabled("something-o1-suffix") is True
    assert model_needs_formatting_reenabled("prefix/o1/suffix") is True


def test_models_that_contain_but_not_match() -> None:
    """Test that models containing the strings but not matching word boundaries do not match."""
    # These should not match because they don't have proper word boundaries
    assert (
        model_needs_formatting_reenabled("gpt-50") is False
    )  # gpt-5 is part of gpt-50
    assert model_needs_formatting_reenabled("o30") is False  # o3 is part of o30
    assert model_needs_formatting_reenabled("o10") is False  # o1 is part of o10
    assert model_needs_formatting_reenabled("gpt-51") is False
    assert (
        model_needs_formatting_reenabled("somethingo3") is False
    )  # no boundary before o3
    assert (
        model_needs_formatting_reenabled("o3something") is False
    )  # no boundary after o3


def test_empty_string() -> None:
    """Test that empty string does not match."""
    assert model_needs_formatting_reenabled("") is False


def test_real_litellm_model_names() -> None:
    """Test with real model names that might appear in litellm."""
    # Based on common patterns from models.litellm.ai
    assert model_needs_formatting_reenabled("openai/gpt-5") is True
    assert model_needs_formatting_reenabled("openai/o3-mini") is True
    assert model_needs_formatting_reenabled("openai/o1-preview") is True

    # These should not match
    assert model_needs_formatting_reenabled("openai/gpt-4o") is False
    assert model_needs_formatting_reenabled("openai/gpt-4-turbo") is False
    assert (
        model_needs_formatting_reenabled("anthropic/claude-3-5-sonnet-20241022")
        is False
    )
    assert model_needs_formatting_reenabled("google/gemini-1.5-pro") is False
