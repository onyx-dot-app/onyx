# TeamsBot configuration (experimental)

This first implementation adds configuration storage and an administrator API.
It does not receive Teams messages or generate answers yet.
The [design proposal](https://github.com/onyx-dot-app/onyx/pull/14919) describes the remaining work.

Run the database migration, then set `ENABLE_TEAMS_BOT=true` on the API server.
The feature is disabled by default. This increment supports self-hosted deployments only.
All configuration routes require `MANAGE_BOTS`.

Use `/api/manage/admin/teams-bot/config` through the frontend:

| Method | Purpose | Request fields |
| --- | --- | --- |
| GET | Read configuration; `null` when absent | None |
| POST | Create the deployment's bot configuration | `app_id`, `directory_id`, `client_secret`; optional `enabled`, `persona_id` |
| PUT | Replace settings and optionally rotate the secret | Required `enabled`, `persona_id`; optional `client_secret` |
| DELETE | Remove the configuration | None |

Use the Entra application ID for `app_id` and its directory tenant ID for `directory_id`.
Provide the client secret value, not its identifier. Do not put secrets in shell history or source control.
The response never includes the secret. Omitting it during an update preserves the stored value.
Application and directory IDs cannot change during an update. Delete and recreate the configuration to replace them.
New configurations default to disabled. No bot runtime uses the `enabled` setting in this increment.

Credentials use Onyx's existing `EncryptedString` storage and sensitive-value wrapper.
At-rest encryption requires Enterprise Edition with `ENCRYPTION_KEY_SECRET` configured; Community Edition stores credential bytes without encryption.
The Teams SDK, identity linking, message callback, delivery worker, and administration UI will follow in separate changes.
