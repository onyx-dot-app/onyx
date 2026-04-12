# Nuclear Reset Script - Improvements

## Overview

The improved `nuclear_reset_improved.sh` script provides a comprehensive database and system reset for clean testing environments, with enhanced features for production-like deployments (nginx, RDS, etc.).

## Key Improvements

### 1. **Flexible Configuration**
- **Command-line arguments** for all options (no need to edit script)
- **Custom compose file** support (`-c` flag)
- **Custom env file** support (`-f` flag)
- **Environment variable detection** for both IAM auth and password auth

### 2. **Comprehensive Reset Options**

| Component | Flag | Description |
|-----------|------|-------------|
| PostgreSQL | (always) | Drops all schemas and recreates clean |
| Redis | `--no-redis` | Flushes all cache data (default: enabled) |
| Vespa | `--no-vespa` | Deletes all indexed documents (default: enabled) |
| OpenSearch | `--reset-opensearch` | Deletes all indices (default: disabled) |

### 3. **Safety Features**
- **Dry run mode** (`--dry-run`) - see what will happen without executing
- **Interactive confirmation** (unless `-y` flag is used)
- **Clear warning messages** with color-coded output
- **Service health checks** before operations
- **Error handling** with proper exit codes

### 4. **Automation**
- **Automatic service restart** after reset (configurable with `--no-restart`)
- **Migration monitoring** - waits for migrations to complete
- **Health checks** - ensures services are ready before proceeding
- **Optional admin user seeding** (disabled with `--no-seed`)

### 5. **Production Deployment Support**
- **IAM authentication** support for RDS
- **SSL/TLS connection** handling
- **Works with docker-compose.prod-aws.yml** by default
- **Environment-aware** - detects `MULTI_TENANT`, `USE_IAM_AUTH`, etc.

### 6. **Better User Experience**
- **Comprehensive help** (`-h` flag)
- **Color-coded output** (green=success, yellow=warning, red=error)
- **Progress indicators** for long-running operations
- **Summary report** at the end
- **Clear next steps** after completion

## Usage Examples

### Basic Usage

```bash
# Interactive reset with all defaults
./backend/scripts/nuclear_reset_improved.sh

# Non-interactive (CI/CD)
./backend/scripts/nuclear_reset_improved.sh --yes

# See what would happen (dry run)
./backend/scripts/nuclear_reset_improved.sh --dry-run
```

### Advanced Usage

```bash
# Reset everything including OpenSearch
./backend/scripts/nuclear_reset_improved.sh --reset-opensearch --yes

# Reset only database, skip cache/index cleanup
./backend/scripts/nuclear_reset_improved.sh --no-redis --no-vespa

# Custom compose file for local development
./backend/scripts/nuclear_reset_improved.sh \
  -c deployment/docker_compose/docker-compose.dev.yml \
  -f deployment/docker_compose/.env

# Manual restart (for debugging)
./backend/scripts/nuclear_reset_improved.sh --no-restart --yes
```

### Production-like Testing

```bash
# Full reset on EC2 with RDS
./backend/scripts/nuclear_reset_improved.sh \
  -c deployment/docker_compose/docker-compose.prod-aws.yml \
  --reset-opensearch \
  --yes
```

## Deployment Workflow on EC2

### Step 1: Upload Script to EC2

```bash
# From your local machine
scp -i ~/.ssh/ai-dev-ed25519 \
  backend/scripts/nuclear_reset_improved.sh \
  ubuntu@<EC2_IP>:/opt/onyx/backend/scripts/

# Make executable on EC2
ssh -i ~/.ssh/ai-dev-ed25519 ubuntu@<EC2_IP> \
  "chmod +x /opt/onyx/backend/scripts/nuclear_reset_improved.sh"
```

### Step 2: Run Reset on EC2

```bash
# SSH to EC2
ssh -i ~/.ssh/ai-dev-ed25519 ubuntu@<EC2_IP>

# Navigate to onyx directory
cd /opt/onyx

# Run reset (dry run first to verify)
./backend/scripts/nuclear_reset_improved.sh --dry-run

# Execute reset
./backend/scripts/nuclear_reset_improved.sh --yes
```

### Step 3: Verify Services

```bash
# Check service status
docker compose -f deployment/docker_compose/docker-compose.prod-aws.yml ps

# Check API health
curl http://localhost:8080/health

# Check web interface (through nginx)
curl http://localhost:3000
```

## What Gets Reset

