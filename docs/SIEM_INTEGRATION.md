# Onyx Audit Logging & SIEM Integration

Onyx emits a **normalized, structured audit-event stream** for security-relevant
activity. Every event is a single JSON object on a dedicated audit log channel,
so you can forward it into your existing SIEM — **Splunk, Microsoft Sentinel,
Elastic, Google Chronicle, AWS Security Lake** — with no Onyx-specific
integration to build and maintain. You point your log shipper at Onyx's output,
filter to the audit channel, and parse the JSON.

The schema and event taxonomy are shaped toward **OCSF** (the Open Cybersecurity
Schema Framework), so events map cleanly onto the categories your SIEM already
understands.

## What gets audited

Onyx records security-relevant actions across four areas. Each event captures
**who** did it (user / API key, with email and auth method), **what** they acted
on (resource type + id), the **outcome** (success / failure / denied), the
**tenant**, the originating **client IP**, and a **request id** that correlates
the event with the rest of that request's logs.

| Category | Events |
|---|---|
| **Authentication** | login, login failure, logout, registration, password-reset request, email verification |
| **Access control** | user role change, deactivate, reactivate, delete |
| **Admin configuration** | LLM provider create/update/delete; connector create/update/delete; connector-credential link create/update/delete; API key create/regenerate/delete |
| **Credentials** | create, update, delete, **and every decrypt/access** of a stored credential |

> Credential **access** events are notable: Onyx logs each time a stored secret
> is decrypted for use, attributed to the actor and tenant — without ever
> logging the secret value. This is the kind of trail that catches credential
> misuse that infrastructure-level tooling can't see.

## What an event looks like

```json
{
  "audit_schema_version": "1.0",
  "ts": 1750000000.123,
  "action": "user.role_change",
  "ocsf_class": "account_change",
  "outcome": "success",
  "tenant_id": "tenant_abc",
  "actor": { "user_id": "u-42", "email": "admin@example.com", "auth_type": "oauth" },
  "resource_type": "user",
  "resource_id": "u-99",
  "request_id": "01J...",
  "endpoint": "PATCH /manage/set-user-role",
  "source_ip": "203.0.113.5",
  "extra": { "target_email": "bob@example.com", "old_role": "basic", "new_role": "admin" }
}
```

Field highlights:

- **`action`** — a stable `<domain>.<verb>` value (e.g. `auth.login`,
  `llm_provider.update`, `credential.access`). These are an append-only contract
  you can safely build dashboards and alerts against.
- **`ocsf_class`** — `authentication`, `account_change`, or `api_activity`, so
  you can route by OCSF category.
- **`outcome`** — `success`, `failure`, or `denied` (a `denied` is an
  authentication/authorization refusal, distinct from an operational error).
- **`actor`** — never contains a secret; an `api_key_id` is the key's identifier,
  never its value.
- **`extra`** — additional non-secret context relevant to the specific action.

## How to enable and forward it

1. **Run Onyx with `LOG_FORMAT=json`.** This makes all log records structured and
   promotes tenant/request context to top-level fields. (Audit event bodies are
   already self-contained JSON regardless of this setting.)
2. **Ship Onyx's logs** (container stdout, or the on-disk log files) with your
   collector of choice — Fluent Bit, Vector, the CloudWatch agent, Filebeat, the
   Azure Monitor agent, etc.
3. **Filter to the audit channel** by the logger-name prefix **`onyx.audit`**,
   and parse each record's `message` as JSON.

Drop-in shipper configurations for **Splunk (HEC)**, **Microsoft Sentinel
(Azure Monitor)**, **Elastic (Filebeat)**, **Vector**, and **Fluent Bit** are in
the engineering reference, [`AUDIT_LOGGING.md`](./AUDIT_LOGGING.md).

The audit channel is split into sub-channels by OCSF class
(`onyx.audit.authentication`, `onyx.audit.account_change`,
`onyx.audit.api_activity`, `onyx.audit.credential_access`) if you prefer to route
categories to different indexes.

## Reliability guarantees

- **Never disrupts the application.** Audit emission sits on request and indexing
  hot paths and is fully fail-safe — a failure to gather context or write a log
  is swallowed, never raised into the user's request.
- **No silent drops from infrastructure trouble.** High-volume event classes are
  de-duplicated through Redis within a short window; if Redis is unavailable,
  emission falls back to always-emit rather than dropping events.
- **Tenant-tagged.** Every event carries its tenant, so multi-tenant deployments
  can segregate audit trails per customer.

## Compliance mapping

The audit stream directly supports common control requirements:

- **SOC 2** — CC7 (system monitoring).
- **FedRAMP / NIST 800-53 AU family** — AU-2 (auditable events), AU-3 (content of
  audit records), AU-6 (review/analysis), AU-12 (audit generation).

Because the events are normalized and exportable, the review/retention/alerting
controls (AU-6, AU-11) are satisfied by your SIEM's existing capabilities.

## Scope today, and what's on the roadmap

**Available now:** the full audit-event stream described above, exportable to any
SIEM via standard log forwarding, with the schema and shipper configs documented.

**On the roadmap (ask if any are a requirement for your deployment):**

- An in-product audit viewer with a queryable `audit_event` store and retention
  controls (today the trail is exported to your SIEM, not browsed inside Onyx).
- A native **syslog/CEF** formatter and a full **OCSF-envelope** emitter mode for
  SIEMs that prefer those wire formats over JSON.
- Optional high-volume **document-access** auditing, gated behind a flag for
  customers with AU-level data-access requirements.
