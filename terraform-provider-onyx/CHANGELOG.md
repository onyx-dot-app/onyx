# Changelog

## 0.3.0 (Unreleased)

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
