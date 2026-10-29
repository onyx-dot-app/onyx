# Image Generation

> Turns a prompt, and optional reference images, into an image through one
> admin-chosen provider. It serves the `generate_image` chat tool and a
> standalone endpoint that the CLI and Craft use.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE. EE tenant provisioning creates a default config from the
deployment's `OPENAI_DEFAULT_API_KEY` when `AUTO_PROVISION_DEFAULT_LLM_PROVIDERS`
is on (`ee/onyx/server/tenants/provisioning.py`).

---

## User experience

- **An end user** asks for an image in chat. A progress indicator shows, then
  the image appears in the answer. The user can ask for changes to an image
  they attached or to one that the assistant made, and the model uses it as a
  reference. After an image, the assistant answers without calling more tools.
- **An admin** opens the image generation admin page, picks a model from
  OpenAI, Azure or Vertex AI, enters credentials, and makes it the default. A
  test call can generate one image to check the credentials. A
  model that the vendor withdrew shows only while it is connected, with a
  warning to switch. Onyx does not switch a saved config by itself.
- **With no default config**, the model is not offered the tool. The user sees
  no error. A complete config with a rejected key passes this check and fails
  when the tool runs, with an error that the user can see.
- **An API caller**, such as `onyx-cli image` inside a Craft sandbox, calls
  `POST /image-generation/generate`. It gets a 404 when no provider is set up,
  and a 429 when too many generations wait.

---

## Scope

This component owns the provider classes and the default-config resolver,
`ImageGenerationTool`, the admin API and page, the standalone endpoint, and the
`ImageGenerationConfig` table.

It does not own:
- Credential storage. Each config points to a `ModelConfiguration` and an
  `LLMProvider` row, which [[llm-providers]] owns.
- File storage and the session stamp on generated images
  ([[file-store-and-user-files]]).
- The chat cycle that ends tool calls after an image ([[core-chat-loop]]).
- The Craft `image-generation` skill, which calls the CLI ([[skills]]). The
  skill is offered only when `is_image_generation_configured` is true.

---

## Architecture

```
admin page -> /admin/image-generation/config    creates LLMProvider + ModelConfiguration
                                                + ImageGenerationConfig(is_default)
chat turn
  ImageGenerationTool.is_available               generation.py:is_image_generation_configured
  tool_constructor.py:_get_image_generation_config   default config -> credentials
  ImageGenerationTool._run
    _resolve_reference_image_file_ids            dedupe, cap, reject if unsupported
    worker thread: generate_images_with_provider tool thread polls for cancellation
    save_files(base64, chat_session_id)          -> FinalImageGenerationResponse details
  chat/renderer.py:ToolRenderer                  ImageGenerationToolStart, then
                                                 ImageGenerationFinal from the details
standalone
  POST /image-generation/generate                ensure_image_generation_configured (404)
    _GenerationRun in a bounded pool             whitespace keepalives, then one JSON body
```

**Providers.** `image_gen/factory.py:PROVIDERS` maps a provider name to an
`ImageGenerationProvider` subclass. Each class checks that its credentials are
complete (`validate_credentials`) and states whether it accepts reference
images. OpenAI and Azure use LiteLLM, and Vertex AI uses `genai.Client` for
edits. Every call is traced with `LLMFlow.IMAGE_GENERATION` or
`LLMFlow.IMAGE_EDIT` ([[observability]]).

**Model catalogue.** The list of models that an admin can pick lives in the
frontend, in `web/src/views/admin/ImageGenerationPage/constants.ts`. Each entry
has a static `image_provider_id`, which is the primary key of
`ImageGenerationConfig`.

