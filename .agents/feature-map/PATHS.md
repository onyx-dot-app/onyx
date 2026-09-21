# Path → Component Lookup

**Start here when verifying a diff.**

```bash
git diff --name-only <base>...HEAD
```

Match each changed path against the table below, longest prefix wins. Then read
those component documents in [components/](components/).

Some paths map to more than one component. Read all of them.

---

## Backend: core loop

| Path | Component(s) |
|---|---|
| `backend/onyx/chat/llm_loop.py`, `llm_step.py`, `process_message.py`, `chat_state.py`, `emitter.py`, `stop_signal_checker.py`, `stream_buffer.py` | core-chat-loop |
| `backend/onyx/chat/prompt_utils.py`, `compression.py`, `token_budget.py`, `incognito*.py` | context-assembly |
| `backend/onyx/prompts/`, `backend/ee/onyx/prompts/` | context-assembly, agents-personas |
| `backend/onyx/chat/citation_processor.py`, `citation_utils.py` | citations |
| `backend/onyx/chat/save_chat.py`, `backend/onyx/db/chat.py`, `db/chat_search.py`, `db/feedback.py` | chat-persistence |
| `backend/onyx/server/query_and_chat/chat_backend.py`, `models.py`, `session_loading.py`, `chat_utils.py` | core-chat-loop, chat-persistence |
| `backend/onyx/server/query_and_chat/streaming_models.py`, `placement.py` | streaming-protocol |
| `backend/onyx/server/query_and_chat/token_limit.py` | rate-and-usage-limits |
| `backend/onyx/chat/search_receipts.py`, `docs/SEARCH_RECEIPTS.md` | search-receipts |

## Backend: tools

| Path | Component(s) |
|---|---|
| `backend/onyx/tools/interface.py`, `models.py`, `tool_constructor.py`, `tool_runner.py`, `built_in_tools.py`, `tool_name.py` | tools-framework |
| `backend/onyx/tools/tool_implementations/search/`, `search_like_tool_utils.py` | internal-search, tools-framework |
| `backend/onyx/tools/tool_implementations/web_search/`, `open_url/` | web-search |
| `backend/onyx/tools/tool_implementations/knowledge_graph/` | knowledge-graph |
| `backend/onyx/tools/tool_implementations/images/` | image-generation |
| `backend/onyx/tools/tool_implementations/bash/`, `python/` | code-execution |
| `backend/onyx/tools/tool_implementations/mcp/`, `custom/` | mcp-and-custom-tools |
| `backend/onyx/tools/tool_implementations/memory/`, `backend/onyx/db/memory.py` | chat-preferences |
| `backend/onyx/tools/tool_implementations/file_reader/` | file-store-and-user-files |
| `backend/onyx/tools/tool_implementations/coding_agent/`, `backend/onyx/coding_agent/` | craft-sessions, tools-framework |
| `backend/onyx/tools/fake_tools/`, `backend/onyx/deep_research/` | tools-framework |

## Backend: search and index

| Path | Component(s) |
|---|---|
| `backend/onyx/context/` | internal-search |
| `backend/onyx/document_index/`, `backend/ee/onyx/document_index/` | document-index |
| `backend/onyx/natural_language_processing/` | document-index, internal-search |
| `backend/onyx/db/search_settings.py`, `db/swap_index.py`, `db/opensearch_migration.py`, `server/manage/opensearch_migration/` | document-index |
| `backend/onyx/server/manage/search_settings.py`, `server/manage/embedding/` | document-index |
| `backend/onyx/server/features/search/`, `server/query_and_chat/query_backend.py` | internal-search |
| `backend/onyx/access/`, `backend/ee/onyx/access/`, `backend/onyx/db/document_access.py`, `db/permissions.py`, `db/scoped_permissions.py` | access-control |
| `backend/onyx/db/document_set.py`, `db/user_group.py`, `server/features/document_set/` | access-control |
| `backend/ee/onyx/external_permissions/`, `backend/onyx/db/permission_sync_attempt.py` | permission-sync |
| `backend/onyx/kg/`, `backend/onyx/db/entities.py`, `db/entity_type.py`, `db/relationships.py`, `db/kg_config.py` | knowledge-graph |
| `backend/onyx/federated_connectors/`, `backend/onyx/db/federated.py`, `server/federated/` | federated-search |
| `backend/onyx/server/features/web_search/`, `server/manage/web_search/`, `db/web_search.py` | web-search |

## Backend: ingestion

