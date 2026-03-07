# Local Development Setup Guide

Your development environment is ready! Here's how to run everything locally.

## ✅ What's Already Set Up

- ✅ Docker services running (PostgreSQL, Redis, Vespa, MinIO)
- ✅ Python 3.11 virtual environment created
- ✅ Backend dependencies installed
- ✅ Frontend dependencies installed
- ✅ Database migrations completed
- ✅ `.env.development` file created

## 🚀 Running the Application

You'll need 4 terminal windows/tabs:

### Terminal 1: Backend API Server

```bash
cd /Users/robimoller/Development/HOP
source .venv/bin/activate
export $(cat .env.development | xargs)
cd backend
uvicorn onyx.main:app --reload --port 8080
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8080
INFO:     Application startup complete
```

### Terminal 2: Model Server (for embeddings/inference)

```bash
cd /Users/robimoller/Development/HOP
source .venv/bin/activate
export $(cat .env.development | xargs)
cd backend
uvicorn model_server.main:app --reload --port 9000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:9000
```

### Terminal 3: Background Jobs (Celery Workers)

```bash
cd /Users/robimoller/Development/HOP
source .venv/bin/activate
export $(cat .env.development | xargs)
cd backend
python ./scripts/dev_run_background_jobs.py
```

**Expected output:**
```
Starting celery worker...
[tasks] Ready to accept tasks!
```

### Terminal 4: Frontend (Next.js)

```bash
cd /Users/robimoller/Development/HOP/web
npm run dev
```

**Expected output:**
```
  ▲ Next.js 16.1.6
  ▶ Local:        http://localhost:3000
```

## 🌐 Access Your App

Once all 4 servers are running:

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8080 (not used directly, go through frontend)
- **Model Server**: http://localhost:9000

## 🛠 Development Workflow

### Making Backend Changes
- Edit files in `backend/onyx/`
- Uvicorn will auto-reload when you save (with `--reload` flag)
- Check the backend terminal for errors

### Making Frontend Changes
- Edit files in `web/src/`
- Next.js will auto-reload when you save
- Check the frontend terminal for errors

### Database Changes
If you modify the database schema:

```bash
cd backend
alembic revision -m "Your migration description"
# Edit the generated file in alembic/versions/
alembic upgrade head
```

Then restart your backend server.

## 🐛 Debugging

### Check Docker Service Status
```bash
docker ps
# Or check detailed logs
docker compose logs -f [service_name]
```

### View Backend Logs
```bash
tail -f backend/log/api_server_debug.log
tail -f backend/log/background_worker_debug.log
```

### Check Database
```bash
docker exec -it hop-relational_db-1 psql -U postgres -d onyx -c "SELECT COUNT(*) FROM document;"
```

### Clear Redis Cache
```bash
docker exec -it hop-cache-1 redis-cli FLUSHALL
```

## 🔑 Environment Variables

You can customize `.env.development`:
- Add `OPENAI_API_KEY=sk-...` for LLM features
- Change `AUTH_TYPE=disabled` to enable authentication
- Adjust `LOG_LEVEL=DEBUG` for more verbose logs

## ⚠️ Important Notes

1. **Activate venv** before running anything: `source .venv/bin/activate`
2. **All 4 servers** must be running for the app to work fully
3. **Check logs** in backend terminal if something breaks
4. **Don't modify migrations** after they've been run—create new ones instead
5. **Restart backend** if you change Celery task definitions

## 🎯 Code Standards

Before committing, check CLAUDE.md for:
- **Frontend**: Use absolute imports (`@/`), custom components from `refresh-components`, no `dark:` modifiers
- **Backend**: Use `@shared_task` for Celery, place DB ops in `backend/onyx/db/`
- **Types**: Everything must be strictly typed (Python + TypeScript)

## 🚨 Stuck?

1. Check `.env.development` is loaded: `echo $DB_HOST`
2. Verify Docker services: `docker ps`
3. Check logs in `backend/log/` or terminal output
4. Try restarting the specific server
5. Clear Python cache: `find . -type d -name __pycache__ -exec rm -r {} +`

Happy coding! 🎉