**Admin writes.** `server/manage/image_generation/api.py:update_config` renames
the old `LLMProvider`, creates a new provider and model configuration, points the
config at them, and deletes the old provider. It does not reuse the LLM provider
upsert, because that upsert deletes model configurations, and the delete
cascades to `ImageGenerationConfig`. The LLM provider list hides these rows
([[llm-providers#image-gen-rows-hidden-from-list]]).

**Standalone endpoint.** `server/features/image_generation/api.py:generate_image`
checks the config before it starts the stream. It then sends whitespace every
15 s, so that load balancers do not close an idle connection, and ends with one
JSON body: the images or an `{error_code, detail}` envelope. It returns base64
and saves no files. The caller needs `Permission.GENERATE_IMAGE`.

---

## Contracts and traps

1. `two-default-config-readers` **Two functions read the default config.
   Change both.** `image_gen/generation.py:_default_provider_and_model` serves
   the availability check and the standalone endpoint.
   `tools/tool_constructor.py:_get_image_generation_config` feeds the chat tool,
   and `_construct_tools_impl` then uses the model name when `deployment_name`
   is empty. The standalone path has no such fallback. A new credential field or
   provider rule must go into both.
2. `configured-means-complete` **"Configured" means complete, not working.**
   `image_gen/generation.py:is_image_generation_configured` calls `validate_credentials`, which checks
   only that the fields are present. It does not call the provider. A wrong key
   shows the tool and fails at run time.
3. `image-ends-tool-phase` **Image generation ends the tool phase.**
   [[core-chat-loop]] owns the stopping-tool rule. After an image,
   `chat/agent.py:ChatAgent._prepare_step` offers no tools, and
   `chat/prompt_utils.py:build_chat_reminder` uses
   `prompts/chat_prompts.py:IMAGE_GEN_REMINDER`. Any tool added to
   `tools/built_in_tools.py:STOPPING_TOOLS_NAMES` also gets this image reminder.
4. `response-format-per-model` **`response_format` depends on the model.**
   `image_gen/generation.py:response_format_for_model` leaves it out for
   `gpt-image-*` models, which reject it, and asks for `b64_json` for the rest.
   `generate_images_with_provider` reads only `b64_json`, so a model that
   returns URLs fails with "No base64 image data".
5. `reference-image-checks` **Reference-image support is checked at two
   levels.**
   `tools/tool_implementations/images/image_generation_tool.py:ImageGenerationTool._resolve_reference_image_file_ids`
   rejects
   references when the provider does not support them, with a message that the
   model can act on. It cuts the list to `max_reference_images` without a
   message. Model-level limits, such as a model that cannot edit, are checked
   inside the provider's `generate_image`. They raise `ValueError`, which
   `ImageGenerationTool._generate_image` turns into a `ToolExecutionException`
   with an error packet that the user sees.
6. `masked-key-keeps-old` **A masked key means "keep the old key".** The
   credentials endpoint returns the key masked by
   `server/manage/image_generation/models.py:_mask_api_key`. The docstring of
   `server/manage/image_generation/api.py:get_config_credentials` says
   unmasked, which is wrong. `server/manage/image_generation/api.py:update_config` keeps the stored key when
   `api_key_changed` is false and the key is empty or contains `****`. On cloud,
   a kept key also needs the same `api_base` and `custom_config`
   (`server/manage/llm/api.py:_validate_llm_provider_change`). A client that sends the masked key with
   `api_key_changed=true` saves the masked text as the key.
7. `images-carry-session` **Generated images carry the chat session ID.** The
   tool passes `chat_session_id` to `save_files`, and
   `tools/tool_constructor.py:_require_chat_session_id` refuses to build the
   tool without it. See [[file-store-and-user-files]] for the access rule.
8. `frontend-packet-names` **Frontend packet names do not match the backend
   names.** The web enum calls the finished-image packet
   `IMAGE_GENERATION_TOOL_DELTA`, but its value is `"image_generation_final"`
   (`web/src/app/app/services/streamingModels.ts`). The renderer treats "start
   with no end" as running. Match packets by their string value.
9. `one-image-per-chat-call` **The chat tool makes one image per call.**
   `ImageGenerationTool._generate_image` passes `n=1`. Only the standalone
   endpoint accepts `n`, up to `server/features/image_generation/api.py:_MAX_IMAGES`.
10. `standalone-errors-in-body` **The standalone endpoint reports late errors in
    the body, and early errors as HTTP status.** Older CLIs cannot read the
    in-body envelope, so "not configured" must stay a real 404 before the 200
    starts. After the 200 starts, a provider error, a timeout of
    `_MAX_STREAM_DURATION_S`, or a failed run arrives as an
    `{error_code, detail}` body with status 200. Clients must check for
    `error_code`. `X-Accel-Buffering: no` stops nginx from holding back the
    keepalives.

---

## Known issues

- **No database rule keeps one default.** `ImageGenerationConfig.is_default`
  has an index, not a unique constraint. The write paths clear other defaults
  first, but two writes at the same time can leave two defaults.
  `get_default_image_generation_config` then returns one of them.
- **Reference images skip the file access check.**
  `ImageGenerationTool._load_reference_images` reads each file ID that the model
  passes with `file_store/utils.py:load_chat_file_by_id`, which does not check
  that the user can read the file. A file ID that reaches the model, for example
  through document text, can load another user's image.

---

## Dependencies

- [[llm-providers]]: `LLMProvider` rows hold the encrypted credentials.
- [[tools-framework]]: the tool interface, `is_available` and construction.
- [[file-store-and-user-files]]: `save_files` and `load_chat_file_by_id`.
- [[streaming-protocol]]: the start and final packets.
- [[observability]]: `traced_llm_call` around each provider call.

---

## Recipes

- `model-for-existing-provider` **A model for an existing provider.** Copy an entry in
  `web/src/views/admin/ImageGenerationPage/constants.ts` and give it a new
  static `image_provider_id`. List the current models with
  `git grep image_provider_id -- web/src/views/admin/ImageGenerationPage/`. If
  its size or `response_format` rules differ, change
  `image_gen/generation.py:resolve_image_size` and `response_format_for_model`.
- `image-provider` **A provider.** Copy `image_gen/providers/azure_img_gen.py`. List the current
  providers in `PROVIDERS`. Subclass `image_gen/interfaces.py:ImageGenerationProvider`,
  add it to `ImageGenerationProviderName` and `PROVIDERS`, and set its
  reference-image properties. Add a form under
  `web/src/views/admin/ImageGenerationPage/forms/` and a case in
  `web/src/views/admin/ImageGenerationPage/forms/getImageGenForm.tsx`. Check
  both config readers ([[#two-default-config-readers]]).
- `investigate-image-tool-missing` **Investigate "the image tool is not offered" or a standalone 404.** Check
  that one config has `is_default` set and that its `LLMProvider` row exists.
  Then check that `validate_credentials` passes for that provider
  ([[#configured-means-complete]]). If the tool shows but every call fails, the
  key or the model is wrong; the user-visible error text comes from
  `ImageGenerationTool._generate_image`. The agent and per-message gates are in
  [[tools-framework#investigate-tool-not-called]].

---

## Verification

- Unit tests: `backend/tests/unit/onyx/image_gen/`, the image generation files
  in `backend/tests/unit/onyx/tools/`,
  `backend/tests/unit/onyx/server/features/image_generation/` and
  `backend/tests/unit/onyx/server/manage/image_generation/`.
- External dependency unit tests: `backend/tests/external_dependency_unit/tools/`.
- Integration: `backend/tests/integration/tests/image_generation/` and
  `backend/tests/integration/tests/tools/`.
- Playwright: `web/tests/e2e/admin/image-generation/`.
- By hand, set a default config and ask for an image. Then remove the default:
  the next message must have no image tool call and no error.