| Path | Component(s) |
|---|---|
| `backend/onyx/connectors/` | connectors |
| `backend/onyx/indexing/` | indexing-pipeline |
| `backend/onyx/background/indexing/`, `backend/onyx/db/index_attempt*.py`, `db/indexing_coordination.py` | indexing-pipeline |
| `backend/onyx/db/connector.py`, `db/credentials.py`, `db/connector_credential_pair.py`, `db/credential_capability.py`, `db/connector_alerts.py` | cc-pairs-and-credentials |
| `backend/onyx/db/document.py`, `db/chunk.py`, `db/tag.py` | indexing-pipeline, document-index |
| `backend/onyx/file_processing/`, `backend/onyx/file_store/`, `backend/onyx/db/file_record.py`, `db/file_content.py`, `db/user_file.py` | file-store-and-user-files |
| `backend/onyx/server/documents/` | cc-pairs-and-credentials, indexing-pipeline |

## Backend: configuration surfaces

| Path | Component(s) |
|---|---|
| `backend/onyx/db/persona.py`, `db/persona_sharing.py`, `db/pinned_personas.py`, `server/features/persona/`, `server/features/default_assistant/` | agents-personas |
| `backend/onyx/db/projects.py`, `server/features/projects/` | projects |
| `backend/onyx/skills/`, `backend/onyx/db/skill.py`, `server/features/skill/` | skills |
| `backend/onyx/db/mcp.py`, `server/features/mcp/`, `server/features/tool/`, `db/tools.py` | mcp-and-custom-tools |
| `backend/onyx/db/input_prompt.py`, `db/user_preferences.py`, `server/features/input_prompt/` | chat-preferences |
| `backend/onyx/db/hierarchy.py`, `server/features/hierarchy/` | agents-personas |

## Backend: platform

| Path | Component(s) |
|---|---|
| `backend/onyx/auth/`, `backend/ee/onyx/auth/`, `backend/onyx/server/auth/`, `server/saml*.py`, `server/oidc_multi.py`, `server/sso_discovery.py`, `server/manage/sso/` | auth-and-identity |
| `backend/onyx/db/users.py`, `db/auth.py`, `db/api_key.py`, `db/pat.py`, `db/saml.py`, `db/sso_provider.py`, `server/api_key/`, `server/pat/`, `server/manage/users.py` | auth-and-identity |
| `backend/onyx/oauth/`, `backend/onyx/db/oauth_config.py`, `server/features/oauth_config/`, `db/user_oauth_token.py` | auth-and-identity |
| `backend/onyx/db/tenant_shard.py`, `db/engine/`, `backend/onyx/server/middleware/` | multi-tenancy |
| `backend/onyx/background/celery/`, `background/periodic_poller.py`, `background/task_utils.py`, `backend/ee/onyx/background/`, `backend/onyx/db/tasks.py`, `db/scheduled_task.py`, `db/sync_record.py` | background-jobs |
| `backend/onyx/feature_flags/`, `backend/ee/onyx/feature_flags/`, `backend/onyx/db/gated_app.py`, `backend/onyx/configs/` | editions-and-gating |
| `backend/onyx/tracing/`, `server/manage/tracing/`, `db/tracing.py`, `server/metrics/`, `docs/METRICS.md`, `docs/AUDIT_LOGGING.md` | observability |
| `backend/onyx/db/llm_usage.py`, `db/usage.py`, `db/user_usage.py`, `db/system_usage.py`, `server/features/usage/`, `docs/usage/` | observability |
| `backend/onyx/db/token_limit.py`, `server/token_rate_limits/`, `server/usage_limits.py`, `server/tenant_usage_limits.py` | rate-and-usage-limits |
| `backend/onyx/db/notification.py`, `db/release_notes.py`, `db/admin_banner.py`, `server/features/notifications/`, `features/release_notes/`, `features/admin_banner/` | notifications |
| `backend/onyx/db/models.py` | **any**. Check which tables the diff touches, then map those. |
| `backend/alembic/`, `backend/alembic_tenants/` | the component that owns the table being migrated |
| `backend/onyx/server/settings/`, `server/security/`, `db/security_settings.py` | editions-and-gating, auth-and-identity |
| `backend/onyx/hooks/`, `backend/ee/onyx/hooks/`, `db/hook.py`, `server/features/hooks/` | observability |
| `backend/onyx/server/features/password/` | auth-and-identity |
| `backend/onyx/evals/` | the component being evaluated. A prompt or retrieval change needs an eval, not only a unit test. |
| `backend/onyx/seeding/`, `backend/onyx/db/seeding/` | the component owning the seeded rows. Built-in tools, default agents, and default prompts are seeded here. |
| `backend/onyx/secondary_llm_flows/` | internal-search (query expansion, filters, selection) and chat-persistence (chat naming) |

### Shared infrastructure (not product components)

