"""Unit tests for tracing setup functions."""

import importlib
import os
from unittest.mock import patch

from onyx.configs import app_configs
from onyx.tracing import setup as tracing_setup


def test_setup_tracing_with_no_creds() -> None:
    """Test that setup_tracing returns empty list when no credentials are configured."""
    # Ensure no tracing credentials are set
    os.environ.pop("BRAINTRUST_API_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)

    # Reload modules to pick up environment changes
    importlib.reload(app_configs)
    importlib.reload(tracing_setup)

    # Reset the initialized flag
    tracing_setup._initialized = False

    # Call the function - should return empty list
    result = tracing_setup.setup_tracing()
    assert result == []


def test_setup_tracing_is_idempotent() -> None:
    """Test that setup_tracing only initializes once."""
    # Ensure no tracing credentials are set
    os.environ.pop("BRAINTRUST_API_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)

    # Reload modules
    importlib.reload(app_configs)
    importlib.reload(tracing_setup)

    # Reset the initialized flag
    tracing_setup._initialized = False

    # First call
    tracing_setup.setup_tracing()

    # Second call should return empty (already initialized)
    result2 = tracing_setup.setup_tracing()
    assert result2 == []

    # Clean up
    tracing_setup._initialized = False


def test_setup_tracing_with_braintrust_creds() -> None:
    """Test that setup_tracing initializes Braintrust when credentials are available."""
    # Set Braintrust credentials
    os.environ["BRAINTRUST_API_KEY"] = "test-api-key"
    os.environ["BRAINTRUST_PROJECT"] = "test-project"
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)

    # Reload modules to pick up new environment variables
    importlib.reload(app_configs)
    importlib.reload(tracing_setup)

    # Reset the initialized flag
    tracing_setup._initialized = False

    # Mock the _setup_braintrust function to avoid actual initialization
    with patch.object(tracing_setup, "_setup_braintrust") as mock_setup:
        result = tracing_setup.setup_tracing()
        mock_setup.assert_called_once()
        assert "braintrust" in result

    # Clean up
    os.environ.pop("BRAINTRUST_API_KEY", None)
    os.environ.pop("BRAINTRUST_PROJECT", None)
    tracing_setup._initialized = False
    importlib.reload(app_configs)


def test_setup_tracing_with_langfuse_creds() -> None:
    """Test that setup_tracing initializes Langfuse when credentials are available."""
    # Set Langfuse credentials
    os.environ["LANGFUSE_SECRET_KEY"] = "test-secret-key"
    os.environ["LANGFUSE_PUBLIC_KEY"] = "test-public-key"
    os.environ.pop("BRAINTRUST_API_KEY", None)

    # Reload modules to pick up new environment variables
    importlib.reload(app_configs)
    importlib.reload(tracing_setup)

    # Reset the initialized flag
    tracing_setup._initialized = False

    # Mock the _setup_langfuse function to avoid actual initialization
    with patch.object(tracing_setup, "_setup_langfuse") as mock_setup:
        result = tracing_setup.setup_tracing()
        mock_setup.assert_called_once()
        assert "langfuse" in result

    # Clean up
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    tracing_setup._initialized = False
    importlib.reload(app_configs)


def test_setup_tracing_with_both_providers() -> None:
    """Test that setup_tracing initializes both providers when both credentials are available."""
    # Set both credentials
    os.environ["BRAINTRUST_API_KEY"] = "test-api-key"
    os.environ["BRAINTRUST_PROJECT"] = "test-project"
    os.environ["LANGFUSE_SECRET_KEY"] = "test-secret-key"
    os.environ["LANGFUSE_PUBLIC_KEY"] = "test-public-key"

    # Reload modules to pick up new environment variables
    importlib.reload(app_configs)
    importlib.reload(tracing_setup)

    # Reset the initialized flag
    tracing_setup._initialized = False

    # Mock both setup functions to avoid actual initialization
    with (
        patch.object(tracing_setup, "_setup_braintrust") as mock_bt,
        patch.object(tracing_setup, "_setup_langfuse") as mock_lf,
    ):
        result = tracing_setup.setup_tracing()
        mock_bt.assert_called_once()
        mock_lf.assert_called_once()
        assert "braintrust" in result
        assert "langfuse" in result

    # Clean up
    os.environ.pop("BRAINTRUST_API_KEY", None)
    os.environ.pop("BRAINTRUST_PROJECT", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    tracing_setup._initialized = False
    importlib.reload(app_configs)
