# Onyx DigitalOcean Deployment Guide

Comprehensive guide for deploying Onyx to a DigitalOcean Ubuntu 24.04 VPS.

## Deployment Details

- **Domain**: klugermax.com
- **Droplet IP**: 45.55.68.178
- **SSL Email**: robimoller@gmail.com
- **Environment Type**: Sandbox (low traffic, development/testing)
- **Architecture**: All services on single VPS with Docker Compose

## Prerequisites Checklist

Before starting deployment, verify:

- [ ] DigitalOcean droplet created (Ubuntu 24.04)
- [ ] SSH access to droplet confirmed
- [ ] Domain name purchased and ready
- [ ] Domain A record pointing to droplet IP (45.55.68.178)
- [ ] You have the deployment scripts from this repository

## Step 1: Prepare Domain DNS

**IMPORTANT**: Complete this BEFORE starting deployment. The Let's Encrypt SSL certificate requires DNS to be set up.

### Update Your Domain's A Record

1. Go to your domain registrar's DNS management (e.g., GoDaddy, Namecheap, Route53)
2. Find the DNS records section
3. Create/Update an **A Record**:
   - **Host/Name**: `@` (root domain)
   - **Type**: A
   - **Value**: `45.55.68.178`
   - **TTL**: 3600 (or default)
4. Save changes

### Verify DNS Propagation

```bash
# On your local machine, check if DNS is resolving
nslookup klugermax.com
# Should return: 45.55.68.178

# Or use dig
dig klugermax.com
# Should show the IP address
```

DNS can take 5-15 minutes to propagate. Continue while waiting.

---

## Step 2: Connect to Your Droplet

```bash
# SSH into your droplet
ssh root@45.55.68.178

# Or if you set up a non-root user
ssh ubuntu@45.55.68.178

# Once connected, verify Ubuntu version
cat /etc/os-release | grep PRETTY_NAME
# Should show: Ubuntu 24.04 LTS
```

---

## Step 3: Run the Deployment Script

The deployment script automates the entire setup process.

### Option A: Download and Run (Recommended)

```bash
# On your droplet, download the deployment script
curl -O https://raw.githubusercontent.com/HOP-RAG/HOP/main/deploy-digitalocean.sh
chmod +x deploy-digitalocean.sh

# Run the deployment
./deploy-digitalocean.sh
```

### Option B: Clone Repository First

```bash
# Clone the HOP repository
git clone https://github.com/HOP-RAG/HOP.git
cd HOP

# Make script executable and run
chmod +x deploy-digitalocean.sh
./deploy-digitalocean.sh
```

### What the Script Does

The deployment script executes in 9 phases:

1. **Install Docker & Dependencies** (3-5 minutes)
   - Updates system packages
   - Installs Docker Engine and Docker Compose
   - Enables Docker daemon
   - Adds current user to docker group

2. **Clone Repository** (1-2 minutes)
   - Clones Onyx from GitHub
   - Or pulls latest if already cloned

3. **Create Data Directories** (seconds)
   - Creates persistent volume directories:
     - `postgres_data/` - PostgreSQL database
     - `redis_data/` - Redis cache
     - `vespa_data/` - Vector database
     - `minio_data/` - S3-compatible storage
     - `nginx_logs/` - Reverse proxy logs

4. **Configure Environment** (seconds)
   - Creates `.env` file with:
     - Database credentials
     - Service connection strings
     - SSL/TLS settings
     - MinIO S3 configuration
     - Embedding model settings

5. **Set Up Docker Compose** (seconds)
   - Uses production-ready docker-compose configuration
   - Includes all services (API, frontend, workers, databases)

6. **Pull Docker Images** (5-15 minutes)
   - Downloads container images from registry
   - Download size: ~3-4 GB depending on caching

7. **Start Services** (1-2 minutes)
   - Launches all containers in background
   - Services start in dependency order

8. **Verify Health** (30 seconds)
   - Checks that containers are running
   - Validates basic connectivity

9. **Run Migrations** (1-2 minutes)
   - Initializes database schema
   - Creates tables and indexes
   - Runs any pending Alembic migrations

**Total Time**: 15-30 minutes (mostly depends on internet speed for pulling images)

---

## Step 4: Monitor the Deployment

While the script runs, you can monitor progress in another terminal:

```bash
# Watch all service logs
cd /opt/onyx
sudo docker-compose logs -f

# Watch specific service (e.g., backend)
sudo docker-compose logs -f backend

# Watch only recent logs
sudo docker-compose logs --tail=50 -f
```

### Expected Log Output

