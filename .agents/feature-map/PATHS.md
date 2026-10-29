# Path → Component Lookup

The only record of which component owns which code. Rules for this file are in
[README.md](README.md#components).

```bash
git diff --name-only <base>...HEAD
```

Match each changed path against the tables below. The longest matching path
wins. Then read the component documents it names, in
[components/](components/) or [components/connectors/](components/connectors/).
A row that names two components means both own rules in that code: read both.
A path that only a broad row or `## Not mapped` covers is not low risk: read
the nearest code and its tests.

Each path is a repo-root path. A `*` matches any characters, so a glob row
covers new files that match it.

---

## Backend: core loop

| Path | Component(s) |
|---|---|
| `backend/onyx/chat/execution.py`, `backend/onyx/chat/agent.py`, `backend/onyx/chat/errors.py` | core-chat-loop |
| `backend/onyx/chat/renderer.py`, `backend/onyx/chat/presentation.py` | streaming-protocol, core-chat-loop |
| `backend/onyx/chat/persistence.py` | chat-persistence, core-chat-loop |
| `backend/onyx/chat/history_store.py`, `backend/onyx/chat/response.py`, `backend/onyx/db/chat_checkpoint.py` | chat-persistence |
| `backend/onyx/chat/run_store.py`, `backend/onyx/chat/checkpoint.py`, `backend/onyx/chat/restoration.py` | agent-runtime, chat-persistence |
| `backend/onyx/chat/subagents.py` | agent-runtime |
| `backend/onyx/chat/files.py` | context-assembly, projects |
| `backend/onyx/chat/README.md` | core-chat-loop, context-assembly |
| `backend/onyx/chat/models.py` | core-chat-loop, streaming-protocol |
| `backend/onyx/chat/COMPRESSION.md`, `backend/onyx/chat/prompt_utils.py`, `backend/onyx/chat/prompt_formatting.py`, `backend/onyx/llm/token_budget.py` | context-assembly |
| `backend/onyx/chat/chat_utils.py` | context-assembly, chat-persistence |
| `backend/onyx/chat/process_message.py`, `backend/onyx/chat/chat_processing_checker.py`, `backend/onyx/chat/stop_signal_checker.py` | core-chat-loop |
| `backend/onyx/deep_research/` | core-chat-loop, tools-framework |
| `backend/onyx/chat/emitter.py`, `backend/onyx/chat/stream_buffer.py` | core-chat-loop, streaming-protocol |
| `backend/onyx/chat/incognito.py`, `backend/onyx/db/incognito.py` | chat-persistence |
| `backend/onyx/chat/incognito_context.py` | chat-persistence, context-assembly |
| `backend/onyx/prompts/`, `backend/ee/onyx/prompts/` | context-assembly |
| `backend/onyx/chat/citation_processor.py`, `backend/onyx/chat/citation_utils.py` | citations |
| `backend/onyx/db/chat_response.py`, `backend/onyx/db/chat_subagents.py` | chat-persistence |
| `backend/onyx/db/chat.py`, `backend/onyx/db/chat_search.py`, `backend/onyx/db/feedback.py` | chat-persistence |
| `backend/ee/onyx/background/celery/tasks/ttl_management/` | chat-persistence, background-jobs |
| `backend/onyx/server/query_and_chat/chat_backend.py`, `backend/onyx/server/query_and_chat/models.py`, `backend/onyx/server/query_and_chat/session_loading.py`, `backend/onyx/server/query_and_chat/chat_utils.py` | core-chat-loop, chat-persistence |
| `backend/onyx/server/query_and_chat/streaming_models.py`, `backend/onyx/server/query_and_chat/placement.py` | streaming-protocol |
| `backend/onyx/server/query_and_chat/token_limit.py` | rate-and-usage-limits |
| `backend/onyx/secondary_llm_flows/chat_session_naming.py` | chat-persistence |
| `backend/onyx/secondary_llm_flows/memory_update.py` | chat-preferences |

## Backend: tools

| Path | Component(s) |
|---|---|
| `backend/onyx/tools/` | tools-framework |
| `backend/onyx/tools/tool_implementations/search/`, `backend/onyx/tools/tool_implementations/search_like_tool_utils.py` | internal-search |
| `backend/onyx/tools/tool_implementations/web_search/`, `backend/onyx/tools/tool_implementations/open_url/` | web-search |
| `backend/onyx/tools/tool_implementations/images/` | image-generation |
| `backend/onyx/tools/tool_implementations/bash/`, `backend/onyx/tools/tool_implementations/python/` | code-execution |
| `backend/onyx/tools/tool_implementations/mcp/`, `backend/onyx/tools/tool_implementations/custom/` | mcp-and-custom-tools |
| `backend/onyx/tools/tool_implementations/memory/`, `backend/onyx/db/memory.py`, `backend/onyx/context/models.py` | chat-preferences |
| `backend/onyx/tools/tool_implementations/file_reader/` | file-store-and-user-files |
| `backend/onyx/tools/file_snapshot.py` | file-store-and-user-files, chat-persistence |
| `backend/onyx/tools/tool_implementations/coding_agent/`, `backend/onyx/coding_agent/` | tools-framework |

## Backend: search and index

| Path | Component(s) |
|---|---|
| `backend/onyx/context/` | internal-search |
| `backend/onyx/context/search/federated/` | federated-search |
| `backend/onyx/context/search/preprocessing/access_filters.py` | access-control |
| `backend/onyx/secondary_llm_flows/`, `backend/ee/onyx/secondary_llm_flows/`, `backend/ee/onyx/db/search.py` | internal-search |
| `backend/onyx/server/features/search/`, `backend/onyx/server/query_and_chat/query_backend.py`, `backend/ee/onyx/server/query_and_chat/`, `backend/ee/onyx/search/` | internal-search |
| `web/src/ee/sections/SearchUI.tsx`, `web/src/ee/sections/SearchCard.tsx`, `web/src/ee/lib/search/`, `web/src/ee/providers/QueryControllerProvider.tsx`, `web/src/providers/QueryControllerProvider.tsx` | internal-search |
| `backend/onyx/document_index/` | document-index |
| `backend/onyx/server/manage/opensearch_health/`, `web/src/lib/opensearch-health/`, `web/src/sections/banners/OpenSearchResourceWarning.tsx` | document-index |
| `backend/onyx/natural_language_processing/` | document-index, internal-search |
| `backend/onyx/db/search_settings.py`, `backend/onyx/db/swap_index.py`, `backend/onyx/db/port_attempt.py`, `backend/onyx/db/port_orphan_candidate.py` | document-index |
| `backend/onyx/redis/redis_document_set.py`, `backend/onyx/redis/redis_usergroup.py`, `backend/ee/onyx/background/celery/tasks/vespa/` | document-index |
| `backend/onyx/server/manage/search_settings.py`, `backend/onyx/server/manage/embedding/` | document-index |
| `backend/onyx/background/celery/tasks/vespa/`, `backend/onyx/background/celery/tasks/port/`, `backend/onyx/background/celery/tasks/index_reclaim/`, `backend/onyx/background/celery/tasks/cc_pair_ids_backfill/` | document-index |
| `backend/model_server/`, `backend/shared_configs/embedding_models.py` | document-index |
| `backend/onyx/access/`, `backend/ee/onyx/access/`, `backend/onyx/db/document_access.py` | access-control |
| `backend/onyx/db/document_set.py`, `backend/onyx/db/user_group.py`, `backend/onyx/server/features/document_set/`, `backend/ee/onyx/db/document_set.py` | access-control |
| `backend/ee/onyx/server/user_group/`, `backend/ee/onyx/db/user_group.py` | access-control, authorization |
| `backend/ee/onyx/external_permissions/`, `backend/onyx/db/permission_sync_attempt.py` | permission-sync |
| `backend/ee/onyx/external_permissions/post_query_censoring.py` | access-control |
| `backend/ee/onyx/background/celery/tasks/doc_permission_syncing/`, `backend/ee/onyx/background/celery/tasks/external_group_syncing/`, `backend/ee/onyx/db/external_perm.py`, `backend/ee/onyx/db/document.py` | permission-sync |
| `backend/onyx/background/celery/tasks/shared/lease_heartbeat.py` | permission-sync |
| `backend/onyx/federated_connectors/`, `backend/onyx/db/federated.py`, `backend/onyx/server/federated/` | federated-search |
| `backend/onyx/server/features/web_search/`, `backend/onyx/server/manage/web_search/`, `backend/onyx/db/web_search.py` | web-search |

## Backend: ingestion

| Path | Component(s) |
|---|---|
| `backend/onyx/connectors/` | connectors |
| `backend/onyx/connectors/capability_checks/`, `backend/ee/onyx/connectors/`, `backend/onyx/background/celery/tasks/capability_checks/`, `backend/onyx/server/documents/capability_check_runs.py`, `backend/onyx/server/documents/credential_capabilities.py` | connector-capability-checks |
| `backend/onyx/connectors/*/capability_checks.py`, `backend/ee/onyx/external_permissions/*/capability_checks.py` | connector-capability-checks |
| `backend/onyx/connectors/pairing_access.py` | access-control, cc-pairs-and-creds |
| `backend/onyx/server/documents/connector_edit.py`, `backend/onyx/server/documents/connector_edit_models.py`, `backend/onyx/db/connector_edit_requests.py`, `backend/onyx/db/backfill_models.py` | connectors |
| `backend/onyx/connectors/confluence/` | confluence |
| `backend/onyx/connectors/slack/` | slack |
| `backend/onyx/connectors/google_drive/`, `backend/onyx/connectors/google_utils/` | google-drive |
| `backend/onyx/connectors/microsoft_utils/`, `backend/onyx/connectors/sharepoint/`, `backend/onyx/connectors/onedrive/` | microsoft-graph |
| `backend/onyx/connectors/outlook/` | outlook |
| `backend/onyx/connectors/teams/` | teams |
| `backend/onyx/indexing/` | indexing-pipeline |
| `backend/onyx/indexing/adapters/user_file_indexing_adapter.py` | file-store-and-user-files, indexing-pipeline |
| `backend/onyx/background/indexing/`, `backend/onyx/db/index_attempt*.py`, `backend/onyx/db/indexing_coordination.py` | indexing-pipeline |
| `backend/onyx/background/celery/tasks/docfetching/`, `backend/onyx/background/celery/tasks/docprocessing/`, `backend/onyx/background/celery/tasks/tabular_rechunk/` | indexing-pipeline |
| `backend/onyx/file_store/document_batch_storage.py`, `backend/onyx/db/targeted_reindex.py`, `backend/onyx/redis/redis_docprocessing.py` | indexing-pipeline |
| `backend/onyx/db/connector.py`, `backend/onyx/db/credentials.py`, `backend/onyx/db/connector_credential_pair.py`, `backend/onyx/db/credential_capability.py`, `backend/ee/onyx/db/connector.py`, `backend/ee/onyx/db/credentials.py` | cc-pairs-and-creds |
| `backend/onyx/db/cc_pair_runs.py`, `backend/onyx/db/cc_pair_runs_models.py`, `backend/onyx/db/cc_pair_run_resolution.py`, `backend/onyx/db/deletion_attempt.py` | cc-pairs-and-creds |
| `backend/onyx/utils/encryption.py`, `backend/onyx/utils/sensitive.py`, `backend/ee/onyx/utils/encryption.py`, `backend/onyx/db/rotate_encryption_key.py` | cc-pairs-and-creds |
| `backend/onyx/server/manage/administrative.py` | cc-pairs-and-creds, indexing-pipeline |
| `backend/ee/onyx/server/oauth/` | cc-pairs-and-creds |
| `backend/ee/onyx/server/documents/`, `backend/ee/onyx/db/connector_credential_pair.py` | cc-pairs-and-creds, permission-sync |
| `backend/ee/onyx/db/cc_pair_data_access.py`, `backend/ee/onyx/db/connector_manage_access.py` | cc-pairs-and-creds, access-control |
| `backend/onyx/db/document.py`, `backend/onyx/db/chunk.py`, `backend/onyx/db/tag.py` | indexing-pipeline, document-index |
| `backend/onyx/file_processing/`, `backend/onyx/file_store/`, `backend/onyx/db/file_record.py`, `backend/onyx/db/file_content.py`, `backend/onyx/db/user_file.py` | file-store-and-user-files |
| `backend/onyx/background/celery/tasks/user_file_processing/` | file-store-and-user-files |
| `backend/onyx/server/documents/` | cc-pairs-and-creds, indexing-pipeline |

## Backend: configuration surfaces

| Path | Component(s) |
|---|---|
| `backend/onyx/db/persona.py`, `backend/onyx/db/persona_sharing.py`, `backend/onyx/db/pinned_personas.py`, `backend/onyx/server/features/persona/`, `backend/onyx/server/features/default_assistant/`, `backend/ee/onyx/db/persona.py` | agents-personas |
| `backend/onyx/db/projects.py`, `backend/onyx/server/features/projects/` | projects |
| `backend/onyx/skills/`, `backend/onyx/db/skill.py`, `backend/onyx/server/features/skill/` | skills |
| `backend/onyx/db/mcp.py`, `backend/onyx/server/features/mcp/`, `backend/onyx/server/features/tool/`, `backend/onyx/db/tools.py`, `backend/ee/onyx/db/mcp.py` | mcp-and-custom-tools |
| `backend/onyx/server/features/tool/tool_visibility.py` | mcp-and-custom-tools, plugins |
| `terraform-provider-onyx/internal/client/custom_tool.go`, `terraform-provider-onyx/internal/client/custom_tool_test.go`, `terraform-provider-onyx/internal/provider/custom_tool_resource.go`, `terraform-provider-onyx/internal/provider/custom_tool_resource_test.go`, `terraform-provider-onyx/internal/provider/custom_tool_availability_test.go`, `terraform-provider-onyx/docs/resources/custom_tool.md` | mcp-and-custom-tools |
| `backend/onyx/db/input_prompt.py`, `backend/onyx/db/user_preferences.py`, `backend/onyx/server/features/input_prompt/` | chat-preferences |
| `backend/onyx/server/settings/api.py`, `backend/onyx/server/settings/models.py`, `backend/onyx/server/settings/store.py` | chat-preferences |
| `backend/onyx/db/hierarchy.py`, `backend/onyx/server/features/hierarchy/`, `backend/ee/onyx/db/hierarchy.py` | agents-personas, access-control |

## Backend: platform

| Path | Component(s) |
|---|---|
| `backend/onyx/auth/`, `backend/ee/onyx/auth/`, `backend/onyx/server/auth/`, `backend/onyx/server/saml*.py`, `backend/onyx/server/oidc_multi.py`, `backend/onyx/server/sso_discovery.py`, `backend/onyx/server/manage/sso/`, `backend/onyx/server/manage/oauth_test.py` | auth-and-identity |
| `backend/onyx/server/auth/mobile.py`, `backend/onyx/auth/mobile_sso/` | mobile-app, auth-and-identity |
| `backend/ee/onyx/server/scim/`, `backend/ee/onyx/db/saml.py`, `backend/ee/onyx/db/scim.py`, `backend/ee/onyx/db/tenant_sso_domain.py`, `backend/ee/onyx/background/celery/tasks/sso_domain_revalidation/` | auth-and-identity |
| `backend/onyx/db/users.py`, `backend/onyx/db/auth.py`, `backend/onyx/db/api_key.py`, `backend/onyx/db/pat.py`, `backend/onyx/db/saml.py`, `backend/onyx/db/sso_provider.py`, `backend/onyx/server/api_key/`, `backend/onyx/server/pat/`, `backend/onyx/server/manage/users.py` | auth-and-identity |
| `backend/onyx/oauth/`, `backend/onyx/db/oauth_config.py`, `backend/onyx/server/features/oauth_config/`, `backend/onyx/server/features/user_oauth_token/` | auth-and-identity |
| `backend/onyx/oauth_provider/`, `backend/onyx/db/oauth_provider.py`, `backend/onyx/server/oauth_provider/` | auth-and-identity |
| `backend/onyx/server/security/`, `backend/onyx/db/security_settings.py`, `backend/onyx/server/features/password/` | auth-and-identity |
| `backend/onyx/utils/url.py`, `backend/onyx/utils/playwright_fetch.py` | auth-and-identity |
| `backend/onyx/auth/permissions.py`, `backend/onyx/auth/scoped_permissions.py`, `backend/onyx/auth/permission_projection.py` | authorization |
| `backend/onyx/db/permissions.py`, `backend/onyx/db/scoped_permissions.py` | authorization |
| `backend/onyx/server/auth_check.py`, `backend/ee/onyx/server/auth_check.py` | authorization |
| `backend/onyx/server/pat/models.py` | authorization |
| `backend/onyx/db/tenant_shard.py`, `backend/onyx/db/engine/` | multi-tenancy |
| `backend/ee/onyx/server/tenants/`, `backend/ee/onyx/db/user_tenant_mapping.py`, `backend/ee/onyx/db/tenant_snapshot.py`, `backend/ee/onyx/background/celery/tasks/tenant_provisioning/` | multi-tenancy |
| `backend/shared_configs/contextvars.py`, `backend/alembic/run_multitenant_migrations.py`, `backend/alembic/env.py`, `backend/alembic_tenants/`, `backend/onyx/redis/tenant_redis_client.py`, `backend/onyx/redis/redis_pool.py` | multi-tenancy |
| `backend/onyx/utils/threadpool_concurrency.py`, `backend/onyx/utils/middleware.py` | multi-tenancy |
| `backend/ee/onyx/server/middleware/tenant_tracking.py` | multi-tenancy, billing |
| `backend/onyx/server/middleware/rate_limiting.py` | rate-and-usage-limits |
| `backend/onyx/server/middleware/latency_logging.py` | observability |
| `backend/onyx/background/celery/`, `backend/onyx/background/periodic_poller.py`, `backend/onyx/background/task_utils.py`, `backend/onyx/background/error_logging.py`, `backend/onyx/background/README.md`, `backend/ee/onyx/background/`, `backend/onyx/db/tasks.py`, `backend/onyx/db/sync_record.py`, `backend/onyx/db/background_error.py` | background-jobs |
| `backend/onyx/redis/redis_connector_prune.py`, `backend/onyx/redis/redis_connector_delete.py`, `backend/onyx/redis/redis_connector_stop.py` | background-jobs |
| `backend/onyx/feature_flags/`, `backend/ee/onyx/feature_flags/`, `backend/onyx/utils/variable_functionality.py`, `backend/scripts/make_foss_repo.sh` | editions-and-gating |
| `backend/ee/onyx/server/middleware/tier_gate.py`, `backend/ee/onyx/configs/license_enforcement_config.py`, `backend/onyx/server/settings/tier_order.py`, `web/src/lib/tiers/` | editions-and-gating |
| `backend/onyx/configs/llm_configs.py`, `backend/onyx/configs/model_configs.py` | llm-providers |
| `backend/onyx/configs/onyxbot_configs.py` | slack-bot |
| `backend/onyx/tracing/`, `backend/onyx/server/manage/tracing/`, `backend/onyx/db/tracing.py`, `backend/onyx/server/metrics/` | observability |
| `backend/onyx/server/metrics/mcp_server.py` | mcp-server, observability |
| `backend/onyx/server/metrics/mcp_client.py` | mcp-and-custom-tools, observability |
| `backend/onyx/db/llm_usage.py`, `backend/onyx/db/usage.py`, `backend/onyx/db/user_usage.py`, `backend/onyx/db/system_usage.py`, `backend/onyx/server/features/usage/` | observability |
| `backend/ee/onyx/server/analytics/`, `backend/ee/onyx/db/analytics.py`, `backend/ee/onyx/db/usage_export.py` | observability |
| `backend/onyx/utils/audit.py`, `backend/ee/onyx/server/query_history/`, `backend/ee/onyx/db/query_history.py`, `backend/ee/onyx/server/reporting/`, `backend/ee/onyx/background/celery/tasks/usage_reporting/` | observability |
| `backend/onyx/db/cost_override.py`, `backend/onyx/llm/cost_overrides.py` | observability, llm-providers |
| `backend/onyx/utils/telemetry.py`, `backend/onyx/utils/timing.py`, `backend/ee/onyx/utils/telemetry.py`, `backend/ee/onyx/utils/posthog_client.py` | observability |
| `backend/onyx/utils/fleet_telemetry.py`, `backend/onyx/utils/fleet_query_telemetry.py`, `backend/onyx/utils/fleet_telemetry_collector.py`, `backend/onyx/utils/fleet_telemetry_resources.py`, `backend/onyx/db/fleet_enrollment.py`, `backend/onyx/db/fleet_telemetry.py`, `deployment/fleet-telemetry.md` | fleet-telemetry |
| `backend/ee/onyx/server/log_export/`, `backend/ee/onyx/background/celery/tasks/log_export/`, `deployment/helm/charts/onyx/templates/log-export-rbac.yaml`, `deployment/helm/charts/onyx/dashboards/` | observability |
| `backend/onyx/hooks/`, `backend/ee/onyx/hooks/`, `backend/onyx/db/hook.py`, `backend/onyx/server/features/hooks/`, `backend/ee/onyx/server/features/hooks/`, `backend/onyx/utils/external_endpoint.py` | hooks |
| `backend/onyx/db/token_limit.py`, `backend/onyx/server/token_rate_limits/`, `backend/onyx/server/usage_limits.py`, `backend/onyx/server/tenant_usage_limits.py`, `backend/onyx/server/manage/invite_rate_limit.py`, `backend/onyx/db/tenant_invite_counter.py` | rate-and-usage-limits |
| `backend/onyx/server/api_key_usage.py`, `backend/ee/onyx/server/usage_limits.py`, `backend/ee/onyx/server/tenant_usage_limits.py`, `backend/ee/onyx/server/token_rate_limits/`, `backend/ee/onyx/db/token_limit.py`, `backend/ee/onyx/server/query_and_chat/token_limit.py` | rate-and-usage-limits |
| `backend/ee/onyx/server/billing/`, `backend/ee/onyx/server/license/`, `backend/ee/onyx/server/metrics/`, `backend/scripts/seed_dev_license.py` | billing |
| `backend/ee/onyx/server/middleware/license_enforcement.py`, `backend/ee/onyx/db/license.py`, `backend/ee/onyx/utils/license.py`, `backend/ee/onyx/utils/license_expiry.py`, `backend/ee/onyx/background/celery/tasks/license_reclaim/` | billing |
| `backend/ee/onyx/server/tenants/proxy.py`, `backend/ee/onyx/server/tenants/product_gating.py`, `backend/ee/onyx/configs/multi_tenant_gating_config.py` | billing |
| `backend/ee/onyx/server/tenants/billing.py`, `backend/ee/onyx/server/tenants/billing_api.py`, `backend/ee/onyx/server/tenants/tier_management.py` | billing |
| `backend/ee/onyx/utils/tier.py`, `backend/ee/onyx/server/settings/` | billing, editions-and-gating |
| `backend/ee/onyx/db/community_downgrade.py` | billing |
| `backend/ee/onyx/server/enterprise_settings/` | whitelabelling-and-theme |
| `backend/ee/onyx/db/standard_answer.py`, `backend/ee/onyx/server/manage/standard_answer.py`, `backend/ee/onyx/onyxbot/slack/handlers/handle_standard_answers.py`, `backend/ee/onyx/server/query_and_chat/query_backend.py` | standard-answers |
| `backend/onyx/db/notification.py`, `backend/onyx/db/release_notes.py`, `backend/onyx/db/admin_banner.py`, `backend/onyx/server/features/notifications/`, `backend/onyx/server/features/release_notes/`, `backend/onyx/server/features/admin_banner/`, `backend/onyx/db/connector_alerts.py` | notifications |
| `backend/ee/onyx/utils/license_notifications.py` | notifications |
| `backend/ee/onyx/background/celery/tasks/license_notifications/` | notifications, billing |

## Backend: integrations

| Path | Component(s) |
|---|---|
| `backend/onyx/onyxbot/`, `backend/ee/onyx/onyxbot/`, `backend/onyx/db/slack_bot.py`, `backend/onyx/db/slack_channel_config.py`, `backend/onyx/server/manage/slack_bot.py`, `backend/onyx/server/manage/validate_tokens.py` | slack-bot |
| `backend/onyx/onyxbot/discord/`, `backend/onyx/db/discord_bot.py`, `backend/onyx/server/manage/discord_bot/` | discord-bot |
| `backend/onyx/server/onyx_api/` | onyx-api |
| `backend/scripts/onyx_openapi_schema.py`, `backend/scripts/transform_openapi_for_docs.py`, `backend/scripts/api_inference_sample.py`, `documentation/scripts/generate.sh` | onyx-api |
| `backend/onyx/mcp_server/`, `backend/onyx/mcp_server_main.py`, `backend/onyx/oauth_provider/auth.py` | mcp-server |
| `deployment/tests/test_oauth_proxy.py`, `deployment/tests/test_next_oauth_discovery.py`, `backend/tests/unit/onyx/oauth_provider/test_native_client_cleanup.py`, `backend/tests/unit/onyx/oauth_provider/test_codex_response_reader.py` | mcp-server |
| `.github/workflows/mcp-compatibility.yml`, `.github/scripts/check-mcp-compatibility.py`, `deployment/tests/test_mcp_compatibility_probe.py` | mcp-server |
| `deployment/docker_compose/docker-compose.mcp-ci.yml`, `deployment/docker_compose/mcp-ci-web.conf`, `deployment/tests/test_mcp_compose.py`, `deployment/tests/test_mcp_canary_workflow.py` | mcp-server |
| `deployment/data/nginx/mcp.conf.inc.template`, `deployment/data/nginx/mcp_upstream.conf.inc.template` | mcp-server |
| `deployment/helm/charts/onyx/templates/mcp-server-deployment.yaml`, `deployment/helm/charts/onyx/templates/mcp-server-service.yaml`, `deployment/helm/charts/onyx/templates/mcp-server-servicemonitor.yaml`, `deployment/helm/charts/onyx/templates/ingress-mcp.yaml`, `deployment/helm/charts/onyx/templates/ingress-mcp-oauth-callback.yaml` | mcp-server |
| `backend/onyx/server/gateway/`, `backend/ee/onyx/server/gateway/`, `backend/onyx/server/features/build/craft_gateway.py` | llm-gateway |
| `backend/onyx/voice/`, `backend/onyx/server/manage/voice/`, `backend/onyx/db/voice.py` | voice |
| `backend/onyx/image_gen/`, `backend/onyx/server/features/image_generation/`, `backend/onyx/server/manage/image_generation/`, `backend/onyx/db/image_generation.py` | image-generation |
| `backend/onyx/db/code_interpreter.py`, `backend/onyx/server/manage/code_interpreter/` | code-execution |
| `backend/onyx/agents/` | agent-runtime |
| `backend/onyx/agents/compaction.py` | agent-runtime, context-assembly |
| `backend/onyx/agents/tool_execution.py`, `backend/onyx/agents/tools.py` | agent-runtime, tools-framework |
| `backend/onyx/llm/`, `backend/onyx/server/manage/llm/`, `backend/onyx/db/llm.py` | llm-providers |
| `cli/internal/parser/`, `cli/internal/models/events.go` | streaming-protocol |

## Backend: Craft

| Path | Component(s) |
|---|---|
| `backend/onyx/server/features/build/` | craft-sessions |
| `backend/onyx/server/features/build/api.py`, `backend/onyx/server/features/build/utils.py` | craft-admin, craft-sessions |
| `backend/onyx/server/features/build/packets.py`, `backend/onyx/server/features/build/session/streaming.py`, `backend/onyx/server/features/build/interactive_turns/api.py` | craft-streaming, craft-sessions |
| `backend/onyx/server/features/build/approvals/` | craft-external-apps |
| `backend/onyx/server/features/build/external_apps/`, `backend/onyx/server/features/build/action_policies.py` | craft-external-apps, craft-admin |
| `backend/onyx/server/features/build/connect_app.py`, `backend/onyx/server/features/build/sandbox/image/opencode-plugins/connect-app.ts` | craft-external-apps |
| `backend/onyx/server/features/build/db/action_approval.py` | craft-external-apps |
| `backend/onyx/db/action_policy.py`, `web/src/sections/actions/PolicyEditor.tsx` | craft-external-apps |
| `backend/onyx/server/features/build/scheduled_tasks/`, `backend/onyx/db/scheduled_task.py`, `backend/onyx/background/celery/tasks/scheduled_tasks/`, `backend/onyx/background/celery/apps/scheduled_tasks.py` | craft-scheduled-tasks |
| `backend/onyx/server/features/build/sandbox/` | craft-sandboxes |
| `backend/onyx/server/features/build/sandbox/opencode/`, `backend/onyx/server/features/build/sandbox/event_schema.py`, `backend/onyx/server/features/build/sandbox/sse.py` | craft-streaming |
| `backend/onyx/server/features/build/sandbox/serve_transport.py` | craft-streaming, craft-sandboxes |
| `backend/onyx/server/features/build/sandbox/image/sandbox_daemon/models.py` | craft-sandboxes, craft-sessions |
| `backend/onyx/server/features/build/session/sandbox_lifecycle.py`, `backend/onyx/server/features/build/db/sandbox.py`, `backend/onyx/server/features/build/session/resource_cleanup.py`, `backend/onyx/background/celery/tasks/build/tasks.py` | craft-sandboxes |
| `backend/onyx/server/features/build/static_preview.py`, `backend/onyx/server/features/build/webapp_proxy.py`, `backend/onyx/server/features/build/sandbox/nextjs_dev.py`, `backend/onyx/server/features/build/templates/` | craft-webapp-proxy |
| `backend/onyx/server/features/build/sandbox/image/opencode-plugins/webapp.ts`, `backend/onyx/server/features/build/sandbox/image/templates/outputs/web/` | craft-webapp-proxy |
| `backend/onyx/server/features/build/session/output_cards.py` | craft-sessions, craft-scheduled-tasks |
| `backend/onyx/sandbox_proxy/`, `deployment/helm/charts/onyx/templates/sandbox-proxy/` | craft-external-apps |
| `backend/onyx/external_apps/`, `backend/onyx/db/external_app.py` | craft-external-apps, craft-admin |
| `deployment/helm/charts/onyx/templates/sandbox-podtemplate.yaml`, `deployment/helm/charts/onyx/templates/sandbox-rbac.yaml`, `deployment/helm/charts/onyx/templates/network-policy-sandbox-egress.yaml`, `deployment/helm/charts/onyx/templates/network-policy-sandbox-push.yaml`, `deployment/helm/charts/onyx/templates/sandbox-image-prepuller.yaml` | craft-sandboxes |
| `deployment/helm/dev/`, `.zed/run-all-k8s.sh`, `.zed/process-compose.k8s.yaml` | craft-sandboxes |

## Frontend: chat and user surfaces

| Path | Component(s) |
|---|---|
| `web/src/app/app/`, `web/src/views/AppPage.tsx` | chat-frontend |
| `web/src/app/api/[...path]/route.ts` | chat-frontend |
| `web/src/hooks/useChatController.ts`, `web/src/hooks/useChatSessionController.ts`, `web/src/hooks/useFeedbackController.ts`, `web/src/hooks/useMultiModelChat.ts`, `web/src/hooks/useChatSessions.ts`, `web/src/hooks/useQueuedMessageNavigation.ts`, `web/src/hooks/useDeepResearchToggle.ts` | chat-frontend |
| `web/src/sections/chat/`, `web/src/sections/sidebar/`, `web/src/sections/document-sidebar/`, `web/src/sections/input/`, `web/src/lib/chat/`, `web/src/lib/multiModel/`, `web/src/lib/sidebar/`, `web/src/lib/searchFilters/`, `web/src/sections/modals/ShareChatSessionModal.tsx` | chat-frontend |
| `web/src/providers/IncognitoProvider.tsx` | chat-frontend, chat-persistence |
| `web/src/sections/model-selector/` | chat-frontend, llm-providers |
| `web/src/lib/search/streamingUtils.ts`, `web/src/app/app/services/streamingModels.ts` | streaming-protocol |
| `web/src/app/app/components/files/`, `web/src/sections/modals/UserFilesModal.tsx`, `web/src/sections/cards/FileCard.tsx` | file-store-and-user-files |
| `web/src/sections/modals/PreviewModal/` | chat-frontend |
| `web/src/app/app/agents/` | chat-frontend, agents-personas |
| `web/src/app/app/plugins/` | plugins, chat-frontend |
| `web/src/app/app/settings/llm-gateway/` | llm-gateway |
| `web/src/app/app/settings/usage/` | observability |
| `web/src/views/SettingsPage.tsx` | chat-preferences |
| `web/src/hooks/useUserPersonalization.ts`, `web/src/hooks/usePromptShortcuts.ts`, `web/src/hooks/useMemoryManager.ts`, `web/src/sections/settings/Memories.tsx`, `web/src/refresh-components/modals/MemoriesModal.tsx` | chat-preferences |
| `web/src/lib/settings/`, `web/src/providers/SettingsProvider.tsx` | chat-preferences, whitelabelling-and-theme |
| `web/src/providers/VoiceModeProvider.tsx`, `web/src/hooks/useVoiceRecorder.ts`, `web/src/hooks/useVoicePlayback.ts`, `web/src/hooks/useVoiceStatus.ts`, `web/src/lib/streamingTTS.ts`, `web/src/sections/input/MicrophoneButton.tsx`, `web/src/components/voice/` | voice |
| `web/src/lib/projects/` | projects |
| `web/src/lib/tools/` | plugins |
| `web/src/lib/tools/components/ToolsPopover.tsx` | plugins, chat-frontend |
| `web/src/lib/onboarding/` | chat-frontend |
| `web/src/views/AgentEditorPage.tsx`, `web/src/views/AgentsNavigationPage.tsx`, `web/src/sections/agents/` | agents-personas |
| `web/src/lib/notifications/`, `web/src/lib/banner/`, `web/src/sections/banners/BannerQueue.tsx`, `web/src/sections/sidebar/NotificationsPopover.tsx`, `web/src/hooks/useNotifications.ts` | notifications |
| `web/src/app/nrf/`, `web/src/app/components/nrf/`, `web/src/lib/extension/` | desktop-widget-extensions, chat-frontend |
| `mobile/` | mobile-app |
| `mobile/src/chat/streamingModels.ts`, `mobile/src/chat/ndjson.ts` | mobile-app, streaming-protocol |
| `desktop/`, `widget/`, `extensions/` | desktop-widget-extensions |

## Frontend: Craft

| Path | Component(s) |
|---|---|
| `web/src/app/craft/`, `web/src/providers/CraftStreamingProvider.tsx` | craft-frontend |
| `web/src/app/craft/utils/parsePacket.ts`, `web/src/app/craft/utils/subagentRouting.ts`, `web/src/app/craft/utils/packetTypes.ts`, `web/src/app/craft/types/streamingTypes.ts` | craft-streaming |
| `web/src/app/craft/components/output-panel/`, `web/src/app/craft/components/OutputPanel.tsx`, `web/src/lib/build/hooks.ts`, `web/src/lib/build/types.ts` | craft-frontend |
| `web/src/app/craft/services/workspaceDirectorySnapshots.ts`, `web/src/app/craft/services/outputInventorySnapshots.ts`, `web/src/app/craft/services/outputThumbnailCache.ts`, `web/src/app/craft/services/workspaceFiles.ts`, `web/src/app/craft/services/outputPanelPreferences.ts`, `web/src/app/craft/services/filePreview.ts` | craft-frontend |
| `web/tools/prepare-pdf-assets.cjs`, `web/src/lib/readSpreadsheetPreview.ts`, `web/src/lib/spreadsheetPreview.worker.ts`, `web/src/lib/spreadsheetPreview.ts` | craft-frontend |
| `web/src/lib/docx/`, `web/src/lib/csv.ts` | chat-frontend, craft-frontend |
| `web/src/app/craft/v1/tasks/` | craft-scheduled-tasks |
| `web/src/app/craft/v1/apps/`, `web/src/lib/externalApps/`, `web/src/hooks/useUserExternalApps.ts` | craft-external-apps |
| `web/src/app/craft/v1/plugins/` | craft-external-apps, plugins |
| `web/src/app/craft/v1/skills/`, `web/src/app/craft/components/SkillsStaleNotice.tsx` | skills |
| `web/src/views/SkillsPage.tsx`, `web/src/views/SkillEditorPage.tsx`, `web/src/sections/skills/`, `web/src/sections/modals/skills/`, `web/src/sections/cards/SkillCard.tsx`, `web/src/hooks/useUserSkills.ts`, `web/src/lib/skills/`, `web/src/sections/modals/SkillPreviewModal.tsx` | skills |

## Frontend: admin and platform

| Path | Component(s) |
|---|---|
| `web/src/app/admin/plugins/external-app/` | craft-admin, craft-external-apps |
| `web/src/app/admin/craft/`, `web/src/views/admin/CraftPage/`, `web/src/views/admin/CraftPreferencesPage/` | craft-admin |
| `web/src/app/admin/connector/`, `web/src/app/admin/connectors/`, `web/src/app/admin/indexing-status/` | cc-pairs-and-creds |
| `web/src/app/admin/document-processing/` | file-store-and-user-files |
| `web/src/lib/connectors/`, `web/src/views/admin/connectors/`, `web/src/lib/connector.ts`, `web/src/lib/fileConnector.ts`, `web/src/lib/googleDrive.ts`, `web/src/lib/gmail.ts` | connectors, cc-pairs-and-creds |
| `web/src/lib/connectors/edit/`, `web/src/views/admin/connectors/EditConnectorPage/` | connectors |
| `web/src/lib/connectors/checks/`, `web/src/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard.tsx`, `web/src/views/admin/connectors/ConnectorDetailPage/PairChecksCard.tsx`, `web/src/views/admin/connectors/ConnectorDetailPage/CheckRunPopover.tsx` | connector-capability-checks |
| `web/src/lib/credentials/`, `web/src/lib/ccPair.ts`, `web/src/hooks/useCCPairs.ts`, `web/src/app/connector/oauth/` | cc-pairs-and-creds |
| `web/src/lib/indexAttempt.ts`, `web/src/hooks/useIndexAttemptStageMetrics.ts`, `web/src/lib/targeted_reindex.ts` | indexing-pipeline |
| `web/src/app/admin/index-settings/`, `web/src/views/admin/IndexSettingsPage/`, `web/src/lib/searchSettings/`, `web/src/app/admin/documents/` | document-index |
| `web/src/app/admin/documents/sets/`, `web/src/hooks/useGroups.ts`, `web/src/hooks/useShareableGroups.ts`, `web/src/lib/hooks/useDocumentSets.ts`, `web/src/sections/cards/DocumentSetCard.tsx` | access-control |
| `web/src/sections/knowledge/`, `web/src/lib/hierarchy/` | agents-personas, access-control |
| `web/src/app/admin/federated/`, `web/src/components/admin/federated/`, `web/src/hooks/useFederatedOAuthStatus.ts`, `web/src/app/federated/oauth/`, `web/src/components/chat/FederatedOAuthModal.tsx` | federated-search |
| `web/src/app/admin/groups*/`, `web/src/app/ee/admin/groups/`, `web/src/views/admin/GroupsPage/` | access-control, authorization |
| `web/src/lib/permissions/` | authorization |
| `web/src/app/admin/scim/`, `web/src/app/admin/users/`, `web/src/app/admin/service-accounts/`, `web/src/app/ee/admin/scim/`, `web/src/app/ee/admin/service-accounts/`, `web/src/views/admin/ScimPage/`, `web/src/views/admin/ServiceAccountsPage/`, `web/src/views/admin/UsersPage/` | auth-and-identity |
| `web/src/hooks/useScimToken.ts`, `web/src/hooks/useAdminUsers.ts`, `web/src/hooks/useUsers.ts`, `web/src/hooks/useUserCounts.ts`, `web/src/providers/UserProvider.tsx`, `web/src/lib/hooks/useCaptcha.ts` | auth-and-identity |
| `web/src/app/admin/sso-providers/`, `web/src/app/admin/security/`, `web/src/app/admin/oauth-test/`, `web/src/views/admin/SSOProvidersPage.tsx`, `web/src/views/admin/SecurityHardeningPage.tsx`, `web/src/sections/modals/sso/` | auth-and-identity |
| `web/src/app/auth/`, `web/src/app/oauth-config/`, `web/src/lib/oauth/`, `web/src/app/anonymous/` | auth-and-identity |
| `web/src/app/oauth-provider/`, `web/src/sections/oauth-provider/`, `web/src/lib/oauth-provider/`, `web/src/lib/sso/`, `web/src/lib/users/`, `web/src/lib/auth/` | auth-and-identity |
| `web/src/app/admin/agents/`, `web/src/lib/agents/`, `web/src/views/admin/AgentsPage.tsx`, `web/src/views/admin/AgentsPage/`, `web/src/app/ee/agents/stats/` | agents-personas |
| `web/src/app/admin/chat-preferences/` | chat-preferences |
| `web/src/views/admin/ChatPreferencesPage.tsx`, `web/src/views/admin/ChatTaskModelSettings.tsx` | chat-preferences, llm-providers |
| `web/src/app/admin/language-models/`, `web/src/views/admin/LanguageModelsPage.tsx`, `web/src/sections/modals/languageModels/`, `web/src/lib/languageModels/`, `web/src/lib/hooks/useLLMProviderOptions.ts` | llm-providers |
| `web/src/app/admin/decision-models/`, `web/src/views/admin/DecisionModelsPage.tsx`, `web/src/views/admin/DecisionModelSetting.tsx`, `backend/onyx/llm/decisions/` | llm-providers |
| `web/src/app/admin/llm-gateway/`, `web/src/views/admin/LLMGatewayPage/` | llm-gateway |
| `web/src/app/admin/voice/`, `web/src/views/admin/VoicePage/`, `web/src/lib/voice/` | voice |
| `web/src/app/admin/plugins/`, `web/src/app/admin/mcp-actions/`, `web/src/app/admin/openapi-actions/` | plugins |
| `web/src/sections/plugins/`, `web/src/lib/plugins/`, `web/src/sections/actions/modals/MCPPluginSetupModal.tsx` | plugins |
| `web/src/sections/plugins/ExternalAppPluginDetail.tsx`, `web/src/sections/plugins/CraftAppEditorTabs.tsx` | craft-admin |
| `web/src/sections/actions/`, `web/src/lib/mcp/`, `web/src/app/mcp/oauth/`, `web/src/app/api/chat/mcp/oauth/`, `web/src/hooks/useOpenApiTools.ts`, `web/src/lib/hooks/useToolOAuthStatus.ts` | plugins, mcp-and-custom-tools |
| `web/src/app/mcp/[[...path]]/` | mcp-server |
| `web/src/app/admin/bots/`, `web/src/lib/updateSlackBotField.ts` | slack-bot |
| `web/src/app/admin/discord-bot/` | discord-bot |
| `web/src/app/admin/token-rate-limits/` | rate-and-usage-limits |
| `web/src/app/admin/billing/`, `web/src/lib/billing/`, `web/src/components/GatedContentWrapper.tsx`, `web/src/sections/modals/DowngradeToCommunityModal.tsx`, `web/src/components/errorPages/AccessRestrictedPage.tsx`, `web/src/providers/ProductGatingWrapper.tsx`, `web/src/hooks/useLicense.ts`, `web/src/hooks/useBillingInformation.ts`, `web/src/hooks/useCloudSubscription.ts` | billing |
| `web/src/proxy.ts`, `web/src/app/ee/layout.tsx`, `web/src/app/ee/EEFeatureRedirect.tsx` | editions-and-gating |
| `web/src/app/admin/hooks/`, `web/src/ee/views/admin/HooksPage/`, `web/src/ee/hooks/` | hooks |
| `web/src/app/ee/admin/standard-answer/`, `web/src/components/standardAnswers/` | standard-answers |
| `web/src/app/ee/admin/performance/`, `web/src/app/ee/admin/export-logs/`, `web/src/app/admin/tracing/`, `web/src/app/admin/systeminfo/`, `web/src/views/admin/TracingPage/`, `web/src/views/admin/WorkspaceAnalyticsPage/`, `web/src/views/admin/CostOverridesPanel.tsx`, `web/src/views/admin/PerUserUsagePanel.tsx`, `web/src/views/admin/SystemUsagePanel.tsx` | observability |
| `web/src/sections/usage/`, `web/src/lib/usage/`, `web/src/lib/tracing/` | observability |
| `web/src/lib/analytics/` | observability, editions-and-gating |
| `web/src/app/ee/admin/theme/`, `web/src/lib/app/components.tsx`, `web/src/lib/analytics/shared.tsx` | whitelabelling-and-theme |
| `web/src/app/admin/web-search/`, `web/src/views/admin/WebSearchPage/`, `web/src/lib/webSearch/` | web-search |
| `web/src/app/admin/image-generation/`, `web/src/views/admin/ImageGenerationPage/` | image-generation |
| `web/src/app/admin/code-interpreter/`, `web/src/views/admin/CodeInterpreterPage/`, `web/src/hooks/useCodeInterpreter.ts` | code-execution |

---

## Not mapped

No component owns these paths. Read the reason before you change one. To list
the admin routes and check that each has a row above, run
`grep -oE 'path: "/admin[^"]*"' web/src/lib/admin-routes.ts | sort -u`.

| Path | Reason |
|---|---|
| `backend/onyx/kg/`, `backend/onyx/db/entities.py`, `backend/onyx/db/entity_type.py`, `backend/onyx/db/relationships.py`, `backend/onyx/db/kg_config.py`, `backend/onyx/db/kg_temp_view.py`, `backend/onyx/configs/kg_configs.py`, `backend/onyx/server/kg/` | The knowledge graph is an incomplete feature. Its tables, config and `/admin/kg` API exist, but no pipeline fills the tables and no admin page uses them. The tool cannot run (Known issues of [[tools-framework]]). Keep the code when you clean up nearby code. |
| `backend/onyx/db/models.py`, `backend/onyx/db/enums.py` | Models and enums for every table. Look up the components that own the tables the diff touches. |
| `backend/onyx/db/dal.py`, `backend/onyx/db/utils.py`, `backend/onyx/db/constants.py`, `backend/onyx/db/pydantic_type.py`, `backend/onyx/db/README.md`, `backend/onyx/db/_deprecated/` | Database helpers that every component uses. |
| `backend/alembic/` | Migrations. Read the component that owns the table being migrated. |
| `documentation/` | Customer docs (Mintlify). `documentation/AGENTS.md` sets their rules, and `documentation/audit/` maps each page to the components it describes. A code change updates the page that covers it. |
| `backend/onyx/db/seeding/`, `backend/onyx/seeding/`, `backend/ee/onyx/server/seeding.py` | Seed data for rows that several components own. The default agent and the built-in tool rows come from migrations. |
| `backend/onyx/evals/`, `backend/onyx/server/evals/`, `backend/ee/onyx/server/evals/` | The eval harness. Read the component being evaluated. A prompt or retrieval change needs an eval, not only a unit test. |
| `backend/onyx/main.py`, `backend/ee/onyx/main.py`, `backend/onyx/setup.py` | App assembly: router and middleware registration and startup. Read the component of each router or middleware you change. |
| `backend/onyx/cache/`, `backend/onyx/redis/`, `backend/onyx/key_value_store/`, `backend/onyx/db/encrypted_kv_store.py` | Cache and key-value libraries. Fences, rate limits and the stream buffer use them, so check the callers. |
| `backend/onyx/error_handling/` | `OnyxError` and the error codes that clients see. |
| `backend/onyx/utils/` | Shared helpers. Check the callers. |
| `backend/onyx/configs/`, `backend/ee/onyx/configs/app_configs.py`, `backend/shared_configs/` | Settings for every area. Read the component that documents the setting. |
| `backend/onyx/server/runtime/` | `OnyxRuntime` resolves a setting from the database, the cache, env vars and defaults. |
| `backend/onyx/server/middleware/api_prefix.py` | Removes the API prefix from a request path for the middlewares that match on routes. |
| `backend/onyx/server/manage/get_state.py`, `backend/onyx/server/manage/models.py`, `backend/onyx/server/models.py`, `backend/onyx/server/utils.py`, `backend/onyx/server/utils_vector_db.py` | Health, version and auth-type probes, and models and helpers that many routes share. |
| `deployment/` | Deployment files. Read the component of the service you deploy. |
| `deployment/data/nginx/`, `cli/internal/deploy/deployfiles/embedded/data/nginx/` | Reverse-proxy templates. The `cli/` copies are generated: run `ods generate-compose --write` after you change `deployment/data/nginx/`. |
| `cli/` | The Onyx CLI client. Only its packet parser has an owner (streaming-protocol). |
| `tools/`, `backend/scripts/`, `backend/requirements/` | Developer tooling and dependency files. |
| `.github/` | CI. Read the workflow. |
| `web/src/app/ee/admin/` | A second admin route tree. `web/src/proxy.ts:EE_ROUTES` rewrites the `/admin/...` paths it lists to this tree. Check `EE_ROUTES` before you decide which copy serves an `/admin/...` path. |
| `web/src/lib/admin-routes.ts`, `web/src/app/admin/layout.tsx` | The admin route list and the admin shell. A new admin route needs its own row above. |
| `web/src/components/`, `web/src/refresh-components/`, `web/src/layouts/`, `web/lib/opal/`, `web/lib/shared/` | Shared UI. Read the calling component, and the Opal rules in `web/AGENTS.md`. |
| `web/src/app/layout.tsx`, `web/src/app/page.tsx`, `web/src/app/providers.tsx`, `web/src/app/css/`, `web/src/i18n/`, `web/public/` | The app shell, global styles, translations and static assets. |
