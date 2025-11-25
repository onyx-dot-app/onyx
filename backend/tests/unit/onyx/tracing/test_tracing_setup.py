"""Unit tests for tracing setup functions."""

import importlib
import os

from onyx.configs import app_configs


def test_setup_langfuse_if_creds_available_with_creds() -> None:
    """Test that setup_langfuse_if_creds_available executes without error when credentials are available."""
    # Set credentials to non-empty values to avoid early return
    os.environ["LANGFUSE_SECRET_KEY"] = "test-secret-key"
    os.environ["LANGFUSE_PUBLIC_KEY"] = "test-public-key"

    # Reload modules to pick up new environment variables
    importlib.reload(app_configs)
    from onyx.tracing import langfuse_tracing

    importlib.reload(langfuse_tracing)

    # Call the function - should not raise an error
    langfuse_tracing.setup_langfuse_if_creds_available()

    # Clean up
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    importlib.reload(app_configs)


def test_setup_braintrust_if_creds_available_with_creds() -> None:
    """Test that setup_braintrust_if_creds_available executes without error when credentials are available."""
    # Set credentials to non-empty values to avoid early return
    os.environ["BRAINTRUST_API_KEY"] = "test-api-key"
    os.environ["BRAINTRUST_PROJECT"] = "test-project"

    # Reload modules to pick up new environment variables
    importlib.reload(app_configs)
    from onyx.tracing import braintrust_tracing

    importlib.reload(braintrust_tracing)

    # Call the function - should not raise an error
    braintrust_tracing.setup_braintrust_if_creds_available()

    # Clean up environment variables
    os.environ.pop("BRAINTRUST_API_KEY", None)
    os.environ.pop("BRAINTRUST_PROJECT", None)
    importlib.reload(app_configs)