**Backend initializing**:
```
backend_1 | INFO:     Uvicorn running on http://0.0.0.0:8080
backend_1 | INFO:     Application startup complete
```

**Model Server ready**:
```
inference_model_server_1 | INFO:     Application startup complete
```

**Frontend ready**:
```
web_1 | ready - started server on 0.0.0.0:3000, url: http://localhost:3000
```

---

## Step 5: Verify Deployment Success

Once the deployment script completes, run the verification script:

```bash
cd /opt/onyx
chmod +x ../verify-deployment.sh
../verify-deployment.sh
```

This checks:
- ✓ All Docker containers running
- ✓ Backend API responding (port 8080)
- ✓ Model Server responding (port 9000)
- ✓ Frontend responding (port 3000)
- ✓ PostgreSQL database connectivity
- ✓ Redis cache connectivity
- ✓ DNS resolution
- ✓ SSL certificate validity
- ✓ Database migrations completed

All checks should show green checkmarks (✓).

---

## Step 6: Access Your Onyx Instance

### Wait for DNS (First Time Only)

If you just updated DNS, wait 5-15 minutes for propagation:

```bash
# Keep checking until it resolves to your droplet IP
watch -n 5 'nslookup klugermax.com'
```

### First Access

```bash
# Once DNS is propagated:
https://klugermax.com

# HTTP automatically redirects to HTTPS
http://klugermax.com → https://klugermax.com
```

The Nginx reverse proxy:
- Handles SSL/TLS termination
- Routes requests to backend services
- Manages Let's Encrypt certificate renewal

### SSL Certificate Status

```bash
# Check certificate details
openssl s_client -connect klugermax.com:443 </dev/null 2>/dev/null | \
  openssl x509 -noout -text | grep -A2 "Not Before\|Not After"

# Or use certbot
sudo docker-compose exec -T certbot certbot certificates
```

---

## Step 7: Initialize Admin User

Access the web interface and create an admin user:

1. Visit https://klugermax.com
2. Click "Create Account"
3. Enter credentials for admin user
4. Log in

Alternatively, create user via API:

```bash
curl -X POST https://klugermax.com/api/admin/create-user \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "admin@example.com",
    "password": "secure-password",
    "name": "Admin User"
  }'
```

---

## Step 8: Verify Core Functionality

Once logged in, verify:

1. **Dashboard Access**: Check that you can see the main dashboard
2. **Create a Connector**: Go to Admin → Connectors and add a test connector
3. **Upload a Document**: Upload a test document to verify indexing
4. **Search**: Verify document appears in search results
5. **Background Jobs**: Check that Celery workers are processing tasks
   ```bash
   sudo docker-compose logs -f background
   ```

---

## Ongoing Operations

### View Logs

```bash
# All services
cd /opt/onyx && sudo docker-compose logs -f

# Specific service
sudo docker-compose logs -f backend
sudo docker-compose logs -f web
sudo docker-compose logs -f background

# Last N lines
sudo docker-compose logs --tail=100 backend
```

### Check Service Status

```bash
cd /opt/onyx && sudo docker-compose ps
```

### Restart Services

```bash
cd /opt/onyx

# Restart all services
sudo docker-compose restart

# Restart specific service
sudo docker-compose restart backend
```

### Stop Services

```bash
cd /opt/onyx && sudo docker-compose down
```

### Update Environment Variables

```bash
# Edit the .env file
cd /opt/onyx && sudo nano .env

# Restart services to apply changes
sudo docker-compose restart
```

### Database Access

```bash
# Connect to PostgreSQL
sudo docker exec -it onyx-relational_db-1 psql -U postgres -d onyx

# Example queries
SELECT version();
\dt  -- list all tables
```

### Redis Access

```bash
# Connect to Redis CLI
sudo docker exec -it onyx-redis-1 redis-cli

# Check memory usage
INFO memory

# Monitor commands in real-time
MONITOR
```

---

## Monitoring & Maintenance

### Disk Space

```bash
# Check disk usage
df -h /opt/onyx

# Clean up old Docker images
sudo docker image prune -a --filter "until=720h"
```

### Database Backups

```bash
# Backup PostgreSQL database
sudo docker exec onyx-relational_db-1 pg_dump -U postgres onyx > onyx_backup.sql

# Restore from backup
sudo docker exec -i onyx-relational_db-1 psql -U postgres onyx < onyx_backup.sql
```

### View Service Statistics

```bash
# CPU and memory usage per container
sudo docker stats

# Network statistics
sudo docker ps --format "table {{.Names}}\t{{.Status}}"
```

---

## Troubleshooting

### Services Not Starting

