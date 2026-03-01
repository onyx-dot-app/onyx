# Onyx Data Backup & Restore Scripts

Scripts for backing up and restoring PostgreSQL, Vespa, and MinIO data from an Onyx deployment.

## Overview

Two backup modes are supported:

| Mode | Description | Pros | Cons |
|------|-------------|------|------|
| **volume** | Exports Docker volumes directly | Fast, complete, preserves everything | Services must be stopped for consistency |
| **api** | Uses pg_dump and Vespa REST API | Services can stay running, more portable | Slower for large datasets |

## Quick Start

### Backup (from a running instance)

```bash
# Full backup using volume mode (recommended for complete backups)
# Note: For consistency, stop services first
docker compose -f deployment/docker_compose/docker-compose.yml stop
./scripts/dump_data.sh --mode volume --output ./backups
docker compose -f deployment/docker_compose/docker-compose.yml start

# Or use API mode (services can stay running)
./scripts/dump_data.sh --mode api --output ./backups
```

### Restore (to a local instance)

```bash
# Restore from latest backup
./scripts/restore_data.sh --input ./backups/latest

# Restore from specific backup
./scripts/restore_data.sh --input ./backups/20240115_120000

# Force restore without confirmation
./scripts/restore_data.sh --input ./backups/latest --force
```

## Detailed Usage

### dump_data.sh

```
Usage: ./scripts/dump_data.sh [OPTIONS]

Options:
  --mode <volume|api>     Backup mode (default: volume)
  --output <dir>          Output directory (default: ./onyx_backup)
  --project <name>        Docker Compose project name (default: onyx)
  --postgres-only         Only backup PostgreSQL
  --vespa-only            Only backup Vespa
  --minio-only            Only backup MinIO
  --no-minio              Skip MinIO backup
  --help                  Show help message
```

**Examples:**

```bash
# Default volume backup
./scripts/dump_data.sh

# API-based backup
./scripts/dump_data.sh --mode api

# Only backup PostgreSQL
./scripts/dump_data.sh --postgres-only --mode api

# Custom output directory
./scripts/dump_data.sh --output /mnt/backups/onyx

# Different project name (if using custom docker compose project)
./scripts/dump_data.sh --project my-onyx-instance
```

### restore_data.sh

```
Usage: ./scripts/restore_data.sh [OPTIONS]

Options:
  --input <dir>           Backup directory (required)
  --project <name>        Docker Compose project name (default: onyx)
  --postgres-only         Only restore PostgreSQL
  --vespa-only            Only restore Vespa
  --minio-only            Only restore MinIO
  --no-minio              Skip MinIO restore
  --force                 Skip confirmation prompts
  --help                  Show help message
```

**Examples:**

```bash
# Restore all components
./scripts/restore_data.sh --input ./onyx_backup/latest

# Restore only PostgreSQL
./scripts/restore_data.sh --input ./onyx_backup/latest --postgres-only

# Non-interactive restore
./scripts/restore_data.sh --input ./onyx_backup/latest --force
```

## Backup Directory Structure

After running a backup, the output directory contains:

```
onyx_backup/
├── 20240115_120000/           # Timestamp-named backup
│   ├── metadata.json          # Backup metadata
│   ├── postgres_volume.tar.gz # PostgreSQL data (volume mode)
│   ├── postgres_dump.backup   # PostgreSQL dump (api mode)
│   ├── vespa_volume.tar.gz    # Vespa data (volume mode)
│   ├── vespa_documents.jsonl  # Vespa documents (api mode)
│   ├── minio_volume.tar.gz    # MinIO data (volume mode)
│   └── minio_data.tar.gz      # MinIO data (api mode)
└── latest -> 20240115_120000  # Symlink to latest backup
```

## Environment Variables

You can customize behavior with environment variables:

```bash
# PostgreSQL settings
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=password
export POSTGRES_DB=postgres
export POSTGRES_PORT=5432

# Vespa settings
export VESPA_HOST=localhost
export VESPA_PORT=8081
export VESPA_INDEX=danswer_index
```

## Typical Workflows

### Migrate to a new server

```bash
# On source server
./scripts/dump_data.sh --mode volume --output ./migration_backup
tar czf onyx_backup.tar.gz ./migration_backup/latest

# Transfer to new server
scp onyx_backup.tar.gz newserver:/opt/onyx/

# On new server
cd /opt/onyx
tar xzf onyx_backup.tar.gz
./scripts/restore_data.sh --input ./migration_backup/latest --force
docker compose up -d
```

### Create a development copy from production

```bash
# On production (use API mode to avoid downtime)
./scripts/dump_data.sh --mode api --output ./prod_backup

# Copy to dev machine
rsync -avz ./prod_backup/latest dev-machine:/home/dev/onyx_backup/

# On dev machine
./scripts/restore_data.sh --input /home/dev/onyx_backup --force
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### Scheduled backups (cron)

```bash
# Add to crontab: crontab -e
# Daily backup at 2 AM
0 2 * * * cd /opt/onyx && ./scripts/dump_data.sh --mode api --output /backups/onyx >> /var/log/onyx-backup.log 2>&1

# Weekly cleanup (keep last 7 days)
0 3 * * 0 find /backups/onyx -maxdepth 1 -type d -mtime +7 -exec rm -rf {} \;
```

## Troubleshooting

### "Volume not found" error

Ensure the Docker Compose project name matches:
```bash
docker volume ls | grep db_volume
# If it shows "myproject_db_volume", use --project myproject
```

### "Container not running" error (API mode)

Start the required services:
```bash
cd deployment/docker_compose
docker compose up -d relational_db index minio
```

### Vespa restore fails with "not ready"

Vespa takes time to initialize. Wait and retry:
```bash
# Check Vespa health
curl http://localhost:8081/state/v1/health
```

### PostgreSQL restore shows warnings

`pg_restore` often shows warnings about objects that don't exist (when using `--clean`). These are usually safe to ignore if the restore completes.

## Alternative: Python Script

For more control, you can also use the existing Python script:

```bash
cd backend

# Save state
python -m scripts.save_load_state --save --checkpoint_dir ../onyx_checkpoint

# Load state
python -m scripts.save_load_state --load --checkpoint_dir ../onyx_checkpoint
```

See `backend/scripts/save_load_state.py` for the Python implementation.
