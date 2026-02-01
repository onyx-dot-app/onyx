# Multi-Tenant Database Seeding Guide

This guide explains how to populate your development database with realistic multi-tenant test data.

## Overview

The `seed_multitenant_dev_db.py` script creates a realistic multi-tenant environment with:
- Multiple tenant organizations
- Admin users for each tenant
- Chat history with realistic queries and responses
- Documents with proper metadata, ACLs, and embeddings
- Vespa index population

## Prerequisites

1. **Start the multi-tenant dev environment:**

```bash
cd deployment/docker_compose
docker-compose -f docker-compose.multitenant-dev.yml up
```

Wait for all services to be healthy (especially Postgres, Vespa, and the API server).

2. **Verify the API server is accessible:**

```bash
curl http://localhost:8080/health
```

## Basic Usage

From the `backend` directory:

```bash
# Simple: Create 3 tenants with default settings
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py

# Create 5 tenants with more data
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py --tenants 5 --sessions-per-tenant 100 --docs-per-tenant 200
```

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--tenants` | 3 | Number of tenants to create |
| `--sessions-per-tenant` | 50 | Number of chat sessions per tenant |
| `--messages-per-session` | 4 | Number of messages per chat session |
| `--days-of-history` | 90 | Days to spread chat history across |
| `--docs-per-tenant` | 100 | Number of documents per tenant |
| `--chunks-per-doc` | 5 | Number of chunks per document |
| `--skip-chat` | false | Skip seeding chat history |
| `--skip-docs` | false | Skip seeding documents |
| `--api-url` | http://127.0.0.1:8080 | API server URL |

## Examples

### Quick Test Setup (Small Dataset)

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 2 \
  --sessions-per-tenant 10 \
  --docs-per-tenant 20
```

### Realistic Development Setup

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 5 \
  --sessions-per-tenant 100 \
  --messages-per-session 6 \
  --docs-per-tenant 200 \
  --chunks-per-doc 10
```

### Large Dataset for Performance Testing

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 10 \
  --sessions-per-tenant 500 \
  --docs-per-tenant 1000 \
  --chunks-per-doc 5
```

### Skip Chat History (Documents Only)

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 3 \
  --docs-per-tenant 500 \
  --skip-chat
```

### Skip Documents (Chat Only)

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 3 \
  --sessions-per-tenant 200 \
  --skip-docs
```

## What Gets Created

### Tenants

Each tenant is created with:
- A unique admin user (email: `admin_<uuid>@<company>.com`)
- Password: `TestPassword123!` (for all users)
- A dedicated schema in Postgres
- Company name from a list of realistic names

### Chat History

For each tenant:
- Chat sessions with realistic timestamps spread over the specified time period
- Alternating user/assistant messages
- Sample queries covering common topics (HR, IT, policies, etc.)
- Varied response lengths

### Documents

For each tenant:
- Documents with various types (Policy, Procedure, Guide, Report, Manual)
- Realistic metadata (department, document type, company name)
- Multiple chunks per document with embeddings
- ACL entries (user emails and groups)
- Document sets for organization
- Random boost factors for relevance testing

## Output

The script will provide detailed progress information and a final summary:

```
================================================================================
SEEDING COMPLETE!
================================================================================
Created 5 tenants:
  - Acme Corp: admin_abc123@acmecorp.com (password: TestPassword123!)
  - TechStart Inc: admin_def456@techstartinc.com (password: TestPassword123!)
  ...

Total chat sessions: 250
Total chat messages: 1000
Total documents: 500
Total chunks: 2500

You can now test multi-tenant upgrades on this populated database!
================================================================================
```

## Testing Multi-Tenant Upgrades

Once your database is seeded:

1. **Take a database snapshot:**
```bash
docker exec -it onyx-relational_db-1 pg_dump -U postgres > backup_before_upgrade.sql
```

2. **Run your upgrade/migration:**
```bash
# Your upgrade workflow here
alembic upgrade head
```

3. **Verify data integrity** for each tenant:
```bash
# Login as each tenant admin and verify:
# - Chat history is preserved
# - Documents are searchable
# - No data leakage between tenants
```

4. **Performance testing:**
```bash
# Use the populated data to test query performance
cd scripts/query_time_check
PYTHONPATH=. python test_query_times.py
```

## Troubleshooting

### "Cannot reach API server"

- Ensure multi-tenant dev environment is running
- Check that port 8080 is not blocked
- Verify docker containers are healthy: `docker ps`

### "Failed to create tenant"

- Check API server logs: `docker logs onyx-api_server-1`
- Ensure `MULTI_TENANT=true` in docker-compose
- Verify database is accessible

### "Failed to seed documents"

- Check Vespa is running: `curl http://localhost:8081/state/v1/health`
- Verify model server is up: `docker logs onyx-inference_model_server-1`
- Check available disk space

### Memory Issues

If seeding large datasets:
- Reduce `--docs-per-tenant` or `--chunks-per-doc`
- Increase Docker memory limits
- Use `--skip-docs` or `--skip-chat` to seed incrementally

## Cleaning Up

To reset the database and start fresh:

```bash
# Stop containers
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml down

# Remove volumes (WARNING: deletes all data)
docker volume rm onyx_db_volume onyx_vespa_volume

# Start fresh
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml up
```

## Advanced Usage

### Custom API URL

If your API server is running on a different host/port:

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --api-url http://my-dev-server:8080
```

### Scripted Testing

Combine with other scripts for automated testing:

```bash
#!/bin/bash
set -e

# Start environment
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml up -d

# Wait for health
sleep 30

# Seed data
cd backend
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py --tenants 5

# Run your tests
pytest tests/integration/multitenant_tests/

# Cleanup
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml down
```

## Related Scripts

- `chat_history_seeding.py` - Seed chat history for single tenant
- `query_time_check/seed_dummy_docs.py` - Seed documents for performance testing
- `tenant_cleanup/` - Tools for cleaning up tenants in production

## Notes

- All passwords are set to `TestPassword123!` for convenience
- Embeddings are randomly generated (not from actual models)
- Company names are from a predefined list
- Chat messages use templated queries and responses
- This is for **development/testing only** - do not use in production!

