import argparse
import logging
from logging import getLogger

from onyx.db.seeding.chat_history_seeding import seed_chat_history

# Configure the logger
logging.basicConfig(
    level=logging.INFO,  # Set the log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Log format
    handlers=[logging.StreamHandler()],  # Output logs to console
)

logger = getLogger(__name__)


def go_main(num_sessions: int, num_messages: int, num_days: int) -> None:
    seed_chat_history(num_sessions, num_messages, num_days)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed chat history")
    parser.add_argument(
        "--sessions",
        type=int,
        default=2048,
        help="Number of chat sessions to seed",
    )

    parser.add_argument(
        "--messages",
        type=int,
        default=4,
        help="Number of chat messages to seed per session",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days looking backwards over which to seed the timestamps with",
    )

    args = parser.parse_args()
    go_main(args.sessions, args.messages, args.days)
