"""clear model context limits frozen at the LiteLLM fallback

Revision ID: d4e7a1b93c22
Revises: ad99acb9be41
Create Date: 2026-09-15 19:05:00.000000

`ModelConfigurationView.from_model` serves `stored or get_max_input_tokens(...)`,
and the provider modals round-trip that resolved number back into the next PUT.
For a model LiteLLM did not know, the resolved number is the fallback, so saving
any provider froze every unknown model at it. `get_max_input_tokens_from_llm_provider`
prefers the stored value, so those rows stayed pinned even after a LiteLLM upgrade
learned the real context window.

Clearing them restores read-time resolution. This is safe in both directions: if
LiteLLM still does not know the model the runtime recomputes the identical number,
and if it does the model finally gets its real limit.

Only the exact fallback arithmetic is matched — the default 32000 - 1024 = 30976,
plus the same arithmetic under any deployment that overrode those env vars. That
value is computed, never typed, so it does not collide with a deliberate pin.
Providers that source a context limit from their own API are excluded.
"""

import os

from alembic import op
from sqlalchemy import bindparam, text


# revision identifiers, used by Alembic.
revision = "d4e7a1b93c22"
down_revision = "ad99acb9be41"
branch_labels = None
depends_on = None

# Mirrors onyx.configs.model_configs. Read here rather than imported so the
# migration keeps working if those constants later move or change shape.
_FALLBACK_MAX = int(os.environ.get("GEN_AI_MODEL_FALLBACK_MAX_TOKENS") or 32000)
_RESERVED_OUTPUT = int(os.environ.get("GEN_AI_NUM_RESERVED_OUTPUT_TOKENS") or 1024)

# Mirrors SOURCE_API_CONTEXT_LIMIT_PROVIDERS in onyx.llm.constants.
_SOURCE_API_PROVIDERS = (
    "openrouter",
    "bedrock",
    "ollama_chat",
    "lm_studio",
    "bifrost",
    "openai_compatible",
    "nebius_tokenfactory",
    "portkey",
)


def upgrade() -> None:
    frozen_value = _FALLBACK_MAX - _RESERVED_OUTPUT
    if frozen_value <= 0:
        return

    op.execute(
        text(
            """
            UPDATE model_configuration AS mc
            SET max_input_tokens = NULL
            FROM llm_provider AS lp
            WHERE lp.id = mc.llm_provider_id
              AND mc.max_input_tokens = :frozen_value
              AND lp.provider NOT IN :source_api_providers
            """
        ).bindparams(
            bindparam("frozen_value", value=frozen_value),
            # expanding, or the tuple binds as a single opaque parameter
            bindparam(
                "source_api_providers",
                value=list(_SOURCE_API_PROVIDERS),
                expanding=True,
            ),
        )
    )


def downgrade() -> None:
    # The cleared rows are indistinguishable from models that never had an
    # override, so restoring the fallback would invent overrides that did not
    # exist. Runtime resolution already yields the same number.
    pass