These are libraries every component uses. A change here has repo-wide blast radius,
so verify the callers rather than a single component.

| Path | What it is |
|---|---|
| `backend/onyx/cache/`, `backend/onyx/redis/`, `backend/onyx/key_value_store/` | Cache and KV abstractions. Used by fences, rate limits, and the stream buffer. |
| `backend/onyx/error_handling/` | `OnyxError` and the error-code taxonomy surfaced to clients. |
| `backend/onyx/utils/`, `backend/onyx/httpx/` | Shared helpers. `utils/variable_functionality.py` holds `fetch_versioned_implementation` and `fetch_ee_implementation_or_noop`, the CE-to-EE dispatch mechanism. |

## Backend: integrations

| Path | Component(s) |
|---|---|
| `backend/onyx/onyxbot/`, `backend/ee/onyx/onyxbot/`, `backend/onyx/db/slack_bot.py`, `db/slack_channel_config.py`, `server/manage/slack_bot.py` | slack-bot |
| `backend/onyx/db/discord_bot.py`, `server/manage/discord_bot/` | discord-bot |
| `backend/onyx/server/onyx_api/` | onyx-api |
| `backend/onyx/mcp_server/`, `mcp_server_main.py` | mcp-server |
| `backend/onyx/server/gateway/` | llm-gateway |
| `backend/onyx/voice/`, `server/manage/voice/`, `db/voice.py` | voice |
| `backend/onyx/image_gen/`, `server/features/image_generation/`, `server/manage/image_generation/`, `db/image_generation.py` | image-generation |
| `backend/onyx/db/code_interpreter.py`, `server/manage/code_interpreter/` | code-execution |
| `backend/onyx/llm/`, `server/manage/llm/`, `db/llm.py` | llm-providers |

## Backend: Craft

| Path | Component(s) |
|---|---|
| `backend/onyx/server/features/build/` | craft-sessions |
| `backend/onyx/sandbox_proxy/` | craft-webapp-proxy |
| `backend/onyx/external_apps/`, `backend/onyx/db/external_app.py` | craft-external-apps |
| `docs/craft/` | the matching `craft-*` component |

## Frontend

| Path | Component(s) |
|---|---|
| `web/src/app/app/` | chat-frontend |
| `web/src/app/app/agents/` | chat-frontend, agents-personas |
| `web/src/app/craft/` | craft-sessions, craft-streaming |
| `web/src/app/admin/connector*/`, `admin/add-connector/`, `admin/indexing/`, `admin/index-settings/`, `admin/document-processing/` | connectors, cc-pairs-and-credentials, indexing-pipeline |
| `web/src/app/admin/documents/`, `admin/groups*/`, `admin/scim/`, `admin/users/`, `admin/service-accounts/` | access-control, auth-and-identity |
| `web/src/app/admin/agents/` | agents-personas |
| `web/src/app/admin/language-models/` | llm-providers |
| `web/src/app/admin/mcp-actions/`, `admin/openapi-actions/` | mcp-and-custom-tools |
| `web/src/app/admin/bots/`, `admin/discord-bot/` | slack-bot, discord-bot |
| `web/src/app/admin/sso-providers/`, `admin/security/`, `admin/oauth-test/` | auth-and-identity |
| `web/src/app/admin/token-rate-limits/`, `admin/billing/` | rate-and-usage-limits |
| `web/src/app/admin/tracing/`, `admin/systeminfo/` | observability |
| `web/src/app/admin/web-search/` | web-search |
| `web/src/app/admin/voice/`, `admin/image-generation/`, `admin/code-interpreter/` | voice, image-generation, code-execution |
| `web/src/app/auth/`, `web/src/app/oauth-config/` | auth-and-identity |
| `web/src/app/api/` | the component owning the proxied endpoint |
| `web/src/refresh-components/`, `web/src/components/` | the calling component. Also see the Opal migration rule in `web/AGENTS.md`. |
| `web/tests/e2e/` | the component the test covers |
| `mobile/` | mobile-app |
| `desktop/`, `widget/`, `extensions/` | desktop-widget-extensions |

## Infrastructure

| Path | Component(s) |
|---|---|
| `deployment/` | the deployed component. For Craft, also `docs/craft/infra/`. |
| `.github/workflows/` | CI. Not a product component; verify by reading the workflow. |
| `cli/`, `tools/`, `scripts/` | developer tooling. Not a product component. |

---

## If a path is not listed

The component is unmapped. Do two things:

1. Read the nearest sibling code and its tests to build the model yourself.
2. Say in the PR that you verified against an unmapped area, and add the path here.

Never treat "not in the map" as "low risk".
