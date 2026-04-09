#!/usr/bin/env python3
"""
Diagnostic script to check database connection configuration.
Run this inside the API server container to diagnose SSL/IAM auth issues.

Usage:
  python backend/scripts/diagnose_db_connection.py
"""

import os
import sys

print("=" * 70)
print("DATABASE CONNECTION DIAGNOSTICS")
print("=" * 70)
print()

# Check environment variables
print("ENVIRONMENT VARIABLES:")
print("-" * 70)

env_vars = [
    "USE_IAM_AUTH",
    "POSTGRES_REQUIRE_SSL",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "AWS_REGION_NAME",
]

for var in env_vars:
    value = os.getenv(var, "<NOT SET>")
    # Mask password if present
    if "PASSWORD" in var and value != "<NOT SET>":
        value = "***MASKED***"
    print(f"  {var:25s} = {value}")

print()

# Check if boto3 is available (for IAM auth)
print("PYTHON MODULES:")
print("-" * 70)
try:
    import boto3

    print("  ✓ boto3 is installed")
    print(f"    Version: {boto3.__version__}")
except ImportError:
    print("  ✗ boto3 is NOT installed (required for IAM auth)")

try:
    import asyncpg

    print("  ✓ asyncpg is installed")
    print(f"    Version: {asyncpg.__version__}")
except ImportError:
    print("  ✗ asyncpg is NOT installed")

try:
    import psycopg2

    print("  ✓ psycopg2 is installed")
    print(f"    Version: {psycopg2.__version__}")
except ImportError:
    print("  ✗ psycopg2 is NOT installed")

print()

# Check app_configs loading
print("ONYX APP CONFIGS:")
print("-" * 70)
try:
    from onyx.configs.app_configs import USE_IAM_AUTH
    from onyx.configs.app_configs import POSTGRES_REQUIRE_SSL
    from onyx.configs.app_configs import POSTGRES_HOST
    from onyx.configs.app_configs import POSTGRES_PORT
    from onyx.configs.app_configs import POSTGRES_DB
    from onyx.configs.app_configs import POSTGRES_USER

    print(f"  USE_IAM_AUTH           = {USE_IAM_AUTH}")
    print(f"  POSTGRES_REQUIRE_SSL   = {POSTGRES_REQUIRE_SSL}")
    print(f"  POSTGRES_HOST          = {POSTGRES_HOST}")
    print(f"  POSTGRES_PORT          = {POSTGRES_PORT}")
    print(f"  POSTGRES_DB            = {POSTGRES_DB}")
    print(f"  POSTGRES_USER          = {POSTGRES_USER}")
except Exception as e:
    print(f"  ✗ Error loading app_configs: {e}")
    sys.exit(1)

print()

# Check SSL configuration
print("SSL CONFIGURATION:")
print("-" * 70)
if USE_IAM_AUTH or POSTGRES_REQUIRE_SSL:
    print("  ✓ SSL should be ENABLED")
    if USE_IAM_AUTH:
        print("    Reason: USE_IAM_AUTH=true")
    if POSTGRES_REQUIRE_SSL:
        print("    Reason: POSTGRES_REQUIRE_SSL=true")

    try:
        from onyx.db.engine.rds_ssl import get_rds_ssl_context_or_require

        ssl_config = get_rds_ssl_context_or_require()
        print(f"  SSL mode for asyncpg  = {ssl_config}")
    except Exception as e:
        print(f"  ✗ Error getting SSL config: {e}")
else:
    print("  ✗ SSL is DISABLED")
    print("    This will cause 'no encryption' errors on RDS")

print()

# Check IAM token generation
if USE_IAM_AUTH:
    print("IAM AUTHENTICATION:")
    print("-" * 70)
    try:
        from onyx.configs.app_configs import AWS_REGION_NAME
        from onyx.db.engine.iam_auth import get_iam_auth_token

        token = get_iam_auth_token(
            POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, AWS_REGION_NAME
        )
        if token:
            print("  ✓ IAM token generated successfully")
            print(f"    Token (first 50 chars): {token[:50]}...")
        else:
            print("  ✗ IAM token is None")
    except Exception as e:
        print(f"  ✗ Error generating IAM token: {e}")
        import traceback

        traceback.print_exc()

print()

# Test async engine creation
print("ASYNC ENGINE CREATION:")
print("-" * 70)
try:
    from onyx.db.engine.async_sql_engine import get_sqlalchemy_async_engine

    engine = get_sqlalchemy_async_engine()
    print("  ✓ Async engine created successfully")
    print(f"    Engine: {engine}")
    print(f"    URL: {engine.url}")
except Exception as e:
    print(f"  ✗ Error creating async engine: {e}")
    import traceback

    traceback.print_exc()

print()
print("=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
print()
print("NEXT STEPS:")
print("  1. Verify USE_IAM_AUTH or POSTGRES_REQUIRE_SSL is set to 'true'")
print("  2. Check the logs above for any errors")
print("  3. If SSL is disabled, set the appropriate environment variable")
print("  4. Rebuild and restart the container after making changes")
