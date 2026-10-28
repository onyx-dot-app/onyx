# Changelog

The section headings are load-bearing: the mirror's Publish workflow extracts the
block for the tag being released and uses it as the GitHub release body, which is
what the Terraform Registry shows. A release whose version has no section here
fails rather than publishing empty notes.

## 0.4.0 (Unreleased)

BREAKING CHANGES:

* provider: this release supports Onyx v4.8.0 and later. On Onyx v4.7 and earlier, pin the
  provider to `~> 0.3.0`. (`~> 0.3` also allows 0.4.0.) This release reads by id and no longer resends agent attachments, so
  on older Onyx, resources can look deleted and agent attachments can be cleared.
* resource/onyx_custom_tool: `enabled` now controls whether the action is available in
  default Chat (`default_chat_enabled`). It no longer disables the action globally, and
  custom agents keep their own settings. `enabled = false` needs Onyx v5.0 or later. On
  v5.0 and later, 0.3.0 failed to apply it.
* resource/onyx_connector: `refresh_freq` below 60 and `prune_freq` below 300 now fail at
  plan time. Onyx already rejected these values on write.

FEATURES:

* **New resource:** `onyx_agent_label`.
* **New data source:** `onyx_tools`. Use it to find built-in action ids for
  `onyx_agent.tool_ids`.
* **New data source:** `onyx_user_groups` (Enterprise Edition).

ENHANCEMENTS:

* resource/onyx_cc_pair: `groups`, `auto_sync_options` and `processing_mode` are read back,
  so import fills them and drift shows in the plan. A change to one still replaces the pair.
* resource/onyx_cc_pair: new `access_type = "sync_restricted"` (Onyx v5.0+). Like every
  `access_type` change, switching to it replaces the pair.
* resource/onyx_cc_pair: new `data_access_group_ids` (Onyx v5.0+, Enterprise Edition), updated
  in place. On other servers, apply fails instead of leaving the readers unrestricted.
* resource/onyx_connector: new `check_freq` (Onyx v5.0+). `onyx_connectors` exposes it.
* resource/onyx_embedding_provider: new `provider_type` values `bifrost` (Onyx v5.0+) and
  `openai_compatible` (Onyx v5.1+). A configured key is sent with `api_key_changed`.
* resource/onyx_llm_provider: new `model_configurations` attributes `reasoning_effort_max`,
  `reasoning_effort_default` and `temperature_default`.
* resource/onyx_llm_provider_default: new `craft_provider_id` and `craft_model_name`.
* resource/onyx_llm_provider_default: new `search_selection_provider_id` and
  `search_selection_model_name` (Onyx v5.0+).
* resource/onyx_settings: new `reasoning_override_enabled` and `hide_provider_grouping`. New
  on Onyx v5.0+: `default_language`, `llm_gateway_enabled`,
  `embedding_rate_limit_requests` and `embedding_rate_limit_period_seconds`. The
  `onyx_settings` data source exposes them.
* resource/onyx_settings: `image_analysis_max_size_mb` is deprecated. Onyx no longer has the
  setting, and the provider no longer sends it.

BUG FIXES:

* resource/onyx_connector: an unset `prune_freq` is no longer sent as null, which turns
  pruning off on Onyx v5.1 and later.
* resource/onyx_user_group: roster changes no longer resend connector links, which could
  revert a link added at the same time. Destroy retries while the group syncs. A scoped group
  manager can now run a plan.
* resource/onyx_agent: updates no longer read and resend attached folders and documents.
  Create sends empty lists, so an agent that reuses a deleted agent's name does not inherit
  its old attachments.
* resource/onyx_llm_provider: the delete error says that `force_delete` does not override the
  decision model.

## 0.3.0 (September 8, 2026)

BREAKING CHANGES:

* resource/onyx_persona: renamed to `onyx_agent`. Onyx calls this object an agent
  everywhere users see it, and the REST API is moving the same way, so the provider
  now matches. Rename the resource in your configuration and move the state entry:

  ```
  terraform state mv onyx_persona.example onyx_agent.example
  ```

* resource/onyx_agent: `builtin_persona` renamed to `builtin_agent`.
* resource/onyx_user_group: `persona_ids` renamed to `agent_ids`.
* resource/onyx_llm_provider: `personas` renamed to `agents`.

NOTES:

* The wire format is unchanged. Onyx still serves create, read, update, delete and
  listed under `/persona`, and still spells two JSON fields `personas` and
  `builtin_persona`. Only the Terraform-facing names moved, so this release works
  against the same Onyx versions as 0.2.0.
