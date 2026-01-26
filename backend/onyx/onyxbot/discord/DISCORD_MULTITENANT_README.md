# Discord Bot Multitenant Architecture

This document analyzes how the Discord cache manager and API client coordinate to handle multitenant API keys from a single Discord client.

## Overview

The Discord bot uses a **single-client, multi-tenant** architecture where one `OnyxDiscordClient` instance serves multiple tenants (organizations) simultaneously. Tenant isolation is achieved through:

- **Cache Manager**: Maps Discord guilds to tenants and stores per-tenant API keys
- **API Client**: Stateless HTTP client that accepts dynamic API keys per request

```
┌─────────────────────────────────────────────────────────────────────┐
│                      OnyxDiscordClient                              │
│                                                                     │
│  ┌─────────────────────────┐    ┌─────────────────────────────┐    │
│  │   DiscordCacheManager   │    │      OnyxAPIClient          │    │
│  │                         │    │                             │    │
│  │  guild_id → tenant_id   │───▶│  send_chat_message(         │    │
│  │  tenant_id → api_key    │    │    message,                 │    │
│  │                         │    │    api_key=<per-tenant>,    │    │
│  └─────────────────────────┘    │    persona_id=...           │    │
│                                 │  )                          │    │
│                                 └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Cache Manager (`backend/onyx/onyxbot/discord/cache.py`)

The `DiscordCacheManager` maintains two critical in-memory mappings:

```python
class DiscordCacheManager:
    _guild_tenants: dict[int, str]   # guild_id → tenant_id
    _api_keys: dict[str, str]        # tenant_id → api_key
    _lock: asyncio.Lock              # Concurrency control
```

#### Key Responsibilities

| Function | Purpose |
|----------|---------|
| `get_tenant(guild_id)` | O(1) lookup: guild → tenant |
| `get_api_key(tenant_id)` | O(1) lookup: tenant → API key |
| `refresh_all()` | Full cache rebuild from database |
| `refresh_guild()` | Incremental update for single guild |

#### API Key Provisioning Strategy

API keys are **lazily provisioned** - only created when first needed:

```python
async def _load_tenant_data(self, tenant_id: str) -> tuple[list[int], str | None]:
    needs_key = tenant_id not in self._api_keys

    with get_session_with_tenant(tenant_id) as db:
        # Load guild configs
        configs = get_discord_bot_configs(db)
        guild_ids = [c.guild_id for c in configs if c.enabled]

        # Only provision API key if not already cached
        api_key = None
        if needs_key:
            api_key = get_or_create_discord_service_api_key(db, tenant_id)

    return guild_ids, api_key
```

This optimization avoids repeated database calls for API key generation.

#### Concurrency Control

All write operations acquire an async lock to prevent race conditions:

```python
async def refresh_all(self) -> None:
    async with self._lock:
        # Safe to modify _guild_tenants and _api_keys
        for tenant_id in get_all_tenant_ids():
            guild_ids, api_key = await self._load_tenant_data(tenant_id)
            # Update mappings...
```

Read operations (`get_tenant`, `get_api_key`) are lock-free since Python dict lookups are atomic.

---

### 2. API Client (`backend/onyx/onyxbot/discord/api_client.py`)

The `OnyxAPIClient` is a **stateless async HTTP client** that communicates with Onyx API pods.

#### Key Design: Per-Request API Key Injection

```python
class OnyxAPIClient:
    async def send_chat_message(
        self,
        message: str,
        api_key: str,           # Injected per-request
        persona_id: int | None,
        ...
    ) -> ChatFullResponse:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",  # Tenant-specific auth
        }
        # Make request...
```

The client accepts `api_key` as a parameter to each method, enabling **dynamic tenant selection at request time**. This design allows a single client instance to serve multiple tenants:

```python
# Same client, different tenants
await api_client.send_chat_message(msg, api_key=key_for_tenant_1, ...)
await api_client.send_chat_message(msg, api_key=key_for_tenant_2, ...)
```

---

## Coordination Flow

### Message Processing Pipeline

When a Discord message arrives, the client coordinates cache and API client:

```python
async def on_message(self, message: Message) -> None:
    guild_id = message.guild.id

    # Step 1: Cache lookup - guild → tenant
    tenant_id = self.cache.get_tenant(guild_id)
    if not tenant_id:
        return  # Guild not registered

    # Step 2: Cache lookup - tenant → API key
    api_key = self.cache.get_api_key(tenant_id)
    if not api_key:
        logger.warning(f"No API key for tenant {tenant_id}")
        return

    # Step 3: API call with tenant-specific credentials
    await process_chat_message(
        message=message,
        api_key=api_key,              # Tenant-specific
        persona_id=persona_id,         # Tenant-specific
        api_client=self.api_client,
    )
