# Quick Start: Multi-Tenant Database Seeding

Get a populated multi-tenant dev database in 3 easy steps!

## 🚀 Quick Start (5 minutes)

### 1. Start the multi-tenant dev environment

```bash
cd /home/jamison/code/onyx
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml up -d
```

Wait ~30 seconds for all services to start, then verify:

```bash
curl http://localhost:8080/health
```

### 2. Seed the database

```bash
cd backend
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py
```

This creates **3 tenants** with:
- 50 chat sessions each (200 messages total)
- 100 documents each (500 chunks total)
- Realistic data spread over 90 days

### 3. Done! 🎉

The script outputs the tenant credentials. You can now:
- Login to test the UI
- Run your upgrade workflows
- Test multi-tenant features

**Example output:**
```
Created 3 tenants:
  - Acme Corp: admin_a1b2c3d4@acmecorp.com (password: TestPassword123!)
  - TechStart Inc: admin_e5f6g7h8@techstartinc.com (password: TestPassword123!)
  - Global Solutions: admin_i9j0k1l2@globalsolutions.com (password: TestPassword123!)
```

---

## 🎯 Common Use Cases

### More tenants for comprehensive testing

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py --tenants 10
```

### Lots of data for performance testing

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 5 \
  --sessions-per-tenant 200 \
  --docs-per-tenant 500
```

### Just documents (fast)

```bash
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py \
  --tenants 3 \
  --docs-per-tenant 200 \
  --skip-chat
```

---

## 🧪 Testing Upgrades

Use the example workflow script:

```bash
cd /home/jamison/code/onyx
./backend/scripts/example_upgrade_test.sh
```

Or manually:

```bash
# 1. Seed database
cd backend
PYTHONPATH=. python scripts/seed_multitenant_dev_db.py --tenants 5

# 2. Backup
docker exec onyx-relational_db-1 pg_dump -U postgres > backup.sql

# 3. Run your upgrade
# ... your migration commands ...

# 4. Verify (login with tenant credentials and test)
```

---

## 🔧 Troubleshooting

**"Cannot reach API server"**
- Check containers: `docker ps`
- Check logs: `docker logs onyx-api_server-1`
- Make sure you're using the multitenant compose file

**"Script is slow"**
- Use fewer docs: `--docs-per-tenant 50`
- Skip documents: `--skip-docs`
- Check Vespa memory: `docker stats`

**"Need to start over"**
```bash
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml down -v
docker-compose -f deployment/docker_compose/docker-compose.multitenant-dev.yml up -d
# Wait 30 seconds, then seed again
```

---

## 📚 More Info

- Full documentation: `backend/scripts/SEEDING_README.md`
- All options: `python scripts/seed_multitenant_dev_db.py --help`
- Example workflow: `backend/scripts/example_upgrade_test.sh`

