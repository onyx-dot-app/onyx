# Onyx DigitalOcean Deployment - Quick Reference

## Before You Start

```bash
# 1. Update domain A record
#    klugermax.com → 45.55.68.178 (in your registrar's DNS settings)

# 2. SSH into droplet
ssh root@45.55.68.178

# 3. Download and run deployment script
curl -O https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deploy-digitalocean.sh
chmod +x deploy-digitalocean.sh
./deploy-digitalocean.sh
```

---

## Deployment Timeline

| Phase | Time | What It Does |
|-------|------|-------------|
| Install Docker | 3-5 min | Install Docker, Docker Compose, dependencies |
| Clone Repo | 1-2 min | Clone Onyx repository from GitHub |
| Create Directories | <1 min | Create volume directories for persistence |
| Configure .env | <1 min | Set up environment variables |
| Set Up Docker Compose | <1 min | Prepare docker-compose configuration |
| Pull Images | 5-15 min | Download container images (~3-4 GB) |
| Start Services | 1-2 min | Launch all containers |
| Verify Health | <1 min | Check services are running |
| Run Migrations | 1-2 min | Initialize database |
| **TOTAL** | **15-30 min** | Full deployment |

---

## After Deployment

```bash
# Navigate to deployment directory
cd /opt/onyx

# View all service status
sudo docker-compose ps

# View logs (all services)
sudo docker-compose logs -f

# View specific service logs
sudo docker-compose logs -f backend
sudo docker-compose logs -f web
sudo docker-compose logs -f background

# Restart all services
sudo docker-compose restart

# Restart specific service
sudo docker-compose restart backend

# Stop all services
sudo docker-compose down

# Start services
sudo docker-compose up -d
```

---

## Access Your Instance

Once DNS propagates (5-15 minutes):

```
https://klugermax.com
```

- **Web UI**: https://klugermax.com
- **API**: https://klugermax.com/api
- **Admin Panel**: https://klugermax.com/admin

HTTP automatically redirects to HTTPS.

---

## Verify Deployment

```bash
cd /opt/onyx

# Run verification script
../verify-deployment.sh

# Manual checks
curl http://localhost:8080/health    # Backend
curl http://localhost:9000/health    # Model Server
nslookup klugermax.com               # DNS resolution
```

---

## Configuration

All settings in `/opt/onyx/.env`:

```bash
# Edit configuration
sudo nano .env

# Apply changes (restart services)
sudo docker-compose restart
```

Key variables:
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis connection
- `S3_ENDPOINT_URL` - MinIO/S3 storage
- `MODEL_SERVER_HOST` - Embedding model server
- `DOMAIN_NAME` - Your domain (klugermax.com)
- `SECRET_KEY` - Session encryption key

---

## Database Access

```bash
# Connect to PostgreSQL
sudo docker exec -it onyx-relational_db-1 psql -U postgres -d onyx

# Connect to Redis
sudo docker exec -it onyx-redis-1 redis-cli

# Backup database
sudo docker exec onyx-relational_db-1 pg_dump -U postgres onyx > backup.sql

# Restore database
sudo docker exec -i onyx-relational_db-1 psql -U postgres onyx < backup.sql
```

---

## Monitoring

```bash
# Container resource usage
sudo docker stats

# Disk space
df -h /opt/onyx

# Check certificate status
sudo docker-compose exec -T certbot certbot certificates

# View Nginx/reverse proxy logs
sudo docker-compose logs nginx
```

---

## Troubleshooting

### Service Not Starting
```bash
# Check logs
sudo docker-compose logs backend

# Try restarting
sudo docker-compose restart backend
```

### Database Connection Error
```bash
# Check if database is running
sudo docker-compose logs relational_db

# Verify DATABASE_URL in .env
cat .env | grep DATABASE_URL
```

### DNS Not Working
```bash
# Test DNS resolution
nslookup klugermax.com

# If not resolving:
# 1. Check A record in registrar (should be 45.55.68.178)
# 2. Wait 5-15 minutes for propagation
# 3. Try: dig klugermax.com
```

### SSL Certificate Error
```bash
# Check certificate status
sudo docker-compose logs certbot

# Manually renew certificate
sudo docker-compose exec -T certbot certbot renew

# View certificate details
openssl s_client -connect klugermax.com:443 </dev/null 2>/dev/null | openssl x509 -noout -text
```

### Out of Memory / Slow
```bash
# Check resource usage
sudo docker stats

# If needed, reduce concurrency
# Edit .env and set:
# USE_LIGHTWEIGHT_BACKGROUND_WORKER=true
# Then restart: sudo docker-compose restart
```

---

## File Locations

```
/opt/onyx/                          # Deployment root
├── .env                            # Configuration (edit with: sudo nano .env)
├── docker-compose.yml              # Service definitions
├── postgres_data/                  # PostgreSQL persistent data
├── redis_data/                     # Redis persistent data
├── vespa_data/                     # Vector database data
├── minio_data/                     # S3 storage data
└── nginx_logs/                     # Reverse proxy logs
```

---

## Emergency Commands

```bash
# Full restart
cd /opt/onyx && sudo docker-compose down && sudo docker-compose up -d

# Clean up old data (WARNING: deletes data!)
# sudo docker-compose down -v

# View real-time system stats
top
htop

# Check disk usage
du -sh /opt/onyx/*

# Free up space (delete unused images)
sudo docker image prune -a --filter "until=720h"
```

---

## Useful One-Liners

```bash
# Get droplet IP from DNS
nslookup klugermax.com | grep "Address:" | tail -1

# Check if all services are healthy
sudo docker-compose ps | grep -c "Up"

# Tail all logs with timestamp
sudo docker-compose logs -f -t

# Watch service status
watch -n 2 'cd /opt/onyx && sudo docker-compose ps'

# Get certificate expiration date
echo | openssl s_client -servername klugermax.com -connect klugermax.com:443 2>/dev/null | openssl x509 -noout -dates
```

---

## Support Resources

- **Logs**: `cd /opt/onyx && sudo docker-compose logs -f`
- **Docs**: See `DEPLOYMENT_GUIDE.md` for detailed instructions
- **Verification**: Run `../verify-deployment.sh`
- **Status Check**: `sudo docker-compose ps`

---

**Deployment Details**:
- Domain: klugermax.com
- IP: 45.55.68.178
- SSL Email: robimoller@gmail.com
- Deployment Dir: /opt/onyx
- Deployment Type: Docker Compose (single VPS)
