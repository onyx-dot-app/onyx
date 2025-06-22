# Railway Preview Environment Setup Guide

This guide explains how to set up automated preview environments for Onyx using Railway.

## Overview

This setup will:
- Deploy a full Onyx instance for each PR
- Provide a unique URL for testing
- Automatically trigger Keystone tests
- Clean up when PRs are closed

## Setup Steps

### 1. Railway Account Setup

1. Create a Railway account at https://railway.app
2. Create a new project called "onyx-preview-environments"
3. Install the Railway GitHub App and connect your repository

### 2. Configure Railway Project

In your Railway project dashboard:

1. **Add Required Services:**
   - PostgreSQL (click "New" → "Database" → "PostgreSQL")
   - Redis (click "New" → "Database" → "Redis")

2. **Set Environment Variables:**
   ```bash
   # Auth Settings
   AUTH_TYPE=disabled
   INTERNAL_AUTH_TOKEN=preview-token-123
   
   # Model Settings
   ENABLE_MINI_CHUNK=true
   MODEL_SERVER_HOST=model_server
   MODEL_SERVER_PORT=8000
   
   # Other Settings
   LOG_LEVEL=info
   ENV_TYPE=preview
   ```

3. **Get Your Project ID:**
   - Go to Project Settings
   - Copy the Project ID

### 3. GitHub Repository Setup

1. **Add GitHub Secrets:**
   ```
   RAILWAY_TOKEN         # Get from Railway Dashboard → Account Settings → Tokens
   RAILWAY_PROJECT_ID    # Your Railway project ID
   KEYSTONE_API_TOKEN    # Your Keystone API token
   KEYSTONE_TEST_SUITE_ID # ID of the test suite to run
   ```

2. **Commit the Files:**
   ```bash
   git add railway.json
   git add deployment/docker_compose/docker-compose.railway.yml
   git add deployment/docker_compose/nginx-preview.conf
   git add .github/workflows/preview-deploy.yml
   git commit -m "Add Railway preview environment configuration"
   ```

### 4. Keystone Integration

Update the workflow file with your actual Keystone API endpoint:
- Replace `https://api.keystone.com/v1/test-runs` with your endpoint
- Adjust the request payload format if needed

## How It Works

1. **PR Created/Updated** → GitHub Action triggers
2. **Railway Deployment** → Creates isolated environment
3. **Health Check** → Waits for services to be ready
4. **Keystone Tests** → Triggers automated test suite
5. **PR Comment** → Updates with preview URL and test status
6. **PR Closed** → Automatically deletes preview environment

## Resource Optimization

The preview configuration includes several optimizations:
- Disabled authentication for easier testing
- Single model server (CPU only)
- Reduced resource allocations
- Simplified Vespa configuration

## Troubleshooting

### Vespa Issues
If Vespa fails to start without privileged mode:
1. Check Railway logs for specific errors
2. Try adding: `VESPA_NOOP_PRIVILEGED=true`
3. Consider using external Vespa instance

### Memory Issues
If services run out of memory:
1. Upgrade Railway plan for more resources
2. Reduce model server memory usage
3. Disable unused features

### Build Failures
1. Check Docker build logs in Railway
2. Ensure all required files are committed
3. Verify base images are accessible

## Cost Estimation

Railway pricing (as of setup):
- $5/month base + usage
- ~$0.01/hour per GB RAM
- Preview environments auto-sleep after inactivity

Estimated cost per PR:
- Active testing: ~$0.50-$1.00/day
- Idle: ~$0.10/day

## Next Steps

1. Test with a sample PR
2. Monitor resource usage
3. Adjust configurations as needed
4. Set up cost alerts in Railway