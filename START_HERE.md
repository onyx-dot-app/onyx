# Onyx DigitalOcean Deployment - START HERE

## Your Deployment Information

| Item | Value |
|------|-------|
| Domain | klugermax.com |
| Droplet IP | 45.55.68.178 |
| SSL Email | robimoller@gmail.com |
| Deployment Location | /opt/onyx |
| Environment | Sandbox (single VPS) |

---

## ⚠️ CRITICAL: Before Deployment - Update DNS

**You MUST do this before running the deployment script.**

The Let's Encrypt SSL certificate requires DNS to be configured first.

### Step 1: Update Domain A Record

1. Go to your domain registrar (e.g., GoDaddy, Namecheap, Route53, etc.)
2. Find the DNS management / DNS records section
3. Find or create an **A Record**:
   - **Host/Name**: `@` (this means root domain - klugermax.com)
   - **Type**: A
   - **Value/Points To**: `45.55.68.178`
   - **TTL**: 3600 (or keep default)
4. **Save** the record

### Step 2: Verify DNS Propagation

Run this command from your **local machine** (not the droplet yet):

```bash
# Check if DNS is resolving to your droplet
nslookup klugermax.com

# Output should include:
# Address: 45.55.68.178
```

If you don't see the right IP, wait 5-15 minutes and try again. DNS takes time to propagate.

✅ **Only proceed when DNS resolves correctly**

---

## 🚀 Deployment Steps

### Step 1: SSH into Your Droplet

From your local machine:

```bash
# Connect to your droplet
ssh root@45.55.68.178

# If you have a non-root user set up
ssh ubuntu@45.55.68.178

# Once connected, verify you're on Ubuntu 24.04
cat /etc/os-release
```

### Step 2: Download Deployment Script

Run on the droplet:

```bash
# Download the deployment script
curl -O https://raw.githubusercontent.com/HOP-RAG/HOP/main/deploy-digitalocean.sh

# Make it executable
chmod +x deploy-digitalocean.sh
```

### Step 3: Run the Deployment Script

```bash
# Start deployment (this will take 15-30 minutes)
./deploy-digitalocean.sh
```

**What to expect**:
- Script will ask for sudo password (your droplet root password)
- Long output as Docker images are pulled (~3-4 GB)
- Services will start and initialize
- Database migrations will run automatically
- Script will print completion message with next steps

### Step 4: Monitor Progress (Optional)

In another SSH terminal, you can watch the deployment:

```bash
# Monitor all services
cd /opt/onyx && sudo docker-compose logs -f

# Or watch specific service (e.g., backend)
sudo docker-compose logs -f backend
```

### Step 5: Run Verification

Once the deployment script completes, verify everything is working:

```bash
cd /opt/onyx

# Make verification script executable
chmod +x ../verify-deployment.sh

# Run verification
../verify-deployment.sh
```

All checks should show green checkmarks (✓).

---

## ✅ After Deployment

### Wait for DNS Propagation

If DNS hasn't fully propagated yet, wait 5-15 minutes:

```bash
# Keep checking (from your local machine)
watch -n 5 'nslookup klugermax.com'

# Once it shows 45.55.68.178, continue
```

### Access Your Onyx Instance

Open your browser and visit:

```
https://klugermax.com
```

