import json
import os
from tempfile import NamedTemporaryFile

import requests

from danswer.db.engine import get_session_context_manager
from danswer.db.models import Tool
from danswer.server.features.persona.models import CreatePersonaRequest
from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from danswer.server.settings.models import Settings
from ee.danswer.server.enterprise_settings.models import EnterpriseSettings
from ee.danswer.server.seeding import SeedConfiguration
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser


def test_seeding(reset: None) -> None:
    # Create admin user
    admin_user: DATestUser = UserManager.create(name="admin_user")

    # Create temporary files for testing
    with (
        NamedTemporaryFile(mode="w", suffix=".json") as tool_file,
        NamedTemporaryFile(mode="w", suffix=".svg") as logo_file,
    ):
        # Write test tool definition
        tool_definition = {
            "openapi": "3.0.0",
            "info": {"title": "Test Tool", "version": "1.0.0"},
            "paths": {},
        }
        json.dump(tool_definition, tool_file)
        tool_file.flush()

        # Write test logo
        logo_file.write("<svg>Test Logo</svg>")
        logo_file.flush()

        # Create seed configuration
        seed_config = SeedConfiguration(
            llms=[
                LLMProviderUpsertRequest(
                    model_name="test-model",
                    model_provider="test-provider",
                    api_key="test-key",
                )
            ],
            personas=[
                CreatePersonaRequest(
                    name="Test Persona",
                    description="A test persona",
                    num_chunks=5,
                )
            ],
            settings=Settings(
                enable_experimental_features=True,
            ),
            enterprise_settings=EnterpriseSettings(
                disable_source_filters=True,
            ),
            seeded_logo_path=logo_file.name,
            custom_tools=[
                {
                    "name": "test-tool",
                    "description": "A test tool",
                    "definition_path": tool_file.name,
                }
            ],
        )

        # Set environment variable with seed configuration
        os.environ["ENV_SEED_CONFIGURATION"] = seed_config.model_dump_json()

        # Verify seeded LLM
        response = requests.get(
            f"{API_SERVER_URL}/manage/llm-providers",
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        llms = response.json()
        assert any(llm["model_name"] == "test-model" for llm in llms)

        # Verify seeded persona
        response = requests.get(
            f"{API_SERVER_URL}/personas",
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        personas = response.json()
        assert any(persona["name"] == "Test Persona" for persona in personas)

        # Verify seeded tool
        with get_session_context_manager() as db_session:
            tools = db_session.query(Tool).all()
            assert any(tool.name == "test-tool" for tool in tools)

        # Verify settings
        response = requests.get(
            f"{API_SERVER_URL}/settings",
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        settings = response.json()
        assert settings["enable_experimental_features"] is True

        # Verify enterprise settings
        response = requests.get(
            f"{API_SERVER_URL}/enterprise-settings",
            headers=admin_user.headers,
        )
        assert response.status_code == 200
        ee_settings = response.json()
        assert ee_settings["disable_source_filters"] is True

        # Clean up
        os.environ.pop("ENV_SEED_CONFIGURATION", None)