```bash
# Check why a service failed to start
sudo docker-compose logs backend

# Common issues:
# - Port already in use: Change port mappings
# - Out of memory: Increase droplet resources
# - Disk full: Clean up Docker images/containers
```

### Backend Not Responding

```bash
# Check backend logs
sudo docker-compose logs -f backend

# Verify database connectivity
sudo docker-compose logs -f relational_db

# Common causes:
# - Database not running
# - Invalid DATABASE_URL in .env
# - Migration failure
```

### SSL Certificate Issues

```bash
# Check certificate status
sudo docker-compose exec -T certbot certbot certificates

# Renew certificate manually
sudo docker-compose exec -T certbot certbot renew

# Check Nginx logs
sudo docker-compose logs nginx
```

### DNS Not Resolving

```bash
# Verify A record is set correctly
nslookup klugermax.com

# Check DNS propagation (may take 5-15 minutes)
watch -n 5 'nslookup klugermax.com'

# Test from droplet
curl -I https://klugermax.com
```

### Out of Memory / Slow Performance

```bash
# Check resource usage
sudo docker stats

# Reduce worker concurrency in .env if needed
USE_LIGHTWEIGHT_BACKGROUND_WORKER=true
```

---

## Configuration Reference

### Key Environment Variables

Located in `/opt/onyx/.env`:

```env
# Services
IMAGE_TAG=latest
DOMAIN_NAME=klugermax.com

# Database
DATABASE_URL=postgresql://postgres:password@relational_db:5432/onyx
POSTGRES_USER=postgres
POSTGRES_PASSWORD=password

# Cache & Message Broker
REDIS_URL=redis://redis:6379
CELERY_BROKER_URL=redis://redis:6379/0

# File Storage (S3)
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
S3_ENDPOINT_URL=http://minio:9000
FILE_STORE_BACKEND=s3

# Model Server (Embeddings)
MODEL_SERVER_HOST=inference_model_server
EMBEDDING_MODEL=nomic-embed-text-v1.5

# Vector Database
VESPA_HOST=vespa
VESPA_PORT=8081

# Background Jobs
USE_LIGHTWEIGHT_BACKGROUND_WORKER=true

# Security
SECRET_KEY=(auto-generated)
AUTH_TYPE=basic

# Features
DISABLE_VECTOR_DB=false
DISABLE_LLM_CHUNK_FILTER=true
```

### Editing Configuration

```bash
# Edit environment variables
cd /opt/onyx && sudo nano .env

# Apply changes (restart services)
sudo docker-compose restart
```

---

## Advanced: Next Steps for Production

This sandbox deployment is suitable for testing and development. For production:

1. **Scale to Multiple Droplets**:
   - Separate database server
   - Load-balanced frontend/API servers
   - Dedicated worker servers

2. **Add Monitoring & Alerts**:
   - Prometheus for metrics
   - Grafana for dashboards
   - AlertManager for notifications

3. **Enable Email Notifications**:
   - Configure SMTP_SERVER in .env
   - Enable user invitations

4. **Configure OAuth/SAML**:
   - SSO for enterprise teams
   - OAuth providers (Google, GitHub, etc.)

5. **Database Replication**:
   - Primary-replica setup
   - Automated backups

6. **Load Balancing**:
   - Multiple API server instances
   - Connection pooling

7. **Monitoring & Logging**:
   - ELK stack (Elasticsearch, Logstash, Kibana)
   - Centralized log aggregation

---

## Support & Troubleshooting

### Check Service Health

```bash
# Full deployment health
cd /opt/onyx && ../verify-deployment.sh
```

### Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| "Connection refused" | Check if docker-compose is running: `sudo docker-compose ps` |
| "Database not ready" | Check postgres logs: `sudo docker-compose logs relational_db` |
| "Port already in use" | Change port in docker-compose.yml and restart |
| "Out of disk space" | Clean images: `sudo docker image prune -a` |
| "SSL certificate error" | Wait for DNS, check certbot logs: `sudo docker-compose logs certbot` |

### Logs Location

All logs are available via docker-compose:

```bash
# View all logs
cd /opt/onyx && sudo docker-compose logs

# View specific service and follow
sudo docker-compose logs -f <service-name>

# View recent logs
sudo docker-compose logs --tail=50
```

---

## Summary

Your Onyx instance is now deployed and accessible at **https://klugermax.com**.

**Key endpoints**:
- Web UI: https://klugermax.com
- API: https://klugermax.com/api
- Admin: https://klugermax.com/admin

**Management**:
- All services in: `/opt/onyx`
- Logs: `sudo docker-compose logs -f`
- Stop: `sudo docker-compose down`
- Restart: `sudo docker-compose restart`

Happy deploying! 🚀