**First-time access**:
- HTTP (http://klugermax.com) automatically redirects to HTTPS
- SSL certificate should be valid (Let's Encrypt)
- You should see the Onyx login page

### Create Admin User

1. Click "Create Account" on the login page
2. Enter your admin credentials
3. Log in

Or create via API:

```bash
curl -X POST https://klugermax.com/api/admin/create-user \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "admin@example.com",
    "password": "your-secure-password",
    "name": "Admin User"
  }'
```

### Test Core Functionality

1. **Dashboard**: Verify you can access the main dashboard
2. **Create a Connector**: Admin → Connectors → Add a test connector
3. **Upload a Document**: Try uploading a test document
4. **Search**: Verify the document appears in search results

---

## 📋 Deployment Checklist

Use this to track your progress:

### Pre-Deployment
- [ ] Domain purchased and accessible
- [ ] Domain A record created (klugermax.com → 45.55.68.178)
- [ ] DNS propagation verified (nslookup shows 45.55.68.178)
- [ ] DigitalOcean droplet created and accessible via SSH
- [ ] Noted droplet IP and SSH credentials

### Deployment
- [ ] SSH into droplet
- [ ] Downloaded deploy-digitalocean.sh
- [ ] Made script executable (chmod +x)
- [ ] Ran deployment script
- [ ] Monitored logs (optional)
- [ ] Deployment script completed successfully

### Post-Deployment
- [ ] Ran verify-deployment.sh
- [ ] All verification checks passed (✓)
- [ ] DNS resolves correctly
- [ ] Can access https://klugermax.com
- [ ] SSL certificate is valid
- [ ] Created admin user
- [ ] Tested basic functionality (dashboard, upload, search)

---

## 🎯 What Gets Deployed

The deployment script automatically sets up:

### Services
✅ **Frontend** (Next.js) - Web UI
✅ **Backend API** (FastAPI) - Core API
✅ **Model Server** (FastAPI) - Embeddings/AI
✅ **PostgreSQL** - Main database
✅ **Redis** - Cache & message broker
✅ **Vespa** - Vector search database
✅ **MinIO** - S3-compatible file storage
✅ **Nginx** - Reverse proxy & SSL/TLS
✅ **Certbot** - Automatic SSL renewal
✅ **Celery Workers** - Background jobs

### Configuration
✅ Environment variables (.env)
✅ Database schema (auto-migrated)
✅ SSL certificate (Let's Encrypt)
✅ Persistent volumes for data

---

## 🆘 Troubleshooting

### Deployment Failed
```bash
# Check what went wrong
cd /opt/onyx && sudo docker-compose logs

# Common issues:
# - Docker not installed: Restart deployment script
# - DNS not set up: Go back and update your A record
# - Port in use: Very unlikely on new droplet
# - Out of memory: Droplet is too small (unlikely with recommended size)
```

### DNS Not Resolving
```bash
# Check your A record in registrar
# Make sure it points to: 45.55.68.178
# Wait 5-15 minutes for propagation

# Test from droplet
nslookup klugermax.com
```

### Can't Access HTTPS
```bash
# 1. Check DNS (should resolve to 45.55.68.178)
nslookup klugermax.com

# 2. Check if services are running
cd /opt/onyx && sudo docker-compose ps

# 3. Check Nginx/SSL logs
sudo docker-compose logs nginx
sudo docker-compose logs certbot

# 4. Try HTTP first (may redirect to HTTPS)
curl -v http://klugermax.com
```

### Services Not Running
```bash
cd /opt/onyx

# Check status
sudo docker-compose ps

# View logs for failing service
sudo docker-compose logs <service-name>

# Try restarting
sudo docker-compose restart
```

---

## 📚 Documentation

After deployment, refer to:

| Document | Purpose |
|----------|---------|
| `DEPLOYMENT_GUIDE.md` | Comprehensive deployment guide (detailed instructions) |
| `DEPLOYMENT_QUICKREF.md` | Quick reference for common commands |
| `CLAUDE.md` | Project knowledge base (architecture, settings, tech stack) |
| `LOCAL_DEV_GUIDE.md` | Local development setup (reference) |

---

## 🔧 Common Commands (After Deployment)

```bash
cd /opt/onyx

# View all services
sudo docker-compose ps

# View logs
sudo docker-compose logs -f

# Restart services
sudo docker-compose restart

# Stop services
sudo docker-compose down

# Edit configuration
sudo nano .env
# Then restart to apply changes:
sudo docker-compose restart

# Database backup
sudo docker exec onyx-relational_db-1 pg_dump -U postgres onyx > backup.sql

# Check resource usage
sudo docker stats
```

---

## ⏱️ Expected Timeline

| Task | Time |
|------|------|
| DNS setup | 5-15 minutes |
| SSH into droplet | 1 minute |
| Download script | <1 minute |
| Run deployment | 15-30 minutes |
| Verification | 2-3 minutes |
| First access & setup | 5-10 minutes |
| **TOTAL** | **30-60 minutes** |

---

## 🎉 Success!

Once you've completed all steps above, you have:

✅ A fully deployed Onyx instance at **https://klugermax.com**
✅ All services running (Frontend, Backend, Database, Cache, etc.)
✅ Automatic SSL certificates (Let's Encrypt)
✅ Persistent data storage
✅ Background job processing (Celery)

You're ready to:
- Create documents and connectors
- Test search and AI features
- Configure integrations
- Scale up to production later

---

## 📞 Need Help?

1. **Check logs**: `cd /opt/onyx && sudo docker-compose logs -f`
2. **Run verification**: `../verify-deployment.sh`
3. **Review DEPLOYMENT_GUIDE.md**: Detailed troubleshooting section
4. **Check service status**: `sudo docker-compose ps`

---

## Next: Let's Deploy! 🚀

**Ready to start?**

1. ✅ Verify DNS A record is set (klugermax.com → 45.55.68.178)
2. ✅ Confirm DNS propagation (nslookup shows correct IP)
3. ✅ SSH into your droplet
4. ✅ Run the deployment script

**Questions?** Review the sections above or check DEPLOYMENT_GUIDE.md for details.

Good luck! 🎯
