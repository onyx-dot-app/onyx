#!/usr/bin/env python3

import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from onyx.db.engine.sql_engine import get_session_with_shared_schema, SqlEngine
from onyx.db.slack_bot import fetch_slack_bots
from onyx.context.search.federated.slack_search import test_slack_api_simple


def test_new_slack_api():
    """Test the new Slack API function"""
    try:
        # Initialize the database engine first
        SqlEngine.init_engine(
            pool_size=20, max_overflow=5, pool_pre_ping=False, pool_recycle=1200
        )

        # Get the current tenant context
        # tenant_id = "public"  # Default tenant

        with get_session_with_shared_schema() as db_session:
            # Fetch Slack bots for this tenant
            slack_bots = fetch_slack_bots(db_session)

            if not slack_bots:
                print("No Slack bots found")
                return

            bot = slack_bots[0]
            print(f"Testing with bot: {bot.name}")
            print(f"Bot token: {bot.bot_token[:20]}...")

            # Test the new API function
            print("\nTesting new Slack API...")
            results = test_slack_api_simple(
                query_string="test message", bot_token=bot.bot_token, limit=5
            )

            print(f"API Response: {results}")
            if "error" in results:
                print(f"Error: {results['error']}")
            else:
                print("✅ API call successful!")

    except Exception as e:
        print(f"Error testing new Slack API: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_new_slack_api()
