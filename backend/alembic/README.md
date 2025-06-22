<!-- ONYX_METADATA={"link": "https://github.com/onyx-dot-app/onyx/blob/main/backend/alembic/README.md"} -->

# Alembic DB Migrations

These files are for creating/updating the tables in the Relational DB (Postgres).
Onyx migrations use a generic single-database configuration with an async dbapi.

## To generate new migrations:

run from onyx/backend:
`alembic revision --autogenerate -m <DESCRIPTION_OF_MIGRATION>`

More info can be found here: https://alembic.sqlalchemy.org/en/latest/autogenerate.html

## Running migrations

To run all un-applied migrations:
`alembic upgrade head`

To undo migrations:
`alembic downgrade -X`
where X is the number of migrations you want to undo from the current state

### Multi-tenant migrations

For multi-tenant deployments, you can use additional options:

**Upgrade all tenants:**
```bash
alembic -x upgrade_all_tenants=true upgrade head
```

**Upgrade a specific tenant schema:**
```bash
alembic -x schema=tenant_12345678-1234-1234-1234-123456789012 upgrade head
```

**Upgrade tenants within a numeric range (based on first 8 hex digits of UUID):**
```bash
# Upgrade tenants with IDs from 100 to 200 (inclusive)
alembic -x upgrade_all_tenants=true -x tenant_range_start=100 -x tenant_range_end=200 upgrade head

# Upgrade tenants with IDs >= 1000
alembic -x upgrade_all_tenants=true -x tenant_range_start=1000 upgrade head

# Upgrade tenants with IDs <= 500
alembic -x upgrade_all_tenants=true -x tenant_range_end=500 upgrade head
```

**Continue on error (for batch operations):**
```bash
alembic -x upgrade_all_tenants=true -x continue=true upgrade head
```

The tenant range filtering works by converting the first 8 hexadecimal characters of the tenant UUID to an integer. For example:
- `tenant_00000064-1234-...` → 100 (0x64 = 100)
- `tenant_000000c8-1234-...` → 200 (0xc8 = 200)
- `tenant_12345678-1234-...` → 305419896 (0x12345678 = 305419896)
