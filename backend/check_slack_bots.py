#!/usr/bin/env python3

import os
import sys

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from onyx.db.engine.sql_engine import get_session_with_shared_schema, SqlEngine
from onyx.db.slack_bot import fetch_slack_bots


def check_slack_bots():
    """Check what Slack bots are configured in the database"""
    try:
        # Initialize the database engine first
        SqlEngine.init_engine(
            pool_size=20, max_overflow=5, pool_pre_ping=False, pool_recycle=1200
        )

        with get_session_with_shared_schema() as db_session:
            bots = list(fetch_slack_bots(db_session=db_session))

            print(f"Found {len(bots)} Slack bot(s) in database:")
            print("-" * 50)

            for bot in bots:
                print(f"ID: {bot.id}")
                print(f"Name: {bot.name}")
                print(f"Enabled: {bot.enabled}")
                print(f"Has Bot Token: {bool(bot.bot_token)}")
                print(f"Has App Token: {bool(bot.app_token)}")
                print(f"Has User Token: {bool(bot.user_token)}")
                print(f"Bot Token Length: {len(bot.bot_token) if bot.bot_token else 0}")
                print(f"App Token Length: {len(bot.app_token) if bot.app_token else 0}")
                print(
                    f"User Token Length: {len(bot.user_token) if bot.user_token else 0}"
                )
                if bot.user_token:
                    print(f"User Token Prefix: {bot.user_token[:10]}...")
                print("-" * 50)

            return bots

    except Exception as e:
        print(f"Error checking Slack bots: {e}")
        import traceback

        traceback.print_exc()
        return []


if __name__ == "__main__":
    check_slack_bots()
