#!/usr/bin/env python3

import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from onyx.db.engine.sql_engine import get_session_with_shared_schema, SqlEngine
from onyx.db.slack_bot import fetch_slack_bots
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id


def check_tenant_context():
    """Check tenant context and Slack bot configuration"""
    try:
        # Initialize the database engine first
        SqlEngine.init_engine(
            pool_size=20, max_overflow=5, pool_pre_ping=False, pool_recycle=1200
        )

        print(f"Current tenant context: {get_current_tenant_id()}")
        print(f"Default schema: {POSTGRES_DEFAULT_SCHEMA}")
        print("-" * 50)

        # Check bots in shared schema
        with get_session_with_shared_schema() as db_session:
            bots = list(fetch_slack_bots(db_session=db_session))
            print(f"Found {len(bots)} Slack bot(s) in shared schema:")
            for bot in bots:
                print(f"  - ID: {bot.id}, Name: {bot.name}, Enabled: {bot.enabled}")

        print("-" * 50)

        # Check if there are any tenant-specific schemas
        # This would require checking the database directly for tenant schemas

    except Exception as e:
        print(f"Error checking tenant context: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    check_tenant_context()
