"""Vulture whitelist: names that are only referenced dynamically.

vulture treats every name read here as used, in every module. Prefer deleting
dead code. Add a name here only when it is truly used, and group it under a
comment that says how it is reached.

Run the check with `uv run python backend/scripts/check_dead_code.py`.
"""

from typing import Any

_: Any = None

# Looked up by string with fetch_versioned_implementation(),
# fetch_versioned_implementation_with_fallback(), or
# fetch_ee_implementation_or_noop().
_._filter_accessible_hierarchy_node_ids
_._get_access_for_document
_._get_user_external_group_ids
_._handle_standard_answers
_.check_if_valid_sync_source
_.delete_document_set_privacy__no_commit
_.delete_user__ext_group_for_cc_pair__no_commit
_.delete_user__ext_group_for_user__no_commit
_.delete_user_group_cc_pair_relationship__no_commit
_.element_update_permissions
_.ensure_license_expiry_notification_for_user
_.ensure_tenant_membership
_.get_anon_id_from_request
_.get_course_permissions
_.get_default_admin_user_emails_
_.get_posthog_feature_flag_provider
_.get_tenant_invitation
_.get_tenant_usage_limit_overrides
_.is_tenant_on_trial
_.make_doc_set_private
_.make_mcp_server_private
_.register_license_metrics

# Connector classes loaded by `class_name` in onyx/connectors/registry.py and
# onyx/federated_connectors/registry.py.
_.BookstackConnector
_.DrupalWikiConnector
_.MockConnector
_.WikipediaConnector
_.ZulipConnector

# Overrides and handlers that a framework or library calls by name: Starlette
# middleware, BaseHTTPRequestHandler, mistune renderers, reportlab flowables,
# discord.py events, pywikibot families, SDK retry and auth hooks, PyYAML loaders.
_.__bool__
_._can_retry
_._perform_authorization_code_grant
_.block_code
_.block_error
_.block_html
_.block_quote
_.codespan
_.compare_values
_.construct_mapping
_.dispatch
_.do_GET
_.draw
_.emphasis
_.get_params
_.linebreak
_.log_message
_.on_message
_.on_ready
_.prepare_for_next_attempt
_.process_bind_param
_.process_result_value
_.protocol
_.strikethrough
_.strong
_.table_body
_.table_cell
_.table_head
_.table_row
_.thematic_break
_.writefile

# Attributes and module settings that a library reads after we set them:
# Celery config, litellm settings, SDK and stdlib objects, python-docx and
# python-pptx property setters, reportlab chart styles.
_.MAX_IMAGE_PIXELS
_._grant_cache
_._grant_cache_lock
_.add_function_to_prompt
_.angle
_.apex_url
_.api_usage
_.barSpacing
_.base_style
_.beat_scheduler
_.bulk_url
_.categoryNames
_.compress_type
_.disposition
_.drop_params
_.dy
_.fillColor
_.fontName
_.fontSize
_.gridStrokeColor
_.gridStrokeWidth
_.hAlign
_.lifetime
_.modify_params
_.mtime
_.next_attempt_requested
_.oauth2_url
_.operation_id
_.orig_filename
_.rate_limit_user_id
_.right_indent
_.space_after
_.space_before
_.speech_synthesis_voice_name
_.strokeColor
_.strokeWidth
_.superscript
_.suppress_debug_info
_.task_default_base
_.tooling_url
_.valueMin
_.visibleGrid
_.worker_concurrency
_.worker_pool
_.worker_prefetch_multiplier

# Model fields that are written, then persisted or serialized: ORM column
# writes, pydantic fields, and ORM model classes that map live tables.
_.HierarchyFetchAttempt
_.KGTerm
_.Milestone
_.OpenSearchDocumentMigrationRecord
_.Persona__Document
_.Persona__HierarchyNode
_.active_connectors
_.admin_count
_.gpu_enabled
_.granted_at
_.hide_query_history_from_admin_panel
_.KG_MAX_COVERAGE_DAYS
_.information_content_boost
_.last_accessed
_.opensearch_indexing_enabled
_.public_connectors
_.registered_at
_.seat_count
_.show_extra_connectors
_.total_chunks_errored
_.total_connectors

# Imports that only string annotations or casts use.
_.ChatCompletionToolParam
_.ImageGenerationConfigModel
_.LiteLLMModelResponseStream
_.S3Client
_.SpawnProcess

# Test support: names that test tooling reads by name or through __dict__.
_.alembic_runner
_.full_deployment_setup
_.IncompleteSpec
_.ObjectIdentifierTypeDef
_._PaginatedList__nextUrl
_._SourcelessOperations
_.__aexit__
_.__nextUrl
_._parse_page
_.async_auth_flow
_.auto_size
_.close_connection
_.config_ini_section
_.do_DELETE
_.do_HEAD
_.do_POST
_.fetch_all_pages
_.redirect_request
_.should_exit
_.slide_height
_.slide_width
_.word_wrap

# Settings that operators set through deployment/ templates or Helm values.
# Remove them together with those templates.
_.AUTO_PROVISION_DEFAULT_EXTERNAL_APPS
_.CONTINUE_ON_CONNECTOR_FAILURE
_.DISABLE_LITELLM_STREAMING
_.DISABLE_RERANK_FOR_STREAMING
_.NUM_PERMISSION_WORKERS
_.SANDBOX_IMAGE_PULL_POLICY
_.SANDBOX_SERVICE_ACCOUNT_NAME
_.USE_SEMANTIC_KEYWORD_EXPANSIONS_BASIC_SEARCH

# Public interface kept for API parity: EventConnector, and TenantRedisClient,
# which mirrors redis-py.
_.brpop
_.create_lock
_.handle_event

# StubSandboxManager records call payloads for tests to inspect.
_.last_cleanup_session_workspace_payload
_.last_create_opencode_history_snapshot_payload
_.last_create_snapshot_payload
_.last_delete_file_payload
_.last_delete_opencode_session_payload
_.last_dispose_opencode_instance_payload
_.last_ensure_opencode_session_payload
_.last_generate_pptx_preview_payload
_.last_get_upload_stats_payload
_.last_get_webapp_url_payload
_.last_health_check_payload
_.last_list_directory_payload
_.last_list_session_workspaces_payload
_.last_outputs_manifest_payload
_.last_prompt_slot_payload
_.last_provision_payload
_.last_read_file_payload
_.last_regenerate_session_config_payload
_.last_restore_snapshot_payload
_.last_send_message_payload
_.last_session_workspace_exists_payload
_.last_setup_session_workspace_payload
_.last_subscribe_to_opencode_session_payload
_.last_upload_file_payload
_.last_write_files_to_sandbox_payload
_.last_write_sandbox_file_payload
