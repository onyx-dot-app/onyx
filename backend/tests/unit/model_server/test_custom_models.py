from typing import Any
from unittest.mock import Mock
from unittest.mock import patch

import numpy as np
import numpy.typing as npt
import pytest

from model_server.custom_models import run_content_classification_inference
from shared_configs.configs import (
    INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH,
)
from shared_configs.configs import INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX
from shared_configs.configs import INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN
from shared_configs.model_server_models import ContentClassificationPrediction


@pytest.fixture
def mock_content_model() -> Mock:
    model = Mock()

    # Create actual numpy arrays for the mock returns
    predict_output = np.array(
        [1, 0] * 50, dtype=np.int64
    )  # Pre-allocate enough elements
    proba_output = np.array(
        [[0.3, 0.7], [0.7, 0.3]] * 50, dtype=np.float64
    )  # Pre-allocate enough elements

    # Create a mock tensor that has a numpy method and supports indexing
    class MockTensor:
        def __init__(self, value: npt.NDArray[Any]) -> None:
            self.value = value

        def numpy(self) -> npt.NDArray[Any]:
            return self.value

        def __getitem__(self, idx: Any) -> Any:
            result = self.value[idx]
            # Wrap scalar values back in MockTensor
            if isinstance(result, (np.float64, np.int64)):
                return MockTensor(np.array([result]))
            return MockTensor(result)

    # Mock the direct call to return a MockTensor for each input
    def model_call(inputs: list[str]) -> list[MockTensor]:
        batch_size = len(inputs)
        return [MockTensor(predict_output[i : i + 1]) for i in range(batch_size)]

    model.side_effect = model_call

    # Mock predict_proba to return MockTensor-wrapped numpy array
    def predict_proba_call(x: list[str]) -> MockTensor:
        batch_size = len(x)
        return MockTensor(proba_output[:batch_size])

    model.predict_proba.side_effect = predict_proba_call

    return model


@patch("model_server.custom_models.get_local_information_content_model")
def test_run_content_classification_inference(
    mock_get_model: Mock,
    mock_content_model: Mock,
) -> None:
    """
    Test the content classification inference function.
    Verifies that the function correctly processes text inputs and returns appropriate predictions.
    """
    # Setup
    mock_get_model.return_value = mock_content_model

    test_inputs = [
        "Imagine a short text with content",
        "Imagine a short text without content",
        "x "
        * (
            INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH + 1
        ),  # Long input that exceeds maximal length for when the model should be applied
        "",  # Empty input
    ]

    # Execute
    results = run_content_classification_inference(test_inputs)

    # Assert
    assert len(results) == len(test_inputs)
    assert all(isinstance(r, ContentClassificationPrediction) for r in results)

    # Check each prediction has expected attributes and ranges
    for result_num, result in enumerate(results):
        assert hasattr(result, "predicted_label")
        assert hasattr(result, "content_boost_factor")
        assert isinstance(result.predicted_label, int)
        assert isinstance(result.content_boost_factor, float)
        assert (
            INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN
            <= result.content_boost_factor
            <= INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX
        )
        if result_num == 2:
            assert (
                result.content_boost_factor
                == INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MAX
            )
            assert result.predicted_label == 1
        elif result_num == 3:
            assert (
                result.content_boost_factor
                == INDEXING_INFORMATION_CONTENT_CLASSIFICATION_MIN
            )
            assert result.predicted_label == 0

    # Verify model handling of long inputs
    mock_content_model.predict_proba.reset_mock()
    long_input = ["x " * 1000]  # Definitely exceeds MAX_LENGTH
    results = run_content_classification_inference(long_input)
    assert len(results) == 1
    assert (
        mock_content_model.predict_proba.call_count == 0
    )  # Should skip model call for too-long input


@patch("model_server.custom_models.get_local_information_content_model")
def test_batch_processing(
    mock_get_model: Mock,
    mock_content_model: Mock,
) -> None:
    """
    Test that the function correctly handles batch processing of inputs.
    """
    # Setup
    mock_get_model.return_value = mock_content_model

    # Create test input larger than batch size
    test_inputs = [f"Test input {i}" for i in range(40)]  # > BATCH_SIZE (32)

    # Execute
    results = run_content_classification_inference(test_inputs)

    # Assert
    assert len(results) == 40
    # Verify batching occurred (should have called predict_proba twice)
    assert mock_content_model.predict_proba.call_count == 2
