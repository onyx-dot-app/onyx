# Check Logs

Check the Onyx service logs for debugging and troubleshooting.

## Steps:
1. Ask the user which service logs they want to check:
   - **api_server**: Main FastAPI backend server
   - **web_server**: Next.js frontend server
   - **background**: Primary Celery background worker
   - **indexing**: Document indexing worker (docfetching/docprocessing)
   - **light**: Light background tasks worker
   - **heavy**: Heavy operations worker
   - **all**: Show logs from all services

2. Read the appropriate log files from `backend/log/`:
   - `api_server_debug.log`
   - `web_server_debug.log`
   - `background_debug.log`
   - `docfetching_debug.log`
   - `docprocessing_debug.log`
   - `light_debug.log`
   - `heavy_debug.log`

3. Show the last 50-100 lines of the log file(s) by default
4. Highlight any ERROR or WARNING messages
5. Ask if the user wants to:
   - See more lines
   - Filter for specific patterns
   - Check a different service
   - See real-time logs (tail -f)

## Usage Examples:

### Check API server logs
```bash
tail -n 100 backend/log/api_server_debug.log
```

### Check for errors across all logs
```bash
grep -i error backend/log/*.log | tail -n 50
```

### Follow logs in real-time
```bash
tail -f backend/log/api_server_debug.log
```

### Check logs from specific time period
```bash
grep "2025-10-17 12:" backend/log/api_server_debug.log
```

## Important Notes:
- All Onyx services tail their logs to these files
- Logs include timestamps, log levels, and service names
- ERROR and WARNING are the most important to check
- For integration tests, logs show the backend activity during test runs
- Services must be running for logs to be generated

## Common Log Patterns:
- Database errors: Look for "sqlalchemy" or "postgres"
- Celery errors: Look for "celery" or "task"
- Authentication errors: Look for "auth" or "401/403"
- API errors: Look for HTTP status codes (400, 500, etc.)