### PostgreSQL Database
```sql
-- Terminates all active connections
-- Drops all tenant schemas (if MULTI_TENANT=true)
-- Drops public schema CASCADE
-- Recreates public schema
-- Runs alembic migrations (via api_server restart)
-- Creates fresh alembic_version table
```

### Redis Cache (if enabled)
```bash
# Executes FLUSHALL
# Clears all keys across all databases
```

### Vespa Index (if enabled)
```bash
# Deletes all documents
# Index schema remains (defined by application)
```

### OpenSearch (if enabled)
```bash
# Deletes all indices
# Cluster remains configured
```

## Configuration Detection

The script automatically detects your environment:

```bash
# Checks for IAM authentication
USE_IAM_AUTH=true  → Generates IAM token for RDS

# Checks for SSL requirement
POSTGRES_REQUIRE_SSL=true  → Uses sslmode=require

# Checks for multi-tenant mode
MULTI_TENANT=true  → Drops tenant schemas

# Checks for auth type
AUTH_TYPE=basic  → Suggests manual user creation
```

## Comparison with Original Script

| Feature | Original | Improved |
|---------|----------|----------|
| Command-line args | ❌ | ✅ Full support |
| Dry run mode | ❌ | ✅ `--dry-run` |
| Redis reset | ❌ | ✅ Optional |
| Vespa reset | ❌ | ✅ Optional |
| OpenSearch reset | ❌ | ✅ Optional |
| Auto restart | ❌ | ✅ Configurable |
| Migration monitoring | ❌ | ✅ Waits for completion |
| Health checks | ❌ | ✅ Before operations |
| Error handling | Basic | ✅ Comprehensive |
| Color output | ❌ | ✅ Yes |
| Help documentation | ❌ | ✅ `-h` flag |
| Hardcoded compose file | ✅ | ❌ Configurable |
| IAM auth support | ✅ | ✅ Enhanced |
| Password auth support | ❌ | ✅ Yes |

## Troubleshooting

### Script fails with "IAM token error"

```bash
# Verify IAM role has rds-db:connect permission
aws sts get-caller-identity

# Verify RDS resource ID
aws rds describe-db-instances \
  --db-instance-identifier onyx-sensitive-test-postgres \
  --query 'DBInstances[0].DbiResourceId'
```

### Services don't start after reset

```bash
# Check logs
docker compose -f deployment/docker_compose/docker-compose.prod-aws.yml logs api_server

# Manually run migrations
docker compose -f deployment/docker_compose/docker-compose.prod-aws.yml \
  exec api_server alembic upgrade head
```

### Redis flush fails

```bash
# Check if Redis is running
docker compose -f deployment/docker_compose/docker-compose.prod-aws.yml ps cache

# Manually flush
docker compose -f deployment/docker_compose/docker-compose.prod-aws.yml \
  exec cache redis-cli FLUSHALL
```

### Vespa reset fails

```bash
# Check Vespa health
curl http://localhost:8081/state/v1/health

# Manually delete documents
docker compose -f deployment/docker_compose/docker-compose.prod-aws.yml \
  exec index vespa-visit --remove
```

## Integration with CI/CD

```bash
#!/bin/bash
# Example CI/CD integration

# Run tests with fresh database
./backend/scripts/nuclear_reset_improved.sh --yes --no-seed

# Run your test suite
pytest backend/tests/integration

# Cleanup
./backend/scripts/nuclear_reset_improved.sh --yes
```

## Future Enhancements

Potential additions for future versions:

1. **Backup before reset** - Optional snapshot creation
2. **Partial reset** - Reset only specific schemas/services
3. **Migration rollback** - Roll back to specific migration
4. **Data seeding** - Load sample data after reset
5. **Pre-reset hooks** - Custom scripts before reset
6. **Post-reset hooks** - Custom scripts after reset
7. **Parallel execution** - Reset services concurrently
8. **Remote execution** - SSH support for remote resets
9. **Logging** - Detailed logs to file
10. **Notification** - Slack/email on completion

## Best Practices

1. **Always use `--dry-run` first** on production-like environments
2. **Backup important data** before running (even in dev/test)
3. **Run during maintenance windows** if services are live
4. **Monitor logs** after reset for migration issues
5. **Verify services** before declaring success
6. **Document custom flags** in your deployment docs
7. **Test the script** on a non-critical environment first

## Script Location

The improved script is located at:
```
backend/scripts/nuclear_reset_improved.sh
```

The original script remains at:
```
backend/scripts/nuclear_reset.sh
```

Both scripts are available for different use cases.
