from onyx.llm.llm_provider_options import curated_models


class TestCuratedModelsFormat:
    """Test the format and constraints of the curated_models data structure."""

    def test_deprecated_models_have_false_flags(self) -> None:
        for provider_name, models in curated_models.items():
            for model in models:
                if model.get("deprecated", False):
                    assert (
                        model.get("recommended_default_model", False) is False
                    ), f"Deprecated model '{model['name']}' in provider '{provider_name}' has recommended_default_model=True"

                    assert (
                        model.get("recommended_fast_default_model", False) is False
                    ), f"Deprecated model '{model['name']}' in provider '{provider_name}' has recommended_fast_default_model=True"

                    assert (
                        model.get("recommended_is_visible", False) is False
                    ), f"Deprecated model '{model['name']}' in provider '{provider_name}' has recommended_is_visible=True"

    def test_model_names_are_globally_unique(self) -> None:
        all_model_names = []

        for _, models in curated_models.items():
            for model in models:
                model_name = model["name"]
                assert (
                    model_name not in all_model_names
                ), f"Model name '{model_name}' appears in multiple providers."
                all_model_names.append(model_name)

    def test_at_most_one_default_model_per_provider(self) -> None:
        for provider_name, models in curated_models.items():
            default_models = []
            fast_default_models = []

            for model in models:
                if model.get("recommended_default_model", False):
                    default_models.append(model["name"])

                if model.get("recommended_fast_default_model", False):
                    fast_default_models.append(model["name"])

            assert (
                len(default_models) <= 1
            ), f"Provider '{provider_name}' has multiple recommended_default_model set to True: {default_models}"

            assert (
                len(fast_default_models) <= 1
            ), f"Provider '{provider_name}' has multiple recommended_fast_default_model set to True: {fast_default_models}"

    def test_required_fields_present(self) -> None:
        """Test that all required fields are present in each model definition."""
        required_fields = [
            "name",
            "friendly_name",
            "recommended_default_model",
            "recommended_fast_default_model",
            "recommended_is_visible",
            "deprecated",
        ]

        for provider_name, models in curated_models.items():
            for model in models:
                for field in required_fields:
                    assert (
                        field in model
                    ), f"Model '{model.get('name', 'UNKNOWN')}' in provider '{provider_name}' is missing required field '{field}'"

    def test_field_types_are_correct(self) -> None:
        """Test that all fields have the correct types."""
        for provider_name, models in curated_models.items():
            for model in models:
                # Test string fields
                assert isinstance(
                    model["name"], str
                ), f"Model name must be a string in provider '{provider_name}'"
                assert isinstance(
                    model["friendly_name"], str
                ), f"Model friendly_name must be a string in provider '{provider_name}'"

                # Test boolean fields
                assert isinstance(
                    model["recommended_default_model"], bool
                ), f"Model recommended_default_model must be a boolean in provider '{provider_name}'"
                assert isinstance(
                    model["recommended_fast_default_model"], bool
                ), f"Model recommended_fast_default_model must be a boolean in provider '{provider_name}'"
                assert isinstance(
                    model["recommended_is_visible"], bool
                ), f"Model recommended_is_visible must be a boolean in provider '{provider_name}'"
                assert isinstance(
                    model["deprecated"], bool
                ), f"Model deprecated must be a boolean in provider '{provider_name}'"
