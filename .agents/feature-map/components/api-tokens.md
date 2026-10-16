# API tokens

> One table of third-party API keys that features point to by id, so an admin
> can reuse a saved key in another feature and rotate it in one place.

**Verified against:** `44ffc8d71c` (2026-10-16)
**Domain:** configuration
**Edition:** CE
**Owns:**
`backend/onyx/db/api_token.py`, `backend/onyx/server/manage/api_token/`
(`api.py`, `models.py`), `web/src/lib/api-tokens/`

---

## 1. What the user experiences

Every API key field in the admin UI looks and works the same. An admin types a
new key, or opens the list under the field and picks a saved key for the same
service ("Reuse OpenAI API Keys"). Each saved key shows its masked value and the
places that use it ("Used for LLM provider **OpenAI** and image generation
**gpt-image-1**"). Saved keys have no name. Only full admins see the list; other
admins can still type a key.

A key that no feature uses anymore is deleted, so the list never holds unused
keys.

---

## 2. Surfaces

### Admin HTTP endpoints (`/admin/api-tokens`, `server/manage/api_token/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/admin/api-tokens?platform=` | `list_tokens` | Saved keys for one platform, masked, with usages. Onyx-owned keys are left out. Full admin. |
| PATCH | `/admin/api-tokens/{token_id}` | `rotate_token` | Replaces a key's value for every feature that uses it. Full admin. |

### Request field

Every consumer's request carries the key as `api_key: ApiTokenInput | None`
(`server/manage/api_token/models.py`):

- `{"type": "new", "value": "..."}` creates a token.
- `{"type": "existing", "id": 12}` points at a saved token.
- A plain string is read as `new`, so older clients and Terraform keep working.
- `null` clears the key. Leaving the field out of an update keeps the current
  key (`keep_omitted_api_token`).

### Consumers

LLM providers (and image generation through its hidden LLM provider row), voice
providers (`api_key` only; `api_secret` stays on the row), cloud embedding
providers, web search and web content providers, tracing providers, hooks (EE),
and the Unstructured key (the key-value store holds its token id under
`unstructured_api_token_id`).

---

## 3. Data model

- `ApiToken` (`api_token`, `db/models.py`): `platform` (e.g. `openai`, `exa`),
  `value` (`EncryptedString`), `base_url` (where the key was first saved),
  `is_system` (Onyx-owned Cloud keys), timestamps.
- Each consumer table has `api_token_id` (FK, `ON DELETE RESTRICT`), an
  `api_token` relationship loaded with the row, and a read-only `api_key`
  property that returns the token's value.
- Migration `eb0c14780dc5` moved every stored key into its own row, copying the
  encrypted bytes, and moved the plaintext Unstructured key into an encrypted
  row.

---

## 4. How it works

1. A form's key field (`ApiTokenField` / `ApiTokenInput` in
   `web/src/lib/api-tokens/components/`) holds an `ApiTokenValue`. On edit it
   starts as `existing` with the row's `api_token_id`.
2. The request sends `toApiTokenPayload(value)`.
3. The consumer's write path calls `db/api_token.py:assign_api_token`, which
   resolves the input (`resolve_api_token`), points the row at the token, and
   deletes the previous token if nothing else uses it (`release_api_token`).
4. Test-before-save endpoints read the key with `peek_api_token_value` without
   saving anything.
5. Runtime code reads `row.api_key` as before.
6. `get_api_token_usages` builds the "Used for" list from each consumer's FK
   and the Unstructured key-value entry.

---

## 5. Contracts and invariants

- An `existing` token must be for the same platform and not Onyx-owned, unless
  it is the row's current token.
- In multi-tenant, a saved key is only sent to the base URL it was saved for.
  This replaced the per-feature "stored key, same base URL" guards.
- Deleting a consumer row must release its token after the row is gone.
  Soft-deleted hooks clear `api_token_id` first.
- Responses never return a raw key. Views carry a masked value and
  `api_token_id`.

---

## 6. Relationships

**Depends on**
- `onyx/utils/encryption.py` for `EncryptedString`, masking and key rotation
  (`db/rotate_encryption_key.py` finds `api_token.value` by itself).

**Depended on by**
- [[llm-providers]], [[image-generation]], [[voice]], [[web-search]],
  [[observability]] (tracing, hooks), [[document-index]] (Unstructured), and
  the embedding provider settings.

---

## 7. Blast radius

| Change | Check |
|---|---|
| A new consumer | Add its FK to the migration pattern, a usage kind in `get_api_token_usages` and `ApiTokenUsageKind`, and its copy key in `common.apiTokens.usage`. |
| `resolve_api_token` rules | Every consumer's save and test endpoints, multi-tenant base URL behaviour. |
| `ApiTokenInput` shape | Terraform `llm_provider` and `embedding_provider` resources, every frontend service. |

---

## 8. How to verify a change

- Integration: `backend/tests/integration/tests/api_token/`.
- Per consumer: the LLM provider, web search and image generation integration
  tests, and the voice, embedding, tracing, hook and Unstructured unit tests.
- Manual: save an OpenAI key on an LLM provider, open the image generation
  OpenAI form, and pick the same key from the list.

---

## 9. Footguns

- Assigning `row.api_key` does nothing useful: it is a read-only property. Use
  `assign_api_token`.
- Python callers must pass `NewApiToken(value=...)`. The plain-string coercion
  runs at request parsing only, and `ty` rejects a `str`.
- Releasing a token whose row still points at it is a no-op, by design. Delete
  or repoint the row first.
