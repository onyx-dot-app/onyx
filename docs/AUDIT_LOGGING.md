# Audit Logging

Onyx emits a normalized, structured **audit-event stream** for security-relevant
actions (authentication, admin-config changes, access-control changes,
credential access). The stream is designed to be exported to any SIEM
(Splunk, Microsoft Sentinel, Elastic, Google Chronicle, AWS Security Lake) with
**no per-SIEM integration on Onyx's side** — you point your log shipper at the
container stdout / log file, filter on the audit logger names, and parse the
JSON.

This maps directly onto common compliance controls: SOC 2 CC7 and the
FedRAMP/NIST 800-53 **AU** family (AU-2 auditable events, AU-3 record content,
AU-6 review, AU-12 generation).

## How it works

Audit events are plain `INFO` log records emitted on a dedicated **`onyx.audit`**
logger tree. The **message body of each record is a single JSON object** — we
serialize the event to JSON ourselves rather than relying on the structured log
formatter, so the audit line is byte-identical whether the app runs in
`LOG_FORMAT=plain` or `LOG_FORMAT=json`. (Setting `LOG_FORMAT=json` is still
recommended so *all* logs are machine-parseable and tenant/request context is
promoted to top-level fields — see `backend/shared_configs/configs.py`.)

Emission is **fail-safe and never raises into the caller**: it sits on request
and connector hot paths, so any failure to gather context, dedup, or log is
swallowed. High-volume event classes (e.g. credential access) are **deduped via
Redis** within a short window; if Redis is unavailable, emission degrades to
always-emit (an audit event is never silently dropped because of infra trouble).

### Logger names

| Logger | Contents |
|---|---|
| `onyx.audit` | Root of the audit tree (filter on this prefix to capture everything). |
| `onyx.audit.authentication` | OCSF Authentication class events. |
| `onyx.audit.account_change` | OCSF Account Change class events. |
| `onyx.audit.api_activity` | OCSF API Activity class events. |
| `onyx.audit.credential_access` | Credential-decrypt events (predates the generalized schema; see note below). |

## Event schema

Field names and the action taxonomy are shaped toward **OCSF** (the Open
Cybersecurity Schema Framework) so events map cleanly onto OCSF event classes.
We emit plain JSON today; every event carries an `ocsf_class` hint so a future
OCSF-native emitter mode is a formatting change, not a re-instrumentation.

Generalized events (`emit_audit_event`, `backend/onyx/utils/audit.py`):

| Field | Type | Description |
|---|---|---|
| `audit_schema_version` | string | Schema version (currently `"1.0"`). |
| `ts` | float | Event time, epoch seconds. |
| `action` | string | Action taxonomy value, `<domain>.<verb>` (e.g. `llm_provider.update`). Append-only contract. |
| `ocsf_class` | string | `authentication` \| `account_change` \| `api_activity`. |
| `outcome` | string | `success` \| `failure` \| `denied`. |
| `tenant_id` | string \| null | Tenant the action occurred in (best-effort). |
| `actor` | object \| null | `{ user_id, email, api_key_id, auth_type }`. Never contains a secret. |
| `resource_type` | string \| null | Affected resource type (e.g. `llm_provider`, `user`, `api_key`). |
| `resource_id` | string \| null | Affected resource identifier (row id or name), normalized to string. |
| `request_id` | string \| null | Onyx request id, correlates with the rest of the request's logs. |
| `endpoint` | string \| null | Route handler that produced the event. |
| `source_ip` | string \| null | Globally-routable client IP (from `X-Forwarded-For`). |
| `extra` | object \| null | Additional non-secret context. **Never put secrets here.** |

### Action taxonomy

The `action` values are a stable, append-only contract (consumers filter on
them). Current taxonomy (`AuditAction` in `backend/onyx/utils/audit.py`):

- **Authentication:** `auth.login`, `auth.login_failure`, `auth.logout`,
  `auth.register`, `auth.password_forgot`, `auth.password_reset`,
  `auth.email_verify`, `auth.impersonate`
- **Account change:** `user.create`, `user.delete`, `user.deactivate`,
  `user.reactivate`, `user.role_change`, `user.group_change`
- **API activity (admin config / resource CRUD):** `llm_provider.{create,update,delete}`,
  `connector.{create,update,delete}`, `cc_pair.{create,update,delete}`,
  `api_key.{create,regenerate,delete}`, `credential.{create,update,delete}`,
  `credential.access`

> All actions in the taxonomy are wired to call sites.

### Example event

```json
{
  "audit_schema_version": "1.0",
  "ts": 1750000000.123,
  "action": "llm_provider.update",
  "ocsf_class": "api_activity",
  "outcome": "success",
  "tenant_id": "tenant_abc",
  "actor": {"user_id": "u-42", "email": "admin@example.com", "api_key_id": null, "auth_type": "oauth"},
  "resource_type": "llm_provider",
  "resource_id": "7",
  "request_id": "01J...",
  "endpoint": "PUT /admin/llm/provider",
  "source_ip": "203.0.113.5",
  "extra": null
}
```

### Credential-access events (legacy shape)

`onyx.audit.credential_access` predates the generalized schema and keeps its own
(slightly different) field set for backward compatibility with existing
consumers — notably `credential_type`, `provider`, `row_id`, `client_ip`,
`user_id` at the top level (no nested `actor`). It shares the same fail-safe
plumbing and Redis dedup as the generalized emitter. See
`backend/onyx/utils/credential_audit.py`.

## Exporting to a SIEM

Because audit events are just JSON log lines on a known logger prefix, any log
shipper works. The general pattern:

1. Run Onyx with `LOG_FORMAT=json` so the surrounding log records are structured.
2. Ship container stdout (or the `backend/log/*.log` files) with Fluent Bit /
   Vector / the CloudWatch agent / Filebeat.
3. Filter to audit events by `logger` prefix `onyx.audit` and parse the
   `message` field as JSON.

Example **Vector** transform that isolates the audit stream:

```toml
[transforms.onyx_audit]
type = "filter"
inputs = ["onyx_logs"]
condition = '''starts_with(string!(.logger), "onyx.audit")'''

[transforms.onyx_audit_parsed]
type = "remap"
inputs = ["onyx_audit"]
source = '. = parse_json!(.message)'
```

Example **Fluent Bit** grep filter:

```ini
[FILTER]
    Name    grep
    Match   onyx.*
    Regex   logger ^onyx\.audit
```

> Roadmap: a syslog/CEF formatter, an OCSF-native emitter mode, and an in-product
> `audit_event` table + read API are planned follow-ups. The JSON export path
> documented here is the supported MVP.
