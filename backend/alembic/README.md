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

**Upgrade specific schemas:**
```bash
# Single schema
alembic -x schemas=tenant_12345678-1234-1234-1234-123456789012 upgrade head

# Multiple schemas (comma-separated)
alembic -x schemas=tenant_12345678-1234-1234-1234-123456789012,public,another_tenant upgrade head
```

**Upgrade tenants within an alphabetical range:**
```bash
# Upgrade tenants 100-200 when sorted alphabetically (positions 100 to 200)
alembic -x upgrade_all_tenants=true -x tenant_range_start=100 -x tenant_range_end=200 upgrade head

# Upgrade tenants starting from position 1000 alphabetically
alembic -x upgrade_all_tenants=true -x tenant_range_start=1000 upgrade head

# Upgrade first 500 tenants alphabetically
alembic -x upgrade_all_tenants=true -x tenant_range_end=500 upgrade head
```

**Continue on error (for batch operations):**
```bash
alembic -x upgrade_all_tenants=true -x continue=true upgrade head
```

The tenant range filtering works by:
1. Sorting tenant IDs alphabetically
2. Using 1-based position numbers (1st, 2nd, 3rd tenant, etc.)
3. Filtering to the specified range of positions
4. Non-tenant schemas (like 'public') are always included