```

### Startup Sequence

```python
async def setup_hook(self) -> None:
    # 1. Initialize API client (create aiohttp session)
    await self.api_client.initialize()

    # 2. Populate cache with all tenants
    await self.cache.refresh_all()

    # 3. Start background refresh task
    self._cache_refresh_task = self.loop.create_task(
        self._periodic_cache_refresh()  # Every 60 seconds
    )
```

### Shutdown Sequence

```python
async def close(self) -> None:
    # 1. Cancel background refresh
    if self._cache_refresh_task:
        self._cache_refresh_task.cancel()

    # 2. Close Discord connection
    await super().close()

    # 3. Close API client session
    await self.api_client.close()

    # 4. Clear cache
    self.cache.clear()
```

---

## Tenant Isolation Mechanisms

### 1. Per-Tenant API Keys

Each tenant has a dedicated service API key:

```python
# backend/onyx/db/discord_bot.py
def get_or_create_discord_service_api_key(db_session: Session, tenant_id: str) -> str:
    existing = get_discord_service_api_key(db_session)
    if existing:
        return regenerate_key(existing)

    # Create LIMITED role key (chat-only permissions)
    return insert_api_key(
        db_session=db_session,
        api_key_args=APIKeyArgs(
            name=DISCORD_SERVICE_API_KEY_NAME,
            role=UserRole.LIMITED,  # Minimal permissions
        ),
        user_id=None,  # Service account (system-owned)
    ).api_key
```

### 2. Database Context Variables

The cache uses context variables for proper tenant-scoped DB sessions:

```python
context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
try:
    with get_session_with_tenant(tenant_id) as db:
        # All DB operations scoped to this tenant
        ...
finally:
    CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
```

### 3. Enterprise Gating Support

Gated tenants are filtered during cache refresh:

```python
gated_tenants = fetch_ee_implementation_or_noop(
    "onyx.server.tenants.product_gating",
    "get_gated_tenants",
    set(),
)()

for tenant_id in get_all_tenant_ids():
    if tenant_id in gated_tenants:
        continue  # Skip gated tenants
```

---

## Cache Refresh Strategy

| Trigger | Method | Scope |
|---------|--------|-------|
| Startup | `refresh_all()` | All tenants |
| Periodic (60s) | `refresh_all()` | All tenants |
| Guild registration | `refresh_guild()` | Single tenant |

### Error Handling

- **Tenant-level errors**: Logged and skipped (doesn't stop other tenants)
- **Missing API key**: Bot silently ignores messages from that guild
- **Network errors**: Logged, cache continues with stale data until next refresh

---

## Key Design Insights

1. **Single Client, Multiple Tenants**: One `OnyxAPIClient` and one `DiscordCacheManager` instance serves all tenants via dynamic API key injection.

2. **Cache-First Architecture**: Guild lookups are O(1) in-memory; API keys are cached after first provisioning to avoid repeated DB calls.

3. **Graceful Degradation**: If an API key is missing or stale, the bot simply doesn't respond (no crash or error propagation).

4. **Thread Safety Without Blocking**: `asyncio.Lock` prevents race conditions while maintaining async concurrency for reads.

5. **Lazy Provisioning**: API keys are only created when first needed, then cached for performance.

6. **Stateless API Client**: The HTTP client holds no tenant state - all tenant context is injected per-request via the `api_key` parameter.

---

## File References

| Component | Path |
|-----------|------|
| Cache Manager | `backend/onyx/onyxbot/discord/cache.py` |
| API Client | `backend/onyx/onyxbot/discord/api_client.py` |
| Discord Client | `backend/onyx/onyxbot/discord/client.py` |
| API Key DB Operations | `backend/onyx/db/discord_bot.py` |
| Cache Manager Tests | `backend/tests/unit/onyx/onyxbot/discord/test_cache_manager.py` |
| API Client Tests | `backend/tests/unit/onyx/onyxbot/discord/test_api_client.py` |